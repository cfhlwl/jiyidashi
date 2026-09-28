from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from app.life_event_models import LifeEventKind
from app.life_stage_models import LifeStageKind


class LifeHistoryItemKind(StrEnum):
    LIFE_EVENT = "LIFE_EVENT"
    LIFE_STAGE_STARTED = "LIFE_STAGE_STARTED"
    LIFE_STAGE_ENDED = "LIFE_STAGE_ENDED"


class LifeHistoryItem(BaseModel):
    kind: LifeHistoryItemKind
    occurred_at: datetime
    title: str
    custom_label: str | None

    life_event_id: UUID | None = None
    event_kind: LifeEventKind | None = None
    event_ended_at: datetime | None = None
    place_id: UUID | None = None

    life_stage_id: UUID | None = None
    stage_kind: LifeStageKind | None = None


class LifeHistoryTimelineResponse(BaseModel):
    timezone: str
    start_year: int
    end_year: int
    as_of: datetime
    items: list[LifeHistoryItem] = Field(default_factory=list)
    next_cursor: str | None = None
