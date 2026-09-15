from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import create_access_token
from app.models import User
from app.schemas import DevTokenRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
DbSession = Annotated[Session, Depends(get_db)]


@router.post("/dev-token", response_model=TokenResponse)
def dev_token(payload: DevTokenRequest, db: DbSession) -> TokenResponse:
    # Fail closed: the endpoint is absent-by-policy unless explicitly enabled.
    # APP_ENV alone can never make dev authentication available.
    if not settings.enable_dev_auth:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="NOT_FOUND",
        )

    user_id = payload.user_id or uuid4()
    user = db.get(User, user_id)
    if user is None:
        user = User(id=user_id, nickname=payload.nickname)
        db.add(user)
        db.commit()

    return TokenResponse(
        access_token=create_access_token(user_id),
        user_id=user_id,
    )
