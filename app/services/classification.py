from __future__ import annotations
"""Entity classification layer.

The detector (YOLO/COCO) already distinguishes ~80 fine-grained classes. This
module is the explicit, auditable mapping from those fine-grained classes to
the four coarse categories the brief requires -- human / animal / vehicle /
other -- plus a confidence-aware guard: if the detector itself is not
confident, the entity is classified as UNKNOWN rather than guessed.

Keeping this mapping in one small, well-named module (rather than scattered
string checks) is what makes classification "a major feature" instead of an
implicit side effect of the detector's label.
"""

HUMAN = "human"
ANIMAL = "animal"
VEHICLE = "vehicle"
OTHER = "other"
UNKNOWN = "unknown"

_ANIMAL_CLASSES = {
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe",
}
_VEHICLE_CLASSES = {
    "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
}
# Everything else COCO can detect that is neither a person, an animal, nor a vehicle,
# but is still worth reporting (bags, weapons-adjacent objects, furniture, etc.)
# falls through to OTHER with its raw label preserved for operators.


def classify_entity(raw_label: str, confidence: float, min_confidence: float) -> dict:
    """Classify a single detection into the coarse taxonomy.

    This never upgrades a low-confidence detection into a specific category --
    low-confidence detections become UNKNOWN, consistent with the "do not
    guess from insufficient data" requirement.
    """
    label = (raw_label or "").lower().strip()
    if confidence < min_confidence:
        return {"category": UNKNOWN, "raw_label": label, "confidence": confidence}

    if label == "person":
        category = HUMAN
    elif label in _ANIMAL_CLASSES:
        category = ANIMAL
    elif label in _VEHICLE_CLASSES:
        category = VEHICLE
    elif label:
        category = OTHER
    else:
        category = UNKNOWN

    return {"category": category, "raw_label": label, "confidence": confidence}


def is_person(classification: dict) -> bool:
    return classification.get("category") == HUMAN


def is_vehicle(classification: dict) -> bool:
    return classification.get("category") == VEHICLE


def is_animal(classification: dict) -> bool:
    return classification.get("category") == ANIMAL
