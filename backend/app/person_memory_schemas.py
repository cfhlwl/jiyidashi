from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models import MemoryType
from app.person_memory_models import PersonMemoryRelationKind


class PersonMemoryLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relation_kind: PersonMemoryRelationKind


class PersonMemoryLinkPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relation_kind: PersonMemoryRelationKind
    expected_revision: int = Field(ge=0)


class PersonMemoryLinkRead(BaseModel):
    id: UUID
    person_id: UUID
    memory_id: UUID
    relation_kind: PersonMemoryRelationKind
    revision: int
    created_at: datetime
    updated_at: datetime


class PersonMemoryTimelineRow(PersonMemoryLinkRead):
    occurred_at: datetime
    memory_title: str | None
    memory_content: str
    memory_type: MemoryType


class PersonInteractionRow(PersonMemoryLinkRead):
    person_display_name: str
    occurred_at: datetime
