from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.life_event_models import LifeEventKind
from app.models import MemoryType, SourceType

LifeEventTitle = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=240),
]
LifeEventCustomLabel = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
]
LifeEventNote = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=5000),
]


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


class LifeEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_kind: LifeEventKind
    title: LifeEventTitle
    custom_label: LifeEventCustomLabel | None = None
    note: LifeEventNote | None = None
    started_at: datetime
    ended_at: datetime | None = None
    place_id: UUID | None = None

    @model_validator(mode="after")
    def validate_contract(self):
        if not _is_aware(self.started_at):
            raise ValueError("started_at must be timezone-aware")
        if self.ended_at is not None:
            if not _is_aware(self.ended_at):
                raise ValueError("ended_at must be timezone-aware")
            if self.ended_at < self.started_at:
                raise ValueError("ended_at must be greater than or equal to started_at")
        if self.event_kind == LifeEventKind.OTHER:
            if self.custom_label is None:
                raise ValueError("OTHER requires custom_label")
        elif self.custom_label is not None:
            raise ValueError("custom_label is valid only for OTHER")
        return self


class LifeEventPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    event_kind: LifeEventKind | None = None
    title: LifeEventTitle | None = None
    custom_label: LifeEventCustomLabel | None = None
    note: LifeEventNote | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    place_id: UUID | None = None

    @model_validator(mode="after")
    def validate_patch_scalars(self):
        for required in ("event_kind", "title", "started_at"):
            if required in self.model_fields_set and getattr(self, required) is None:
                raise ValueError(f"{required} cannot be null")
        for field in ("started_at", "ended_at"):
            if field in self.model_fields_set:
                value = getattr(self, field)
                if value is not None and not _is_aware(value):
                    raise ValueError(f"{field} must be timezone-aware")
        return self


class LifeEventRead(BaseModel):
    id: UUID
    event_kind: LifeEventKind
    title: str
    custom_label: str | None
    note: str | None
    started_at: datetime
    ended_at: datetime | None
    place_id: UUID | None
    revision: int
    created_at: datetime
    updated_at: datetime


class LifeEventMemoryEvidenceRead(BaseModel):
    link_id: UUID
    memory_id: UUID
    memory_type: MemoryType
    title: str | None
    content: str
    occurred_at: datetime
    source_type: SourceType
    created_at: datetime
