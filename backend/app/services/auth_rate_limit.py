import hashlib
import hmac
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth_models import AuthRateLimitBucket
from app.core.config import get_settings
from app.security_models import SecuritySignalCode
from app.services.security_alerting import SecurityScope, record_security_signal

settings = get_settings()

_SECURITY_SCOPE_BY_RATE_SCOPE = {
    "register_ip": SecurityScope.AUTH_REGISTER_IP,
    "login_ip": SecurityScope.AUTH_LOGIN_IP,
    "login_account_ip": SecurityScope.AUTH_LOGIN_ACCOUNT_IP,
    "refresh_session": SecurityScope.AUTH_REFRESH_SESSION,
    "verify_ip": SecurityScope.AUTH_VERIFY_IP,
    "verify_account": SecurityScope.AUTH_VERIFY_ACCOUNT,
    "password_reset_ip": SecurityScope.AUTH_PASSWORD_RESET_IP,
    "password_reset_account": SecurityScope.AUTH_PASSWORD_RESET_ACCOUNT,
    "password_reset_confirm": SecurityScope.AUTH_PASSWORD_RESET_CONFIRM,
    "admin_login_ip": SecurityScope.ADMIN_LOGIN_IP,
    "admin_login_account_ip": SecurityScope.ADMIN_LOGIN_ACCOUNT_IP,
    "phone_one_tap_ip": SecurityScope.AUTH_PHONE_ONE_TAP,
    "phone_one_tap_device": SecurityScope.AUTH_PHONE_ONE_TAP,
    "phone_one_tap_request": SecurityScope.AUTH_PHONE_ONE_TAP,
    "phone_one_tap_token": SecurityScope.AUTH_PHONE_ONE_TAP,
    "sms_otp_ip": SecurityScope.AUTH_LOGIN_IP,
    "sms_otp_device": SecurityScope.AUTH_LOGIN_IP,
    "sms_otp_phone": SecurityScope.AUTH_LOGIN_ACCOUNT_IP,
    "sms_otp_verify_ip": SecurityScope.AUTH_LOGIN_IP,
    "sms_otp_verify_request": SecurityScope.AUTH_LOGIN_ACCOUNT_IP,
}


def _record_auth_security_signal(
    db: Session,
    *,
    signal_code: SecuritySignalCode,
    scope: str,
    value: str,
) -> None:
    security_scope = _SECURITY_SCOPE_BY_RATE_SCOPE.get(scope)
    if scope.startswith("api_"):
        security_scope = SecurityScope.API_AUTHENTICATED
        signal_code = SecuritySignalCode.API_RATE_LIMIT_TRIGGERED
    if security_scope is None:
        return
    record_security_signal(
        db.get_bind(),
        signal_code=signal_code,
        correlation_kind=scope,
        correlation_value=value,
        scope=security_scope,
    )


@dataclass(frozen=True)
class RatePolicy:
    limit: int
    window_seconds: int


class ApiRouteClass(StrEnum):
    NORMAL_READ = "NORMAL_READ"
    NORMAL_MUTATION = "NORMAL_MUTATION"
    MEDIA_TRANSFER = "MEDIA_TRANSFER"
    EXPENSIVE_AI = "EXPENSIVE_AI"
    EXPENSIVE_EXPORT = "EXPENSIVE_EXPORT"


