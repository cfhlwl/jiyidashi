from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import or_, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.observability import (
    emit_operational_event,
    emit_security_alert_event_checked,
)
from app.security_models import (
    SecurityAlert,
    SecurityAlertDeliveryStatus,
    SecuritySeverity,
    SecuritySignalCode,
    SecuritySignalWindow,
)
from app.services.security_alert_human_delivery import (
    HumanDeliveryResult,
    SecurityAlertHumanDeliveryAdapter,
    SecurityAlertHumanMessage,
    get_security_alert_human_adapter,
)

MAX_DELIVERY_ATTEMPTS = 5
DELIVERY_BACKOFF_BASE_SECONDS = 30
DELIVERY_BACKOFF_MAX_SECONDS = 900


class SecurityScope(StrEnum):
    AUTH_REGISTER_IP = "AUTH_REGISTER_IP"
    AUTH_LOGIN_IP = "AUTH_LOGIN_IP"
    AUTH_LOGIN_ACCOUNT_IP = "AUTH_LOGIN_ACCOUNT_IP"
    AUTH_REFRESH_SESSION = "AUTH_REFRESH_SESSION"
    AUTH_VERIFY_IP = "AUTH_VERIFY_IP"
    AUTH_VERIFY_ACCOUNT = "AUTH_VERIFY_ACCOUNT"
    AUTH_PASSWORD_RESET_IP = "AUTH_PASSWORD_RESET_IP"
    AUTH_PASSWORD_RESET_ACCOUNT = "AUTH_PASSWORD_RESET_ACCOUNT"
    AUTH_PASSWORD_RESET_CONFIRM = "AUTH_PASSWORD_RESET_CONFIRM"
    AUTH_PHONE_ONE_TAP = "AUTH_PHONE_ONE_TAP"
    ADMIN_LOGIN_IP = "ADMIN_LOGIN_IP"
    ADMIN_LOGIN_ACCOUNT_IP = "ADMIN_LOGIN_ACCOUNT_IP"
    FAMILY_CURRENT_LOCATION = "FAMILY_CURRENT_LOCATION"
    FAMILY_TODAY_FOOTPRINT = "FAMILY_TODAY_FOOTPRINT"
    FAMILY_MEMORY = "FAMILY_MEMORY"
    FAMILY_PHOTO_LIST = "FAMILY_PHOTO_LIST"
    FAMILY_PHOTO_DOWNLOAD = "FAMILY_PHOTO_DOWNLOAD"
    FAMILY_SENSITIVE_ACCESS = "FAMILY_SENSITIVE_ACCESS"
    DATA_DELETE = "DATA_DELETE"
    ACCOUNT_DELETE = "ACCOUNT_DELETE"
    MEDIA_UPLOAD = "MEDIA_UPLOAD"
    MEDIA_COMPLETE = "MEDIA_COMPLETE"
    MEDIA_DOWNLOAD = "MEDIA_DOWNLOAD"
    FAMILY_PHOTO_STORAGE = "FAMILY_PHOTO_STORAGE"
    API_AUTHENTICATED = "API_AUTHENTICATED"
    PROVIDER_AI = "PROVIDER_AI"
    PROVIDER_ASR = "PROVIDER_ASR"
    PROVIDER_EMBEDDING = "PROVIDER_EMBEDDING"
    ARGON2 = "ARGON2"


@dataclass(frozen=True)
class SecurityRulePolicy:
    window_seconds: int
    threshold: int
    cooldown_seconds: int
    severity: SecuritySeverity
    allowed_scopes: frozenset[SecurityScope]


