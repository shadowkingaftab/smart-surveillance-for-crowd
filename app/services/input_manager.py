from __future__ import annotations
import logging
import queue
import threading
import time
import cv2
from app.core.config import CameraConfig, settings
from app.services.db import upsert_camera

log = logging.getLogger(__name__)


class CameraStream:
    """Owns one camera's capture thread. Frames are pushed into a bounded queue
    so a slow downstream worker cannot cause unbounded memory growth -- when
    the queue is full, the OLDEST frame is dropped in favor of the newest
    (frame sampling/throttling under load, never an unbounded backlog).

    Automatically retries on open/read failure with exponential backoff, and
    reports status via `status` / `last_error` for the dashboard/API and for
    the `cameras` DB table.
    """

    def __init__(self, config: CameraConfig, stop_event: threading.Event):
        self.config = config
        self.stop_event = stop_event
        self.frame_queue: "queue.Queue" = queue.Queue(maxsize=settings.frame_queue_size)
        self.status = "starting"
        self.last_error: str | None = None
        self.last_frame_at = 0.0
        self.thread = threading.Thread(target=self._run, name=f"capture-{config.camera_id}", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _run(self) -> None:
        backoff = settings.reconnect_initial_backoff
        while not self.stop_event.is_set():
            cap = None
            try:
                cap = cv2.VideoCapture(self.config.resolved_source())
                if not cap.isOpened():
                    raise RuntimeError(f"cannot open source: {self.config.source}")
                self.status = "online"
                self.last_error = None
                backoff = settings.reconnect_initial_backoff
                upsert_camera(self.config.camera_id, self.config.name, self.config.group,
                               str(self.config.source), "online")
                log.info("camera %s connected (%s)", self.config.camera_id, self.config.source)

                fps = cap.get(cv2.CAP_PROP_FPS) or (self.config.target_fps or settings.target_fps)
                period = 1.0 / max(fps, 1)
                next_tick = time.perf_counter()

                while not self.stop_event.is_set():
                    ok, frame = cap.read()
                    if not ok:
                        raise RuntimeError("frame read failed (camera disconnected?)")
                    self.last_frame_at = time.time()
                    self._enqueue(frame)

                    next_tick += period
                    delay = next_tick - time.perf_counter()
                    if delay > 0:
                        time.sleep(delay)
                    else:
                        next_tick = time.perf_counter()
            except Exception as exc:  # noqa: BLE001 - any capture failure triggers reconnect
                self.status = "reconnecting"
                self.last_error = str(exc)
                upsert_camera(self.config.camera_id, self.config.name, self.config.group,
                               str(self.config.source), "reconnecting", str(exc))
                log.warning("camera %s error: %s (retry in %.1fs)", self.config.camera_id, exc, backoff)
            finally:
                if cap is not None:
                    cap.release()

            if self.stop_event.is_set():
                break
            # Backoff before reconnecting, capped, so a dead camera cannot busy-loop.
            time.sleep(backoff)
            backoff = min(backoff * 2, settings.max_reconnect_backoff)

        self.status = "stopped"
        upsert_camera(self.config.camera_id, self.config.name, self.config.group,
                       str(self.config.source), "stopped")

    def _enqueue(self, frame) -> None:
        try:
            self.frame_queue.put_nowait(frame)
        except queue.Full:
            try:
                self.frame_queue.get_nowait()  # drop oldest
            except queue.Empty:
                pass
            try:
                self.frame_queue.put_nowait(frame)
            except queue.Full:
                pass  # downstream is fully saturated this tick; skip this frame


class InputManager:
    """Owns one CameraStream per configured camera and the shared stop signal."""

    def __init__(self, cameras: list[CameraConfig]):
        self.stop_event = threading.Event()
        self.streams: dict[str, CameraStream] = {
            c.camera_id: CameraStream(c, self.stop_event) for c in cameras
        }

    def start(self) -> None:
        for stream in self.streams.values():
            stream.start()

    def stop(self) -> None:
        self.stop_event.set()
        for stream in self.streams.values():
            stream.thread.join(timeout=5)

    def health(self) -> dict:
        return {
            cam_id: {"status": s.status, "last_error": s.last_error, "last_frame_at": s.last_frame_at}
            for cam_id, s in self.streams.items()
        }
