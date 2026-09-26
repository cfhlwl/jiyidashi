from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.person_relationship_models import PersonRelationshipKind

RelationshipLabelText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
]
RelationshipNoteText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=5000),
]


class PersonRelationshipCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_a_id: UUID
    person_b_id: UUID
    relationship_kind: PersonRelationshipKind
    custom_label: RelationshipLabelText | None = None
    note: RelationshipNoteText | None = None

    @model_validator(mode="after")
    def validate_relation_shape(self):
        if self.person_a_id == self.person_b_id:
            raise ValueError("self relationships are not allowed")
        if self.relationship_kind == PersonRelationshipKind.OTHER:
            if self.custom_label is None:
                raise ValueError("OTHER requires custom_label")
        elif self.custom_label is not None:
            raise ValueError("custom_label is only allowed for OTHER")
        return self


class PersonRelationshipPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    relationship_kind: PersonRelationshipKind | None = None
    custom_label: RelationshipLabelText | None = None
    note: RelationshipNoteText | None = None


class PersonRelationshipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    person_a_id: UUID
    person_b_id: UUID
    relationship_kind: PersonRelationshipKind
    custom_label: str | None
    note: str | None
    revision: int
    created_at: datetime
    updated_at: datetime


class PersonRelationshipOtherPerson(BaseModel):
    id: UUID
    display_name: str


class PersonRelationshipProjection(BaseModel):
    relationship_id: UUID
    relationship_kind: PersonRelationshipKind
    custom_label: str | None
    note: str | None
    revision: int
    other_person: PersonRelationshipOtherPerson
    created_at: datetime
    updated_at: datetime
