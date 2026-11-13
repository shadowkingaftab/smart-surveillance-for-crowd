"""Seed the local development database with demo cameras and incidents.

This is for reviewing the operator console (and API pagination/filters) without
running cameras or model weights. It writes ordinary rows through the same
schema the pipeline uses; it does not fake the detector itself.

Usage:
    python tools/seed_demo_data.py
    python tools/seed_demo_data.py --reset     # replace existing demo rows

The script refuses to reset a non-SQLite database unless --force is passed, so
a configured PostgreSQL instance is never wiped by accident.
"""
from __future__ import annotations
import argparse
import random
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.services.db import (
    Camera, Incident, Observation, SessionLocal, add_incident, init_db,
)

NOW = datetime.now(timezone.utc).replace(tzinfo=None)

CAMERAS = [
    {
        "camera_id": "CAM-01", "name": "Front Entrance", "group": "perimeter",
        "source": "rtsp://10.20.0.11:554/stream1", "status": "online",
        "minutes_ago": 0.1, "last_error": None,
    },
    {
        "camera_id": "CAM-02", "name": "Loading Dock", "group": "perimeter",
        "source": "rtsp://10.20.0.12:554/stream1", "status": "online",
        "minutes_ago": 0.2, "last_error": None,
    },
    {
        "camera_id": "CAM-03", "name": "Parking Lot", "group": "parking",
        "source": "rtsp://10.20.0.13:554/stream1", "status": "online",
        "minutes_ago": 0.3, "last_error": None,
    },
    {
        "camera_id": "CAM-04", "name": "Warehouse Aisle 4", "group": "internal",
        "source": "rtsp://10.20.0.14:554/stream1", "status": "reconnecting",
        "minutes_ago": 1.0, "last_error": "frame read failed (camera disconnected?)",
    },
    {
        "camera_id": "CAM-05", "name": "North Gate", "group": "perimeter",
        "source": "rtsp://10.20.0.15:554/stream1", "status": "offline",
        "minutes_ago": 137.0, "last_error": "connection refused",
    },
]

# Minutes before now. Spread deliberately so the 1h / 24h / 7d filters all
# return something and the activity chart has a realistic shape.
OFFSETS = [
    2, 9, 18, 33, 47, 66, 89, 112,
    150, 190, 240, 310, 380, 455, 520, 610, 700, 830, 960, 1100, 1250, 1380,
    1500, 1700, 2000, 2400, 2900, 3200, 3800, 4200,
    5000, 5800, 6900, 8100, 9300,
]

TYPES = (
    ["accident"] * 5
    + ["violence_fight"] * 6
    + ["robbery_intrusion"] * 5
    + ["dangerous_activity"] * 5
    + ["crowd_anomaly"] * 3
    + ["vehicle_incident"] * 5
    + ["other_configured"] * 6
)

CAMERA_POOL = (
    ["CAM-01"] * 12 + ["CAM-02"] * 7 + ["CAM-03"] * 8 + ["CAM-04"] * 5 + ["CAM-05"] * 3
)

REASONING = {
    "accident": [
        "sustained fall-like temporal pattern",
        "8 frames of sustained fall-like posture",
        "subject remained on the ground beyond the confirmation window",
    ],
    "violence_fight": [
        "sustained close-contact interaction with elevated motion",
        "7 frames of sustained close contact between two human tracks",
        "repeated rapid movement above the track baseline",
    ],
    "robbery_intrusion": [
        "presence in restricted zone 'restricted-dock-area' during active hours",
        "sustained multi-person interaction near the asset cage",
        "track persisted inside the restricted polygon for 14s",
    ],
    "dangerous_activity": [
        "sustained multi-person interaction",
        "sudden movement above the track baseline",
        "subject lingering in the service corridor",
    ],
    "crowd_anomaly": [
        "crowd count 14 is 2.6x the camera's rolling baseline",
        "human cluster persisted for 38s",
        "simultaneous human count crossed the camera threshold",
    ],
    "vehicle_incident": [
        "repeated human-vehicle interaction",
        "sustained human-vehicle spatial interaction",
        "vehicle stopped across the pedestrian path",
    ],
    "other_configured": [
        "sustained evidence without a matching specialised class",
        "multi-signal pattern persisted across the fusion window",
        "track flagged after repeated corroborating observations",
    ],
}


def reset_rows(force: bool) -> None:
    if not settings.database_url.startswith("sqlite") and not force:
        raise SystemExit(
            "Refusing to clear a non-SQLite database. Re-run with --force if this "
            f"really is a disposable demo database ({settings.database_url})."
        )
    with SessionLocal() as db:
        incidents = db.query(Incident).delete()
        cameras = db.query(Camera).delete()
        observations = db.query(Observation).delete()
        db.commit()
    print(f"Cleared {incidents} incidents, {cameras} cameras, {observations} observations.")


def seed_cameras() -> None:
    with SessionLocal() as db:
        for spec in CAMERAS:
            row = db.get(Camera, spec["camera_id"])
            if row is None:
                row = Camera(camera_id=spec["camera_id"])
                db.add(row)
            row.name = spec["name"]
            row.group = spec["group"]
            row.source = spec["source"]
            row.status = spec["status"]
            row.last_seen = NOW - timedelta(minutes=spec["minutes_ago"])
            row.last_error = spec["last_error"]
        db.commit()
    print(f"Seeded {len(CAMERAS)} cameras.")


