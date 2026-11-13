from __future__ import annotations
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.core.config import ROOT, settings
from app.services.db import init_db, list_events, list_cameras, list_incidents
from app.services.privacy import run_retention_sweep
from app.models.schema import HealthResponse

app = FastAPI(title="Intelligent Video Intelligence API", version="1.1.0")

# The console is served same-origin from this app; these origins are only for
# running the static files from a separate dev server (e.g. Live Server/Vite).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000", "http://localhost:8000",
        "http://127.0.0.1:5500", "http://localhost:5500",
        "http://127.0.0.1:5173", "http://localhost:5173",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok", camera_id=settings.camera_id, database=settings.database_url.split(":", 1)[0])


@app.get("/cameras")
def cameras():
    """Status of every camera known to the system (online/reconnecting/stopped,
    last frame time, last error) -- populated by the input manager as each
    camera stream connects, drops, or reconnects."""
    return list_cameras()


@app.get("/incidents")
def incidents(
    limit: int = Query(100, ge=1, le=500),
    camera_id: str | None = None,
    incident_type: str | None = None,
):
    """Stored incidents (accident / violence_fight / robbery_intrusion /
    dangerous_activity / crowd_anomaly / vehicle_incident / other_configured),
    optionally filtered by camera or incident type."""
    return list_incidents(limit=limit, camera_id=camera_id, incident_type=incident_type)


@app.get("/events")
def events(limit: int = 100):
    """Deprecated alias for /incidents (kept for backward compatibility with
    earlier single-camera deployments that polled this path)."""
    return list_events(max(1, min(limit, 500)))


@app.post("/retention/run")
def run_retention():
    """Triggers the configured privacy retention sweep immediately (observations,
    incidents, and evidence clips older than their configured windows). Also
    runs automatically on a schedule when `tools/retention_cleanup.py` is
    invoked via cron/systemd timer/Task Scheduler."""
    return run_retention_sweep()


# Mount the operator console at the root, after all API routes so /health,
# /cameras, /incidents, /docs etc. keep resolving first.
_frontend_dir = ROOT / "frontend"
if _frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="console")