def _api_policy(route_class: ApiRouteClass) -> tuple[RatePolicy, RatePolicy]:
    window = settings.api_rate_window_seconds
    if route_class == ApiRouteClass.NORMAL_READ:
        return (
            RatePolicy(settings.api_normal_user_limit, window),
            RatePolicy(settings.api_normal_ip_limit, window),
        )
    if route_class == ApiRouteClass.NORMAL_MUTATION:
        return (
            RatePolicy(settings.api_mutation_user_limit, window),
            RatePolicy(settings.api_mutation_ip_limit, window),
        )
    if route_class == ApiRouteClass.MEDIA_TRANSFER:
        return (
            RatePolicy(settings.api_media_user_limit, window),
            RatePolicy(settings.api_media_ip_limit, window),
        )
    if route_class == ApiRouteClass.EXPENSIVE_AI:
        return (
            RatePolicy(settings.api_expensive_user_limit, window),
            RatePolicy(settings.api_expensive_ip_limit, window),
        )
    return (
        RatePolicy(settings.api_export_user_limit, window),
        RatePolicy(settings.api_export_ip_limit, window),
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _bucket_key(scope: str, value: str) -> str:
    # [人工注释][S1-FIX-003] bucket key 使用服务端密钥做 HMAC，避免在限流表中存原始 IP / 邮箱。
    message = f"{scope}:{value}".encode()
    return hmac.new(settings.jwt_secret.encode(), message, hashlib.sha256).hexdigest()


def _rate_limited(
    retry_after_seconds: int,
    *,
    detail: str = "AUTH_RATE_LIMITED",
) -> HTTPException:
    retry_after = max(1, retry_after_seconds)
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
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
            _record_auth_security_signal(
                db,
                signal_code=SecuritySignalCode.AUTH_RATE_LIMIT_TRIGGERED,
                scope=scope,
                value=value,
            )
            raise _rate_limited(
                retry_after,
                detail=(
                    "API_RATE_LIMITED"
                    if scope.startswith("api_")
                    else "AUTH_RATE_LIMITED"
                ),
            )
        bucket.blocked_until = None

    if bucket.attempts >= policy.limit:
        window_end = _as_utc(bucket.window_started_at) + timedelta(
            seconds=policy.window_seconds
        )
        bucket.blocked_until = max(now + timedelta(seconds=1), window_end)
        bucket.updated_at = now
        retry_after = math.ceil((bucket.blocked_until - now).total_seconds())
        db.commit()
        _record_auth_security_signal(
            db,
            signal_code=SecuritySignalCode.AUTH_RATE_LIMIT_TRIGGERED,
            scope=scope,
            value=value,
        )
        raise _rate_limited(
            retry_after,
            detail=(
                "API_RATE_LIMITED"
                if scope.startswith("api_")
                else "AUTH_RATE_LIMITED"
            ),
        )

    bucket.attempts += 1
    bucket.updated_at = now
    db.commit()
    return bucket


def consume_authenticated_api_attempt(
    db: Session,
    *,
    user_id: UUID,
    client_ip: str,
    route_class: ApiRouteClass,
) -> None:
    if not settings.api_rate_limit_enabled:
        return
    user_policy, ip_policy = _api_policy(route_class)
    # Route class is part of the HMAC input so policies are independent. Raw user/IP
    # values never enter the persisted key.
    _consume(
        db,
        scope=f"api_user:{route_class.value}",
        value=str(user_id),
        policy=user_policy,
    )
    _consume(
        db,
        scope=f"api_ip:{route_class.value}",
        value=client_ip,
        policy=ip_policy,
    )


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


def consume_phone_one_tap_attempt(
    db: Session,
    *,
    client_ip: str,
    device_id: str,
    request_id: str,
    token_fingerprint: str | None = None,
) -> None:
    """Consume anonymous one-tap gates before external provider I/O."""

    if not settings.auth_rate_limit_enabled:
        return
    window = settings.auth_phone_one_tap_window_seconds
    _consume(
        db,
        scope="phone_one_tap_ip",
        value=client_ip,
        policy=RatePolicy(
            limit=settings.auth_phone_one_tap_ip_limit,
            window_seconds=window,
        ),
    )
    _consume(
        db,
        scope="phone_one_tap_device",
        value=device_id,
        policy=RatePolicy(
            limit=settings.auth_phone_one_tap_device_limit,
            window_seconds=window,
        ),
    )
    _consume(
        db,
        scope="phone_one_tap_request",
        value=request_id,
        policy=RatePolicy(
            limit=settings.auth_phone_one_tap_request_limit,
            window_seconds=window,
        ),
    )
    if token_fingerprint:
        _consume(
            db,
            scope="phone_one_tap_token",
            value=token_fingerprint,
            policy=RatePolicy(
                limit=settings.auth_phone_one_tap_token_limit,
                window_seconds=window,
            ),
        )


def consume_sms_otp_request_attempt(
    db: Session,
    *,
    client_ip: str,
    device_id: str,
    phone_subject: str,
) -> None:
    if not settings.auth_rate_limit_enabled:
        return
    window = settings.auth_sms_otp_window_seconds
    _consume(
        db,
        scope="sms_otp_ip",
        value=client_ip,
        policy=RatePolicy(settings.auth_sms_otp_ip_limit, window),
    )
    _consume(
        db,
        scope="sms_otp_device",
        value=device_id,
        policy=RatePolicy(settings.auth_sms_otp_device_limit, window),
    )
    _consume(
        db,
        scope="sms_otp_phone",
        value=phone_subject,
        policy=RatePolicy(settings.auth_sms_otp_phone_limit, window),
    )


def consume_sms_otp_verify_attempt(
    db: Session,
    *,
    client_ip: str,
    request_id: str,
) -> None:
    if not settings.auth_rate_limit_enabled:
        return
    window = settings.auth_sms_otp_window_seconds
    _consume(
        db,
        scope="sms_otp_verify_ip",
        value=client_ip,
        policy=RatePolicy(settings.auth_sms_otp_verify_ip_limit, window),
    )
    _consume(
        db,
        scope="sms_otp_verify_request",
        value=request_id,
        policy=RatePolicy(settings.auth_sms_otp_verify_request_limit, window),
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
    _record_auth_security_signal(
        db,
        signal_code=SecuritySignalCode.AUTH_LOGIN_FAILURE_BURST,
        scope="login_account_ip",
        value=f"{client_ip}\n{subject}",
    )


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

def consume_admin_login_ip_attempt(db: Session, client_ip: str) -> None:
    if not settings.auth_rate_limit_enabled:
        return
    _consume(
        db,
        scope="admin_login_ip",
        value=client_ip,
        policy=RatePolicy(
            limit=settings.admin_login_ip_limit,
            window_seconds=settings.admin_login_window_seconds,
        ),
    )


def consume_admin_login_account_attempt(
    db: Session,
    client_ip: str,
    subject: str,
) -> None:
    if not settings.auth_rate_limit_enabled:
        return
    _consume(
        db,
        scope="admin_login_account_ip",
        value=f"{client_ip}\n{subject}",
        policy=RatePolicy(
            limit=settings.admin_login_account_ip_limit,
            window_seconds=settings.admin_login_window_seconds,
        ),
    )


def record_admin_login_failure(db: Session, client_ip: str, subject: str) -> None:
    if not settings.auth_rate_limit_enabled:
        return

    now = datetime.now(UTC)
    policy = RatePolicy(
        limit=settings.admin_login_account_ip_limit,
        window_seconds=settings.admin_login_window_seconds,
    )
    bucket = _get_or_create_bucket(
        db,
        scope="admin_login_account_ip",
        value=f"{client_ip}\n{subject}",
        now=now,
    )
    _refresh_window(bucket, now=now, policy=policy)
    bucket.failures += 1

    if bucket.failures >= settings.admin_login_backoff_after_failures:
        exponent = bucket.failures - settings.admin_login_backoff_after_failures
        seconds = min(
            2 ** (exponent + 1),
            settings.admin_login_backoff_max_seconds,
        )
        bucket.blocked_until = now + timedelta(seconds=seconds)

    bucket.updated_at = now
    db.commit()
    _record_auth_security_signal(
        db,
        signal_code=SecuritySignalCode.AUTH_LOGIN_FAILURE_BURST,
        scope="admin_login_account_ip",
        value=f"{client_ip}\n{subject}",
    )


def clear_admin_login_account_penalty(
    db: Session,
    client_ip: str,
    subject: str,
) -> None:
    if not settings.auth_rate_limit_enabled:
        return

    key = _bucket_key("admin_login_account_ip", f"{client_ip}\n{subject}")
    bucket = db.scalar(
        select(AuthRateLimitBucket)
        .where(AuthRateLimitBucket.key == key)
        .with_for_update()
    )
    if bucket is None:
        return

    now = datetime.now(UTC)
    bucket.window_started_at = now
    bucket.attempts = 0
    bucket.failures = 0
    bucket.blocked_until = None
    bucket.updated_at = now
    db.commit()

def consume_refresh_attempt(db: Session, session_scope: str) -> None:
    if not settings.auth_rate_limit_enabled:
        return
    _consume(
        db,
        scope="refresh_session",
        value=session_scope,
        policy=RatePolicy(
            limit=settings.auth_refresh_session_limit,
            window_seconds=settings.auth_refresh_window_seconds,
        ),
    )


def consume_verification_resend(
    db: Session,
    client_ip: str,
    subject: str,
) -> None:
    if not settings.auth_rate_limit_enabled:
        return
    _consume(
        db,
        scope="verify_ip",
        value=client_ip,
        policy=RatePolicy(
            limit=settings.auth_verify_resend_ip_limit,
            window_seconds=settings.auth_verify_resend_window_seconds,
        ),
    )
    _consume(
        db,
        scope="verify_account",
        value=subject,
        policy=RatePolicy(
            limit=settings.auth_verify_resend_account_limit,
            window_seconds=settings.auth_verify_resend_window_seconds,
        ),
    )


def consume_password_reset_request(
    db: Session,
    client_ip: str,
    subject: str,
) -> None:
    if not settings.auth_rate_limit_enabled:
        return
    _consume(
        db,
        scope="password_reset_ip",
        value=client_ip,
        policy=RatePolicy(
            limit=settings.auth_password_reset_ip_limit,
            window_seconds=settings.auth_password_reset_window_seconds,
        ),
    )
    _consume(
        db,
        scope="password_reset_account",
        value=subject,
        policy=RatePolicy(
            limit=settings.auth_password_reset_account_limit,
            window_seconds=settings.auth_password_reset_window_seconds,
        ),
    )


def consume_password_reset_confirmation(
    db: Session,
    client_ip: str,
    token_digest: str,
) -> None:
    if not settings.auth_rate_limit_enabled:
        return
    _consume(
        db,
        scope="password_reset_confirm",
        value=f"{client_ip}\n{token_digest}",
        policy=RatePolicy(
            limit=settings.auth_password_reset_confirm_limit,
            window_seconds=settings.auth_password_reset_window_seconds,
        ),
    )

