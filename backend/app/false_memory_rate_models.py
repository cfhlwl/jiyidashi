"""Typed result contract for S3-019 False Memory Rate."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FalseMemoryRateStatus(StrEnum):
    READY = "READY"
    NO_JUDGED_REVISIONS = "NO_JUDGED_REVISIONS"


@dataclass(frozen=True)
class FalseMemoryRateResult:
    status: FalseMemoryRateStatus
    false_revisions: int
    confirmed_true_revisions: int
    judged_revisions: int
    delete_only_revisions: int
    false_memory_rate: float | None