RULES: dict[SecuritySignalCode, SecurityRulePolicy] = {
    SecuritySignalCode.AUTH_RATE_LIMIT_TRIGGERED: SecurityRulePolicy(
        window_seconds=600,
        threshold=1,
        cooldown_seconds=600,
        severity=SecuritySeverity.MEDIUM,
        allowed_scopes=frozenset(
            {
                SecurityScope.AUTH_REGISTER_IP,
                SecurityScope.AUTH_LOGIN_IP,
                SecurityScope.AUTH_LOGIN_ACCOUNT_IP,
                SecurityScope.AUTH_REFRESH_SESSION,
                SecurityScope.AUTH_VERIFY_IP,
                SecurityScope.AUTH_VERIFY_ACCOUNT,
                SecurityScope.AUTH_PASSWORD_RESET_IP,
                SecurityScope.AUTH_PASSWORD_RESET_ACCOUNT,
                SecurityScope.AUTH_PASSWORD_RESET_CONFIRM,
                SecurityScope.ADMIN_LOGIN_IP,
                SecurityScope.ADMIN_LOGIN_ACCOUNT_IP,
                SecurityScope.AUTH_PHONE_ONE_TAP,
            }
        ),
    ),
    SecuritySignalCode.AUTH_LOGIN_FAILURE_BURST: SecurityRulePolicy(
        window_seconds=900,
        threshold=5,
        cooldown_seconds=900,
        severity=SecuritySeverity.HIGH,
        allowed_scopes=frozenset(
            {
                SecurityScope.AUTH_LOGIN_ACCOUNT_IP,
                SecurityScope.ADMIN_LOGIN_ACCOUNT_IP,
            }
        ),
    ),
    SecuritySignalCode.AUTH_REFRESH_REPLAY: SecurityRulePolicy(
        window_seconds=3600,
        threshold=1,
        cooldown_seconds=3600,
        severity=SecuritySeverity.HIGH,
        allowed_scopes=frozenset({SecurityScope.AUTH_REFRESH_SESSION}),
    ),
    SecuritySignalCode.FAMILY_SENSITIVE_READ_DENIED: SecurityRulePolicy(
        window_seconds=600,
        threshold=5,
        cooldown_seconds=600,
        severity=SecuritySeverity.MEDIUM,
        allowed_scopes=frozenset(
            {
                SecurityScope.FAMILY_CURRENT_LOCATION,
                SecurityScope.FAMILY_TODAY_FOOTPRINT,
                SecurityScope.FAMILY_MEMORY,
                SecurityScope.FAMILY_PHOTO_LIST,
            }
        ),
    ),
    SecuritySignalCode.FAMILY_SENSITIVE_DOWNLOAD_DENIED: SecurityRulePolicy(
        window_seconds=600,
        threshold=3,
        cooldown_seconds=600,
        severity=SecuritySeverity.HIGH,
        allowed_scopes=frozenset({SecurityScope.FAMILY_PHOTO_DOWNLOAD}),
    ),
    SecuritySignalCode.FAMILY_SENSITIVE_ACCESS_BURST: SecurityRulePolicy(
        window_seconds=600,
        threshold=10,
        cooldown_seconds=600,
        severity=SecuritySeverity.HIGH,
        allowed_scopes=frozenset({SecurityScope.FAMILY_SENSITIVE_ACCESS}),
    ),
    SecuritySignalCode.DESTRUCTIVE_OPERATION_FAILURE: SecurityRulePolicy(
        window_seconds=900,
        threshold=3,
        cooldown_seconds=900,
        severity=SecuritySeverity.HIGH,
        allowed_scopes=frozenset(
            {SecurityScope.DATA_DELETE, SecurityScope.ACCOUNT_DELETE}
        ),
    ),
    SecuritySignalCode.DESTRUCTIVE_OPERATION_RETRY_BURST: SecurityRulePolicy(
        window_seconds=900,
        threshold=3,
        cooldown_seconds=900,
        severity=SecuritySeverity.HIGH,
        allowed_scopes=frozenset(
            {SecurityScope.DATA_DELETE, SecurityScope.ACCOUNT_DELETE}
        ),
    ),
    SecuritySignalCode.STORAGE_CAPABILITY_FAILURE_BURST: SecurityRulePolicy(
        window_seconds=600,
        threshold=5,
        cooldown_seconds=600,
        severity=SecuritySeverity.HIGH,
        allowed_scopes=frozenset(
            {
                SecurityScope.MEDIA_UPLOAD,
                SecurityScope.MEDIA_COMPLETE,
                SecurityScope.MEDIA_DOWNLOAD,
                SecurityScope.FAMILY_PHOTO_STORAGE,
            }
        ),
    ),
    SecuritySignalCode.API_RATE_LIMIT_TRIGGERED: SecurityRulePolicy(
        window_seconds=300,
        threshold=1,
        cooldown_seconds=300,
        severity=SecuritySeverity.MEDIUM,
        allowed_scopes=frozenset({SecurityScope.API_AUTHENTICATED}),
    ),
    SecuritySignalCode.PROVIDER_CONCURRENCY_SATURATED: SecurityRulePolicy(
        window_seconds=300,
        threshold=3,
        cooldown_seconds=300,
        severity=SecuritySeverity.MEDIUM,
        allowed_scopes=frozenset(
            {
                SecurityScope.PROVIDER_AI,
                SecurityScope.PROVIDER_ASR,
                SecurityScope.PROVIDER_EMBEDDING,
                SecurityScope.AUTH_PHONE_ONE_TAP,
            }
        ),
    ),
    SecuritySignalCode.ARGON2_CONCURRENCY_SATURATED: SecurityRulePolicy(
        window_seconds=300,
        threshold=3,
        cooldown_seconds=300,
        severity=SecuritySeverity.HIGH,
        allowed_scopes=frozenset({SecurityScope.ARGON2}),
    ),
}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _bucket_start(now: datetime, seconds: int) -> datetime:
    timestamp = int(_as_utc(now).timestamp())
    return datetime.fromtimestamp(timestamp - timestamp % seconds, tz=UTC)


