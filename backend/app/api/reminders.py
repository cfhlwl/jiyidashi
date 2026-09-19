from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.models import Reminder, ReminderStatus
from app.schemas import ReminderCreate, ReminderRead
from app.services.idempotency_service import (
    IdempotencyConflict,
    IdempotencyResourceGone,
    execute_idempotent_mutation,
)
from app.services.reminder_service import (
    ReminderNotFound,
    ReminderTimeInvalid,
    ReminderTransitionConflict,
    create_reminder,
    get_reminder_for_user,
    list_reminders,
    transition_reminder,
)

router = APIRouter(prefix="/reminders", tags=["reminders"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]
# [人工注释][S1-025] Reminder create 必须携带稳定客户端 UUID；
# 这不是可选优化，而是防止 response-loss 产生重复 PENDING reminder 的协议门禁。
IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]


@router.post("", response_model=ReminderRead, status_code=status.HTTP_201_CREATED)
def create_reminder_endpoint(
    payload: ReminderCreate,
    user_id: CurrentUser,
    db: DbSession,
    idempotency_key: IdempotencyKey,
) -> Reminder:
    # [人工注释][S1-025] fingerprint 冻结完整创建意图；同 key + 同 payload 返回原 Reminder，
    # 同 key + 不同 payload 必须 409，绝不能“帮用户猜”这是另一个提醒。
    fingerprint_payload = payload.model_dump(mode="json")
    try:
        return execute_idempotent_mutation(
            db,
            user_id=user_id,
            operation_type="REMINDER_CREATE",
            client_uuid=idempotency_key,
            fingerprint_payload=fingerprint_payload,
            resource_type="REMINDER",
            create_resource=lambda session: create_reminder(
                session,
                user_id=user_id,
                payload=payload,
            ),
            resource_id=lambda reminder: reminder.id,
            load_resource=lambda session, resource_id: get_reminder_for_user(
                session,
                user_id=user_id,
                reminder_id=resource_id,
            ),
        )
    except ReminderNotFound as exc:
        # 不区分不存在、跨 owner、已软删除，避免 Memory 存在性探测。
        raise HTTPException(status_code=404, detail=exc.code) from exc
    except ReminderTimeInvalid as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.code,
        ) from exc
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except IdempotencyResourceGone as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc


@router.get("", response_model=list[ReminderRead])
def list_reminders_endpoint(
    user_id: CurrentUser,
    db: DbSession,
    reminder_status: Annotated[ReminderStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[Reminder]:
    return list_reminders(
        db,
        user_id=user_id,
        status_filter=reminder_status,
        limit=limit,
    )


def _transition(
    reminder_id: UUID,
    target: ReminderStatus,
    user_id: UUID,
    db: Session,
) -> Reminder:
    try:
        reminder = transition_reminder(
            db,
            user_id=user_id,
            reminder_id=reminder_id,
            target=target,
        )
    except ReminderNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.code) from exc
    except ReminderTransitionConflict as exc:
        raise HTTPException(status_code=409, detail=exc.code) from exc
    db.commit()
    db.refresh(reminder)
    return reminder


@router.post("/{reminder_id}/done", response_model=ReminderRead)
def complete_reminder_endpoint(
    reminder_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
) -> Reminder:
    return _transition(reminder_id, ReminderStatus.DONE, user_id, db)


@router.post("/{reminder_id}/cancel", response_model=ReminderRead)
def cancel_reminder_endpoint(
    reminder_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
) -> Reminder:
    return _transition(reminder_id, ReminderStatus.CANCELLED, user_id, db)
