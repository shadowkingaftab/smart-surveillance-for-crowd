from __future__ import annotations
from dataclasses import dataclass
from typing import Any

@dataclass
class TrackState:
    track_id: str
    entity_type: str
    bbox: list[int]
    confidence: float
    last_seen: float

class TrackRegistry:
    """Keeps lightweight metadata for active tracks; detector/tracker owns association."""
    def __init__(self):
        self.active: dict[str, TrackState] = {}

    def update(self, tracks: list[dict[str, Any]], timestamp: float) -> None:
        for t in tracks:
            self.active[t["track_id"]] = TrackState(
                track_id=t["track_id"], entity_type=t["entity_type"],
                bbox=t["bbox"], confidence=t["confidence"], last_seen=timestamp
            )

    def prune(self, now: float, max_age: float = 5.0) -> None:
        self.active = {k: v for k, v in self.active.items() if now - v.last_seen <= max_age}
