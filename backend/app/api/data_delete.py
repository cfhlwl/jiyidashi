from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.observability import emit_operational_event
from app.data_deletion_models import DataDeletionStatus
from app.deps import get_authenticated_user_id
from app.security_models import SecuritySignalCode
from app.services.account_deletion_service import (
    AccountDeletionError,
    lock_external_data_delete_entry,
)
from app.services.data_deletion_service import DataDeletionError, delete_all_user_data
from app.services.security_alerting import SecurityScope, record_security_signal
from app.services.object_storage import ObjectStorage, get_object_storage

router = APIRouter(prefix="/data", tags=["data"])
AuthenticatedUser = Annotated[UUID, Depends(get_authenticated_user_id)]
DbSession = Annotated[Session, Depends(get_db)]
Storage = Annotated[ObjectStorage, Depends(get_object_storage)]


class DataDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    # [人工注释][S1-021] destructive confirmation is an exact protocol value, not a
    # truthy boolean; accidental/malformed callers must fail schema validation before mutation.
    confirmation: Literal["DELETE_MY_DATA"]


class DataDeleteResponse(BaseModel):
    request_id: UUID
    status: DataDeletionStatus
    completed: bool
    retry_after_seconds: int | None = None
    deleted_counts: dict[str, int]


@router.post("/delete", response_model=DataDeleteResponse)
def delete_current_user_data(
    payload: DataDeleteRequest,
    response: Response,
    user_id: AuthenticatedUser,
    db: DbSession,
    storage: Storage,
) -> DataDeleteResponse:
    # This endpoint intentionally bypasses the normal data-access deletion gate so the same
    # authenticated account can retry a partially completed deletion operation.
    # [人工注释][S1-022] Account Delete gate 建立后，外部 S1-021 入口必须停止接收
    # 新/旧 data-delete intent；否则会在 M 已冻结 data_deletion_request_id 后抢占另一条 active op。
    # M orchestrator 直接调用 delete_all_user_data()，因此自身恢复路径不受此 HTTP gate 影响。
    try:
        lock_external_data_delete_entry(db, user_id=user_id)
        result = delete_all_user_data(
            db,
            user_id=user_id,
            request_id=payload.request_id,
            storage=storage,
        )
    except (AccountDeletionError, DataDeletionError) as exc:
        retryable = exc.status_code >= 500 or exc.status_code in {409, 423, 429}
        emit_operational_event(
            event="data_deletion.failed",
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
            scope=SecurityScope.DATA_DELETE,
        )
        if retryable:
            record_security_signal(
                db.get_bind(),
                signal_code=SecuritySignalCode.DESTRUCTIVE_OPERATION_RETRY_BURST,
                correlation_kind="deletion_request",
                correlation_value=str(payload.request_id),
                scope=SecurityScope.DATA_DELETE,
            )
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc

    if not result.completed:
        response.status_code = status.HTTP_202_ACCEPTED
    emit_operational_event(
        event="data_deletion.progress",
        operation_request_id=str(result.request_id),
        operation_status=result.status.value,
        completed=result.completed,
        status_code=response.status_code,
    )
    return DataDeleteResponse(
        request_id=result.request_id,
        status=result.status,
        completed=result.completed,
        retry_after_seconds=result.retry_after_seconds,
        deleted_counts=result.deleted_counts,
    )
