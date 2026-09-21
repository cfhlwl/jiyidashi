"""Deterministic trust-first ordering over persisted MemorySource evidence.

S3-012 is an internal read-only seam. It ranks existing owner-scoped evidence but does
not decide whether a Memory is confirmed/answerable and never persists ranking state.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Memory, MemorySource, SourceType


class EvidenceRankClass(StrEnum):
    USER_DIRECT = "USER_DIRECT"
    SENSOR_DIRECT = "SENSOR_DIRECT"
    SYSTEM_DERIVED = "SYSTEM_DERIVED"
    AI_INFERENCE = "AI_INFERENCE"


class EvidenceRankingError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class EvidenceRankedSource:
    memory_source_id: UUID
    memory_id: UUID
    source_type: SourceType
    rank_class: EvidenceRankClass
    confidence: float
    created_at: datetime


_SOURCE_RANK_CLASS: dict[SourceType, EvidenceRankClass] = {
    SourceType.USER_TEXT: EvidenceRankClass.USER_DIRECT,
    SourceType.USER_VOICE: EvidenceRankClass.USER_DIRECT,
    SourceType.USER_PHOTO: EvidenceRankClass.USER_DIRECT,
    SourceType.GPS: EvidenceRankClass.SENSOR_DIRECT,
    SourceType.PHOTO_EXIF: EvidenceRankClass.SENSOR_DIRECT,
    SourceType.SYSTEM_PLACE: EvidenceRankClass.SYSTEM_DERIVED,
    SourceType.AI_INFERENCE: EvidenceRankClass.AI_INFERENCE,
}

# [人工注释][S3-012] class precedence 是服务端固定 trust policy，不允许 confidence、
# recency、provider score 或未来模型输出跨 class 改写。数值越小，Evidence 越可信。
_RANK_PRECEDENCE: dict[EvidenceRankClass, int] = {
    EvidenceRankClass.USER_DIRECT: 0,
    EvidenceRankClass.SENSOR_DIRECT: 1,
    EvidenceRankClass.SYSTEM_DERIVED: 2,
    EvidenceRankClass.AI_INFERENCE: 3,
}


def rank_class_for_source_type(source_type: SourceType) -> EvidenceRankClass:
    try:
        return _SOURCE_RANK_CLASS[source_type]
    except (KeyError, TypeError) as exc:
        # 未登记的新 SourceType 必须先显式审查 trust mapping，不能默认落入某一档。
        raise EvidenceRankingError("EVIDENCE_SOURCE_TYPE_UNSUPPORTED") from exc


def _validated_confidence(value: float) -> float:
    confidence = float(value)
    if not isfinite(confidence) or confidence < 0.0 or confidence > 1.0:
        raise EvidenceRankingError("EVIDENCE_CONFIDENCE_INVALID")
    return confidence


def _utc_timestamp(value: datetime) -> float:
    # SQLite 会把 timezone-aware DateTime 读回 naive；这里把数据库约定的 naive 值
    # 当作 UTC 只用于稳定排序，不改变持久化时间，也不参与跨 trust-class 晋级。
    normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return normalized.timestamp()


def _to_ranked_source(source: MemorySource) -> EvidenceRankedSource:
    if not isinstance(source.id, UUID) or not isinstance(source.memory_id, UUID):
        raise EvidenceRankingError("EVIDENCE_SOURCE_ID_INVALID")
    if not isinstance(source.created_at, datetime):
        raise EvidenceRankingError("EVIDENCE_CREATED_AT_INVALID")

    rank_class = rank_class_for_source_type(source.source_type)
    return EvidenceRankedSource(
        memory_source_id=source.id,
        memory_id=source.memory_id,
        source_type=source.source_type,
        rank_class=rank_class,
        confidence=_validated_confidence(source.confidence),
        created_at=source.created_at,
    )


def _sort_key(item: EvidenceRankedSource) -> tuple[int, float, float, str]:
    return (
        _RANK_PRECEDENCE[item.rank_class],
        -item.confidence,
        -_utc_timestamp(item.created_at),
        str(item.memory_source_id),
    )


def rank_evidence_sources(
    db: Session,
    *,
    user_id: UUID,
    memory_ids: Sequence[UUID] | None = None,
) -> tuple[EvidenceRankedSource, ...]:
    """Load and rank one owner's persisted evidence without mutating trust or storage."""

    query = (
        select(MemorySource)
        .join(Memory, Memory.id == MemorySource.memory_id)
        .where(
            Memory.user_id == user_id,
            Memory.is_deleted.is_(False),
        )
    )
    if memory_ids is not None:
        stable_ids = tuple(dict.fromkeys(memory_ids))
        if not stable_ids:
            return ()
        query = query.where(Memory.id.in_(stable_ids))

    try:
        # [人工注释][S3-012-FIX-001] ranking 是纯读取 seam；即使调用方 Session
        # 已有 pending/dirty ORM 状态，也不能由本查询触发隐式 flush。
        with db.no_autoflush:
            sources = db.scalars(query).all()
    except LookupError as exc:
        # An unknown persisted enum value is safer as an explicit failure than an implicit rank.
        raise EvidenceRankingError("EVIDENCE_SOURCE_TYPE_UNSUPPORTED") from exc

    ranked = [_to_ranked_source(source) for source in sources]
    ranked.sort(key=_sort_key)
    return tuple(ranked)
