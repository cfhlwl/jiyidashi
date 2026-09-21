"""Server-owned answer trust state classification for authoritative persisted state.

S3-013 is an internal read-only foundation. Retrieval rank, vector similarity, provider
output and arbitrary metadata are deliberately absent from the resolver input contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.models import (
    Memory,
    MemoryEdit,
    MemorySource,
    ObjectItem,
    ObjectLocation,
    ObjectLocationStatus,
    SourceType,
)

MIN_ANSWER_EVIDENCE_CONFIDENCE = 0.6


class AnswerTrustState(StrEnum):
    CONFIRMED = "CONFIRMED"
    EVIDENCE_SUPPORTED = "EVIDENCE_SUPPORTED"
    INFERENCE_ONLY = "INFERENCE_ONLY"
    NO_EVIDENCE = "NO_EVIDENCE"


class AnswerTrustReason(StrEnum):
    CURRENT_OBJECT_LOCATION_CONFIRMED = "CURRENT_OBJECT_LOCATION_CONFIRMED"
    MEMORY_EVIDENCE_SUPPORTED = "MEMORY_EVIDENCE_SUPPORTED"
    MEMORY_INFERENCE_ONLY = "MEMORY_INFERENCE_ONLY"
    MEMORY_UNAVAILABLE = "MEMORY_UNAVAILABLE"
    MEMORY_TRUST_GATE_FAILED = "MEMORY_TRUST_GATE_FAILED"
    MEMORY_NO_QUALIFYING_EVIDENCE = "MEMORY_NO_QUALIFYING_EVIDENCE"
    OBJECT_LOCATION_UNAVAILABLE = "OBJECT_LOCATION_UNAVAILABLE"
    OBJECT_LOCATION_NOT_CURRENT = "OBJECT_LOCATION_NOT_CURRENT"


@dataclass(frozen=True)
class AnswerTrustResolution:
    state: AnswerTrustState
    reason: AnswerTrustReason
    memory_id: UUID | None = None
    evidence_source_id: UUID | None = None
    object_location_id: UUID | None = None

    @property
    def can_answer(self) -> bool:
        return self.state in {
            AnswerTrustState.CONFIRMED,
            AnswerTrustState.EVIDENCE_SUPPORTED,
        }


def _no_evidence(
    reason: AnswerTrustReason,
    *,
    memory_id: UUID | None = None,
    object_location_id: UUID | None = None,
) -> AnswerTrustResolution:
    return AnswerTrustResolution(
        state=AnswerTrustState.NO_EVIDENCE,
        reason=reason,
        memory_id=memory_id,
        object_location_id=object_location_id,
    )


def _confidence_is_eligible(value: float) -> bool:
    confidence = float(value)
    return isfinite(confidence) and confidence >= MIN_ANSWER_EVIDENCE_CONFIDENCE


def _engine_bind(db: Session):
    bind = db.get_bind()
    return bind.engine if isinstance(bind, Connection) else bind


def _read_session(db: Session) -> Session:
    # [人工注释][S3-013-FIX-002] Trust state 必须只看已提交 authoritative state。
    # 独立 autoflush=False Session 同时隔离 caller 的 pending/dirty identity map。
    return Session(
        bind=_engine_bind(db),
        autoflush=False,
        expire_on_commit=False,
    )


def _current_text_sources(db: Session, memory: Memory) -> tuple[MemorySource, ...]:
    """Return persisted Evidence authoritative for the current Memory text revision."""

    latest_content_edit = db.execute(
        select(MemoryEdit.revision, MemoryEdit.memory_source_id)
        .where(
            MemoryEdit.memory_id == memory.id,
            MemoryEdit.user_id == memory.user_id,
            MemoryEdit.changed_content.is_(True),
        )
        .order_by(desc(MemoryEdit.revision))
        .limit(1)
    ).first()
    if latest_content_edit is not None:
        _, edited_source_id = latest_content_edit
        # [人工注释][S3-013-FIX-001] 必须先锁定最新正文 revision，再验证其 source。
        # 最新 revision 的 source 为 NULL/缺失/错误类型时直接 fail closed，绝不回退旧 revision。
        if edited_source_id is None:
            return ()
        source = db.scalar(
            select(MemorySource).where(
                MemorySource.id == edited_source_id,
                MemorySource.memory_id == memory.id,
                # 当前正文被用户改写后，只有 edit flow 创建的 USER_TEXT source
                # 能证明当前文本；旧照片/语音来源不能重新覆盖当前 revision。
                MemorySource.source_type == SourceType.USER_TEXT,
            )
        )
        return () if source is None else (source,)

    return tuple(
        db.scalars(
            select(MemorySource).where(MemorySource.memory_id == memory.id)
        ).all()
    )


def _qualifying_non_ai_source(
    sources: tuple[MemorySource, ...],
) -> MemorySource | None:
    eligible = [
        source
        for source in sources
        if source.source_type != SourceType.AI_INFERENCE
        and _confidence_is_eligible(source.confidence)
    ]
    if not eligible:
        return None
    # This is not Evidence Ranking. It only chooses stable provenance for the trust result
    # after the fixed eligibility gate has already been satisfied.
    return sorted(
        eligible,
        key=lambda source: (-float(source.confidence), str(source.id)),
    )[0]


def _resolve_loaded_memory(
    db: Session,
    memory: Memory,
) -> AnswerTrustResolution:
    # [人工注释][S3-013] Unconfirmed/AI-derived Memory stays inference-only even when it
    # retains direct original Evidence. Evidence Ranking metadata cannot promote this state.
    if not memory.is_confirmed or memory.source_type == SourceType.AI_INFERENCE:
        return AnswerTrustResolution(
            state=AnswerTrustState.INFERENCE_ONLY,
            reason=AnswerTrustReason.MEMORY_INFERENCE_ONLY,
            memory_id=memory.id,
        )

    if not _confidence_is_eligible(memory.confidence):
        return _no_evidence(
            AnswerTrustReason.MEMORY_TRUST_GATE_FAILED,
            memory_id=memory.id,
        )

    source = _qualifying_non_ai_source(_current_text_sources(db, memory))
    if source is None:
        return _no_evidence(
            AnswerTrustReason.MEMORY_NO_QUALIFYING_EVIDENCE,
            memory_id=memory.id,
        )

    # Generic Memory keeps the existing public "evidence" semantics. CONFIRMED is reserved
    # for a stronger structured CURRENT state in this foundation.
    return AnswerTrustResolution(
        state=AnswerTrustState.EVIDENCE_SUPPORTED,
        reason=AnswerTrustReason.MEMORY_EVIDENCE_SUPPORTED,
        memory_id=memory.id,
        evidence_source_id=source.id,
    )


def resolve_memory_answer_trust(
    db: Session,
    *,
    user_id: UUID,
    memory_id: UUID,
) -> AnswerTrustResolution:
    """Resolve one persisted Memory without flushing caller-pending ORM state."""

    try:
        with _read_session(db) as read_db:
            memory = read_db.scalar(
                select(Memory).where(
                    Memory.id == memory_id,
                    Memory.user_id == user_id,
                    Memory.is_deleted.is_(False),
                )
            )
            if memory is None:
                return _no_evidence(AnswerTrustReason.MEMORY_UNAVAILABLE)
            return _resolve_loaded_memory(read_db, memory)
    except LookupError:
        # Unknown persisted enum state must fail closed rather than invent a trust class.
        return _no_evidence(AnswerTrustReason.MEMORY_TRUST_GATE_FAILED)


def resolve_object_location_answer_trust(
    db: Session,
    *,
    user_id: UUID,
    object_location_id: UUID,
) -> AnswerTrustResolution:
    """Resolve structured CURRENT ObjectLocation trust without changing public query behavior."""

    try:
        with _read_session(db) as read_db:
            location = read_db.scalar(
                select(ObjectLocation)
                .join(ObjectItem, ObjectItem.id == ObjectLocation.object_id)
                .where(
                    ObjectLocation.id == object_location_id,
                    ObjectLocation.user_id == user_id,
                    ObjectItem.user_id == user_id,
                )
            )
            if location is None:
                return _no_evidence(AnswerTrustReason.OBJECT_LOCATION_UNAVAILABLE)
            if (
                location.status != ObjectLocationStatus.CURRENT
                or location.memory_id is None
            ):
                return _no_evidence(
                    AnswerTrustReason.OBJECT_LOCATION_NOT_CURRENT,
                    object_location_id=location.id,
                )

            memory = read_db.scalar(
                select(Memory).where(
                    Memory.id == location.memory_id,
                    Memory.user_id == user_id,
                    Memory.is_deleted.is_(False),
                )
            )
            if memory is None:
                return _no_evidence(
                    AnswerTrustReason.MEMORY_UNAVAILABLE,
                    object_location_id=location.id,
                )

            backing = _resolve_loaded_memory(read_db, memory)
            if backing.state != AnswerTrustState.EVIDENCE_SUPPORTED:
                return AnswerTrustResolution(
                    state=backing.state,
                    reason=backing.reason,
                    memory_id=backing.memory_id,
                    evidence_source_id=backing.evidence_source_id,
                    object_location_id=location.id,
                )

            return AnswerTrustResolution(
                state=AnswerTrustState.CONFIRMED,
                reason=AnswerTrustReason.CURRENT_OBJECT_LOCATION_CONFIRMED,
                memory_id=memory.id,
                evidence_source_id=backing.evidence_source_id,
                object_location_id=location.id,
            )
    except LookupError:
        return _no_evidence(AnswerTrustReason.MEMORY_TRUST_GATE_FAILED)
