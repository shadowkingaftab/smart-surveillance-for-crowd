from __future__ import annotations
"""Incident classification taxonomy.

The fusion engine (app/services/fusion.py) decides WHETHER a track has enough
sustained, multi-signal evidence to be a candidate incident at all (NORMAL /
REVIEW / INCIDENT_CANDIDATE). This module decides WHAT KIND of incident it
looks like, so every stored incident carries an explicit, operator-readable
type instead of a bare confidence score.

Every branch here requires the same thing the rest of the project insists on:
multiple corroborating signals, not a single frame or a single cue. When no
specific type fits but the fusion engine still flagged sustained evidence,
the incident is stored as DANGEROUS_ACTIVITY (still true to "do not guess
details you cannot support") rather than invented.
"""

ACCIDENT = "accident"
VIOLENCE_FIGHT = "violence_fight"
ROBBERY_INTRUSION = "robbery_intrusion"
DANGEROUS_ACTIVITY = "dangerous_activity"
CROWD_ANOMALY = "crowd_anomaly"
VEHICLE_INCIDENT = "vehicle_incident"
OTHER_CONFIGURED = "other_configured"


def classify_incident(
    *,
    fusion_decision: dict,
    recent_signals: list[dict],
    relation: dict,
    zone_hit: dict | None,
    crowd: dict | None,
    entity_category: str,
) -> dict:
    """Returns {"incident_type": str, "reasoning": [str, ...]} given everything
    already computed for this track this frame/window. Order matters: more
    specific, higher-evidence categories are checked before the generic
    fallback."""
    reasoning: list[str] = list(fusion_decision.get("reasoning", []))

    # Zone intrusion takes priority when it is the dominant corroborated signal --
    # a person present in a restricted zone during its configured active hours.
    if zone_hit and entity_category == "human":
        reasoning.append(f"presence in restricted zone '{zone_hit['zone']}' during active hours")
        return {"incident_type": ROBBERY_INTRUSION, "reasoning": reasoning}

    # Vehicle proximity/collision signal.
    if relation.get("collision_candidate"):
        reasoning.append("sustained human-vehicle spatial interaction")
        return {"incident_type": VEHICLE_INCIDENT, "reasoning": reasoning}

    # Sustained tight-overlap interaction between two people with repeated fast
    # movement is treated as a fight candidate, never a single frame of contact.
    fight_frames = sum(1 for s in recent_signals if s.get("fight_candidate"))
    high_motion_frames = sum(1 for s in recent_signals if float(s.get("movement", 0)) > 35)
    if fight_frames >= 5 and high_motion_frames >= 3:
        reasoning.append(f"{fight_frames} frames of sustained close contact with elevated motion")
        return {"incident_type": VIOLENCE_FIGHT, "reasoning": reasoning}

    # Sustained fall-like pattern with no vehicle/fight corroboration reads as an
    # accident (e.g. person down), not an assumed assault.
    fall_frames = sum(1 for s in recent_signals if s.get("signal") == "fall_candidate")
    if fall_frames >= 5:
        reasoning.append(f"{fall_frames} frames of sustained fall-like posture")
        return {"incident_type": ACCIDENT, "reasoning": reasoning}

    if crowd and crowd.get("anomaly"):
        reasoning.append(
            f"crowd count {crowd['count']} is {crowd['count'] / max(crowd['baseline'], 0.01):.1f}x the camera's rolling baseline"
        )
        return {"incident_type": CROWD_ANOMALY, "reasoning": reasoning}

    if fusion_decision.get("event_type") == "INCIDENT_CANDIDATE":
        return {"incident_type": DANGEROUS_ACTIVITY, "reasoning": reasoning}

    return {"incident_type": OTHER_CONFIGURED, "reasoning": reasoning}