def build_metadata(rng: random.Random, incident_type: str) -> dict:
    if incident_type == "vehicle_incident":
        entity_type, category = "car", "vehicle"
    elif incident_type == "other_configured" and rng.random() < 0.4:
        entity_type, category = "dog", "animal"
    else:
        entity_type, category = "person", "human"

    x = rng.randint(80, 1500)
    y = rng.randint(60, 900)
    bbox = [x, y, x + rng.randint(60, 140), y + rng.randint(60, 180)]

    anomaly = incident_type == "crowd_anomaly"
    crowd_count = rng.randint(12, 18) if anomaly else rng.randint(1, 5)
    crowd_baseline = round(rng.uniform(2.0, 6.0), 2)

    return {
        "entity_type": entity_type,
        "category": category,
        "bbox": bbox,
        "pose": {
            "success": rng.random() < 0.8,
            "tier": rng.choice(["FULL_BODY", "UPPER_BODY", "FACE_ONLY", "PARTIAL"]),
            "position": "ground" if incident_type == "accident" else rng.choice(["standing", "standing", "sitting", "bending"]),
            "movement": round(rng.uniform(2.0, 78.0), 1),
        },
        "face": {
            "success": rng.random() < 0.55,
            "quality": rng.choice(["good", "low", "unavailable"]),
            "expression": rng.choice(["neutral", "neutral", "unknown"]),
        },
        "crowd": {
            "count": crowd_count,
            "baseline": crowd_baseline,
            "anomaly": anomaly,
        },
    }


def mark_verified(incident_id: int) -> None:
    with SessionLocal() as db:
        row = db.get(Incident, incident_id)
        if row is not None:
            row.verified = 1
            db.commit()


def seed_incidents(seed: int = 42) -> Counter:
    rng = random.Random(seed)
    types = list(TYPES)
    cameras = list(CAMERA_POOL)
    rng.shuffle(types)
    rng.shuffle(cameras)
    offsets = sorted(OFFSETS)

    camera_ids = [c["camera_id"] for c in CAMERAS]
    counts: Counter = Counter()

    for incident_type, camera_id, minutes in zip(types, cameras, offsets):
        roll = rng.random()
        if roll < 0.42:
            confidence = rng.randint(72, 96)
        elif roll < 0.8:
            confidence = rng.randint(38, 68)
        else:
            confidence = rng.randint(18, 34)

        timestamp = NOW - timedelta(minutes=minutes)
        track_count = 2 if incident_type in {"violence_fight", "crowd_anomaly"} else 1
        track_ids = [str(rng.randint(1, 40)) for _ in range(track_count)]

        bank = REASONING[incident_type]
        reasoning = rng.sample(bank, k=min(len(bank), rng.choice([2, 3])))

        links = []
        if incident_type in {"violence_fight", "robbery_intrusion", "dangerous_activity"} and rng.random() < 0.35:
            other = [c for c in camera_ids if c != camera_id]
            links.append({
                "camera_id": rng.choice(other),
                "track_id": str(rng.randint(1, 40)),
                "similarity": round(rng.uniform(0.79, 0.93), 3),
            })

        evidence_path = None
        if rng.random() < 0.6:
            stamp = timestamp.strftime("%Y%m%d_%H%M%S")
            evidence_path = f"data/events/incident_{stamp}_{camera_id}.mp4"

        incident_id = add_incident({
            "camera_id": camera_id,
            "incident_type": incident_type,
            "confidence": confidence,
            "timestamp": timestamp,
            "track_ids": track_ids,
            "reasoning": reasoning,
            "metadata": build_metadata(rng, incident_type),
            "evidence_path": evidence_path,
            "cross_camera_links": links,
        })
        if rng.random() < 0.22:
            mark_verified(incident_id)
        counts[incident_type] += 1
        print(
            f"  #{incident_id:<3} {timestamp:%d %b %H:%M}  {camera_id}  "
            f"{incident_type:<18} conf={confidence:<3} tracks={','.join(track_ids)}"
        )

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo cameras and incidents for the web console")
    parser.add_argument("--reset", action="store_true", help="Delete existing incidents/cameras/observations first")
    parser.add_argument("--force", action="store_true", help="Allow --reset on a non-SQLite database")
    args = parser.parse_args()

    init_db()

    if args.reset:
        reset_rows(args.force)
    else:
        with SessionLocal() as db:
            existing = db.query(Incident).count()
        if existing:
            print(
                f"Database already contains {existing} incidents. "
                "Re-run with --reset to replace demo data, or delete data/ivi.db for a clean slate."
            )
            return

    seed_cameras()
    counts = seed_incidents()

    print("\nDemo data ready.")
    print(f"  Database: {settings.database_url}")
    for incident_type, count in counts.most_common():
        print(f"  {incident_type:<20} {count}")
    print("\nOpen the console:  uvicorn app.api.main:app --host 127.0.0.1 --port 8000")
    print("Then browse to:    http://127.0.0.1:8000/")


if __name__ == "__main__":
    main()