def security_correlation_digest(kind: str, value: str) -> str:
    """Return a server-keyed one-way correlation digest; raw input is never persisted."""

    settings = get_settings()
    message = f"security-v1:{kind}:{value}".encode()
    return hmac.new(settings.jwt_secret.encode(), message, hashlib.sha256).hexdigest()


def _dedupe_key(
    *,
    rule_code: SecuritySignalCode,
    severity: SecuritySeverity,
    correlation_digest: str,
    scope: SecurityScope,
    identity_started_at: datetime,
) -> str:
    controlled = "|".join(
        (
            rule_code.value,
            severity.value,
            correlation_digest,
            scope.value,
            identity_started_at.isoformat(),
        )
    )
    return hashlib.sha256(controlled.encode()).hexdigest()


def _get_or_create_window(
    db: Session,
    *,
    rule_code: SecuritySignalCode,
    correlation_digest: str,
    scope: SecurityScope,
    window_started_at: datetime,
    window_seconds: int,
    now: datetime,
) -> SecuritySignalWindow:
    query = (
        select(SecuritySignalWindow)
        .where(
            SecuritySignalWindow.rule_code == rule_code.value,
            SecuritySignalWindow.correlation_digest == correlation_digest,
            SecuritySignalWindow.scope == scope.value,
            SecuritySignalWindow.window_started_at == window_started_at,
        )
        .with_for_update()
    )
    row = db.scalar(query)
    if row is not None:
        return row

    candidate = SecuritySignalWindow(
        rule_code=rule_code.value,
        correlation_digest=correlation_digest,
        scope=scope.value,
        window_started_at=window_started_at,
        window_seconds=window_seconds,
        signal_count=0,
        first_seen_at=now,
        last_seen_at=now,
    )
    try:
        with db.begin_nested():
            db.add(candidate)
            db.flush()
        return candidate
    except IntegrityError:
        row = db.scalar(query)
        if row is None:
            raise
        return row


