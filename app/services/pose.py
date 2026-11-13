from __future__ import annotations
import numpy as np
from app.core.config import settings

VIS = 0.5


class DemoPoseAnalyzer:
    """Model-free stand-in used only when `settings.demo_mode` is on. Cycles
    through plausible pose readings so the fusion/incident layers downstream
    have real variation to react to during an offline demo run."""

    _CYCLE = [
        {"success": True, "tier": "FULL_BODY", "position": "standing", "movement": 5.0},
        {"success": True, "tier": "UPPER_BODY", "position": "sitting", "movement": 2.0},
        {"success": True, "tier": "FACE_ONLY", "position": "unknown", "movement": 0.0},
        {"success": False, "tier": "UNKNOWN", "position": "unknown", "movement": 0.0},
    ]

    def __init__(self):
        self._i = 0

    def analyze(self, crop):
        out = dict(self._CYCLE[self._i % len(self._CYCLE)])
        self._i += 1
        return out


class PoseAnalyzer:
    def __init__(self):
        from ultralytics import YOLO  # imported lazily: not required in demo mode
        path = settings.model_dir / settings.pose_model
        self.model = YOLO(str(path) if path.exists() else settings.pose_model)

    def analyze(self, crop):
        if crop is None or crop.size == 0:
            return {"success": False, "tier": "UNKNOWN", "position": "unknown", "movement": 0.0}
        result = self.model(crop, verbose=False)[0]
        if result.keypoints is None or len(result.keypoints) == 0:
            return {"success": False, "tier": "UNKNOWN", "position": "unknown", "movement": 0.0}
        k = result.keypoints[0]
        xy = k.xy[0].cpu().numpy()
        conf = k.conf[0].cpu().numpy() if k.conf is not None else np.ones(len(xy))
        names = {"nose":0,"ls":5,"rs":6,"lh":11,"rh":12,"lk":13,"rk":14,"lw":9,"rw":10}
        def ok(n): return conf[names[n]] >= VIS
        head = ok("nose"); shoulders = ok("ls") or ok("rs"); hips = ok("lh") or ok("rh"); knees = ok("lk") or ok("rk")
        hands = ok("lw") or ok("rw")
        if head and shoulders and hips and knees: tier = "FULL_BODY"
        elif head and shoulders and hips: tier = "UPPER_BODY"
        elif head and shoulders: tier = "FACE_ONLY"
        elif hands: tier = "PARTIAL"
        else: tier = "UNKNOWN"
        position = "unknown"
        if tier in {"FULL_BODY", "UPPER_BODY"}:
            sh = xy[names["ls"]] if ok("ls") else xy[names["rs"]]
            hp = xy[names["lh"]] if ok("lh") else xy[names["rh"]]
            dy, dx = abs(float(hp[1]-sh[1])), abs(float(hp[0]-sh[0]))
            position = "standing" if dy >= dx else "bending"
            if tier == "FULL_BODY":
                kn = xy[names["lk"]] if ok("lk") else xy[names["rk"]]
                if abs(float(kn[1]-hp[1])) < max(dy * 0.22, 8):
                    position = "sitting"
        return {"success": True, "tier": tier, "position": position, "movement": 0.0}


def build_pose_analyzer():
    """Factory used by the pipeline: demo pose analyzer under DEMO_MODE,
    otherwise the real YOLO-pose-backed analyzer."""
    return DemoPoseAnalyzer() if settings.demo_mode else PoseAnalyzer()
