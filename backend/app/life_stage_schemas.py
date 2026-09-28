from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.life_event_models import LifeEventKind
from app.life_stage_models import LifeStageKind

LifeStageTitle = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=240),
]
LifeStageCustomLabel = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
]
LifeStageNote = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=5000),
]


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


class LifeStageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_kind: LifeStageKind
    title: LifeStageTitle
    custom_label: LifeStageCustomLabel | None = None
    note: LifeStageNote | None = None
    started_at: datetime
    ended_at: datetime | None = None

    @model_validator(mode="after")
    def validate_contract(self):
        if not _is_aware(self.started_at):
            raise ValueError("started_at must be timezone-aware")
        if self.ended_at is not None:
            if not _is_aware(self.ended_at):
                raise ValueError("ended_at must be timezone-aware")
            if self.ended_at < self.started_at:
                raise ValueError("ended_at must be greater than or equal to started_at")
        if self.stage_kind == LifeStageKind.OTHER:
            if self.custom_label is None:
                raise ValueError("OTHER requires custom_label")
        elif self.custom_label is not None:
            raise ValueError("custom_label is valid only for OTHER")
        return self


class LifeStagePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    stage_kind: LifeStageKind | None = None
    title: LifeStageTitle | None = None
    custom_label: LifeStageCustomLabel | None = None
    note: LifeStageNote | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None

    @model_validator(mode="after")
    def validate_patch_scalars(self):
        for required in ("stage_kind", "title", "started_at"):
            if required in self.model_fields_set and getattr(self, required) is None:
                raise ValueError(f"{required} cannot be null")
        for field in ("started_at", "ended_at"):
            if field in self.model_fields_set:
                value = getattr(self, field)
                if value is not None and not _is_aware(value):
                    raise ValueError(f"{field} must be timezone-aware")
        return self


class LifeStageRead(BaseModel):
    id: UUID
    stage_kind: LifeStageKind
    title: str
    custom_label: str | None
    note: str | None
    started_at: datetime
    ended_at: datetime | None
    revision: int
    created_at: datetime
    updated_at: datetime


class LifeStageEventEvidenceRead(BaseModel):
    link_id: UUID
    life_event_id: UUID
    event_kind: LifeEventKind
    title: str
    custom_label: str | None
    note: str | None
    started_at: datetime
    ended_at: datetime | None
    place_id: UUID | None
    created_at: datetime