def _lock_security_identity(
    db: Session,
    *,
    rule_code: SecuritySignalCode,
    correlation_digest: str,
    scope: SecurityScope,
) -> None:
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return
    material = f"{rule_code.value}|{correlation_digest}|{scope.value}".encode()
    lock_key = int.from_bytes(
        hashlib.sha256(material).digest()[:8],
        byteorder="big",
        signed=True,
    )
    db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})


def _latest_matching_alert_for_update(
    db: Session,
    *,
    rule_code: SecuritySignalCode,
    correlation_digest: str,
    scope: SecurityScope,
) -> SecurityAlert | None:
    return db.scalar(
        select(SecurityAlert)
        .where(
            SecurityAlert.rule_code == rule_code.value,
            SecurityAlert.correlation_digest == correlation_digest,
            SecurityAlert.scope == scope.value,
        )
        .order_by(SecurityAlert.created_at.desc(), SecurityAlert.id.desc())
        .limit(1)
        .with_for_update()
    )


def _get_or_create_alert(
    db: Session,
    *,
    dedupe_key: str,
    rule_code: SecuritySignalCode,
    policy: SecurityRulePolicy,
    correlation_digest: str,
    scope: SecurityScope,
    window_started_at: datetime,
    signal_count: int,
    now: datetime,
) -> tuple[SecurityAlert, bool]:
    query = select(SecurityAlert).where(SecurityAlert.dedupe_key == dedupe_key).with_for_update()
    alert = db.scalar(query)
    if alert is not None:
        alert.signal_count = max(alert.signal_count, signal_count)
        alert.updated_at = now
        return alert, False

    candidate = SecurityAlert(
        dedupe_key=dedupe_key,
        rule_code=rule_code.value,
        severity=policy.severity.value,
        correlation_digest=correlation_digest,
        scope=scope.value,
        window_started_at=window_started_at,
        window_seconds=policy.window_seconds,
        signal_count=signal_count,
        delivery_status=SecurityAlertDeliveryStatus.PENDING.value,
        delivery_attempts=0,
        created_at=now,
        updated_at=now,
    )
    try:
        with db.begin_nested():
            db.add(candidate)
            db.flush()
        return candidate, True
    except IntegrityError:
        alert = db.scalar(query)
        if alert is None:
            raise
        alert.signal_count = max(alert.signal_count, signal_count)
        alert.updated_at = now
        return alert, False


def record_security_signal(
    bind: Engine,
    *,
    signal_code: SecuritySignalCode,
    correlation_kind: str,
    correlation_value: str,
    scope: SecurityScope,
    now: datetime | None = None,
) -> str | None:
    """Best-effort durable signal aggregation. It must never change business semantics."""

    try:
        policy = RULES[signal_code]
        if scope not in policy.allowed_scopes:
            return None
        observed_at = _as_utc(now or datetime.now(UTC))
        correlation_digest = security_correlation_digest(
            correlation_kind,
            correlation_value,
        )
        window_started_at = _bucket_start(observed_at, policy.window_seconds)
        with Session(bind=bind, autoflush=False, expire_on_commit=False) as db:
            _lock_security_identity(
                db,
                rule_code=signal_code,
                correlation_digest=correlation_digest,
                scope=scope,
            )
            window = _get_or_create_window(
                db,
                rule_code=signal_code,
                correlation_digest=correlation_digest,
                scope=scope,
                window_started_at=window_started_at,
                window_seconds=policy.window_seconds,
                now=observed_at,
            )
            window.signal_count += 1
            window.last_seen_at = observed_at
            db.flush()

            if window.signal_count < policy.threshold:
                db.commit()
                return None

            latest_alert = _latest_matching_alert_for_update(
                db,
                rule_code=signal_code,
                correlation_digest=correlation_digest,
                scope=scope,
            )
            if latest_alert is not None:
                elapsed = observed_at - _as_utc(latest_alert.created_at)
                if elapsed < timedelta(seconds=policy.cooldown_seconds):
                    latest_alert.signal_count = max(
                        latest_alert.signal_count,
                        window.signal_count,
                    )
                    latest_alert.updated_at = observed_at
                    alert = latest_alert
                    created = False
                else:
                    latest_alert = None

            if latest_alert is None:
                dedupe_key = _dedupe_key(
                    rule_code=signal_code,
                    severity=policy.severity,
                    correlation_digest=correlation_digest,
                    scope=scope,
                    identity_started_at=window_started_at,
                )
                alert, created = _get_or_create_alert(
                    db,
                    dedupe_key=dedupe_key,
                    rule_code=signal_code,
                    policy=policy,
                    correlation_digest=correlation_digest,
                    scope=scope,
                    window_started_at=window_started_at,
                    signal_count=window.signal_count,
                    now=observed_at,
                )
            alert_id = str(alert.id)
            db.commit()

        if created:
            # Alert creation stays observational on the business request path.
            # Human HTTP delivery is worker-only; this event never marks HIGH/CRITICAL
            # as delivered.
            emit_security_alert_event_checked(
                level=(
                    "ERROR"
                    if policy.severity
                    in {SecuritySeverity.HIGH, SecuritySeverity.CRITICAL}
                    else "WARNING"
                ),
                alert_id=alert_id,
                rule_code=signal_code.value,
                severity=policy.severity.value,
                signal_count=alert.signal_count,
                window_seconds=policy.window_seconds,
                correlation_id=alert.correlation_digest,
                delivery_status=SecurityAlertDeliveryStatus.PENDING.value,
            )
        return alert_id
    except Exception:
        # SEC-015 is observational. Alerting failure must not rewrite the canonical API result.
        return None


