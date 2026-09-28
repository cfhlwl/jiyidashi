"""Typed contracts for V2-007 evidence-backed long-term reasoning."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.services.ai_gateway import AIProvenance
from app.services.answer_trust_service import AnswerTrustState


class LongTermReasoningStatus(StrEnum):
    ANSWERED = "ANSWERED"
    NO_ANSWERABLE_EVIDENCE = "NO_ANSWERABLE_EVIDENCE"
    EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    MALFORMED_PROVIDER_OUTPUT = "MALFORMED_PROVIDER_OUTPUT"
    INVALID_CITATION = "INVALID_CITATION"
    EVIDENCE_CHANGED_DURING_GENERATION = "EVIDENCE_CHANGED_DURING_GENERATION"


class LongTermEvidenceKind(StrEnum):
    LIFE_STAGE = "LIFE_STAGE"
    LIFE_EVENT = "LIFE_EVENT"
    MEMORY = "MEMORY"


@dataclass(frozen=True)
class LongTermReasoningCitation:
    slot: str
    kind: LongTermEvidenceKind
    life_stage_id: UUID | None
    life_event_id: UUID | None
    memory_id: UUID | None
    memory_source_id: UUID | None
    memory_trust_state: AnswerTrustState | None


@dataclass(frozen=True)
class LongTermReasoningResult:
    status: LongTermReasoningStatus
    answer: str | None
    citations: tuple[LongTermReasoningCitation, ...]
    provider_error_code: str | None
    ai_provenance: AIProvenance | None
