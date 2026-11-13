from __future__ import annotations
import os
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    # Testing/demo mode: runs the full pipeline wiring with a synthetic detector
    # instead of loading YOLO/pose/face models, so the system can be smoke-tested
    # end-to-end offline, without GPU, model weights, or real camera hardware.
    demo_mode: bool = _bool("DEMO_MODE", False)
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./data/ivi.db")

    # Legacy single-camera fields (still used by run.py for backward compatibility)
    camera_id: str = os.getenv("CAMERA_ID", "CAM-01")
    camera_name: str = os.getenv("CAMERA_NAME", "Local Camera")
    video_source: str = os.getenv("VIDEO_SOURCE", "0")

    # Multi-camera config file (see config/cameras.example.yaml)
    cameras_config: str = os.getenv("CAMERAS_CONFIG", "")

    target_fps: float = float(os.getenv("TARGET_FPS", "15"))
    detection_interval: int = int(os.getenv("DETECTION_INTERVAL", "1"))
    pose_interval: int = int(os.getenv("POSE_INTERVAL", "2"))
    face_interval: int = int(os.getenv("FACE_INTERVAL", "15"))
    event_pre_seconds: int = int(os.getenv("EVENT_PRE_SECONDS", "10"))
    event_post_seconds: int = int(os.getenv("EVENT_POST_SECONDS", "20"))
    event_cooldown_seconds: int = int(os.getenv("EVENT_COOLDOWN_SECONDS", "10"))
    min_detection_conf: float = float(os.getenv("MIN_DETECTION_CONF", "0.35"))
    min_track_conf: float = float(os.getenv("MIN_TRACK_CONF", "0.35"))
    min_face_size: int = int(os.getenv("MIN_FACE_SIZE", "64"))
    show_all_labels: bool = _bool("SHOW_ALL_LABELS", True)
    enable_face_analysis: bool = _bool("ENABLE_FACE_ANALYSIS", True)
    enable_pose: bool = _bool("ENABLE_POSE", True)
    enable_alerts: bool = _bool("ENABLE_ALERTS", False)
    alert_webhook_url: str = os.getenv("ALERT_WEBHOOK_URL", "")
    detector_model: str = os.getenv("MODEL_DETECTOR", "yolo11n.pt")
    pose_model: str = os.getenv("MODEL_POSE", "yolo11n-pose.pt")
    model_dir: Path = ROOT / "data" / "models"
    events_dir: Path = ROOT / "data" / "events"
    logs_dir: Path = ROOT / "logs"

    # --- Performance / resource controls -----------------------------------------
    frame_queue_size: int = int(os.getenv("FRAME_QUEUE_SIZE", "4"))       # bounds memory per camera
    result_queue_size: int = int(os.getenv("RESULT_QUEUE_SIZE", "8"))
    max_reconnect_backoff: float = float(os.getenv("MAX_RECONNECT_BACKOFF", "30"))
    reconnect_initial_backoff: float = float(os.getenv("RECONNECT_INITIAL_BACKOFF", "1"))
    status_log_interval_seconds: float = float(os.getenv("STATUS_LOG_INTERVAL_SECONDS", "15"))
    gc_interval_seconds: float = float(os.getenv("GC_INTERVAL_SECONDS", "60"))

    # --- Privacy / retention -------------------------------------------------------
    save_event_clips: bool = _bool("SAVE_EVENT_CLIPS", True)
    observation_retention_days: int = int(os.getenv("OBSERVATION_RETENTION_DAYS", "7"))
    incident_retention_days: int = int(os.getenv("INCIDENT_RETENTION_DAYS", "90"))
    evidence_retention_days: int = int(os.getenv("EVIDENCE_RETENTION_DAYS", "30"))

    # --- Cross-camera re-identification --------------------------------------------
    enable_cross_camera_reid: bool = _bool("ENABLE_CROSS_CAMERA_REID", True)
    reid_match_window_seconds: float = float(os.getenv("REID_MATCH_WINDOW_SECONDS", "6"))
    reid_similarity_threshold: float = float(os.getenv("REID_SIMILARITY_THRESHOLD", "0.78"))

    # --- Crowd anomaly baseline -----------------------------------------------------
    crowd_baseline_window: int = int(os.getenv("CROWD_BASELINE_WINDOW", "120"))
    crowd_anomaly_ratio: float = float(os.getenv("CROWD_ANOMALY_RATIO", "2.2"))
    crowd_anomaly_min_count: int = int(os.getenv("CROWD_ANOMALY_MIN_COUNT", "6"))

    def prepare_dirs(self) -> None:
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        (ROOT / "data").mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.prepare_dirs()


@dataclass
class ZoneConfig:
    name: str
    polygon: list[list[int]] = field(default_factory=list)  # [[x,y], ...] in frame pixels
    restricted: bool = False
    active_hours: list[str] | None = None  # e.g. ["22:00", "06:00"] overnight window


@dataclass
class CameraConfig:
    camera_id: str
    name: str
    source: str
    group: str = "default"
    enabled: bool = True
    target_fps: float | None = None
    zones: list[ZoneConfig] = field(default_factory=list)

    def resolved_source(self) -> int | str:
        return int(self.source) if str(self.source).isdigit() else self.source


def _parse_zone(raw: dict[str, Any]) -> ZoneConfig:
    return ZoneConfig(
        name=raw.get("name", "zone"),
        polygon=raw.get("polygon", []),
        restricted=bool(raw.get("restricted", False)),
        active_hours=raw.get("active_hours"),
    )


def load_camera_configs(path: str | None = None) -> list[CameraConfig]:
    """Load multi-camera definitions from YAML. Falls back to the single legacy
    camera (CAMERA_ID / VIDEO_SOURCE) if no config file is given, so existing
    single-camera setups keep working unchanged."""
    cfg_path = Path(path) if path else (Path(settings.cameras_config) if settings.cameras_config else None)
    if not cfg_path or not cfg_path.exists():
        return [CameraConfig(camera_id=settings.camera_id, name=settings.camera_name, source=settings.video_source)]

    with open(cfg_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    cameras: list[CameraConfig] = []
    for item in raw.get("cameras", []):
        cameras.append(CameraConfig(
            camera_id=item["camera_id"],
            name=item.get("name", item["camera_id"]),
            source=str(item["source"]),
            group=item.get("group", "default"),
            enabled=bool(item.get("enabled", True)),
            target_fps=item.get("target_fps"),
            zones=[_parse_zone(z) for z in item.get("zones", [])],
        ))
    return [c for c in cameras if c.enabled]
