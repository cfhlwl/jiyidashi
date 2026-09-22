"""Typed internal contracts for S3-016 Monthly Summary Foundation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.services.ai_gateway import AIProvenance
from app.services.answer_trust_service import AnswerTrustState


class MonthlySummaryStatus(StrEnum):
    MONTHLY_SUMMARY_READY = "MONTHLY_SUMMARY_READY"
    NO_SUMMARIZABLE_EVIDENCE = "NO_SUMMARIZABLE_EVIDENCE"
    SUMMARY_INCOMPLETE = "SUMMARY_INCOMPLETE"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    MALFORMED_PROVIDER_OUTPUT = "MALFORMED_PROVIDER_OUTPUT"
    INVALID_CITATION = "INVALID_CITATION"
    DATA_CHANGED_DURING_GENERATION = "DATA_CHANGED_DURING_GENERATION"


class MonthlySummarySlotKind(StrEnum):
    MEMORY = "MEMORY"
    VISIT = "VISIT"


@dataclass(frozen=True)
class MonthlySummaryCitation:
    slot: str
    kind: MonthlySummarySlotKind
    memory_id: UUID | None
    memory_source_id: UUID | None
    visit_id: UUID | None
    trust_state: AnswerTrustState | None


@dataclass(frozen=True)
class MonthlySummaryResult:
    status: MonthlySummaryStatus
    target_month: str
    timezone: str
    summary: str | None
    citations: tuple[MonthlySummaryCitation, ...]
    incomplete_code: str | None
    provider_error_code: str | None
    ai_provenance: AIProvenance | None
