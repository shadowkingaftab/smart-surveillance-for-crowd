from __future__ import annotations
from collections import deque
from pathlib import Path
from datetime import datetime
import cv2
from app.core.config import settings

class EvidenceRecorder:
    def __init__(self, fps: float):
        self.fps = max(1.0, fps)
        self.buffer = deque(maxlen=max(1, int(settings.event_pre_seconds * self.fps)))

    def add(self, frame): self.buffer.append(frame.copy())

    def snapshot(self):
        """Captures the current pre-event rolling buffer immediately (e.g. the
        instant an incident fires), so it can be combined with post-event
        frames later without being overwritten by the rolling buffer in the
        meantime (the buffer keeps accumulating while the post-event window
        elapses)."""
        return list(self.buffer)

    def save(self, frames_after: list, event_type: str, pre_frames: list | None = None):
        frames = (pre_frames if pre_frames is not None else list(self.buffer)) + [f.copy() for f in frames_after]
        if not frames: return None
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        path = settings.events_dir / f"{stamp}_{event_type}.mp4"
        h, w = frames[0].shape[:2]
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), self.fps, (w, h))
        if not writer.isOpened(): return None
        try:
            for frame in frames: writer.write(frame)
        finally:
            writer.release()
        return str(path)
