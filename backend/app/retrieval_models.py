"""Typed internal contracts for S3-010 Structured First Retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.services.evidence_ranking_service import EvidenceRankClass


class RetrievalTier(StrEnum):
    STRUCTURED = "STRUCTURED"
    KEYWORD = "KEYWORD"
    VECTOR = "VECTOR"
    LLM_ASSISTED = "LLM_ASSISTED"


class RetrievalScoreKind(StrEnum):
    STRUCTURED_MATCH = "STRUCTURED_MATCH"
    KEYWORD_MATCH_COUNT = "KEYWORD_MATCH_COUNT"
    COSINE_SIMILARITY = "COSINE_SIMILARITY"


class StructuredResolutionStatus(StrEnum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    RESOLVED = "RESOLVED"
    TERMINAL_MISS = "TERMINAL_MISS"
    CANDIDATE_LIMIT_REACHED = "CANDIDATE_LIMIT_REACHED"


class VectorRetrievalStatus(StrEnum):
    NOT_NEEDED = "NOT_NEEDED"
    SUCCESS = "SUCCESS"
    DATABASE_UNSUPPORTED = "DATABASE_UNSUPPORTED"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    NO_USABLE_CANDIDATE = "NO_USABLE_CANDIDATE"
    VALIDATION_SCAN_LIMIT_REACHED = "VALIDATION_SCAN_LIMIT_REACHED"


class LLMFallbackStatus(StrEnum):
    NOT_ATTEMPTED = "NOT_ATTEMPTED"


@dataclass(frozen=True)
class RetrievalCandidate:
    memory_id: UUID
    retrieval_tier: RetrievalTier
    score_kind: RetrievalScoreKind
    retrieval_score: float
    rank_within_tier: int
    structured_ref_type: str | None
    structured_ref_id: UUID | None
    embedding_fingerprint_validated: bool | None
    evidence_rank_class: EvidenceRankClass | None
    best_memory_source_id: UUID | None
    answer_eligible: bool


@dataclass(frozen=True)
class RetrievalMetrics:
    structured_candidates: int
    keyword_candidates: int
    vector_candidates: int


@dataclass(frozen=True)
class RetrievalResult:
    candidates: tuple[RetrievalCandidate, ...]
    selected_tier: RetrievalTier | None
    structured_status: StructuredResolutionStatus
    vector_status: VectorRetrievalStatus
    vector_error_code: str | None
    llm_fallback_status: LLMFallbackStatus
    query_terms: tuple[str, ...]
    metrics: RetrievalMetrics
