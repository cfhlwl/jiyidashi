from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth_models import AuthIdentity, AuthProvider
from app.models import User
from app.schemas import LoginRequest, RegisterRequest

_password_hasher = PasswordHasher()


def normalize_email(value: str) -> str:
    return value.strip().casefold()


def register_email_password(db: Session, payload: RegisterRequest) -> User:
    subject = normalize_email(str(payload.email))
    # [人工注释][S1-001] provider + subject 是正式身份唯一键；客户端不能指定 user_id。
    existing = db.scalar(
        select(AuthIdentity.id).where(
            AuthIdentity.provider == AuthProvider.EMAIL_PASSWORD,
            AuthIdentity.subject == subject,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="AUTH_IDENTITY_EXISTS",
        )

    user = User(
        nickname=payload.nickname.strip(),
        email=subject,
        timezone=payload.timezone,
        locale=payload.locale,
    )
    identity = AuthIdentity(
        user_id=user.id,
        provider=AuthProvider.EMAIL_PASSWORD,
        subject=subject,
        secret_hash=_password_hasher.hash(payload.password),
    )
    db.add(user)
    db.add(identity)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # [人工注释][S1-001] 并发注册或历史 User.email 冲突统一映射为同一个公开错误。
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="AUTH_IDENTITY_EXISTS",
        ) from exc
    db.refresh(user)
    return user


def authenticate_email_password(db: Session, payload: LoginRequest) -> User:
    subject = normalize_email(str(payload.email))
    identity = db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == AuthProvider.EMAIL_PASSWORD,
            AuthIdentity.subject == subject,
        )
    )

    # [人工注释][S1-001] 不区分“账号不存在”和“密码错误”，避免认证接口泄露账号存在性。
    if identity is None or not identity.secret_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_CREDENTIALS",
        )

    try:
        _password_hasher.verify(identity.secret_hash, payload.password)
    except (VerifyMismatchError, VerificationError, InvalidHashError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_CREDENTIALS",
        ) from exc

    user = db.get(User, identity.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_CREDENTIALS",
        )

    if _password_hasher.check_needs_rehash(identity.secret_hash):
        identity.secret_hash = _password_hasher.hash(payload.password)
    identity.last_login_at = datetime.now(UTC)
    db.commit()
    return user
