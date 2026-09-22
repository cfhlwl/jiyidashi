"""Explicit authenticated Memory feedback with revision-bound audit.

This layer owns only feedback intent/audit. CORRECT delegates mutation semantics to
memory_edit_service.edit_memory(); DELETE delegates to memory_service.soft_delete_memory().
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.memory_feedback_contracts import MemoryFeedbackCreate
from app.memory_feedback_models import MemoryFeedback, MemoryFeedbackAction
from app.models import Memory, MemoryType
from app.schemas import MemoryUpdate
from app.services.memory_edit_service import (
    MemoryEditConflict,
    MemoryEditUnsupported,
    edit_memory,
)
from app.services.memory_service import soft_delete_memory


class MemoryFeedbackNotFound(RuntimeError):
    def __init__(self, code: str = "MEMORY_NOT_FOUND"):
        super().__init__(code)
        self.code = code


class MemoryFeedbackConflict(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class MemoryFeedbackUnsupported(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def get_memory_feedback_for_user(
    db: Session,
    *,
    user_id: UUID,
    feedback_id: UUID,
) -> MemoryFeedback | None:
    return db.scalar(
        select(MemoryFeedback).where(
            MemoryFeedback.id == feedback_id,
            MemoryFeedback.user_id == user_id,
        )
    )


def _existing_revision_action(
    db: Session,
    *,
    user_id: UUID,
    memory_id: UUID,
    memory_revision: int,
    action: MemoryFeedbackAction,
) -> MemoryFeedback | None:
    return db.scalar(
        select(MemoryFeedback).where(
            MemoryFeedback.user_id == user_id,
            MemoryFeedback.memory_id == memory_id,
            MemoryFeedback.memory_revision == memory_revision,
            MemoryFeedback.action == action.value,
        )
    )


def _correction_payload(payload: MemoryFeedbackCreate) -> MemoryUpdate:
    values: dict[str, object] = {"expected_revision": payload.expected_revision}
    if "title" in payload.model_fields_set:
        values["title"] = payload.title
    if "content" in payload.model_fields_set:
        values["content"] = payload.content
    return MemoryUpdate.model_validate(values)


def apply_memory_feedback(
    db: Session,
    *,
    user_id: UUID,
    memory_id: UUID,
    client_uuid: UUID,
    payload: MemoryFeedbackCreate,
) -> MemoryFeedback:
    # [人工注释][S3-018] 三种 feedback 都先锁 authoritative Memory。这样 CONFIRM、
    # CORRECT、DELETE 与并发 edit/delete 在同一 revision 边界上串行，旧 revision 不能越过锁。
    memory = db.scalar(
        select(Memory)
        .where(
            Memory.id == memory_id,
            Memory.user_id == user_id,
            Memory.is_deleted.is_(False),
        )
        .with_for_update()
    )
    if memory is None:
        raise MemoryFeedbackNotFound()

    # ObjectLocation 的当前位置真相由结构化 flow 管理。feedback seam 不允许通过 backing
    # Memory 的确认/纠正/删除去制造第二套结构化事实语义。
    if memory.memory_type == MemoryType.OBJECT_LOCATION:
        raise MemoryFeedbackUnsupported(
            "OBJECT_LOCATION_FEEDBACK_REQUIRES_STRUCTURED_FLOW"
        )

    # Feedback 比通用 edit 的 response-loss no-op 更严格：用户明确评价的是 revision N，
    # 所以即使 payload 恰好等于当前内容，也不能把旧 revision 的反馈套到 revision N+1。
    if memory.edit_revision != payload.expected_revision:
        raise MemoryFeedbackConflict("MEMORY_FEEDBACK_REVISION_CONFLICT")

    existing = _existing_revision_action(
        db,
        user_id=user_id,
        memory_id=memory.id,
        memory_revision=payload.expected_revision,
        action=payload.action,
    )
    if existing is not None:
        # 同一 revision/action 的重复 CONFIRM（或其他重复 action）复用既有 audit；
        # 外层 ClientMutation 仍会把新的稳定 client key 绑定到同一资源。
        return existing

    result_revision: int | None = None
    if payload.action == MemoryFeedbackAction.CORRECT:
        try:
            edited = edit_memory(
                db,
                user_id=user_id,
                memory_id=memory.id,
                payload=_correction_payload(payload),
            )
        except MemoryEditConflict as exc:
            raise MemoryFeedbackConflict(exc.detail) from exc
        except MemoryEditUnsupported as exc:
            raise MemoryFeedbackUnsupported(exc.detail) from exc
        if edited is None:
            raise MemoryFeedbackNotFound()
        if edited.edit_revision == payload.expected_revision:
            # Idempotency replay is handled before this service by ClientMutation. A fresh
            # CORRECT that changes nothing is not a correction and must not pollute S3-019 data.
            raise MemoryFeedbackConflict("MEMORY_FEEDBACK_CORRECTION_NO_CHANGE")
        result_revision = edited.edit_revision
    elif payload.action == MemoryFeedbackAction.DELETE:
        # Reuse the existing trusted delete semantics: embedding invalidation, structured
        # location staling, Reminder cancellation/detach all stay centralized here.
        soft_delete_memory(db, memory)

    feedback = MemoryFeedback(
        user_id=user_id,
        memory_id=memory.id,
        client_uuid=client_uuid,
        memory_revision=payload.expected_revision,
        result_revision=result_revision,
        action=payload.action.value,
    )
    db.add(feedback)
    db.flush()
    return feedback
