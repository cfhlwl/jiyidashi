from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel

from app.person_memory_models import PersonMemoryRelationKind
from app.services.answer_trust_service import AnswerTrustState


class PersonKnownDurationStatus(StrEnum):
    KNOWN_SINCE_MET = "KNOWN_SINCE_MET"
    RELATED_EVIDENCE_ONLY = "RELATED_EVIDENCE_ONLY"
    NO_TRUSTED_EVIDENCE = "NO_TRUSTED_EVIDENCE"
    EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"


class PersonKnownDurationEvidence(BaseModel):
    person_memory_link_id: UUID
    memory_id: UUID
    memory_source_id: UUID
    relation_kind: PersonMemoryRelationKind
    trust_state: AnswerTrustState
    occurred_at: datetime


class PersonKnownDurationRead(BaseModel):
    status: PersonKnownDurationStatus
    person_id: UUID
    display_name: str
    as_of: datetime
    at_least_since_at: datetime | None
    elapsed_days: int | None
    earliest_related_at: datetime | None
    evidence: PersonKnownDurationEvidence | None
