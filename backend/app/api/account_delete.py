from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.data_deletion_models import DataDeletionStatus
from app.deps import get_authenticated_user_id
from app.services.account_deletion_service import (
    AccountDeletionError,
    delete_current_account,
)
from app.services.data_deletion_service import DataDeletionError
from app.services.object_storage import ObjectStorage, get_object_storage

router = APIRouter(prefix="/account", tags=["account"])
AuthenticatedUser = Annotated[UUID, Depends(get_authenticated_user_id)]
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
    user_id: AuthenticatedUser,
    db: DbSession,
    storage: Storage,
) -> AccountDeleteResponse:
    # [人工注释][S1-022] 此端点只做 JWT 认证，不经过普通 user-data gate，
    # 否则已经进入 Account/Delete gate 的账号将无法继续恢复对象存储或 DB 删除。
    try:
        result = delete_current_account(
            db,
            user_id=user_id,
            request_id=payload.request_id,
            storage=storage,
            local_cleanup_ready=payload.local_cleanup_ready,
        )
    except (AccountDeletionError, DataDeletionError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc

    if not result.completed:
        response.status_code = status.HTTP_202_ACCEPTED
    return AccountDeleteResponse(
        request_id=result.request_id,
        data_deletion_status=result.data_deletion_status,
        completed=result.completed,
        retry_after_seconds=result.retry_after_seconds,
        deleted_counts=result.deleted_counts,
    )
