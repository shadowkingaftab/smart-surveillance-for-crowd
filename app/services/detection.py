from __future__ import annotations
import logging
import math
import time
from pathlib import Path
from app.core.config import settings

log = logging.getLogger(__name__)


class DemoDetector:
    """Synthetic, model-free stand-in for `Detector`, used only when
    `settings.demo_mode` is on. Produces a handful of moving boxes with stable
    track ids and mixed entity classes (person/car/dog) so the rest of the
    pipeline (classification, tracking, fusion, incidents, DB, dashboard, API)
    can be exercised end-to-end without GPU hardware, model weights, or a
    network connection -- this is the "testing/demo mode" required by the
    brief, not a substitute for the real detector in production.
    """

    _ENTITIES = [("person", 0), ("person", 0), ("car", 2), ("dog", 16)]

    def __init__(self):
        self.names = {0: "person", 2: "car", 16: "dog"}
        self._t0 = time.time()
        log.warning("DEMO_MODE is on: using a synthetic detector, not a real model.")

    def track(self, frame):
        h, w = frame.shape[:2] if frame is not None else (480, 640)
        t = time.time() - self._t0
        out = []
        for i, (label, cls_id) in enumerate(self._ENTITIES):
            phase = i * 1.3
            cx = w * 0.5 + math.sin(t * 0.5 + phase) * (w * 0.3)
            cy = h * 0.5 + math.cos(t * 0.35 + phase) * (h * 0.25)
            bw, bh = (60, 140) if label == "person" else (90, 60)
            x1, y1 = int(max(0, cx - bw / 2)), int(max(0, cy - bh / 2))
            x2, y2 = int(min(w, cx + bw / 2)), int(min(h, cy + bh / 2))
            out.append({
                "track_id": str(i + 1),
                "entity_type": label,
                "class_id": cls_id,
                "confidence": 0.9,
                "bbox": [x1, y1, x2, y2],
            })
        return out


class Detector:
    def __init__(self):
        from ultralytics import YOLO  # imported lazily: not needed/installed-required in demo mode
        model_path = Path(settings.model_dir) / settings.detector_model
        self.model = YOLO(str(model_path) if model_path.exists() else settings.detector_model)
        self.names = self.model.names

    def track(self, frame):
        results = self.model.track(
            frame, persist=True, tracker="bytetrack.yaml", verbose=False,
            conf=settings.min_detection_conf, iou=0.5
        )
        result = results[0]
        out = []
        boxes = result.boxes
        if boxes is None:
            return out
        ids = boxes.id.int().cpu().tolist() if boxes.id is not None else list(range(len(boxes)))
        for i, box in enumerate(boxes):
            cls_id = int(box.cls.item())
            conf = float(box.conf.item())
            xyxy = [int(x) for x in box.xyxy[0].tolist()]
            out.append({
                "track_id": str(ids[i]),
                "entity_type": str(self.names.get(cls_id, cls_id)),
                "class_id": cls_id,
                "confidence": conf,
                "bbox": xyxy,
            })
        return out


def build_detector():
    """Factory used by the pipeline: returns the synthetic demo detector when
    `DEMO_MODE=true`, otherwise the real YOLO-backed detector."""
    return DemoDetector() if settings.demo_mode else Detector()
