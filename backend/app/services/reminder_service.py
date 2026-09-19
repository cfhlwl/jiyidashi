from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Memory, Reminder, ReminderStatus
from app.schemas import ReminderCreate


class ReminderNotFound(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ReminderTimeInvalid(RuntimeError):
    def __init__(self, code: str = "REMINDER_TIME_MUST_BE_FUTURE"):
        super().__init__(code)
        self.code = code


class ReminderTransitionConflict(RuntimeError):
    def __init__(self, code: str = "REMINDER_STATUS_CONFLICT"):
        super().__init__(code)
        self.code = code


def create_reminder(
    db: Session,
    *,
    user_id: UUID,
    payload: ReminderCreate,
) -> Reminder:
    # [人工注释][S1-025] Reminder 只能绑定当前用户仍可见的 Memory。
    # 与 Memory DELETE 共用 FOR UPDATE，避免“删除完成后又出现 PENDING reminder”的竞态。
    memory = db.scalar(
        select(Memory)
        .where(
            Memory.id == payload.memory_id,
            Memory.user_id == user_id,
            Memory.is_deleted.is_(False),
        )
        .with_for_update()
    )
    if memory is None:
        raise ReminderNotFound("REMINDER_MEMORY_NOT_FOUND")

    remind_at = payload.remind_at.astimezone(UTC)
    # [人工注释][S1-025] Stage 1 没有 OVERDUE/补发调度语义，因此禁止创建过去或当前时刻的
    # PENDING reminder；否则它会永久处于“待提醒”但没有明确执行语义。
    if remind_at <= datetime.now(UTC):
        raise ReminderTimeInvalid()

    reminder = Reminder(
        user_id=user_id,
        memory_id=memory.id,
        title=payload.title,
        content=payload.content,
        remind_at=remind_at,
        status=ReminderStatus.PENDING,
    )
    db.add(reminder)
    db.flush()
    return reminder


def get_reminder_for_user(
    db: Session,
    *,
    user_id: UUID,
    reminder_id: UUID,
) -> Reminder | None:
    # 幂等重放需要读取原 Reminder，即使它后来已 DONE/CANCELLED 或因 Memory 删除而脱钩。
    # owner 条件仍不可省略，ClientMutation 不能变成跨账号资源探针。
    return db.scalar(
        select(Reminder).where(
            Reminder.id == reminder_id,
            Reminder.user_id == user_id,
        )
    )


def list_reminders(
    db: Session,
    *,
    user_id: UUID,
    status_filter: ReminderStatus | None,
    limit: int,
) -> list[Reminder]:
    query = select(Reminder).where(Reminder.user_id == user_id)
    if status_filter is not None:
        query = query.where(Reminder.status == status_filter)

    if status_filter == ReminderStatus.PENDING:
        query = query.order_by(Reminder.remind_at.asc(), Reminder.created_at.asc())
    else:
        query = query.order_by(Reminder.created_at.desc(), Reminder.id.desc())
    return list(db.scalars(query.limit(limit)).all())


def transition_reminder(
    db: Session,
    *,
    user_id: UUID,
    reminder_id: UUID,
    target: ReminderStatus,
) -> Reminder:
    reminder = db.scalar(
        select(Reminder)
        .where(Reminder.id == reminder_id, Reminder.user_id == user_id)
        .with_for_update()
    )
    if reminder is None:
        raise ReminderNotFound("REMINDER_NOT_FOUND")

    # [人工注释][S1-025] response-loss 后重放同一目标动作是安全 no-op；
    # DONE 与 CANCELLED 都是终态，禁止互相改写，避免历史被覆盖。
    if reminder.status == target:
        return reminder
    if reminder.status != ReminderStatus.PENDING:
        raise ReminderTransitionConflict()

    reminder.status = target
    db.flush()
    return reminder
