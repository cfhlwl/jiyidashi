from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.account_deletion_models import AccountDeletionOperation
from app.auth_models import AuthIdentity
from app.data_deletion_models import DataDeletionOperation, DataDeletionStatus
from app.models import User
from app.services.data_deletion_service import (
    DataDeletionError,
    DataDeletionResult,
    delete_all_user_data,
)
from app.services.object_storage import ObjectStorage


class AccountDeletionError(RuntimeError):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class AccountDeletionResult:
    request_id: UUID
    data_deletion_status: DataDeletionStatus | None
    completed: bool
    retry_after_seconds: int | None
    deleted_counts: dict[str, int]


def _result_from_data(
    operation: AccountDeletionOperation,
    result: DataDeletionResult,
) -> AccountDeletionResult:
    return AccountDeletionResult(
        request_id=operation.request_id,
        data_deletion_status=result.status,
        completed=False,
        retry_after_seconds=result.retry_after_seconds,
        deleted_counts=result.deleted_counts,
    )


def _already_deleted(request_id: UUID) -> AccountDeletionResult:
    # [人工注释][S1-022] 合法旧 token 的 subject 所指 User 已不存在时，账号删除已经越过
    # 唯一允许删除 User 的最终事务，因此“User 不存在”本身就是 response-loss 安全的终态。
    # 不额外保存 completed tombstone，避免注销后又长期留下账号身份关联记录。
    return AccountDeletionResult(
        request_id=request_id,
        data_deletion_status=DataDeletionStatus.COMPLETED,
        completed=True,
        retry_after_seconds=None,
        deleted_counts={},
    )


def _begin_or_load_account_deletion(
    db: Session,
    *,
    user_id: UUID,
    request_id: UUID,
) -> AccountDeletionOperation | None:
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        db.rollback()
        return None

    existing = db.scalar(
        select(AccountDeletionOperation).where(
            AccountDeletionOperation.user_id == user_id
        )
    )
    if existing is not None:
        # [人工注释][S1-022] 不要求客户端永久记住首次 request_id。只要账号 gate 已存在，
        # 新 request_id 也 join 同一不可逆注销流程，并返回 canonical request_id。
        db.commit()
        return existing

    active_data_delete = db.scalar(
        select(DataDeletionOperation).where(
            DataDeletionOperation.user_id == user_id,
            DataDeletionOperation.status != DataDeletionStatus.COMPLETED,
        )
    )
    data_request_id = (
        active_data_delete.request_id
        if active_data_delete is not None
        else uuid4()
    )
    # [人工注释][S1-022-FIX-004] 没有 active S1-021 时必须生成全新的 server UUID，
    # 绝不能复用客户端 Account Delete request_id。用户可能曾用相同 request_id 完成过
    # 一次 Data Delete；复用会把历史 COMPLETED receipt 误当本次清理完成，跳过新对象存储。
    operation = AccountDeletionOperation(
        user_id=user_id,
        request_id=request_id,
        data_deletion_request_id=data_request_id,
    )
    db.add(operation)
    try:
        db.commit()
        return operation
    except IntegrityError:
        # User FOR UPDATE 在 PostgreSQL 会串行化首次创建；唯一键仍是 SQLite/异常竞态的最后门禁。
        db.rollback()
        existing = db.scalar(
            select(AccountDeletionOperation).where(
                AccountDeletionOperation.user_id == user_id
            )
        )
        if existing is None:
            raise
        return existing


def lock_external_data_delete_entry(
    db: Session,
    *,
    user_id: UUID,
) -> None:
    # [人工注释][S1-022] 外部 /data/delete 与首次 Account Delete gate 必须锁同一 User row。
    # 这个 helper 故意不 commit：调用方随后进入 S1-021 _begin_or_load_operation，
    # 让“检查 account gate -> 建立/加载 data deletion op”保持在同一 User FOR UPDATE 顺序中。
    user = db.scalar(select(User.id).where(User.id == user_id).with_for_update())
    if user is None:
        raise AccountDeletionError("USER_NOT_FOUND", 404)

    active = db.scalar(
        select(AccountDeletionOperation.id)
        .where(AccountDeletionOperation.user_id == user_id)
        .limit(1)
    )
    if active is not None:
        raise AccountDeletionError("ACCOUNT_DELETION_IN_PROGRESS", 423)


