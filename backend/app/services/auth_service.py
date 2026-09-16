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
from app.services.auth_rate_limit import (
    clear_login_account_penalty,
    consume_login_account_attempt,
    consume_login_ip_attempt,
    consume_registration_attempt,
    record_login_failure,
)

_password_hasher = PasswordHasher()
# [人工注释][S1-FIX-004] 不存在账号也执行一次固定 Argon2 verify，缩小账号存在性的时间侧信道。
_DUMMY_ARGON2_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$CEhs1030PAoj5q0ODmRs5w$"
    "7hkHfPhql7bS5jt+yw3cdNJOFvIab4cwY1pem1n9hmw"
)


def normalize_email(value: str) -> str:
    return value.strip().casefold()


def register_email_password(
    db: Session,
    payload: RegisterRequest,
    *,
    client_ip: str,
) -> User:
    # [人工注释][S1-FIX-003] 注册 IP 门禁在任何 Argon2 hash 之前消费额度，阻止匿名高成本请求洪泛。
    consume_registration_attempt(db, client_ip)

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
        nickname=payload.nickname,
        email=subject,
        timezone=payload.timezone,
        locale=payload.locale,
    )
    db.add(user)
    try:
        # [人工注释][S1-001] User.id 是 ORM insert-time default，必须先 flush 后再建立身份外键。
        db.flush()
        identity = AuthIdentity(
            user_id=user.id,
            provider=AuthProvider.EMAIL_PASSWORD,
            subject=subject,
            secret_hash=_password_hasher.hash(payload.password),
        )
        db.add(identity)
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


def authenticate_email_password(
    db: Session,
    payload: LoginRequest,
    *,
    client_ip: str,
) -> User:
    subject = normalize_email(str(payload.email))

    # [人工注释][S1-FIX-003] IP 总窗口先于账号查询和 Argon2；防止随机账号喷洒造成 CPU/内存耗尽。
    consume_login_ip_attempt(db, client_ip)
    identity = db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == AuthProvider.EMAIL_PASSWORD,
            AuthIdentity.subject == subject,
        )
    )

    if identity is not None:
        # 只有真实存在的身份才建立账号+IP bucket，避免攻击者用随机邮箱制造无界 bucket 行。
        consume_login_account_attempt(db, client_ip, subject)

    verification_hash = (
        identity.secret_hash
        if identity is not None and identity.secret_hash
        else _DUMMY_ARGON2_HASH
    )
    verified = False
    try:
        verified = bool(_password_hasher.verify(verification_hash, payload.password))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        verified = False

    # [人工注释][S1-001][S1-FIX-004] HTTP 语义与 Argon2 成本路径都不区分账号不存在和密码错误。
    if identity is None or not identity.secret_hash or not verified:
        if identity is not None:
            record_login_failure(db, client_ip, subject)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_CREDENTIALS",
        )

    clear_login_account_penalty(db, client_ip, subject)

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
