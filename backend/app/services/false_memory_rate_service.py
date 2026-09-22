"""Deterministic explicit-feedback-derived False Memory Rate.

The metric authority is S3-018 MemoryFeedback only. It deliberately does not inspect
Memory content, trust state, confidence, retrieval/ranking data, or provider output.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.false_memory_rate_models import (
    FalseMemoryRateResult,
    FalseMemoryRateStatus,
)
from app.memory_feedback_models import MemoryFeedback, MemoryFeedbackAction

_VALID_ACTIONS = tuple(action.value for action in MemoryFeedbackAction)


class FalseMemoryRateError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _engine_bind(db: Session):
    bind = db.get_bind()
    return bind.engine if isinstance(bind, Connection) else bind


def _read_session(db: Session) -> Session:
    # [人工注释][S3-019] 指标必须只消费 persisted feedback。独立 read Session 同时
    # 隔离 caller 的 pending/dirty identity map，避免未提交的反馈污染质量指标。
    return Session(
        bind=_engine_bind(db),
        autoflush=False,
        expire_on_commit=False,
    )


def compute_false_memory_rate(
    db: Session,
    *,
    user_id: UUID,
) -> FalseMemoryRateResult:
    """Aggregate one owner's explicitly judged Memory revisions."""

    with _read_session(db) as read_db:
        rows = read_db.execute(
            select(
                MemoryFeedback.memory_id,
                MemoryFeedback.memory_revision,
                func.max(
                    case(
                        (
                            MemoryFeedback.action
                            == MemoryFeedbackAction.CORRECT.value,
                            1,
                        ),
                        else_=0,
                    )
                ).label("has_correct"),
                func.max(
                    case(
                        (
                            MemoryFeedback.action
                            == MemoryFeedbackAction.CONFIRM.value,
                            1,
                        ),
                        else_=0,
                    )
                ).label("has_confirm"),
                func.max(
                    case(
                        (
                            MemoryFeedback.action
                            == MemoryFeedbackAction.DELETE.value,
                            1,
                        ),
                        else_=0,
                    )
                ).label("has_delete"),
                func.max(
                    case(
                        (MemoryFeedback.action.notin_(_VALID_ACTIONS), 1),
                        else_=0,
                    )
                ).label("has_unknown"),
            )
            .where(MemoryFeedback.user_id == user_id)
            .group_by(
                MemoryFeedback.memory_id,
                MemoryFeedback.memory_revision,
            )
            .order_by(
                MemoryFeedback.memory_id.asc(),
                MemoryFeedback.memory_revision.asc(),
            )
        ).all()

    false_revisions = 0
    confirmed_true_revisions = 0
    delete_only_revisions = 0

    for row in rows:
        if int(row.has_unknown or 0):
            # Persisted unknown action is not silently interpreted as correctness.
            raise FalseMemoryRateError("MEMORY_FEEDBACK_ACTION_UNSUPPORTED")

        has_correct = bool(row.has_correct)
        has_confirm = bool(row.has_confirm)
        has_delete = bool(row.has_delete)

        # [人工注释][S3-019] Canonical precedence is revision-scoped, not row-scoped.
        # CONFIRM→CORRECT for the same revision therefore counts exactly one FALSE unit.
        if has_correct:
            false_revisions += 1
        elif has_confirm:
            confirmed_true_revisions += 1
        elif has_delete:
            # DELETE alone is not evidence that the memory was false.
            delete_only_revisions += 1

    judged_revisions = false_revisions + confirmed_true_revisions
    if judged_revisions == 0:
        return FalseMemoryRateResult(
            status=FalseMemoryRateStatus.NO_JUDGED_REVISIONS,
            false_revisions=false_revisions,
            confirmed_true_revisions=confirmed_true_revisions,
            judged_revisions=0,
            delete_only_revisions=delete_only_revisions,
            false_memory_rate=None,
        )

    return FalseMemoryRateResult(
        status=FalseMemoryRateStatus.READY,
        false_revisions=false_revisions,
        confirmed_true_revisions=confirmed_true_revisions,
        judged_revisions=judged_revisions,
        delete_only_revisions=delete_only_revisions,
        false_memory_rate=false_revisions / judged_revisions,
    )
