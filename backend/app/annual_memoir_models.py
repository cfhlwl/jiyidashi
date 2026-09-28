from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.annual_summary_models import AnnualSummarySlotKind, AnnualSummaryStatus
from app.life_history_models import LifeHistoryItem
from app.services.answer_trust_service import AnswerTrustState

_TARGET_YEAR_RE = re.compile(r"^\d{4}$")


class AnnualMemoirStatus(StrEnum):
    MEMOIR_READY = "MEMOIR_READY"
    MEMOIR_PARTIAL = "MEMOIR_PARTIAL"
    MEMOIR_EMPTY = "MEMOIR_EMPTY"


class AnnualMemoirRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_year: str

    @field_validator("target_year")
    @classmethod
    def validate_target_year(cls, value: str) -> str:
        if _TARGET_YEAR_RE.fullmatch(value) is None:
            raise ValueError("target_year must be strict YYYY")
        year = int(value)
        if not 1 <= year <= 9998:
            raise ValueError("target_year is outside the supported calendar range")
        return value


class AnnualMemoirCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot: str
    kind: AnnualSummarySlotKind
    memory_id: UUID | None
    visit_id: UUID | None
    trust_state: AnswerTrustState | None


class AnnualMemoirPhotoItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_id: UUID
    media_id: UUID
    occurred_at: datetime
    title: str | None
    content_type: str


class AnnualMemoirPhotoPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str
    target_year: str
    items: list[AnnualMemoirPhotoItem] = Field(default_factory=list)
    next_cursor: str | None = None


class AnnualMemoirResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AnnualMemoirStatus
    target_year: str
    timezone: str

    narrative_status: AnnualSummaryStatus
    narrative: str | None
    narrative_citations: list[AnnualMemoirCitation] = Field(default_factory=list)

    timeline_items: list[LifeHistoryItem] = Field(default_factory=list)
    timeline_next_cursor: str | None

    photo_items: list[AnnualMemoirPhotoItem] = Field(default_factory=list)
    photo_next_cursor: str | None
