"""Typed internal contracts for S3-014 Reminder Intent Foundation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ReminderIntentState(StrEnum):
    NO_REMINDER_INTENT = "NO_REMINDER_INTENT"
    REMINDER_CANDIDATE = "REMINDER_CANDIDATE"
    AMBIGUOUS = "AMBIGUOUS"
    PROVIDER_FAILED = "PROVIDER_FAILED"


class ReminderIntentReason(StrEnum):
    NO_INTENT = "NO_INTENT"
    CANDIDATE_READY = "CANDIDATE_READY"
    TIME_MISSING = "TIME_MISSING"
    TIME_UNSUPPORTED = "TIME_UNSUPPORTED"
    TIME_NOT_FUTURE = "TIME_NOT_FUTURE"
    TIME_AMBIGUOUS_OR_NONEXISTENT = "TIME_AMBIGUOUS_OR_NONEXISTENT"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    PROVIDER_INVALID_RESPONSE = "PROVIDER_INVALID_RESPONSE"


class ReminderTimeResolution(StrEnum):
    RESOLVED = "RESOLVED"
    MISSING = "MISSING"
    UNSUPPORTED = "UNSUPPORTED"
    NOT_FUTURE = "NOT_FUTURE"
    AMBIGUOUS_OR_NONEXISTENT = "AMBIGUOUS_OR_NONEXISTENT"


@dataclass(frozen=True)
class ReminderIntentProvenance:
    gateway_request_id: str
    purpose: str
    provider_request_id: str | None
    provider: str
    model: str
    trust_class: str


@dataclass(frozen=True)
class ReminderIntentCandidate:
    title: str
    content: str | None
    time_text: str | None
    title_span: str
    content_span: str | None
    time_span: str | None
    remind_at: datetime | None
    time_resolution: ReminderTimeResolution
    provenance: ReminderIntentProvenance
    requires_user_confirmation: bool = True


@dataclass(frozen=True)
class ReminderIntentResult:
    state: ReminderIntentState
    reason: ReminderIntentReason
    candidate: ReminderIntentCandidate | None = None
    provider_error_code: str | None = None
