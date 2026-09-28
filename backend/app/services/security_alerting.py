from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.observability import emit_operational_event
from app.security_models import (
    SecurityAlert,
    SecurityAlertDeliveryStatus,
    SecuritySeverity,
    SecuritySignalCode,
    SecuritySignalWindow,
)

MAX_DELIVERY_ATTEMPTS = 5
DELIVERY_BACKOFF_BASE_SECONDS = 30
DELIVERY_BACKOFF_MAX_SECONDS = 900


class SecurityScope(StrEnum):
    AUTH_REGISTER_IP = "AUTH_REGISTER_IP"
    AUTH_LOGIN_IP = "AUTH_LOGIN_IP"
    AUTH_LOGIN_ACCOUNT_IP = "AUTH_LOGIN_ACCOUNT_IP"
    FAMILY_CURRENT_LOCATION = "FAMILY_CURRENT_LOCATION"
    FAMILY_TODAY_FOOTPRINT = "FAMILY_TODAY_FOOTPRINT"
    FAMILY_MEMORY = "FAMILY_MEMORY"
    FAMILY_PHOTO_LIST = "FAMILY_PHOTO_LIST"
    FAMILY_PHOTO_DOWNLOAD = "FAMILY_PHOTO_DOWNLOAD"
    DATA_DELETE = "DATA_DELETE"
    ACCOUNT_DELETE = "ACCOUNT_DELETE"
    MEDIA_UPLOAD = "MEDIA_UPLOAD"
    MEDIA_COMPLETE = "MEDIA_COMPLETE"
    MEDIA_DOWNLOAD = "MEDIA_DOWNLOAD"
    FAMILY_PHOTO_STORAGE = "FAMILY_PHOTO_STORAGE"


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
            }
        ),
    ),
    SecuritySignalCode.AUTH_LOGIN_FAILURE_BURST: SecurityRulePolicy(
        window_seconds=900,
        threshold=5,
        cooldown_seconds=900,
        severity=SecuritySeverity.HIGH,
        allowed_scopes=frozenset({SecurityScope.AUTH_LOGIN_ACCOUNT_IP}),
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
        allowed_scopes=frozenset(
            {
                SecurityScope.FAMILY_CURRENT_LOCATION,
                SecurityScope.FAMILY_TODAY_FOOTPRINT,
                SecurityScope.FAMILY_MEMORY,
                SecurityScope.FAMILY_PHOTO_LIST,
                SecurityScope.FAMILY_PHOTO_DOWNLOAD,
            }
        ),
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
    cooldown_started_at: datetime,
) -> str:
    controlled = "|".join(
        (
            rule_code.value,
            severity.value,
            correlation_digest,
            scope.value,
            cooldown_started_at.isoformat(),
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
        cooldown_started_at = _bucket_start(observed_at, policy.cooldown_seconds)

        with Session(bind=bind, autoflush=False, expire_on_commit=False) as db:
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

            dedupe_key = _dedupe_key(
                rule_code=signal_code,
                severity=policy.severity,
                correlation_digest=correlation_digest,
                scope=scope,
                cooldown_started_at=cooldown_started_at,
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
            deliver_security_alert(bind, alert_id=alert_id, now=observed_at)
        return alert_id
    except Exception:
        # SEC-015 is observational. Alerting failure must not rewrite the canonical API result.
        return None


def _delivery_backoff(attempt: int) -> int:
    return min(
        DELIVERY_BACKOFF_BASE_SECONDS * (2 ** max(0, attempt - 1)),
        DELIVERY_BACKOFF_MAX_SECONDS,
    )


def deliver_security_alert(
    bind: Engine,
    *,
    alert_id: str,
    now: datetime | None = None,
) -> bool:
    observed_at = _as_utc(now or datetime.now(UTC))
    try:
        with Session(bind=bind, autoflush=False, expire_on_commit=False) as db:
            alert = db.scalar(
                select(SecurityAlert)
                .where(SecurityAlert.id == UUID(alert_id))
                .with_for_update()
            )
            if alert is None:
                return False
            if alert.delivery_status in {
                SecurityAlertDeliveryStatus.DELIVERED.value,
                SecurityAlertDeliveryStatus.TERMINAL_FAILURE.value,
            }:
                return alert.delivery_status == SecurityAlertDeliveryStatus.DELIVERED.value

            alert.delivery_attempts += 1
            delivered = emit_operational_event(
                event="security.alert.triggered",
                level="ERROR"
                if alert.severity in {SecuritySeverity.HIGH.value, SecuritySeverity.CRITICAL.value}
                else "WARNING",
                alert_id=str(alert.id),
                rule_code=alert.rule_code,
                severity=alert.severity,
                signal_count=alert.signal_count,
                window_seconds=alert.window_seconds,
                correlation_id=alert.correlation_digest,
                delivery_status=SecurityAlertDeliveryStatus.DELIVERED.value,
            )
            if delivered:
                alert.delivery_status = SecurityAlertDeliveryStatus.DELIVERED.value
                alert.delivered_at = observed_at
                alert.next_retry_at = None
            elif alert.delivery_attempts >= MAX_DELIVERY_ATTEMPTS:
                alert.delivery_status = SecurityAlertDeliveryStatus.TERMINAL_FAILURE.value
                alert.next_retry_at = None
            else:
                alert.delivery_status = SecurityAlertDeliveryStatus.RETRYABLE_FAILURE.value
                alert.next_retry_at = observed_at + timedelta(
                    seconds=_delivery_backoff(alert.delivery_attempts)
                )
            alert.updated_at = observed_at
            db.commit()
            return bool(delivered)
    except Exception:
        return False


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
