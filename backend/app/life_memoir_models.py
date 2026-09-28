from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.life_stage_models import LifeStageKind
from app.long_term_reasoning_models import LongTermEvidenceKind, LongTermReasoningStatus
from app.services.answer_trust_service import AnswerTrustState


class LifeMemoirChapterStatus(StrEnum):
    CHAPTER_READY = "CHAPTER_READY"
    CHAPTER_EMPTY = "CHAPTER_EMPTY"
    CHAPTER_PARTIAL = "CHAPTER_PARTIAL"


class LifeMemoirStageIndexItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    life_stage_id: UUID
    stage_kind: LifeStageKind
    title: str
    custom_label: str | None
    started_at: datetime
    ended_at: datetime | None


class LifeMemoirStageIndexResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[LifeMemoirStageIndexItem] = Field(default_factory=list)
    next_cursor: str | None = None


class LifeMemoirCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot: str
    kind: LongTermEvidenceKind
    life_stage_id: UUID
    life_event_id: UUID | None
    memory_id: UUID | None
    memory_source_id: UUID | None
    memory_trust_state: AnswerTrustState | None


class LifeMemoirChapterResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: LifeMemoirChapterStatus
    life_stage_id: UUID
    reasoning_status: LongTermReasoningStatus
    narrative: str | None
    citations: list[LifeMemoirCitation] = Field(default_factory=list)
