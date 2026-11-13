from __future__ import annotations
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy import create_engine, String, Float, DateTime, Text, Integer, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from app.core.config import settings

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class Camera(Base):
    __tablename__ = "cameras"
    camera_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), default="")
    group: Mapped[str] = mapped_column(String(128), default="default")
    source: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(String(32), default="unknown")  # online/offline/reconnecting
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Observation(Base):
    __tablename__ = "observations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[str] = mapped_column(String(128), index=True)
    track_id: Mapped[str] = mapped_column(String(128), index=True)
    entity_type: Mapped[str] = mapped_column(String(128), index=True)   # raw detector label
    category: Mapped[str] = mapped_column(String(32), default="unknown", index=True)  # human/animal/vehicle/other/unknown
    confidence: Mapped[float] = mapped_column(Float)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    bbox_json: Mapped[str] = mapped_column(Text, default="[]")
    analysis_json: Mapped[str] = mapped_column(Text, default="{}")


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[str] = mapped_column(String(128), index=True)
    incident_type: Mapped[str] = mapped_column(String(64), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    track_ids: Mapped[str] = mapped_column(Text, default="[]")
    reasoning: Mapped[str] = mapped_column(Text, default="[]")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    evidence_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified: Mapped[int] = mapped_column(Integer, default=0)
    cross_camera_links_json: Mapped[str] = mapped_column(Text, default="[]")


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True, default=datetime.utcnow)
    actor: Mapped[str] = mapped_column(String(128), default="system")
    action: Mapped[str] = mapped_column(String(128), index=True)
    target_type: Mapped[str] = mapped_column(String(64), default="")
    target_id: Mapped[str] = mapped_column(String(128), default="")
    details_json: Mapped[str] = mapped_column(Text, default="{}")


engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)


def audit(action: str, target_type: str = "", target_id: str = "", details: dict | None = None, actor: str = "system") -> None:
    try:
        with SessionLocal() as db:
            db.add(AuditLog(
                timestamp=datetime.utcnow(), actor=actor, action=action,
                target_type=target_type, target_id=str(target_id),
                details_json=json.dumps(details or {}),
            ))
            db.commit()
    except Exception as exc:  # audit logging must never crash the pipeline
        log.error("audit log write failed: %s", exc)


def upsert_camera(camera_id: str, name: str, group: str, source: str, status: str, error: str | None = None) -> None:
    with SessionLocal() as db:
        row = db.get(Camera, camera_id)
        now = datetime.utcnow()
        if row is None:
            row = Camera(camera_id=camera_id, name=name, group=group, source=source,
                          status=status, last_seen=now, last_error=error)
            db.add(row)
        else:
            row.name = name; row.group = group; row.source = source
            row.status = status; row.last_seen = now; row.last_error = error
        db.commit()


def list_cameras() -> list[dict]:
    with SessionLocal() as db:
        rows = db.query(Camera).all()
        return [{
            "camera_id": r.camera_id, "name": r.name, "group": r.group, "source": r.source,
            "status": r.status, "last_seen": r.last_seen.isoformat() if r.last_seen else None,
            "last_error": r.last_error,
        } for r in rows]


def add_incident(data: dict) -> int:
    with SessionLocal() as db:
        row = Incident(
            camera_id=data["camera_id"], incident_type=data["incident_type"],
            confidence=float(data["confidence"]), timestamp=data["timestamp"],
            track_ids=json.dumps(data.get("track_ids", [])),
            reasoning=json.dumps(data.get("reasoning", [])),
            metadata_json=json.dumps(data.get("metadata", {})),
            evidence_path=data.get("evidence_path"),
            cross_camera_links_json=json.dumps(data.get("cross_camera_links", [])),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    audit("incident_created", "incident", row.id, {"incident_type": data["incident_type"], "camera_id": data["camera_id"]})
    return row.id


# Backward-compatible alias (the original project called these "events").
def add_event(data: dict) -> int:
    data = dict(data)
    data.setdefault("incident_type", data.get("event_type", "other_configured"))
    return add_incident(data)


def list_incidents(limit: int = 100, camera_id: str | None = None, incident_type: str | None = None) -> list[dict]:
    with SessionLocal() as db:
        q = db.query(Incident)
        if camera_id:
            q = q.filter(Incident.camera_id == camera_id)
        if incident_type:
            q = q.filter(Incident.incident_type == incident_type)
        rows = q.order_by(Incident.timestamp.desc()).limit(limit).all()
        return [
            {
                "id": r.id, "camera_id": r.camera_id, "incident_type": r.incident_type,
                "event_type": r.incident_type,  # backward-compatible key
                "confidence": r.confidence, "timestamp": r.timestamp.isoformat(),
                "track_ids": json.loads(r.track_ids), "reasoning": json.loads(r.reasoning),
                "metadata": json.loads(r.metadata_json), "evidence_path": r.evidence_path,
                "verified": bool(r.verified),
                "cross_camera_links": json.loads(r.cross_camera_links_json),
            } for r in rows
        ]


def list_events(limit: int = 100) -> list[dict]:
    return list_incidents(limit=limit)


def add_observations(rows: list[dict]) -> None:
    if not rows:
        return
    with SessionLocal() as db:
        for data in rows:
            db.add(Observation(
                camera_id=data["camera_id"], track_id=data["track_id"],
                entity_type=data["entity_type"], category=data.get("category", "unknown"),
                confidence=float(data["confidence"]),
                timestamp=data["timestamp"], bbox_json=json.dumps(data["bbox"]),
                analysis_json=json.dumps(data.get("analysis", {})),
            ))
        db.commit()


# --- Privacy / retention -----------------------------------------------------------

def purge_observations_older_than(days: int) -> int:
    cutoff = datetime.utcnow() - timedelta(days=days)
    with SessionLocal() as db:
        n = db.query(Observation).filter(Observation.timestamp < cutoff).delete()
        db.commit()
    audit("retention_purge", "observations", "-", {"deleted": n, "older_than_days": days})
    return n


def purge_incidents_older_than(days: int) -> tuple[int, list[str]]:
    """Deletes incident rows older than the retention window and returns the
    evidence file paths that were referenced, so the caller can remove the
    files too (DB + filesystem retention stay in sync)."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    with SessionLocal() as db:
        rows = db.query(Incident).filter(Incident.timestamp < cutoff).all()
        paths = [r.evidence_path for r in rows if r.evidence_path]
        n = db.query(Incident).filter(Incident.timestamp < cutoff).delete()
        db.commit()
    audit("retention_purge", "incidents", "-", {"deleted": n, "older_than_days": days})
    return n, paths


def purge_orphan_evidence(evidence_dir: Path, days: int) -> int:
    """Deletes evidence clip files older than the retention window regardless of
    whether their DB row still exists (defense in depth for the privacy
    requirement: never keep raw video longer than configured)."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    removed = 0
    if not evidence_dir.exists():
        return 0
    for f in evidence_dir.glob("*.mp4"):
        try:
            mtime = datetime.utcfromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError as exc:
            log.warning("could not remove evidence file %s: %s", f, exc)
    audit("retention_purge", "evidence_files", "-", {"deleted": removed, "older_than_days": days})
    return removed
