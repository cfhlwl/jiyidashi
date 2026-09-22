"""Typed internal contracts for S3-015 Daily Summary Foundation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from uuid import UUID

from app.services.ai_gateway import AIProvenance
from app.services.answer_trust_service import AnswerTrustState


class DailySummaryStatus(StrEnum):
    DAILY_SUMMARY_READY = "DAILY_SUMMARY_READY"
    NO_SUMMARIZABLE_EVIDENCE = "NO_SUMMARIZABLE_EVIDENCE"
    SUMMARY_INCOMPLETE = "SUMMARY_INCOMPLETE"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    MALFORMED_PROVIDER_OUTPUT = "MALFORMED_PROVIDER_OUTPUT"
    INVALID_CITATION = "INVALID_CITATION"
    DATA_CHANGED_DURING_GENERATION = "DATA_CHANGED_DURING_GENERATION"


class DailySummarySlotKind(StrEnum):
    MEMORY = "MEMORY"
    VISIT = "VISIT"


@dataclass(frozen=True)
class DailySummaryCitation:
    slot: str
    kind: DailySummarySlotKind
    memory_id: UUID | None
    memory_source_id: UUID | None
    visit_id: UUID | None
    trust_state: AnswerTrustState | None


@dataclass(frozen=True)
class DailySummaryResult:
    status: DailySummaryStatus
    day: date
    timezone: str
    summary: str | None
    citations: tuple[DailySummaryCitation, ...]
    incomplete_code: str | None
    provider_error_code: str | None
    ai_provenance: AIProvenance | None