def _delivery_backoff(attempt: int) -> int:
    return min(
        DELIVERY_BACKOFF_BASE_SECONDS * (2 ** max(0, attempt - 1)),
        DELIVERY_BACKOFF_MAX_SECONDS,
    )


@dataclass(frozen=True)
class SecurityAlertDeliveryAttempt:
    alert_id: UUID
    token: UUID
    revision: int
    attempt_number: int
    rule_code: str
    severity: str
    correlation_digest: str
    scope: str
    signal_count: int
    window_seconds: int
    created_at: datetime
    provider: str
    requires_human: bool


def begin_security_alert_delivery_attempt(
    bind: Engine,
    *,
    alert_id: UUID,
    now: datetime | None = None,
) -> SecurityAlertDeliveryAttempt | None:
    observed_at = _as_utc(now or datetime.now(UTC))
    settings = get_settings()
    with Session(bind=bind, autoflush=False, expire_on_commit=False) as db:
        alert = db.scalar(
            select(SecurityAlert)
            .where(SecurityAlert.id == alert_id)
            .with_for_update()
        )
        if alert is None:
            db.rollback()
            return None
        if alert.delivery_status in {
            SecurityAlertDeliveryStatus.DELIVERED.value,
            SecurityAlertDeliveryStatus.TERMINAL_FAILURE.value,
        }:
            db.rollback()
            return None
        if (
            alert.next_retry_at is not None
            and _as_utc(alert.next_retry_at) > observed_at
        ):
            db.rollback()
            return None
        if alert.delivery_attempts >= MAX_DELIVERY_ATTEMPTS:
            alert.delivery_status = SecurityAlertDeliveryStatus.TERMINAL_FAILURE.value
            alert.delivery_error_code = "SECURITY_ALERT_MAX_ATTEMPTS_EXHAUSTED"
            alert.delivery_attempt_token = None
            alert.next_retry_at = None
            alert.updated_at = observed_at
            db.commit()
            return None

        requires_human = alert.severity in {
            SecuritySeverity.HIGH.value,
            SecuritySeverity.CRITICAL.value,
        }
        provider = (
            settings.security_alert_human_provider
            if requires_human
            else "structured_log"
        )
        token = uuid4()
        alert.delivery_attempts += 1
        alert.delivery_revision += 1
        alert.delivery_attempt_token = token
        alert.delivery_provider = provider
        alert.delivery_error_code = None
        alert.updated_at = observed_at
        attempt = SecurityAlertDeliveryAttempt(
            alert_id=alert.id,
            token=token,
            revision=alert.delivery_revision,
            attempt_number=alert.delivery_attempts,
            rule_code=alert.rule_code,
            severity=alert.severity,
            correlation_digest=alert.correlation_digest,
            scope=alert.scope,
            signal_count=alert.signal_count,
            window_seconds=alert.window_seconds,
            created_at=alert.created_at,
            provider=provider,
            requires_human=requires_human,
        )
        db.commit()
        return attempt


