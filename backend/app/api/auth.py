from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import create_access_token
from app.models import User
from app.schemas import DevTokenRequest, LoginRequest, RegisterRequest, TokenResponse
from app.services.auth_service import authenticate_email_password, register_email_password

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()
DbSession = Annotated[Session, Depends(get_db)]


def _client_ip(request: Request) -> str:
    # [人工注释][S1-FIX-003] 认证限流只使用 ASGI 已解析的 client host，不信任可由客户端伪造的普通请求头。
    return request.client.host if request.client is not None else "unknown"


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, db: DbSession) -> TokenResponse:
    # [人工注释][S1-001] 正式注册由服务端生成 user_id，客户端不能选择或覆盖身份归属。
    user = register_email_password(db, payload, client_ip=_client_ip(request))
    return TokenResponse(
        access_token=create_access_token(user.id),
        user_id=user.id,
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: DbSession) -> TokenResponse:
    # [人工注释][S1-001] 登录只在凭证校验成功后签发正式访问 Token。
    user = authenticate_email_password(db, payload, client_ip=_client_ip(request))
    return TokenResponse(
        access_token=create_access_token(user.id),
        user_id=user.id,
    )


@router.post("/dev-token", response_model=TokenResponse)
def dev_token(payload: DevTokenRequest, db: DbSession) -> TokenResponse:
    # [人工注释][FND-019] 生产环境无条件禁用开发认证；即使误配 ENABLE_DEV_AUTH=true 也必须 404。
    if settings.is_production or not settings.enable_dev_auth:
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
