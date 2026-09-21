"""Candidate-only contracts for Stage 3 entity extraction and linking.

Extracted values are AI inference metadata, never trusted personal facts. Only an
unambiguous owner-scoped Object/Place match may reference an existing entity.
"""

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EntityKind(StrEnum):
    OBJECT = "OBJECT"
    PLACE = "PLACE"
    PERSON = "PERSON"
    TIME = "TIME"
    EVENT = "EVENT"


class EntityLinkStatus(StrEnum):
    LINKED = "LINKED"
    UNRESOLVED = "UNRESOLVED"


class EntityLinkReason(StrEnum):
    EXACT_MATCH = "EXACT_MATCH"
    NORMALIZED_MATCH = "NORMALIZED_MATCH"
    AMBIGUOUS = "AMBIGUOUS"
    NO_MATCH = "NO_MATCH"
    NOT_LINKABLE = "NOT_LINKABLE"


class EntityInferenceProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gateway_request_id: str
    purpose: str
    provider_request_id: str | None = None
    provider: str
    model: str
    trust_class: Literal["inference"] = "inference"


class EntityCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: EntityKind
    text: str = Field(min_length=1, max_length=200)
    normalized_text: str = Field(min_length=1, max_length=200)
    provenance: EntityInferenceProvenance


class EntityExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[EntityCandidate] = Field(default_factory=list, max_length=20)


class LinkedEntityReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: EntityKind
    entity_id: UUID
    canonical_name: str


class EntityLinkResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate: EntityCandidate
    status: EntityLinkStatus
    reason: EntityLinkReason
    linked_entity: LinkedEntityReference | None = None

    @model_validator(mode="after")
    def validate_link_state(self):
        linked_reasons = {
            EntityLinkReason.EXACT_MATCH,
            EntityLinkReason.NORMALIZED_MATCH,
        }
        if self.status == EntityLinkStatus.LINKED:
            if self.linked_entity is None or self.reason not in linked_reasons:
                raise ValueError("linked entity result is inconsistent")
            if self.linked_entity.kind not in {EntityKind.OBJECT, EntityKind.PLACE}:
                raise ValueError("only Object/Place can be linked")
        elif self.linked_entity is not None or self.reason in linked_reasons:
            raise ValueError("unresolved entity result is inconsistent")
        return self


class EntityExtractionLinkResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extraction: EntityExtractionResult
    links: list[EntityLinkResult] = Field(default_factory=list, max_length=20)
