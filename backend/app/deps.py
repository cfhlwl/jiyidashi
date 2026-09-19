from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.account_deletion_models import AccountDeletionOperation
from app.core.db import (
    USER_DATA_ADMISSION_INFO_KEY,
    UserDataAdmission,
    get_db,
)
from app.core.security import decode_access_token
from app.data_deletion_models import DataDeletionOperation, DataDeletionStatus
from app.models import User

bearer = HTTPBearer()
BearerCredentials = Annotated[HTTPAuthorizationCredentials, Depends(bearer)]


def get_authenticated_user_id(credentials: BearerCredentials) -> UUID:
    """Authenticate an account without applying application-data lifecycle gates."""

    return decode_access_token(credentials.credentials)


AuthenticatedUser = Annotated[UUID, Depends(get_authenticated_user_id)]
DbSession = Annotated[Session, Depends(get_db)]


def get_current_user_id(user_id: AuthenticatedUser, db: DbSession) -> UUID:
    # [人工注释][S1-021-FIX-001] 请求入口只负责“准入”：在 User KEY SHARE 下读取
    # deletion generation 并保存到 Session.info。真正的持久化门禁由 GuardedSession
    # 在每一次 commit 前重新拿锁并比较 generation，因此 rollback/commit 都不能绕过。
    existing = db.scalar(
        select(User.id).where(User.id == user_id).with_for_update(read=True, key_share=True)
    )
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="USER_NOT_FOUND")

    active_account_deletion = db.scalar(
        select(AccountDeletionOperation.id)
        .where(AccountDeletionOperation.user_id == user_id)
        .limit(1)
    )
    if active_account_deletion is not None:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="ACCOUNT_DELETION_IN_PROGRESS",
        )

    active_deletion = db.scalar(
        select(DataDeletionOperation.id)
        .where(
            DataDeletionOperation.user_id == user_id,
            DataDeletionOperation.status != DataDeletionStatus.COMPLETED,
        )
        .limit(1)
    )
    if active_deletion is not None:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="DATA_DELETION_IN_PROGRESS",
        )

    deletion_generation = int(
        db.scalar(
            select(func.count(DataDeletionOperation.id)).where(
                DataDeletionOperation.user_id == user_id
            )
        )
        or 0
    )
    db.info[USER_DATA_ADMISSION_INFO_KEY] = UserDataAdmission(
        user_id=user_id,
        deletion_generation=deletion_generation,
    )
    return user_id
