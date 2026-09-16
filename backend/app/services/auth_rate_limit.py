import hashlib
import hmac
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth_models import AuthRateLimitBucket
from app.core.config import get_settings

settings = get_settings()


@dataclass(frozen=True)
class RatePolicy:
    limit: int
    window_seconds: int


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _bucket_key(scope: str, value: str) -> str:
    # [人工注释][S1-FIX-003] bucket key 使用服务端密钥做 HMAC，避免在限流表中存原始 IP / 邮箱。
    message = f"{scope}:{value}".encode()
    return hmac.new(settings.jwt_secret.encode(), message, hashlib.sha256).hexdigest()


def _rate_limited(retry_after_seconds: int) -> HTTPException:
    retry_after = max(1, retry_after_seconds)
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="AUTH_RATE_LIMITED",
        headers={"Retry-After": str(retry_after)},
    )


def _get_or_create_bucket(
    db: Session,
    *,
    scope: str,
    value: str,
    now: datetime,
) -> AuthRateLimitBucket:
    key = _bucket_key(scope, value)
    bucket = db.scalar(
        select(AuthRateLimitBucket)
        .where(AuthRateLimitBucket.key == key)
        .with_for_update()
    )
    if bucket is not None:
        return bucket

    bucket = AuthRateLimitBucket(
        key=key,
        scope=scope,
        window_started_at=now,
        attempts=0,
        failures=0,
        updated_at=now,
    )
    db.add(bucket)
    try:
        db.flush()
        return bucket
    except IntegrityError:
        # [人工注释][S1-FIX-003] 并发首次命中同一 bucket 时回滚后重取，不能把限流竞争变成 500。
        db.rollback()
        existing = db.scalar(
            select(AuthRateLimitBucket)
            .where(AuthRateLimitBucket.key == key)
            .with_for_update()
        )
        if existing is None:
            raise
        return existing


def _refresh_window(
    bucket: AuthRateLimitBucket,
    *,
    now: datetime,
    policy: RatePolicy,
) -> None:
    started = _as_utc(bucket.window_started_at)
    if now - started >= timedelta(seconds=policy.window_seconds):
        bucket.window_started_at = now
        bucket.attempts = 0
        bucket.failures = 0
        bucket.blocked_until = None


def _consume(
    db: Session,
    *,
    scope: str,
    value: str,
    policy: RatePolicy,
) -> AuthRateLimitBucket:
    now = datetime.now(UTC)
    bucket = _get_or_create_bucket(db, scope=scope, value=value, now=now)
    _refresh_window(bucket, now=now, policy=policy)

    if bucket.blocked_until is not None:
        blocked_until = _as_utc(bucket.blocked_until)
        if blocked_until > now:
            retry_after = math.ceil((blocked_until - now).total_seconds())
            db.commit()
            raise _rate_limited(retry_after)
        bucket.blocked_until = None

    if bucket.attempts >= policy.limit:
        window_end = _as_utc(bucket.window_started_at) + timedelta(
            seconds=policy.window_seconds
        )
        bucket.blocked_until = max(now + timedelta(seconds=1), window_end)
        bucket.updated_at = now
        retry_after = math.ceil((bucket.blocked_until - now).total_seconds())
        db.commit()
        raise _rate_limited(retry_after)

    bucket.attempts += 1
    bucket.updated_at = now
    db.commit()
    return bucket


def consume_registration_attempt(db: Session, client_ip: str) -> None:
    if not settings.auth_rate_limit_enabled:
        return
    _consume(
        db,
        scope="register_ip",
        value=client_ip,
        policy=RatePolicy(
            limit=settings.auth_register_ip_limit,
            window_seconds=settings.auth_register_window_seconds,
        ),
    )


def consume_login_ip_attempt(db: Session, client_ip: str) -> None:
    if not settings.auth_rate_limit_enabled:
        return
    _consume(
        db,
        scope="login_ip",
        value=client_ip,
        policy=RatePolicy(
            limit=settings.auth_login_ip_limit,
            window_seconds=settings.auth_login_window_seconds,
        ),
    )


def consume_login_account_attempt(db: Session, client_ip: str, subject: str) -> None:
    if not settings.auth_rate_limit_enabled:
        return
    _consume(
        db,
        scope="login_account_ip",
        value=f"{client_ip}\n{subject}",
        policy=RatePolicy(
            limit=settings.auth_login_account_ip_limit,
            window_seconds=settings.auth_login_window_seconds,
        ),
    )


def record_login_failure(db: Session, client_ip: str, subject: str) -> None:
    if not settings.auth_rate_limit_enabled:
        return

    now = datetime.now(UTC)
    policy = RatePolicy(
        limit=settings.auth_login_account_ip_limit,
        window_seconds=settings.auth_login_window_seconds,
    )
    bucket = _get_or_create_bucket(
        db,
        scope="login_account_ip",
        value=f"{client_ip}\n{subject}",
        now=now,
    )
    _refresh_window(bucket, now=now, policy=policy)
    bucket.failures += 1

    if bucket.failures >= settings.auth_login_backoff_after_failures:
        exponent = bucket.failures - settings.auth_login_backoff_after_failures
        seconds = min(2 ** (exponent + 1), settings.auth_login_backoff_max_seconds)
        bucket.blocked_until = now + timedelta(seconds=seconds)

    bucket.updated_at = now
    db.commit()


def clear_login_account_penalty(db: Session, client_ip: str, subject: str) -> None:
    if not settings.auth_rate_limit_enabled:
        return

    key = _bucket_key("login_account_ip", f"{client_ip}\n{subject}")
    bucket = db.scalar(
        select(AuthRateLimitBucket)
        .where(AuthRateLimitBucket.key == key)
        .with_for_update()
    )
    if bucket is None:
        return

    # [人工注释][S1-FIX-003] 成功登录只清当前账号+IP 的失败惩罚；IP 总窗口仍保留以防密码喷洒。
    now = datetime.now(UTC)
    bucket.window_started_at = now
    bucket.attempts = 0
    bucket.failures = 0
    bucket.blocked_until = None
    bucket.updated_at = now
    db.commit()
