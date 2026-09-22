"""Typed internal contracts for S3-011 Memory RAG Foundation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.retrieval_models import RetrievalTier
from app.services.ai_gateway import AIProvenance
from app.services.answer_trust_service import AnswerTrustState


class MemoryRAGStatus(StrEnum):
    ANSWERED = "ANSWERED"
    NO_ANSWERABLE_EVIDENCE = "NO_ANSWERABLE_EVIDENCE"
    RETRIEVAL_INCOMPLETE = "RETRIEVAL_INCOMPLETE"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    MALFORMED_PROVIDER_OUTPUT = "MALFORMED_PROVIDER_OUTPUT"
    INVALID_CITATION = "INVALID_CITATION"
    EVIDENCE_CHANGED_DURING_GENERATION = "EVIDENCE_CHANGED_DURING_GENERATION"


class MemoryRAGProviderStage(StrEnum):
    RETRIEVAL = "RETRIEVAL"
    ANSWER_GENERATION = "ANSWER_GENERATION"


@dataclass(frozen=True)
class MemoryRAGCitation:
    slot: str
    memory_id: UUID
    memory_source_id: UUID
    trust_state: AnswerTrustState
    retrieval_tier: RetrievalTier
    object_location_id: UUID | None


@dataclass(frozen=True)
class MemoryRAGResult:
    status: MemoryRAGStatus
    answer: str | None
    citations: tuple[MemoryRAGCitation, ...]
    trust_state_summary: AnswerTrustState | None
    retrieval_tier: RetrievalTier | None
    retrieval_incomplete_code: str | None
    provider_stage: MemoryRAGProviderStage | None
    provider_error_code: str | None
    ai_provenance: AIProvenance | None
