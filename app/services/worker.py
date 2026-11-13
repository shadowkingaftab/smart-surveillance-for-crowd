from __future__ import annotations
"""Per-camera processing worker.

One `CameraWorker` owns one `VideoPipeline` and consumes frames from the
matching `CameraStream.frame_queue` (see `input_manager.py`) on its own
thread, so a slow or crashing camera's processing can never block another
camera's. A single malformed frame or a transient analysis error is caught,
logged, and skipped -- it never crashes the worker thread or takes down the
whole process (per the brief's "application must not become unresponsive"
and "automatic recovery" requirements).
"""
import logging
import queue
import threading
import time

import cv2

from app.core.config import CameraConfig, settings
from app.services.pipeline import VideoPipeline
from app.services.recorder import EvidenceRecorder
from app.services.reid import CrossCameraLinker

log = logging.getLogger(__name__)


class CameraWorker:
    def __init__(self, camera: CameraConfig, frame_queue: "queue.Queue", stop_event: threading.Event,
                 cross_camera_linker: CrossCameraLinker | None = None, latest_frames: dict | None = None):
        self.camera = camera
        self.frame_queue = frame_queue
        self.stop_event = stop_event
        self.pipeline = VideoPipeline(camera=camera, cross_camera_linker=cross_camera_linker)
        self.recorder = EvidenceRecorder(camera.target_fps or settings.target_fps)
        # Optional shared dict the display/dashboard layer can read the latest
        # annotated frame from, keyed by camera_id -- avoids every worker
        # needing its own cv2.imshow window when running many cameras.
        self.latest_frames = latest_frames
        self._pending_evidence_pre: list | None = None
        self._pending_evidence_post: list = []
        self._pending_evidence_frames_left = 0
        self.frames_processed = 0
        self.errors = 0
        self.thread = threading.Thread(target=self._run, name=f"worker-{camera.camera_id}", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _run(self) -> None:
        log.info("worker started for camera %s", self.camera.camera_id)
        while not self.stop_event.is_set():
            try:
                frame = self.frame_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.recorder.add(frame)
                output, _tracks, incidents = self.pipeline.process(frame)
                self.frames_processed += 1

                for payload in incidents:
                    if payload.get("needs_evidence") and self._pending_evidence_pre is None:
                        # Snapshot the pre-event buffer the instant the incident
                        # fires, then keep collecting post-event frames for a
                        # fixed window before writing the clip once -- never
                        # blocks this worker loop on a synchronous save, and
                        # never lets a second incident mid-window restart the
                        # clip (first incident in a window owns the clip).
                        self._pending_evidence_pre = self.recorder.snapshot()
                        self._pending_evidence_post = []
                        self._pending_evidence_frames_left = max(1, int(
                            settings.event_post_seconds * (self.camera.target_fps or settings.target_fps)
                        ))

                if self._pending_evidence_frames_left > 0:
                    self._pending_evidence_post.append(frame)
                    self._pending_evidence_frames_left -= 1
                    if self._pending_evidence_frames_left == 0:
                        path = self.recorder.save(
                            self._pending_evidence_post, "incident", pre_frames=self._pending_evidence_pre
                        )
                        if path:
                            log.info("evidence clip saved: %s", path)
                        self._pending_evidence_pre = None
                        self._pending_evidence_post = []

                if self.latest_frames is not None:
                    self.latest_frames[self.camera.camera_id] = output
            except Exception:  # noqa: BLE001 - one bad frame must never kill the worker
                self.errors += 1
                log.exception("camera %s: frame processing error (continuing)", self.camera.camera_id)
                time.sleep(0.05)

        log.info("worker stopped for camera %s (frames=%d errors=%d)",
                  self.camera.camera_id, self.frames_processed, self.errors)

    def health(self) -> dict:
        return {"frames_processed": self.frames_processed, "errors": self.errors}
