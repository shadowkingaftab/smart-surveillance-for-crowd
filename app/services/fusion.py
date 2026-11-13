from __future__ import annotations
from dataclasses import dataclass, field
from collections import deque


@dataclass
class TrackEvidence:
    history: deque = field(default_factory=lambda: deque(maxlen=45))


class FusionEngine:
    """Temporal evidence accumulator. One frame is an observation, not an alert."""

    def __init__(self):
        self.state: dict[str, TrackEvidence] = {}

    def recent_history(self, track_id: str, n: int = 12) -> list[dict]:
        st = self.state.get(track_id)
        return list(st.history)[-n:] if st else []

    def update(self, track_id: str, observation: dict) -> dict:
        st = self.state.setdefault(track_id, TrackEvidence())
        st.history.append(observation)
        h = list(st.history)
        score = 0.0
        reasons = []
        recent = h[-12:]
        if sum(x.get("signal") == "fall_candidate" for x in recent) >= 5:
            score += 55
            reasons.append("sustained fall-like temporal pattern")
        if sum(x.get("signal") == "collision_candidate" for x in recent) >= 2:
            score += 45
            reasons.append("repeated human-vehicle interaction")
        movements = [float(x.get("movement", 0)) for x in recent]
        if len(movements) >= 4 and max(movements[-4:]) > 50:
            score += 20
            reasons.append("sudden movement")
        if sum(bool(x.get("interaction_candidate")) for x in recent) >= 4:
            score += 25
            reasons.append("sustained multi-person interaction")
        fight_frames = sum(bool(x.get("fight_candidate")) for x in recent)
        if fight_frames >= 5:
            score += 40
            reasons.append("sustained close-contact interaction with elevated motion")
        # Face expression is contextual only; it never creates an incident by itself.
        expr = [x.get("face", {}).get("expression") for x in recent if x.get("face", {}).get("success")]
        if expr and expr[-1] in {"fear", "angry"}:
            score += 5
            reasons.append("facial-expression cue (context only)")
        if score >= 70:
            event = "INCIDENT_CANDIDATE"
        elif score >= 35:
            event = "REVIEW"
        else:
            event = "NORMAL"
        return {"event_type": event, "confidence": min(score, 100), "reasoning": reasons}
