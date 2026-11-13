from __future__ import annotations
"""Per-camera processing pipeline.

Wires together every analysis stage required by the brief, in order:

    Detection -> Classification -> Tracking -> Feature extraction
    (pose/face, only when visible) -> Behaviour/temporal analysis (fusion)
    -> Incident classification -> Decision/fusion -> alert + DB write

One `VideoPipeline` instance is created per camera (so per-camera track
state, fusion history and crowd baseline never leak between cameras), but a
single shared `CrossCameraLinker` can be passed in so cross-camera candidate
links are still possible without claiming identity across cameras on weak
evidence.

Each stage is deliberately a thin call into its own module
(`detection`, `classification`, `pose`, `face`, `scene`, `fusion`,
`incidents`, `reid`) so any one of them can be swapped (e.g. a trained
action-recognition model replacing the heuristic in `incidents.py`) without
touching this file.
"""
import time
import logging
from collections import defaultdict
from datetime import datetime

import cv2

from app.core.config import settings, CameraConfig
from app.services.detection import build_detector
from app.services.pose import build_pose_analyzer
from app.services.face import build_face_analyzer
from app.services.tracker import TrackRegistry
from app.services.fusion import FusionEngine
from app.services.alerts import AlertService
from app.services.db import add_incident, add_observations, init_db
from app.services.scene import SceneAnalyzer, CrowdMonitor, check_zone_intrusion
from app.services.classification import classify_entity
from app.services.incidents import classify_incident
from app.services.reid import CrossCameraLinker

log = logging.getLogger(__name__)


