from __future__ import annotations
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field

class EntityObservation(BaseModel):
    camera_id: str
    track_id: str
    entity_type: str
    confidence: float
    bbox: list[int]
    timestamp: datetime
    visibility_tier: str = "UNKNOWN"
    analysis: dict[str, Any] = Field(default_factory=dict)

class EventCreate(BaseModel):
    camera_id: str
    event_type: str
    confidence: float
    timestamp: datetime
    track_ids: list[str] = Field(default_factory=list)
    reasoning: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

class HealthResponse(BaseModel):
    status: str
    camera_id: str
    database: str
