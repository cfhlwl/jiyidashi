"""Typed internal contracts for S3-017 Annual Summary Foundation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.services.ai_gateway import AIProvenance
from app.services.answer_trust_service import AnswerTrustState


class AnnualSummaryStatus(StrEnum):
    ANNUAL_SUMMARY_READY = "ANNUAL_SUMMARY_READY"
    NO_SUMMARIZABLE_EVIDENCE = "NO_SUMMARIZABLE_EVIDENCE"
    SUMMARY_INCOMPLETE = "SUMMARY_INCOMPLETE"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    MALFORMED_PROVIDER_OUTPUT = "MALFORMED_PROVIDER_OUTPUT"
    INVALID_CITATION = "INVALID_CITATION"
    DATA_CHANGED_DURING_GENERATION = "DATA_CHANGED_DURING_GENERATION"


class AnnualSummarySlotKind(StrEnum):
    MEMORY = "MEMORY"
    VISIT = "VISIT"


@dataclass(frozen=True)
class AnnualSummaryCitation:
    slot: str
    kind: AnnualSummarySlotKind
    memory_id: UUID | None
    memory_source_id: UUID | None
    visit_id: UUID | None
    trust_state: AnswerTrustState | None


@dataclass(frozen=True)
class AnnualSummaryResult:
    status: AnnualSummaryStatus
    target_year: str
    timezone: str
    summary: str | None
    citations: tuple[AnnualSummaryCitation, ...]
    incomplete_code: str | None
    provider_error_code: str | None
    ai_provenance: AIProvenance | None