def finalize_security_alert_delivery_attempt(
    bind: Engine,
    *,
    attempt: SecurityAlertDeliveryAttempt,
    result: HumanDeliveryResult,
    now: datetime | None = None,
) -> bool:
    observed_at = _as_utc(now or datetime.now(UTC))
    with Session(bind=bind, autoflush=False, expire_on_commit=False) as db:
        alert = db.scalar(
            select(SecurityAlert)
            .where(SecurityAlert.id == attempt.alert_id)
            .with_for_update()
        )
        if (
            alert is None
            or alert.delivery_revision != attempt.revision
            or alert.delivery_attempt_token != attempt.token
            or alert.delivery_status
            in {
                SecurityAlertDeliveryStatus.DELIVERED.value,
                SecurityAlertDeliveryStatus.TERMINAL_FAILURE.value,
            }
        ):
            db.rollback()
            return False

        alert.delivery_attempt_token = None
        alert.delivery_error_code = result.error_code
        if result.delivered:
            alert.delivery_status = SecurityAlertDeliveryStatus.DELIVERED.value
            alert.delivered_at = observed_at
            alert.next_retry_at = None
        elif not result.retryable or alert.delivery_attempts >= MAX_DELIVERY_ATTEMPTS:
            alert.delivery_status = SecurityAlertDeliveryStatus.TERMINAL_FAILURE.value
            alert.next_retry_at = None
        else:
            delay = _delivery_backoff(alert.delivery_attempts)
            if result.retry_after_seconds is not None:
                delay = min(
                    DELIVERY_BACKOFF_MAX_SECONDS,
                    max(delay, result.retry_after_seconds),
                )
            alert.delivery_status = SecurityAlertDeliveryStatus.RETRYABLE_FAILURE.value
            alert.next_retry_at = observed_at + timedelta(seconds=delay)
        alert.updated_at = observed_at
        db.commit()
        return True


def _human_message(attempt: SecurityAlertDeliveryAttempt) -> SecurityAlertHumanMessage:
    return SecurityAlertHumanMessage(
        alert_id=str(attempt.alert_id),
        severity=attempt.severity,
        rule_code=attempt.rule_code,
        scope=attempt.scope,
        signal_count=attempt.signal_count,
        window_seconds=attempt.window_seconds,
        created_at=attempt.created_at,
        correlation_digest=attempt.correlation_digest,
    )


def _emit_human_delivery_event(
    event: str,
    *,
    attempt: SecurityAlertDeliveryAttempt,
    result: HumanDeliveryResult | None = None,
) -> None:
    emit_operational_event(
        event=event,
        level=(
            "ERROR"
            if attempt.severity
            in {SecuritySeverity.HIGH.value, SecuritySeverity.CRITICAL.value}
            else "WARNING"
        ),
        provider=attempt.provider,
        alert_id=str(attempt.alert_id),
        rule_code=attempt.rule_code,
        severity=attempt.severity,
        signal_count=attempt.signal_count,
        window_seconds=attempt.window_seconds,
        correlation_id=attempt.correlation_digest,
        delivery_status=(
            SecurityAlertDeliveryStatus.DELIVERED.value
            if result is not None and result.delivered
            else None
        ),
        retryable=None if result is None else result.retryable,
        error_code=None if result is None else result.error_code,
        attempt_number=attempt.attempt_number,
        retry_after_seconds=(
            None if result is None else result.retry_after_seconds
        ),
    )


