from __future__ import annotations
from math import hypot
from collections import deque, defaultdict
from datetime import datetime, time as dtime
from app.core.config import settings, ZoneConfig


class SceneAnalyzer:
    """Lightweight scene-level relationships; expensive incident models can replace this later."""

    @staticmethod
    def center(b):
        return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)

    @staticmethod
    def iou(a, b):
        x1 = max(a[0], b[0]); y1 = max(a[1], b[1]); x2 = min(a[2], b[2]); y2 = min(a[3], b[3])
        inter = max(0, x2 - x1) * max(0, y2 - y1)
        aa = max(1, (a[2] - a[0]) * (a[3] - a[1])); ab = max(1, (b[2] - b[0]) * (b[3] - b[1]))
        return inter / (aa + ab - inter)

    def relationships(self, tracks):
        """Pairwise proximity signals between detected entities, classification-aware."""
        out = {t["track_id"]: {"interaction_candidate": False, "collision_candidate": False,
                                "fight_candidate": False} for t in tracks}
        for i, a in enumerate(tracks):
            for b in tracks[i + 1:]:
                a_cat = a.get("category"); b_cat = b.get("category")
                near = self.iou(a["bbox"], b["bbox"]) > 0.02
                if not near:
                    ca = self.center(a["bbox"]); cb = self.center(b["bbox"])
                    near = hypot(ca[0] - cb[0], ca[1] - cb[1]) < max(
                        a["bbox"][2] - a["bbox"][0], b["bbox"][2] - b["bbox"][0]) * 0.9
                if near and a_cat == "human" and b_cat == "human":
                    out[a["track_id"]]["interaction_candidate"] = True
                    out[b["track_id"]]["interaction_candidate"] = True
                    # Tight overlap (bodies occupying near-identical space) + both tracked
                    # is one of several signals fusion uses for a fight candidate; it never
                    # decides violence on its own.
                    if self.iou(a["bbox"], b["bbox"]) > 0.15:
                        out[a["track_id"]]["fight_candidate"] = True
                        out[b["track_id"]]["fight_candidate"] = True
                if near and a_cat == "vehicle" and b_cat == "human" or near and a_cat == "human" and b_cat == "vehicle":
                    out[a["track_id"]]["collision_candidate"] = True
                    out[b["track_id"]]["collision_candidate"] = True
        return out


class CrowdMonitor:
    """Tracks a rolling per-camera baseline of simultaneous human count so a crowd
    spike can be flagged as an anomaly relative to that location's normal traffic,
    instead of an arbitrary fixed threshold."""

    def __init__(self, window: int | None = None, ratio: float | None = None, min_count: int | None = None):
        self.window = window or settings.crowd_baseline_window
        self.ratio = ratio or settings.crowd_anomaly_ratio
        self.min_count = min_count or settings.crowd_anomaly_min_count
        self._history: dict[str, deque] = defaultdict(lambda: deque(maxlen=self.window))

    def update(self, camera_id: str, human_count: int) -> dict:
        hist = self._history[camera_id]
        baseline = (sum(hist) / len(hist)) if hist else human_count
        anomaly = human_count >= self.min_count and baseline > 0 and human_count >= baseline * self.ratio
        hist.append(human_count)
        return {"count": human_count, "baseline": round(baseline, 2), "anomaly": bool(anomaly)}


def _point_in_polygon(point: tuple[float, float], polygon: list[list[int]]) -> bool:
    if len(polygon) < 3:
        return False
    x, y = point
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi):
            inside = not inside
        j = i
    return inside


def _within_active_hours(active_hours: list[str] | None, now: dtime | None = None) -> bool:
    if not active_hours or len(active_hours) != 2:
        return True  # no restriction configured -> always active
    now = now or datetime.now().time()
    start = dtime.fromisoformat(active_hours[0])
    end = dtime.fromisoformat(active_hours[1])
    if start <= end:
        return start <= now <= end
    return now >= start or now <= end  # overnight window, e.g. 22:00 -> 06:00


def check_zone_intrusion(bbox: list[int], zones: list[ZoneConfig]) -> dict | None:
    """Returns the restricted zone a bbox center currently falls inside, honoring
    the zone's active-hours window, or None if there is no intrusion."""
    for zone in zones:
        if not zone.restricted or not zone.polygon:
            continue
        if not _within_active_hours(zone.active_hours):
            continue
        cx = (bbox[0] + bbox[2]) / 2
        cy = (bbox[1] + bbox[3]) / 2
        if _point_in_polygon((cx, cy), zone.polygon):
            return {"zone": zone.name}
    return None
