from __future__ import annotations
"""Multi-camera production entrypoint.

    python run_multi.py                         # all cameras from config/cameras.example.yaml (or CAMERAS_CONFIG)
    python run_multi.py --config config/cameras.example.yaml
    python run_multi.py --camera-id CAM-01       # run only one camera in this process
                                                  # (for OS-level process isolation: run one
                                                  # such process per camera, e.g. one per
                                                  # docker-compose service, all pointed at the
                                                  # same PostgreSQL instance)
    python run_multi.py --no-display             # headless/server mode, no cv2 windows

Architecture: Input Manager (one capture thread per camera, bounded queues,
automatic reconnect/backoff) -> one CameraWorker per camera (own VideoPipeline:
detection -> classification -> tracking -> feature extraction -> temporal
analysis -> incident classification -> fusion/decision -> alert -> DB) ->
shared PostgreSQL/SQLite via app/services/db.py.

Shutdown is a single action: press "q" in any display window, or Ctrl+C /
SIGTERM in a headless run. Both stop every capture thread and every worker
thread cleanly (bounded join timeout) rather than killing the process.
"""
import argparse
import gc
import logging
import signal
import threading
import time

import cv2

from app.core.config import load_camera_configs, settings
from app.core.logging import configure_logging
from app.services.db import init_db
from app.services.input_manager import InputManager
from app.services.reid import CrossCameraLinker
from app.services.worker import CameraWorker

log = logging.getLogger(__name__)


def _tile(frames: dict[str, "cv2.typing.MatLike"], max_cols: int = 2):
    import numpy as np
    if not frames:
        return None
    items = sorted(frames.items())
    cell_w, cell_h = 480, 270
    resized = []
    for cam_id, frame in items:
        f = cv2.resize(frame, (cell_w, cell_h))
        cv2.putText(f, cam_id, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        resized.append(f)
    cols = min(max_cols, len(resized))
    rows = (len(resized) + cols - 1) // cols
    canvas = np.zeros((rows * cell_h, cols * cell_w, 3), dtype="uint8")
    for i, f in enumerate(resized):
        r, c = divmod(i, cols)
        canvas[r * cell_h:(r + 1) * cell_h, c * cell_w:(c + 1) * cell_w] = f
    return canvas


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-camera Intelligent Video Intelligence runner")
    parser.add_argument("--config", default=None, help="Path to cameras YAML config")
    parser.add_argument("--camera-id", default=None, help="Run only this camera (process isolation mode)")
    parser.add_argument("--no-display", action="store_true", help="Headless mode, no cv2 windows")
    args = parser.parse_args()

    configure_logging()
    init_db()

    cameras = load_camera_configs(args.config)
    if args.camera_id:
        cameras = [c for c in cameras if c.camera_id == args.camera_id]
        if not cameras:
            raise SystemExit(f"No enabled camera with camera_id={args.camera_id!r} in config")

    if not cameras:
        raise SystemExit("No enabled cameras configured. See config/cameras.example.yaml")

    log.info("starting %d camera(s): %s", len(cameras), [c.camera_id for c in cameras])

    input_manager = InputManager(cameras)
    stop_event = input_manager.stop_event  # shared: one signal stops capture AND workers
    linker = CrossCameraLinker()
    latest_frames: dict = {}

    workers = {
        cam.camera_id: CameraWorker(
            camera=cam,
            frame_queue=input_manager.streams[cam.camera_id].frame_queue,
            stop_event=stop_event,
            cross_camera_linker=linker,
            latest_frames=latest_frames,
        )
        for cam in cameras
    }

    def handle_signal(signum, _frame):
        log.info("signal %s received, shutting down", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    input_manager.start()
    for w in workers.values():
        w.start()

    last_status_log = 0.0
    last_gc = time.perf_counter()
    try:
        while not stop_event.is_set():
            now = time.perf_counter()

            if not args.no_display and latest_frames:
                tiled = _tile(latest_frames)
                if tiled is not None:
                    cv2.imshow("Intelligent Video Intelligence - multi-camera", tiled)
                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord("q"), 27):
                        log.info("shutdown requested via 'q'")
                        stop_event.set()
                        break
            else:
                # Headless: still need a short sleep so this loop doesn't spin.
                time.sleep(0.05)

            if now - last_status_log >= settings.status_log_interval_seconds:
                health = input_manager.health()
                summary = {cid: {**health.get(cid, {}), **workers[cid].health()} for cid in workers}
                log.info("status: %s", summary)
                last_status_log = now

            if now - last_gc >= settings.gc_interval_seconds:
                gc.collect()
                last_gc = now
    except KeyboardInterrupt:
        log.info("KeyboardInterrupt, shutting down")
        stop_event.set()
    finally:
        input_manager.stop()
        for w in workers.values():
            w.thread.join(timeout=5)
        if not args.no_display:
            cv2.destroyAllWindows()
        log.info("shutdown complete")


if __name__ == "__main__":
    main()
