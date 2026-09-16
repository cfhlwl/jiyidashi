from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.models import User
from app.schemas import UserRead, UserUpdate

router = APIRouter(prefix="/user", tags=["user"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]


@router.get("", response_model=UserRead)
def get_user(user_id: CurrentUser, db: DbSession) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="USER_NOT_FOUND")
    return user


@router.patch("", response_model=UserRead)
def update_user(payload: UserUpdate, user_id: CurrentUser, db: DbSession) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="USER_NOT_FOUND")

    # [人工注释][S1-002] 仅允许更新公开资料字段；邮箱/身份归属不通过 profile API 修改。
    if payload.nickname is not None:
        user.nickname = payload.nickname.strip()
    if payload.timezone is not None:
        user.timezone = payload.timezone
    if payload.locale is not None:
        user.locale = payload.locale.strip()

    db.commit()
    db.refresh(user)
    return user
