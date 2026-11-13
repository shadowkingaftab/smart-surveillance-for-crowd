from __future__ import annotations
"""Cross-camera synchronization (re-identification).

This intentionally does NOT use a learned person-ReID embedding model -- that
would be a reasonable production upgrade, but shipping an unvalidated "this is
definitely the same person" claim is worse than not claiming it. Instead this
module computes a color-histogram similarity between the crop of a newly seen
track and recently seen tracks on OTHER cameras within a short time window,
and only reports a "candidate link" above a configurable similarity
threshold -- always labelled with its confidence, never presented as a
verified identity match.
"""
import time
import cv2
import numpy as np
from dataclasses import dataclass, field
from app.core.config import settings


@dataclass
class _SeenTrack:
    camera_id: str
    track_id: str
    histogram: np.ndarray
    last_seen: float
    entity_category: str


class CrossCameraLinker:
    def __init__(self):
        self._recent: dict[str, _SeenTrack] = {}  # key = f"{camera_id}:{track_id}"

    @staticmethod
    def _histogram(crop) -> np.ndarray | None:
        if crop is None or crop.size == 0:
            return None
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
        cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
        return hist

    def observe(self, camera_id: str, track_id: str, crop, entity_category: str) -> dict | None:
        """Record this track's appearance and return the best cross-camera
        candidate link found (if any), as {"camera_id", "track_id", "similarity"}.
        Never mutates the other camera's track identity -- callers decide
        whether/how to record the link (e.g. as a low-confidence annotation)."""
        if not settings.enable_cross_camera_reid:
            return None
        hist = self._histogram(crop)
        key = f"{camera_id}:{track_id}"
        now = time.time()

        best = None
        if hist is not None:
            for other_key, seen in list(self._recent.items()):
                if seen.camera_id == camera_id:
                    continue  # only cross-camera matches count
                if now - seen.last_seen > settings.reid_match_window_seconds:
                    continue
                if seen.entity_category != entity_category:
                    continue
                score = float(cv2.compareHist(hist, seen.histogram, cv2.HISTCMP_CORREL))
                if score >= settings.reid_similarity_threshold and (best is None or score > best["similarity"]):
                    best = {"camera_id": seen.camera_id, "track_id": seen.track_id, "similarity": round(score, 3)}

            self._recent[key] = _SeenTrack(camera_id, track_id, hist, now, entity_category)

        # Prune stale entries so memory does not grow unbounded across a long run.
        stale_cutoff = now - max(settings.reid_match_window_seconds * 4, 30)
        self._recent = {k: v for k, v in self._recent.items() if v.last_seen >= stale_cutoff}
        return best
