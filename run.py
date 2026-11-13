from __future__ import annotations
import argparse, time, logging
import cv2
from app.core.config import settings
from app.core.logging import configure_logging
from app.services.pipeline import VideoPipeline
from app.services.recorder import EvidenceRecorder

log = logging.getLogger(__name__)

def source_value(value: str):
    return int(value) if value.isdigit() else value

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=settings.video_source)
    parser.add_argument("--no-display", action="store_true")
    args = parser.parse_args()
    configure_logging()
    cap = cv2.VideoCapture(source_value(args.source))
    if not cap.isOpened(): raise RuntimeError(f"Cannot open video source: {args.source}")
    fps = cap.get(cv2.CAP_PROP_FPS) or settings.target_fps
    recorder = EvidenceRecorder(fps)
    pipeline = VideoPipeline()
    period = 1.0 / max(settings.target_fps, 1)
    next_tick = time.perf_counter()
    try:
        while True:
            ok, frame = cap.read()
            if not ok: break
            recorder.add(frame)
            output, tracks, events = pipeline.process(frame)
            if not args.no_display:
                cv2.imshow("Intelligent Video Intelligence", output)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27): break
            next_tick += period
            delay = next_tick - time.perf_counter()
            if delay > 0: time.sleep(delay)
            else: next_tick = time.perf_counter()
    except KeyboardInterrupt:
        log.info("Shutdown requested")
    finally:
        cap.release(); cv2.destroyAllWindows()

if __name__ == "__main__": main()