def _delete_auth_identities(db: Session, user_id: UUID) -> None:
    db.execute(delete(AuthIdentity).where(AuthIdentity.user_id == user_id))


def _finalize_account_deletion(
    db: Session,
    *,
    user_id: UUID,
    operation_id: UUID,
    data_request_id: UUID,
) -> None:
    try:
        user = db.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None:
            db.rollback()
            return

        operation = db.scalar(
            select(AccountDeletionOperation)
            .where(
                AccountDeletionOperation.id == operation_id,
                AccountDeletionOperation.user_id == user_id,
            )
            .with_for_update()
        )
        if operation is None:
            db.rollback()
            raise AccountDeletionError("ACCOUNT_DELETION_NOT_FOUND", 409)

        data_operation = db.scalar(
            select(DataDeletionOperation)
            .where(
                DataDeletionOperation.user_id == user_id,
                DataDeletionOperation.request_id == data_request_id,
            )
            .with_for_update()
        )
        if data_operation is None or data_operation.status != DataDeletionStatus.COMPLETED:
            db.rollback()
            raise AccountDeletionError("ACCOUNT_DELETION_DATA_NOT_COMPLETED", 409)

        # [人工注释][S1-022] 身份、S1-021 receipt、Account Delete gate 与 User 必须在
        # 一个事务中消失。任意失败整体 rollback，绝不能出现“User 已删但 AuthIdentity 仍可登录”
        # 或“identity 已删但 User/数据还处于半注销”的状态。
        _delete_auth_identities(db, user_id)
        db.execute(
            delete(DataDeletionOperation).where(
                DataDeletionOperation.user_id == user_id
            )
        )
        db.execute(
            delete(AccountDeletionOperation).where(
                AccountDeletionOperation.user_id == user_id
            )
        )
        db.execute(delete(User).where(User.id == user_id))
        db.commit()
    except AccountDeletionError:
        raise
    except Exception as exc:
        db.rollback()
        raise AccountDeletionError("ACCOUNT_DELETION_DATABASE_FAILED", 503) from exc


def delete_current_account(
    db: Session,
    *,
    user_id: UUID,
    request_id: UUID,
    storage: ObjectStorage,
    local_cleanup_ready: bool,
) -> AccountDeletionResult:
    """Converge account deletion through the existing S1-021 durable data erasure path."""

    operation = _begin_or_load_account_deletion(
        db,
        user_id=user_id,
        request_id=request_id,
    )
    if operation is None:
        return _already_deleted(request_id)

    if not local_cleanup_ready:
        # [人工注释][S1-022-FIX-002] PREPARE 只持久化 AccountDeletionOperation gate。
        # 官方客户端收到这个 durable 锚点后才清本机 owner payload；在客户端明确回报
        # local_cleanup_ready=true 之前，服务端绝不推进 S1-021，更不能删除登录身份。
        return AccountDeletionResult(
            request_id=operation.request_id,
            data_deletion_status=None,
            completed=False,
            retry_after_seconds=None,
            deleted_counts={},
        )

    try:
        data_result = delete_all_user_data(
            db,
            user_id=user_id,
            request_id=operation.data_deletion_request_id,
            storage=storage,
        )
    except DataDeletionError as exc:
        if exc.code == "USER_NOT_FOUND":
            # [人工注释][S1-022] 两个注销请求可同时 join 同一 gate；若另一请求已完成
            # 最终身份事务，本请求可能在进入下一段 S1-021 时才看到 User 消失。
            # 协议已定义 User absence 为 completed，因此这里与入口保持同一幂等语义。
            return _already_deleted(operation.request_id)
        # AccountDeletionOperation intentionally remains present, so normal application
        # writes stay locked while the caller retries the exact S1-021 failure.
        raise

    if not data_result.completed:
        return _result_from_data(operation, data_result)

    canonical_request_id = operation.request_id
    deleted_counts = data_result.deleted_counts
    _finalize_account_deletion(
        db,
        user_id=user_id,
        operation_id=operation.id,
        data_request_id=operation.data_deletion_request_id,
    )
    return AccountDeletionResult(
        request_id=canonical_request_id,
        data_deletion_status=DataDeletionStatus.COMPLETED,
        completed=True,
        retry_after_seconds=None,
        deleted_counts=deleted_counts,
    )
