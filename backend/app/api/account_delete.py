from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.observability import emit_operational_event
from app.data_deletion_models import DataDeletionStatus
from app.deps import AuthenticatedClaims
from app.security_models import SecuritySignalCode
from app.services.account_deletion_service import (
    AccountDeletionError,
    delete_current_account,
)
from app.services.data_deletion_service import DataDeletionError
from app.services.object_storage import ObjectStorage, get_object_storage
from app.services.security_alerting import SecurityScope, record_security_signal

router = APIRouter(prefix="/account", tags=["account"])
DbSession = Annotated[Session, Depends(get_db)]
Storage = Annotated[ObjectStorage, Depends(get_object_storage)]


class AccountDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    # [人工注释][S1-022] 与 DELETE_MY_DATA 使用不同精确确认值；
    # 客户端误把“删除数据”按钮接到“注销账号”端点时必须在 schema 层直接失败。
    confirmation: Literal["DELETE_MY_ACCOUNT"]
    # [人工注释][S1-022-FIX-002] false=只建立 durable Account gate；true=官方客户端
    # 已完成 owner-scoped 本机 purge，可以推进 S1-021 与最终身份删除。
    local_cleanup_ready: bool


class AccountDeleteResponse(BaseModel):
    request_id: UUID
    data_deletion_status: DataDeletionStatus | None
    completed: bool
    retry_after_seconds: int | None = None
    deleted_counts: dict[str, int]


@router.post("/delete", response_model=AccountDeleteResponse)
def delete_account(
    payload: AccountDeleteRequest,
    response: Response,
    claims: AuthenticatedClaims,
    db: DbSession,
    storage: Storage,
) -> AccountDeleteResponse:
    # This endpoint authenticates the exact durable session but intentionally skips
    # the ordinary user-data gate: the account-deletion gate blocks normal data APIs
    # while this one continuation session finishes PREPARE -> local purge -> COMMIT.
    try:
        result = delete_current_account(
            db,
            user_id=claims.user_id,
            request_id=payload.request_id,
            storage=storage,
            local_cleanup_ready=payload.local_cleanup_ready,
            continuation_session_id=claims.session_id,
        )
    except (AccountDeletionError, DataDeletionError) as exc:
        retryable = exc.status_code >= 500 or exc.status_code in {409, 423, 429}
        emit_operational_event(
            event="account_deletion.failed",
            level="WARNING",
            operation_request_id=str(payload.request_id),
            error_code=exc.code,
            status_code=exc.status_code,
            retryable=retryable,
        )
        record_security_signal(
            db.get_bind(),
            signal_code=SecuritySignalCode.DESTRUCTIVE_OPERATION_FAILURE,
            correlation_kind="deletion_request",
            correlation_value=str(payload.request_id),
            scope=SecurityScope.ACCOUNT_DELETE,
        )
        if retryable:
            record_security_signal(
                db.get_bind(),
                signal_code=SecuritySignalCode.DESTRUCTIVE_OPERATION_RETRY_BURST,
                correlation_kind="deletion_request",
                correlation_value=str(payload.request_id),
                scope=SecurityScope.ACCOUNT_DELETE,
            )
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc

    if not result.completed:
        response.status_code = status.HTTP_202_ACCEPTED
    operation_status = (
        result.data_deletion_status.value
        if result.data_deletion_status is not None
        else "ACCOUNT_GATE_ACTIVE"
    )
    emit_operational_event(
        event="account_deletion.progress",
        operation_request_id=str(result.request_id),
        operation_status=operation_status,
        completed=result.completed,
        status_code=response.status_code,
    )
    return AccountDeleteResponse(
        request_id=result.request_id,
        data_deletion_status=result.data_deletion_status,
        completed=result.completed,
        retry_after_seconds=result.retry_after_seconds,
        deleted_counts=result.deleted_counts,
    )
