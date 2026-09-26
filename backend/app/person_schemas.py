from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

PersonNameText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
PersonRelationshipText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
]
PersonNoteText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=5000),
]
PersonAliasText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]


class PersonCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: PersonNameText
    relationship_label: PersonRelationshipText | None = None
    note: PersonNoteText | None = None
    aliases: list[PersonAliasText] = Field(default_factory=list, max_length=100)


class PersonPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    display_name: PersonNameText | None = None
    relationship_label: PersonRelationshipText | None = None
    note: PersonNoteText | None = None
    aliases: list[PersonAliasText] | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def reject_explicit_null_display_name(self):
        if "display_name" in self.model_fields_set and self.display_name is None:
            raise ValueError("display_name cannot be null")
        return self


class PersonAliasRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    alias: str
    created_at: datetime


class PersonRead(BaseModel):
    id: UUID
    display_name: str
    relationship_label: str | None
    note: str | None
    aliases: list[PersonAliasRead]
    revision: int
    created_at: datetime
    updated_at: datetime
