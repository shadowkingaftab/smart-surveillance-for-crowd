from __future__ import annotations
import logging
from app.core.config import settings
from app.services import db

log = logging.getLogger(__name__)


def run_retention_sweep() -> dict:
    """Applies the configured retention windows:
    - observations (per-frame entity detections) purge first and fastest, since
      they are the highest-volume, lowest-sensitivity-justification data.
    - incidents (confirmed/candidate events) purge on a longer window, since
      they may be needed for review.
    - evidence clips purge on their own window and are swept both by DB
      reference and by a filesystem sweep, so a clip is never retained purely
      because its DB row was deleted by some other path.
    """
    obs_deleted = db.purge_observations_older_than(settings.observation_retention_days)
    incidents_deleted, evidence_paths = db.purge_incidents_older_than(settings.incident_retention_days)

    removed_named = 0
    for p in evidence_paths:
        try:
            from pathlib import Path
            path = Path(p)
            if path.exists():
                path.unlink()
                removed_named += 1
        except OSError as exc:
            log.warning("failed to remove evidence file referenced by deleted incident: %s", exc)

    removed_orphan = db.purge_orphan_evidence(settings.events_dir, settings.evidence_retention_days)

    summary = {
        "observations_deleted": obs_deleted,
        "incidents_deleted": incidents_deleted,
        "evidence_files_deleted_with_incident": removed_named,
        "evidence_files_deleted_orphan_sweep": removed_orphan,
    }
    log.info("retention sweep complete: %s", summary)
    return summary
