from __future__ import annotations
import logging
from app.core.config import settings

log = logging.getLogger(__name__)


class DemoFaceAnalyzer:
    """Model-free stand-in used only when `settings.demo_mode` is on -- never
    claims a usable face analysis (face expression is context-only everywhere
    else in this system anyway), so demo runs never fabricate emotion data."""

    def analyze(self, crop):
        return {"success": False, "quality": "unavailable_demo_mode"}


class FaceAnalyzer:
    def analyze(self, crop):
        if not settings.enable_face_analysis or crop is None or crop.size == 0:
            return {"success": False, "quality": "unavailable"}
        h, w = crop.shape[:2]
        if min(h, w) < settings.min_face_size:
            return {"success": False, "quality": "too_small"}
        try:
            from deepface import DeepFace  # imported lazily: not required in demo mode
            result = DeepFace.analyze(crop, actions=["emotion"], enforce_detection=False, silent=True)
            if isinstance(result, list): result = result[0]
            return {
                "success": True,
                "quality": "usable",
                "expression": result.get("dominant_emotion", "unknown"),
                "expression_scores": result.get("emotion", {}),
            }
        except Exception as exc:
            log.debug("face analysis failed: %s", exc)
            return {"success": False, "quality": "analysis_failed"}


def build_face_analyzer():
    """Factory used by the pipeline: demo face analyzer under DEMO_MODE,
    otherwise the real DeepFace-backed analyzer."""
    return DemoFaceAnalyzer() if settings.demo_mode else FaceAnalyzer()