class VideoPipeline:
    def __init__(self, camera: CameraConfig | None = None, cross_camera_linker: CrossCameraLinker | None = None):
        init_db()
        self.camera_id = camera.camera_id if camera else settings.camera_id
        self.zones = camera.zones if camera else []

        self.detector = build_detector()
        self.pose = build_pose_analyzer() if settings.enable_pose else None
        self.face = build_face_analyzer()
        self.registry = TrackRegistry()
        self.fusion = FusionEngine()
        self.alerts = AlertService()
        self.scene = SceneAnalyzer()
        self.crowd = CrowdMonitor()
        self.reid = cross_camera_linker  # shared across cameras; None disables cross-camera linking

        self.frame_index = 0
        self.last_face: dict[str, dict] = {}
        self.last_pose: dict[str, dict] = {}
        self.last_event_at: dict[str, float] = defaultdict(float)
        self.last_observation_write = 0.0

    @staticmethod
    def _crop(frame, bbox):
        x1, y1, x2, y2 = bbox
        h, w = frame.shape[:2]
        return frame[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]

    def process(self, frame):
        """Processes one frame for this camera.

        Returns (annotated_frame, tracks, incident_payloads). incident_payloads
        is a list of dicts already written to the DB (the caller/worker is
        only responsible for optionally saving an evidence clip and/or
        forwarding to an alert channel -- both already attempted here, but a
        worker with access to the pre/post frame buffer should still call its
        recorder when `payload["needs_evidence"]` is true).
        """
        self.frame_index += 1
        now = time.time()
        raw_tracks = self.detector.track(frame)
        self.registry.update(raw_tracks, now)
        self.registry.prune(now)

        # --- Classification: every detection gets an explicit coarse category,
        # never guessed below the confidence floor. ------------------------------
        tracks = []
        for tr in raw_tracks:
            cls = classify_entity(tr["entity_type"], tr["confidence"], settings.min_detection_conf)
            tr = dict(tr, category=cls["category"])
            tracks.append(tr)

        output = frame.copy()
        incident_payloads: list[dict] = []
        relationships = self.scene.relationships(tracks)
        observations_to_write = []

        human_count = sum(1 for t in tracks if t["category"] == "human")
        crowd_status = self.crowd.update(self.camera_id, human_count)

        for tr in tracks:
            tid, etype, bbox, category = tr["track_id"], tr["entity_type"], tr["bbox"], tr["category"]
            crop = self._crop(frame, bbox)

            # --- Adaptive analysis: only run pose/face where the data supports it,
            # and only for human entities. Non-human / unknown entities are never
            # pushed through human-specific analysis. --------------------------------
            pose = self.last_pose.get(tid, {"success": False, "tier": "UNKNOWN", "position": "unknown", "movement": 0.0})
            if self.pose and category == "human" and self.frame_index % settings.pose_interval == 0:
                pose = self.pose.analyze(crop)
                self.last_pose[tid] = pose

            face = self.last_face.get(tid, {"success": False, "quality": "not_run"})
            if category == "human" and self.frame_index % settings.face_interval == 0:
                face = self.face.analyze(crop)
                self.last_face[tid] = face

            relation = relationships.get(tid, {})
            zone_hit = check_zone_intrusion(bbox, self.zones) if category == "human" else None

            signal = None
            if pose.get("position") == "ground":
                signal = "fall_candidate"
            if relation.get("collision_candidate"):
                signal = "collision_candidate"

            observation = {
                "entity_type": etype, "category": category, "movement": pose.get("movement", 0),
                "position": pose.get("position", "unknown"), "signal": signal,
                "face": face, "timestamp": now,
                "interaction_candidate": relation.get("interaction_candidate", False),
                "collision_candidate": relation.get("collision_candidate", False),
                "fight_candidate": relation.get("fight_candidate", False),
            }
            decision = self.fusion.update(tid, observation)

            # Cross-camera candidate link (confidence-scored, never a claimed identity).
            link = self.reid.observe(self.camera_id, tid, crop, category) if self.reid and category == "human" else None

            observations_to_write.append({
                "camera_id": self.camera_id, "track_id": tid, "entity_type": etype,
                "category": category, "confidence": tr["confidence"], "timestamp": datetime.utcnow(),
                "bbox": bbox, "analysis": {"visibility_tier": pose.get("tier"), "position": pose.get("position"), "face": face},
            })

            should_raise = decision["event_type"] in {"REVIEW", "INCIDENT_CANDIDATE"} or bool(zone_hit) or relation.get("collision_candidate")
            if should_raise and now - self.last_event_at[tid] >= settings.event_cooldown_seconds:
                self.last_event_at[tid] = now
                incident_type_info = classify_incident(
                    fusion_decision=decision,
                    recent_signals=self.fusion.recent_history(tid),
                    relation=relation,
                    zone_hit=zone_hit,
                    crowd=crowd_status if category == "human" else None,
                    entity_category=category,
                )
                confidence = max(decision["confidence"], 75 if (zone_hit or relation.get("collision_candidate")) else 0)
                payload = {
                    "camera_id": self.camera_id,
                    "incident_type": incident_type_info["incident_type"],
                    "confidence": confidence,
                    "timestamp": datetime.utcnow(),
                    "track_ids": [tid],
                    "reasoning": incident_type_info["reasoning"],
                    "metadata": {"entity_type": etype, "category": category, "bbox": bbox, "pose": pose, "face": face,
                                 "crowd": crowd_status},
                    "cross_camera_links": [link] if link else [],
                }
                incident_id = add_incident(payload)
                payload["incident_id"] = incident_id
                payload["needs_evidence"] = settings.save_event_clips
                self.alerts.send(payload)
                incident_payloads.append(payload)

            # Minimal always-on display: classification label for every track;
            # detailed incident banner only for tracks that actually need review.
            x1, y1, x2, y2 = bbox
            label = f"{category}:{etype} #{tid} {tr['confidence']:.2f}"
            cv2.rectangle(output, (x1, y1), (x2, y2), (0, 220, 180), 2)
            cv2.putText(output, label, (x1, max(18, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 220, 180), 2)
            if decision["event_type"] != "NORMAL":
                cv2.putText(output, decision["event_type"], (x1, min(output.shape[0] - 10, y2 + 20)),
                            cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 80, 255), 2)

        if crowd_status.get("anomaly"):
            cv2.putText(output, f"CROWD ANOMALY ({crowd_status['count']})", (10, 28),
                        cv2.FONT_HERSHEY_SIMPLEX, .7, (0, 80, 255), 2)

        if now - self.last_observation_write >= 1.0:
            add_observations(observations_to_write)
            self.last_observation_write = now

        return output, tracks, incident_payloads