def deliver_security_alert(
    bind: Engine,
    *,
    alert_id: str,
    now: datetime | None = None,
    authority_check: Callable[[], None] | None = None,
    human_adapter: SecurityAlertHumanDeliveryAdapter | None = None,
    worker_execution: bool = False,
) -> bool:
    observed_at = _as_utc(now or datetime.now(UTC))
    if not worker_execution and human_adapter is None:
        with Session(bind=bind, autoflush=False, expire_on_commit=False) as db:
            severity = db.scalar(
                select(SecurityAlert.severity).where(
                    SecurityAlert.id == UUID(alert_id)
                )
            )
            db.rollback()
        if severity in {
            SecuritySeverity.HIGH.value,
            SecuritySeverity.CRITICAL.value,
        }:
            return False

    attempt = begin_security_alert_delivery_attempt(
        bind,
        alert_id=UUID(alert_id),
        now=observed_at,
    )
    if attempt is None:
        return False

    if authority_check is not None:
        authority_check()

    log_ok = emit_security_alert_event_checked(
        level=(
            "ERROR"
            if attempt.severity
            in {SecuritySeverity.HIGH.value, SecuritySeverity.CRITICAL.value}
            else "WARNING"
        ),
        alert_id=str(attempt.alert_id),
        rule_code=attempt.rule_code,
        severity=attempt.severity,
        signal_count=attempt.signal_count,
        window_seconds=attempt.window_seconds,
        correlation_id=attempt.correlation_digest,
        delivery_status=SecurityAlertDeliveryStatus.PENDING.value,
    )

    if attempt.requires_human:
        _emit_human_delivery_event(
            "security.alert.human_delivery.attempted",
            attempt=attempt,
        )
        if authority_check is not None:
            authority_check()
        adapter = human_adapter or get_security_alert_human_adapter()
        result = adapter.deliver(_human_message(attempt))
        if authority_check is not None:
            authority_check()
    else:
        result = HumanDeliveryResult(
            delivered=bool(log_ok),
            retryable=not bool(log_ok),
            error_code=None if log_ok else "SECURITY_ALERT_LOG_DELIVERY_FAILED",
        )

    finalized = finalize_security_alert_delivery_attempt(
        bind,
        attempt=attempt,
        result=result,
        now=observed_at,
    )
    if not finalized:
        return False

    if attempt.requires_human:
        if result.delivered:
            event = "security.alert.human_delivery.delivered"
        elif result.retryable:
            event = "security.alert.human_delivery.retryable_failure"
        else:
            event = "security.alert.human_delivery.terminal_failure"
        _emit_human_delivery_event(event, attempt=attempt, result=result)
    return result.delivered

def retry_due_security_alerts(
    bind: Engine,
    *,
    now: datetime | None = None,
    limit: int = 25,
) -> int:
    observed_at = _as_utc(now or datetime.now(UTC))
    bounded_limit = max(1, min(limit, 100))
    try:
        with Session(bind=bind, autoflush=False, expire_on_commit=False) as db:
            alert_ids = list(
                db.scalars(
                    select(SecurityAlert.id)
                    .where(
                        SecurityAlert.delivery_status.in_(
                            (
                                SecurityAlertDeliveryStatus.PENDING.value,
                                SecurityAlertDeliveryStatus.RETRYABLE_FAILURE.value,
                            )
                        ),
                        or_(
                            SecurityAlert.next_retry_at.is_(None),
                            SecurityAlert.next_retry_at <= observed_at,
                        ),
                    )
                    .order_by(SecurityAlert.created_at.asc(), SecurityAlert.id.asc())
                    .limit(bounded_limit)
                )
            )
            db.rollback()
        delivered = 0
        for alert_id in alert_ids:
            if deliver_security_alert(bind, alert_id=str(alert_id), now=observed_at):
                delivered += 1
        return delivered
    except Exception:
        return 0
