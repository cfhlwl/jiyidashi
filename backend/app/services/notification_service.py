from __future__ import annotations

import hashlib
import hmac
import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.account_deletion_models import AccountDeletionOperation
from app.admin_models import AdminAccount
from app.auth_models import AuthSession
from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.data_deletion_models import DataDeletionOperation, DataDeletionStatus
from app.maintenance_job_models import MaintenanceJobType
from app.models import Device, User
from app.notification_models import (
    NotificationAudienceType,
    NotificationCampaign,
    NotificationCampaignStatus,
    NotificationCampaignTarget,
    NotificationDelivery,
    NotificationDeliveryStatus,
    NotificationMessage,
    NotificationTargetPlatform,
    PushPlatform,
)
from app.notification_schemas import (
    AdminNotificationCampaignCreate,
    AdminNotificationCampaignRead,
    AdminNotificationCampaignSubmit,
    DevicePushRegistrationRequest,
    DevicePushStateRead,
    NotificationDeliveryCounts,
    NotificationEligibleCounts,
)
from app.services.admin_security import (
    AdminOperationError,
    append_admin_audit,
)
from app.services.auth_session_service import lock_installation_authority_in_transaction
from app.services.maintenance_jobs import (
    MaintenanceJobClaim,
    assert_maintenance_claim_current,
    enqueue_maintenance_job,
)
from app.services.notification_provider import (
    NotificationProviderRequest,
    NotificationProviderResult,
    provider_registration_allowed,
    resolve_notification_provider,
)

FANOUT_BATCH_SIZE = 100
NOTIFICATION_DELIVERY_MAX_ATTEMPTS = 10
NOTIFICATION_FANOUT_MAX_ATTEMPTS = 10
NOTIFICATION_RETRY_MAX_SECONDS = 900
PUSH_DIGEST_LOCK_SEED = 214003
PUSH_DISCLOSURE_LOCK_SEED = 214004

_TERMINAL_DELIVERY_STATUSES = {
    NotificationDeliveryStatus.ACCEPTED.value,
    NotificationDeliveryStatus.TERMINAL_FAILURE.value,
    NotificationDeliveryStatus.CANCELLED.value,
    NotificationDeliveryStatus.EXPIRED.value,
}
_ACTIVE_DELIVERY_STATUSES = {
    NotificationDeliveryStatus.PENDING.value,
    NotificationDeliveryStatus.RUNNING.value,
    NotificationDeliveryStatus.RETRY_WAIT.value,
}


class NotificationDeviceError(RuntimeError):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class NotificationExecutionError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        retryable: bool,
        retry_after_seconds: int | None = None,
    ):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, repr=False)
class NotificationDeliveryAttempt:
    delivery_id: UUID
    device_id: UUID
    revision: int
    attempt_token: UUID
    attempt_count: int
    platform: str
    provider: str
    token_digest: str
    raw_token: str
    title: str
    body: str
    payload: dict


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _safe_error_code(value: str | None) -> str:
    normalized = (value or "NOTIFICATION_DELIVERY_FAILED").strip().upper()
    safe = "".join(
        char if char.isalnum() or char == "_" else "_"
        for char in normalized
    )
    return (safe or "NOTIFICATION_DELIVERY_FAILED")[:80]


def push_token_digest(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _push_state(row: Device) -> DevicePushStateRead:
    return DevicePushStateRead(
        id=row.id,
        client_uuid=row.client_uuid,
        platform=row.platform,
        provider=row.push_provider,
        push_enabled=row.push_enabled,
        push_token_updated_at=row.push_token_updated_at,
        push_invalidated_at=row.push_invalidated_at,
        app_version=row.app_version,
        os_version=row.os_version,
        last_active_at=row.last_active_at,
    )


def _lock_push_digest(db: Session, digest: str) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    db.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            "hashtextextended(:digest, :seed)"
            ")"
        ),
        {"digest": digest, "seed": PUSH_DIGEST_LOCK_SEED},
    )


@contextmanager
def hold_push_disclosure_handoff(*, provider: str, digest: str):
    """Serialize token ownership transition with provider disclosure.

    PostgreSQL session-level advisory authority intentionally spans provider I/O
    without keeping an ordinary ORM transaction or Device row lock open.
    """

    if engine.dialect.name != "postgresql":
        yield
        return

    scope = f"{provider}:{digest}"
    connection = engine.connect()
    acquired = False
    try:
        connection.execute(
            text(
                "SELECT pg_advisory_lock("
                "hashtextextended(:scope, :seed)"
                ")"
            ),
            {"scope": scope, "seed": PUSH_DISCLOSURE_LOCK_SEED},
        )
        connection.commit()
        acquired = True
        yield
    finally:
        if acquired:
            try:
                connection.execute(
                    text(
                        "SELECT pg_advisory_unlock("
                        "hashtextextended(:scope, :seed)"
                        ")"
                    ),
                    {"scope": scope, "seed": PUSH_DISCLOSURE_LOCK_SEED},
                )
                connection.commit()
            except BaseException:
                # A session-level advisory lock survives transaction rollback.
                # Never return a connection with an uncertain lock state to the pool.
                connection.invalidate()
                raise
            finally:
                connection.close()
        else:
            connection.close()


def register_device_push(
    db: Session,
    *,
    user_id: UUID,
    payload: DevicePushRegistrationRequest,
    session_id: UUID | None = None,
) -> DevicePushStateRead:
    now = datetime.now(UTC)
    if not provider_registration_allowed(
        platform=payload.platform.value,
        provider=payload.provider.value,
    ):
        raise NotificationDeviceError("PUSH_PROVIDER_UNAVAILABLE", 503)
    digest = push_token_digest(payload.push_token)

    with hold_push_disclosure_handoff(
        provider=payload.provider.value,
        digest=digest,
    ):
        lock_installation_authority_in_transaction(db, payload.client_uuid)
        _lock_push_digest(db, digest)

        if session_id is not None:
            session_statement = select(AuthSession).where(
                AuthSession.id == session_id,
                AuthSession.user_id == user_id,
            )
            if db.get_bind().dialect.name == "postgresql":
                session_statement = session_statement.with_for_update(
                    read=True,
                    key_share=True,
                )
            session = db.scalar(session_statement)
            if (
                session is None
                or session.revoked_at is not None
                or _as_utc(session.expires_at) <= now
                or session.device_id != payload.client_uuid
            ):
                db.rollback()
                raise NotificationDeviceError("PUSH_SESSION_INVALID", 401)

        if db.get(User, user_id) is None:
            raise NotificationDeviceError("USER_NOT_FOUND", 404)

        current_statement = select(Device).where(
            Device.user_id == user_id,
            Device.client_uuid == payload.client_uuid,
        )
        if db.get_bind().dialect.name == "postgresql":
            current_statement = current_statement.with_for_update()
        current = db.scalar(current_statement)

        conflicting_statement = select(Device).where(
            Device.push_enabled.is_(True),
            Device.push_provider == payload.provider.value,
            Device.push_token_digest == digest,
        )
        if current is not None:
            conflicting_statement = conflicting_statement.where(Device.id != current.id)
        if db.get_bind().dialect.name == "postgresql":
            conflicting_statement = conflicting_statement.with_for_update()
        conflicts = list(db.scalars(conflicting_statement))
        for conflict in conflicts:
            conflict.push_enabled = False
            conflict.push_token = None
            conflict.push_token_digest = None
            conflict.push_invalidated_at = now

        if current is None:
            current = Device(
                user_id=user_id,
                client_uuid=payload.client_uuid,
                platform=payload.platform.value,
                push_token=payload.push_token,
                push_provider=payload.provider.value,
                push_token_digest=digest,
                push_enabled=True,
                push_token_updated_at=now,
                push_invalidated_at=None,
                app_version=payload.app_version,
                os_version=payload.os_version,
                last_active_at=now,
            )
            db.add(current)
        else:
            same_binding = (
                current.push_enabled
                and current.platform == payload.platform.value
                and current.push_provider == payload.provider.value
                and current.push_token_digest == digest
                and current.push_token == payload.push_token
            )
            current.platform = payload.platform.value
            current.app_version = payload.app_version
            current.os_version = payload.os_version
            current.last_active_at = now
            if not same_binding:
                current.push_token = payload.push_token
                current.push_provider = payload.provider.value
                current.push_token_digest = digest
                current.push_enabled = True
                current.push_token_updated_at = now
                current.push_invalidated_at = None

        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise NotificationDeviceError("PUSH_TOKEN_BINDING_CONFLICT", 409) from exc
        db.refresh(current)
        return _push_state(current)


def unregister_device_push(
    db: Session,
    *,
    user_id: UUID,
    client_uuid: str,
) -> DevicePushStateRead:
    while True:
        row = db.scalar(
            select(Device).where(
                Device.user_id == user_id,
                Device.client_uuid == client_uuid,
            )
        )
        if row is None:
            db.rollback()
            raise NotificationDeviceError("PUSH_DEVICE_NOT_FOUND", 404)

        provider = row.push_provider
        digest = row.push_token_digest
        if not row.push_enabled or provider is None or digest is None:
            statement = select(Device).where(
                Device.user_id == user_id,
                Device.client_uuid == client_uuid,
            )
            if db.get_bind().dialect.name == "postgresql":
                statement = statement.with_for_update()
            row = db.scalar(statement)
            assert row is not None
            if row.push_enabled or row.push_token is not None or row.push_token_digest is not None:
                row.push_enabled = False
                row.push_token = None
                row.push_token_digest = None
                row.push_invalidated_at = datetime.now(UTC)
            db.commit()
            db.refresh(row)
            return _push_state(row)

        # Do not hold the ORM transaction while waiting for an in-flight provider
        # disclosure to release the token handoff.
        db.rollback()
        with hold_push_disclosure_handoff(provider=provider, digest=digest):
            statement = select(Device).where(
                Device.user_id == user_id,
                Device.client_uuid == client_uuid,
            )
            if db.get_bind().dialect.name == "postgresql":
                statement = statement.with_for_update()
            row = db.scalar(statement)
            if row is None:
                db.rollback()
                raise NotificationDeviceError("PUSH_DEVICE_NOT_FOUND", 404)

            if row.push_provider != provider or row.push_token_digest != digest:
                db.rollback()
                continue

            if row.push_enabled or row.push_token is not None or row.push_token_digest is not None:
                row.push_enabled = False
                row.push_token = None
                row.push_token_digest = None
                row.push_invalidated_at = datetime.now(UTC)
            db.commit()
            db.refresh(row)
            return _push_state(row)


def fence_other_owner_push_bindings_for_client_uuid(
    db: Session,
    *,
    user_id: UUID,
    client_uuid: str,
) -> None:
    """Revoke stale push authority before this installation changes owners."""

    while True:
        candidate = db.scalar(
            select(Device)
            .where(
                Device.client_uuid == client_uuid,
                Device.user_id != user_id,
                or_(
                    Device.push_enabled.is_(True),
                    Device.push_token.is_not(None),
                    Device.push_token_digest.is_not(None),
                ),
            )
            .order_by(Device.id)
        )
        if candidate is None:
            db.rollback()
            return

        candidate_id = candidate.id
        provider = candidate.push_provider
        digest = candidate.push_token_digest
        db.rollback()

        if provider is not None and digest is not None:
            with hold_push_disclosure_handoff(provider=provider, digest=digest):
                statement = select(Device).where(
                    Device.id == candidate_id,
                    Device.client_uuid == client_uuid,
                    Device.user_id != user_id,
                )
                if db.get_bind().dialect.name == "postgresql":
                    statement = statement.with_for_update()
                current = db.scalar(statement)
                if current is None:
                    db.rollback()
                    continue
                if (
                    current.push_provider != provider
                    or current.push_token_digest != digest
                ):
                    db.rollback()
                    continue

                current.push_enabled = False
                current.push_token = None
                current.push_token_digest = None
                current.push_invalidated_at = datetime.now(UTC)
                db.commit()
                continue

        statement = select(Device).where(
            Device.id == candidate_id,
            Device.client_uuid == client_uuid,
            Device.user_id != user_id,
        )
        if db.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update()
        current = db.scalar(statement)
        if current is None:
            db.rollback()
            continue
        current.push_enabled = False
        current.push_token = None
        current.push_token_digest = None
        current.push_invalidated_at = datetime.now(UTC)
        db.commit()


def _eligible_conditions(
    *,
    campaign: NotificationCampaign,
    cutoff: datetime,
) -> list:
    conditions = [
        Device.push_enabled.is_(True),
        Device.push_token.is_not(None),
        Device.push_provider.is_not(None),
        Device.push_token_digest.is_not(None),
        Device.push_invalidated_at.is_(None),
        Device.platform.in_((PushPlatform.IOS.value, PushPlatform.ANDROID.value)),
        Device.created_at <= cutoff,
        Device.push_token_updated_at.is_not(None),
        Device.push_token_updated_at <= cutoff,
        Device.user_id.not_in(select(AccountDeletionOperation.user_id)),
        Device.user_id.not_in(
            select(DataDeletionOperation.user_id).where(
                DataDeletionOperation.status != DataDeletionStatus.COMPLETED
            )
        ),
    ]
    if campaign.target_platform != NotificationTargetPlatform.ALL.value:
        conditions.append(Device.platform == campaign.target_platform)
    if campaign.audience_type == NotificationAudienceType.USER_IDS.value:
        target_users = select(NotificationCampaignTarget.user_id).where(
            NotificationCampaignTarget.campaign_id == campaign.id,
            NotificationCampaignTarget.user_id.is_not(None),
        )
        conditions.append(Device.user_id.in_(target_users))
    elif campaign.audience_type == NotificationAudienceType.DEVICE_IDS.value:
        target_devices = select(NotificationCampaignTarget.device_id).where(
            NotificationCampaignTarget.campaign_id == campaign.id,
            NotificationCampaignTarget.device_id.is_not(None),
        )
        conditions.append(Device.id.in_(target_devices))
    return conditions


def eligible_device_counts(
    db: Session,
    *,
    campaign: NotificationCampaign,
    cutoff: datetime | None = None,
) -> NotificationEligibleCounts:
    observed = _as_utc(cutoff or campaign.audience_cutoff_at or datetime.now(UTC))
    conditions = _eligible_conditions(campaign=campaign, cutoff=observed)
    rows = db.execute(
        select(Device.platform, func.count(Device.id))
        .where(*conditions)
        .group_by(Device.platform)
    ).all()
    counts = {str(platform): int(count) for platform, count in rows}
    ios = counts.get(PushPlatform.IOS.value, 0)
    android = counts.get(PushPlatform.ANDROID.value, 0)
    return NotificationEligibleCounts(
        total=ios + android,
        ios=ios,
        android=android,
    )


def _validate_target_rows(
    db: Session,
    *,
    payload: AdminNotificationCampaignCreate,
) -> None:
    target = payload.target
    if target.audience == NotificationAudienceType.USER_IDS:
        existing = set(
            db.scalars(select(User.id).where(User.id.in_(target.user_ids)))
        )
        if existing != set(target.user_ids):
            raise AdminOperationError("NOTIFICATION_TARGET_USER_NOT_FOUND", 422)
    elif target.audience == NotificationAudienceType.DEVICE_IDS:
        existing = set(
            db.scalars(select(Device.id).where(Device.id.in_(target.device_ids)))
        )
        if existing != set(target.device_ids):
            raise AdminOperationError("NOTIFICATION_TARGET_DEVICE_NOT_FOUND", 422)


def _safe_payload(
    *,
    destination: str,
    resource_id: UUID | None,
) -> dict[str, str | int | None]:
    return {
        "version": 1,
        "destination": destination,
        "resource_id": None if resource_id is None else str(resource_id),
    }


def create_notification_campaign(
    db: Session,
    *,
    actor: AdminAccount,
    payload: AdminNotificationCampaignCreate,
) -> NotificationCampaign:
    now = datetime.now(UTC)
    if payload.message.expires_at is not None:
        expires_at = _as_utc(payload.message.expires_at)
        if expires_at <= now:
            raise AdminOperationError("NOTIFICATION_EXPIRY_IN_PAST", 422)
    else:
        expires_at = None

    _validate_target_rows(db, payload=payload)
    message = NotificationMessage(
        category=payload.message.category.value,
        title=payload.message.title,
        body=payload.message.body,
        route_intent=payload.message.route_intent.value,
        route_resource_id=payload.message.route_resource_id,
        payload_version=1,
        safe_payload_json=_safe_payload(
            destination=payload.message.route_intent.value,
            resource_id=payload.message.route_resource_id,
        ),
        source_type=payload.message.source_type.value,
        source_id=payload.message.source_id,
        created_at=now,
        expires_at=expires_at,
    )
    db.add(message)
    db.flush()

    campaign = NotificationCampaign(
        message_id=message.id,
        target_platform=payload.target.platform.value,
        audience_type=payload.target.audience.value,
        status=NotificationCampaignStatus.DRAFT.value,
        revision=0,
        created_by_admin_id=actor.id,
        created_at=now,
        updated_at=now,
    )
    db.add(campaign)
    db.flush()

    if payload.target.audience == NotificationAudienceType.USER_IDS:
        db.add_all(
            NotificationCampaignTarget(
                campaign_id=campaign.id,
                user_id=user_id,
                created_at=now,
            )
            for user_id in payload.target.user_ids
        )
    elif payload.target.audience == NotificationAudienceType.DEVICE_IDS:
        db.add_all(
            NotificationCampaignTarget(
                campaign_id=campaign.id,
                device_id=device_id,
                created_at=now,
            )
            for device_id in payload.target.device_ids
        )

    append_admin_audit(
        db,
        actor=actor,
        action="NOTIFICATION_CAMPAIGN_CREATE",
        target_type="NOTIFICATION_CAMPAIGN",
        target_id=campaign.id,
        result="SUCCESS",
        metadata={
            "category": message.category,
            "platform": campaign.target_platform,
            "audience": campaign.audience_type,
            "explicit_targets": (
                len(payload.target.user_ids) + len(payload.target.device_ids)
            ),
        },
    )
    db.commit()
    db.refresh(campaign)
    return campaign


def _target_fingerprint(db: Session, *, campaign_id: UUID) -> str:
    rows = db.execute(
        select(
            NotificationCampaignTarget.user_id,
            NotificationCampaignTarget.device_id,
        )
        .where(NotificationCampaignTarget.campaign_id == campaign_id)
        .order_by(NotificationCampaignTarget.id)
    ).all()
    values = sorted(
        (
            f"U:{user_id}"
            if user_id is not None
            else f"D:{device_id}"
        )
        for user_id, device_id in rows
    )
    return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()


def campaign_confirmation_token(
    db: Session,
    *,
    campaign: NotificationCampaign,
) -> str:
    settings = get_settings()
    fingerprint = _target_fingerprint(db, campaign_id=campaign.id)
    value = (
        f"notify-v1:{campaign.id}:{campaign.revision}:{campaign.message_id}:"
        f"{campaign.target_platform}:{campaign.audience_type}:{fingerprint}"
    )
    return hmac.new(
        settings.jwt_secret.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _locked_campaign(db: Session, campaign_id: UUID) -> NotificationCampaign:
    statement = select(NotificationCampaign).where(
        NotificationCampaign.id == campaign_id
    )
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    campaign = db.scalar(statement)
    if campaign is None:
        raise AdminOperationError("NOTIFICATION_CAMPAIGN_NOT_FOUND", 404)
    return campaign


def submit_notification_campaign(
    db: Session,
    *,
    actor: AdminAccount,
    campaign_id: UUID,
    payload: AdminNotificationCampaignSubmit,
) -> NotificationCampaign:
    campaign = _locked_campaign(db, campaign_id)
    if campaign.status != NotificationCampaignStatus.DRAFT.value:
        raise AdminOperationError("NOTIFICATION_CAMPAIGN_NOT_DRAFT", 409)
    if campaign.revision != payload.expected_revision:
        raise AdminOperationError("ADMIN_STATE_STALE", 409)
    expected = campaign_confirmation_token(db, campaign=campaign)
    if not secrets.compare_digest(expected, payload.confirmation_token):
        raise AdminOperationError("NOTIFICATION_CONFIRMATION_INVALID", 409)

    now = datetime.now(UTC)
    if payload.send_at is None:
        send_at = now
        action = "NOTIFICATION_CAMPAIGN_SEND"
    else:
        send_at = _as_utc(payload.send_at)
        if send_at < now:
            raise AdminOperationError("NOTIFICATION_SEND_AT_IN_PAST", 422)
        action = "NOTIFICATION_CAMPAIGN_SCHEDULE"

    message = db.get(NotificationMessage, campaign.message_id)
    if message is None:
        raise AdminOperationError("NOTIFICATION_MESSAGE_NOT_FOUND", 409)
    if message.expires_at is not None and _as_utc(message.expires_at) <= send_at:
        raise AdminOperationError("NOTIFICATION_EXPIRES_BEFORE_SEND", 422)

    campaign.status = NotificationCampaignStatus.SCHEDULED.value
    campaign.send_at = send_at
    campaign.audience_cutoff_at = now
    campaign.fanout_cursor_device_id = None
    campaign.fanout_completed_at = None
    campaign.submitted_at = now
    campaign.updated_at = now
    campaign.revision += 1
    append_admin_audit(
        db,
        actor=actor,
        action=action,
        target_type="NOTIFICATION_CAMPAIGN",
        target_id=campaign.id,
        result="SUCCESS",
        metadata={
            "revision": campaign.revision,
            "platform": campaign.target_platform,
            "audience": campaign.audience_type,
            "send_at": send_at.isoformat(),
        },
    )
    db.commit()
    db.refresh(campaign)
    return campaign


def cancel_notification_campaign(
    db: Session,
    *,
    actor: AdminAccount,
    campaign_id: UUID,
    expected_revision: int,
) -> NotificationCampaign:
    campaign = _locked_campaign(db, campaign_id)
    if campaign.revision != expected_revision:
        raise AdminOperationError("ADMIN_STATE_STALE", 409)
    if campaign.status in {
        NotificationCampaignStatus.CANCELLED.value,
        NotificationCampaignStatus.COMPLETED.value,
        NotificationCampaignStatus.FAILED.value,
    }:
        raise AdminOperationError("NOTIFICATION_CAMPAIGN_FINAL", 409)

    now = datetime.now(UTC)
    campaign.status = NotificationCampaignStatus.CANCELLED.value
    campaign.cancelled_at = now
    campaign.updated_at = now
    campaign.revision += 1
    db.execute(
        update(NotificationDelivery)
        .where(
            NotificationDelivery.campaign_id == campaign.id,
            NotificationDelivery.status.in_(
                (
                    NotificationDeliveryStatus.PENDING.value,
                    NotificationDeliveryStatus.RETRY_WAIT.value,
                )
            ),
        )
        .values(
            status=NotificationDeliveryStatus.CANCELLED.value,
            revision=NotificationDelivery.revision + 1,
            attempt_token=None,
            next_retry_at=None,
            error_code="NOTIFICATION_CAMPAIGN_CANCELLED",
            updated_at=now,
        )
    )
    append_admin_audit(
        db,
        actor=actor,
        action="NOTIFICATION_CAMPAIGN_CANCEL",
        target_type="NOTIFICATION_CAMPAIGN",
        target_id=campaign.id,
        result="SUCCESS",
        metadata={"revision": campaign.revision},
    )
    db.commit()
    db.refresh(campaign)
    return campaign


def notification_delivery_counts(
    db: Session,
    *,
    campaign_id: UUID,
) -> NotificationDeliveryCounts:
    rows = db.execute(
        select(NotificationDelivery.status, func.count(NotificationDelivery.id))
        .where(NotificationDelivery.campaign_id == campaign_id)
        .group_by(NotificationDelivery.status)
    ).all()
    counts = {str(status): int(count) for status, count in rows}
    return NotificationDeliveryCounts(
        pending=counts.get(NotificationDeliveryStatus.PENDING.value, 0),
        running=counts.get(NotificationDeliveryStatus.RUNNING.value, 0),
        accepted=counts.get(NotificationDeliveryStatus.ACCEPTED.value, 0),
        retry_wait=counts.get(NotificationDeliveryStatus.RETRY_WAIT.value, 0),
        terminal_failure=counts.get(
            NotificationDeliveryStatus.TERMINAL_FAILURE.value, 0
        ),
        cancelled=counts.get(NotificationDeliveryStatus.CANCELLED.value, 0),
        expired=counts.get(NotificationDeliveryStatus.EXPIRED.value, 0),
    )


def notification_campaign_projection(
    db: Session,
    *,
    campaign_id: UUID,
) -> AdminNotificationCampaignRead:
    campaign = db.get(NotificationCampaign, campaign_id)
    if campaign is None:
        raise AdminOperationError("NOTIFICATION_CAMPAIGN_NOT_FOUND", 404)
    message = db.get(NotificationMessage, campaign.message_id)
    if message is None:
        raise AdminOperationError("NOTIFICATION_MESSAGE_NOT_FOUND", 409)
    preview = eligible_device_counts(db, campaign=campaign)
    return AdminNotificationCampaignRead(
        id=campaign.id,
        message_id=campaign.message_id,
        category=message.category,
        title=message.title,
        body=message.body,
        route_intent=message.route_intent,
        route_resource_id=message.route_resource_id,
        source_type=message.source_type,
        source_id=message.source_id,
        target_platform=campaign.target_platform,
        audience_type=campaign.audience_type,
        status=campaign.status,
        revision=campaign.revision,
        send_at=campaign.send_at,
        audience_cutoff_at=campaign.audience_cutoff_at,
        fanout_completed_at=campaign.fanout_completed_at,
        submitted_at=campaign.submitted_at,
        cancelled_at=campaign.cancelled_at,
        completed_at=campaign.completed_at,
        error_code=campaign.error_code,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
        eligible_preview=preview,
        delivery_counts=notification_delivery_counts(
            db,
            campaign_id=campaign.id,
        ),
    )


def _fanout_dedupe_key(campaign: NotificationCampaign) -> str:
    cursor = (
        "start"
        if campaign.fanout_cursor_device_id is None
        else str(campaign.fanout_cursor_device_id)
    )
    return f"notification-fanout:{campaign.id}:{campaign.revision}:{cursor}"


def enqueue_due_notification_campaigns(
    db: Session,
    *,
    now: datetime,
    limit: int,
) -> tuple[int, int]:
    due = list(
        db.scalars(
            select(NotificationCampaign)
            .where(
                NotificationCampaign.status
                == NotificationCampaignStatus.SCHEDULED.value,
                NotificationCampaign.send_at.is_not(None),
                NotificationCampaign.send_at <= now,
            )
            .order_by(
                NotificationCampaign.send_at,
                NotificationCampaign.id,
            )
            .limit(limit)
        )
    )
    created_count = 0
    existing_count = 0
    for campaign in due:
        _, created = enqueue_maintenance_job(
            db,
            job_type=MaintenanceJobType.NOTIFICATION_FANOUT,
            dedupe_key=_fanout_dedupe_key(campaign),
            resource_key=f"notification-campaign:{campaign.id}",
            payload={
                "campaign_id": str(campaign.id),
                "campaign_revision": campaign.revision,
            },
            max_attempts=NOTIFICATION_FANOUT_MAX_ATTEMPTS,
            next_attempt_at=now,
        )
        created_count += int(created)
        existing_count += int(not created)
    return created_count, existing_count


def _enqueue_delivery_job(
    db: Session,
    *,
    delivery: NotificationDelivery,
    now: datetime,
) -> None:
    enqueue_maintenance_job(
        db,
        job_type=MaintenanceJobType.NOTIFICATION_DELIVERY,
        dedupe_key=f"notification-delivery:{delivery.id}",
        owner_user_id=delivery.owner_user_id,
        resource_key=f"notification-delivery:{delivery.id}",
        payload={"delivery_id": str(delivery.id)},
        max_attempts=NOTIFICATION_DELIVERY_MAX_ATTEMPTS,
        next_attempt_at=now,
    )


def process_notification_fanout_claim(claim: MaintenanceJobClaim) -> None:
    try:
        campaign_id = UUID(str(claim.payload.get("campaign_id")))
        expected_revision = int(claim.payload.get("campaign_revision"))
    except (TypeError, ValueError, AttributeError) as exc:
        raise NotificationExecutionError(
            "NOTIFICATION_FANOUT_PAYLOAD_INVALID",
            retryable=False,
        ) from exc

    now = datetime.now(UTC)
    with SessionLocal() as db:
        assert_maintenance_claim_current(
            db,
            job_id=claim.id,
            claim_token=claim.claim_token,
        )
        statement = select(NotificationCampaign).where(
            NotificationCampaign.id == campaign_id
        )
        if db.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update()
        campaign = db.scalar(statement)
        if campaign is None:
            db.rollback()
            return
        if campaign.status in {
            NotificationCampaignStatus.CANCELLED.value,
            NotificationCampaignStatus.COMPLETED.value,
        }:
            db.rollback()
            return
        if campaign.revision != expected_revision:
            db.rollback()
            return
        if campaign.audience_cutoff_at is None:
            raise NotificationExecutionError(
                "NOTIFICATION_CAMPAIGN_CUTOFF_MISSING",
                retryable=False,
            )
        if campaign.status == NotificationCampaignStatus.SCHEDULED.value:
            campaign.status = NotificationCampaignStatus.FANOUT.value
            campaign.updated_at = now
        elif campaign.status != NotificationCampaignStatus.FANOUT.value:
            db.rollback()
            return

        cutoff = _as_utc(campaign.audience_cutoff_at)
        conditions = _eligible_conditions(campaign=campaign, cutoff=cutoff)
        if campaign.fanout_cursor_device_id is not None:
            conditions.append(Device.id > campaign.fanout_cursor_device_id)

        candidate_statement = (
            select(Device)
            .where(*conditions)
            .order_by(Device.id)
            .limit(FANOUT_BATCH_SIZE + 1)
        )
        if db.get_bind().dialect.name == "postgresql":
            # Serialize the selected Device authority with account deletion. A delete
            # that wins first removes the row before this SELECT can return it; a
            # fan-out that wins first keeps the Device alive until its Delivery rows
            # and cursor commit, after which the delete cascade removes both.
            candidate_statement = candidate_statement.with_for_update()
        candidates = list(db.scalars(candidate_statement))
        page = candidates[:FANOUT_BATCH_SIZE]
        has_more = len(candidates) > FANOUT_BATCH_SIZE
        page_ids = [row.id for row in page]
        existing_device_ids: set[UUID] = set()
        if page_ids:
            existing_device_ids = set(
                db.scalars(
                    select(NotificationDelivery.device_id).where(
                        NotificationDelivery.campaign_id == campaign.id,
                        NotificationDelivery.device_id.in_(page_ids),
                    )
                )
            )

        created: list[NotificationDelivery] = []
        for device in page:
            if device.id in existing_device_ids:
                continue
            if (
                not device.push_enabled
                or device.push_invalidated_at is not None
                or device.push_token is None
                or device.push_provider is None
                or device.push_token_digest is None
            ):
                continue
            delivery = NotificationDelivery(
                campaign_id=campaign.id,
                message_id=campaign.message_id,
                device_id=device.id,
                owner_user_id=device.user_id,
                platform_snapshot=device.platform,
                provider_snapshot=device.push_provider,
                token_digest_snapshot=device.push_token_digest,
                status=NotificationDeliveryStatus.PENDING.value,
                attempt_count=0,
                revision=0,
                next_retry_at=now,
                created_at=now,
                updated_at=now,
            )
            db.add(delivery)
            created.append(delivery)

        db.flush()
        for delivery in created:
            _enqueue_delivery_job(db, delivery=delivery, now=now)

        if page:
            campaign.fanout_cursor_device_id = page[-1].id
            campaign.updated_at = now

        if not has_more:
            campaign.fanout_completed_at = now
            has_deliveries = bool(
                db.scalar(
                    select(func.count(NotificationDelivery.id)).where(
                        NotificationDelivery.campaign_id == campaign.id
                    )
                )
            )
            if has_deliveries:
                campaign.status = NotificationCampaignStatus.DELIVERING.value
            else:
                campaign.status = NotificationCampaignStatus.COMPLETED.value
                campaign.completed_at = now
        else:
            enqueue_maintenance_job(
                db,
                job_type=MaintenanceJobType.NOTIFICATION_FANOUT,
                dedupe_key=_fanout_dedupe_key(campaign),
                resource_key=f"notification-campaign:{campaign.id}",
                payload={
                    "campaign_id": str(campaign.id),
                    "campaign_revision": campaign.revision,
                },
                max_attempts=NOTIFICATION_FANOUT_MAX_ATTEMPTS,
                next_attempt_at=now,
            )

        db.commit()


def _retry_delay(attempt_count: int) -> int:
    return min(30 * (2 ** max(0, attempt_count - 1)), NOTIFICATION_RETRY_MAX_SECONDS)


def _refresh_campaign_completion(db: Session, *, campaign_id: UUID, now: datetime) -> None:
    campaign = db.get(NotificationCampaign, campaign_id)
    if (
        campaign is None
        or campaign.status == NotificationCampaignStatus.CANCELLED.value
        or campaign.fanout_completed_at is None
    ):
        return
    active = int(
        db.scalar(
            select(func.count(NotificationDelivery.id)).where(
                NotificationDelivery.campaign_id == campaign_id,
                NotificationDelivery.status.in_(_ACTIVE_DELIVERY_STATUSES),
            )
        )
        or 0
    )
    if active == 0:
        campaign.status = NotificationCampaignStatus.COMPLETED.value
        campaign.completed_at = now
        campaign.updated_at = now


def begin_notification_delivery_attempt(
    claim: MaintenanceJobClaim,
) -> NotificationDeliveryAttempt | None:
    try:
        delivery_id = UUID(str(claim.payload.get("delivery_id")))
    except (TypeError, ValueError, AttributeError) as exc:
        raise NotificationExecutionError(
            "NOTIFICATION_DELIVERY_PAYLOAD_INVALID",
            retryable=False,
        ) from exc

    now = datetime.now(UTC)
    with SessionLocal() as db:
        assert_maintenance_claim_current(
            db,
            job_id=claim.id,
            claim_token=claim.claim_token,
        )
        statement = select(NotificationDelivery).where(
            NotificationDelivery.id == delivery_id
        )
        if db.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update()
        delivery = db.scalar(statement)
        if delivery is None:
            db.rollback()
            return None
        if delivery.status in _TERMINAL_DELIVERY_STATUSES:
            db.rollback()
            return None

        campaign = db.get(NotificationCampaign, delivery.campaign_id)
        message = db.get(NotificationMessage, delivery.message_id)
        device = db.get(Device, delivery.device_id)
        if campaign is None or message is None or device is None:
            delivery.status = NotificationDeliveryStatus.CANCELLED.value
            delivery.error_code = "NOTIFICATION_AUTHORITY_MISSING"
            delivery.attempt_token = None
            delivery.next_retry_at = None
            delivery.revision += 1
            delivery.updated_at = now
            _refresh_campaign_completion(
                db,
                campaign_id=delivery.campaign_id,
                now=now,
            )
            db.commit()
            return None

        if campaign.status == NotificationCampaignStatus.CANCELLED.value:
            delivery.status = NotificationDeliveryStatus.CANCELLED.value
            delivery.error_code = "NOTIFICATION_CAMPAIGN_CANCELLED"
            delivery.attempt_token = None
            delivery.next_retry_at = None
            delivery.revision += 1
            delivery.updated_at = now
            db.commit()
            return None

        if message.expires_at is not None and _as_utc(message.expires_at) <= now:
            delivery.status = NotificationDeliveryStatus.EXPIRED.value
            delivery.error_code = "NOTIFICATION_EXPIRED"
            delivery.attempt_token = None
            delivery.next_retry_at = None
            delivery.revision += 1
            delivery.updated_at = now
            _refresh_campaign_completion(
                db,
                campaign_id=delivery.campaign_id,
                now=now,
            )
            db.commit()
            return None

        current_authority = (
            device.user_id == delivery.owner_user_id
            and device.push_enabled
            and device.push_invalidated_at is None
            and device.push_token is not None
            and device.push_provider == delivery.provider_snapshot
            and device.push_token_digest == delivery.token_digest_snapshot
            and device.platform == delivery.platform_snapshot
        )
        if not current_authority:
            delivery.status = NotificationDeliveryStatus.CANCELLED.value
            delivery.error_code = "DEVICE_PUSH_AUTHORITY_CHANGED"
            delivery.attempt_token = None
            delivery.next_retry_at = None
            delivery.revision += 1
            delivery.updated_at = now
            _refresh_campaign_completion(
                db,
                campaign_id=delivery.campaign_id,
                now=now,
            )
            db.commit()
            return None

        if (
            delivery.next_retry_at is not None
            and _as_utc(delivery.next_retry_at) > now
        ):
            retry_after = max(
                1,
                int((_as_utc(delivery.next_retry_at) - now).total_seconds()),
            )
            db.rollback()
            raise NotificationExecutionError(
                "NOTIFICATION_DELIVERY_NOT_DUE",
                retryable=True,
                retry_after_seconds=min(
                    retry_after,
                    NOTIFICATION_RETRY_MAX_SECONDS,
                ),
            )

        token = uuid4()
        delivery.status = NotificationDeliveryStatus.RUNNING.value
        delivery.attempt_count += 1
        delivery.revision += 1
        delivery.attempt_token = token
        delivery.next_retry_at = None
        delivery.error_code = None
        delivery.updated_at = now
        revision = delivery.revision
        attempt_count = delivery.attempt_count
        raw_token = device.push_token
        assert raw_token is not None
        db.commit()

        return NotificationDeliveryAttempt(
            delivery_id=delivery.id,
            device_id=device.id,
            revision=revision,
            attempt_token=token,
            attempt_count=attempt_count,
            platform=delivery.platform_snapshot,
            provider=delivery.provider_snapshot,
            token_digest=delivery.token_digest_snapshot,
            raw_token=raw_token,
            title=message.title,
            body=message.body,
            payload=dict(message.safe_payload_json or {}),
        )


def finalize_notification_delivery_attempt(
    *,
    attempt: NotificationDeliveryAttempt,
    result: NotificationProviderResult,
) -> tuple[bool, int | None]:
    now = datetime.now(UTC)
    with SessionLocal() as db:
        statement = select(NotificationDelivery).where(
            NotificationDelivery.id == attempt.delivery_id
        )
        if db.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update()
        delivery = db.scalar(statement)
        if (
            delivery is None
            or delivery.status != NotificationDeliveryStatus.RUNNING.value
            or delivery.revision != attempt.revision
            or delivery.attempt_token != attempt.attempt_token
        ):
            db.rollback()
            return False, None

        retry_after: int | None = None
        delivery.attempt_token = None
        delivery.revision += 1
        delivery.updated_at = now
        if result.accepted:
            delivery.status = NotificationDeliveryStatus.ACCEPTED.value
            delivery.accepted_at = now
            delivery.error_code = None
            delivery.next_retry_at = None
        elif result.retryable:
            retry_after = result.retry_after_seconds
            if retry_after is None:
                retry_after = _retry_delay(delivery.attempt_count)
            retry_after = min(
                max(1, int(retry_after)),
                NOTIFICATION_RETRY_MAX_SECONDS,
            )
            delivery.status = NotificationDeliveryStatus.RETRY_WAIT.value
            delivery.error_code = _safe_error_code(result.error_code)
            delivery.next_retry_at = now + timedelta(seconds=retry_after)
        else:
            delivery.status = NotificationDeliveryStatus.TERMINAL_FAILURE.value
            delivery.error_code = _safe_error_code(result.error_code)
            delivery.next_retry_at = None
            if result.invalid_token:
                device_statement = select(Device).where(
                    Device.id == delivery.device_id
                )
                if db.get_bind().dialect.name == "postgresql":
                    device_statement = device_statement.with_for_update()
                device = db.scalar(device_statement)
                if (
                    device is not None
                    and device.push_enabled
                    and device.push_provider == attempt.provider
                    and device.push_token_digest == attempt.token_digest
                ):
                    device.push_enabled = False
                    device.push_token = None
                    device.push_token_digest = None
                    device.push_invalidated_at = now

        _refresh_campaign_completion(
            db,
            campaign_id=delivery.campaign_id,
            now=now,
        )
        db.commit()
        return True, retry_after


def _cancel_delivery_before_disclosure(
    db: Session,
    *,
    delivery: NotificationDelivery,
    status: NotificationDeliveryStatus,
    error_code: str,
    now: datetime,
) -> None:
    delivery.status = status.value
    delivery.error_code = error_code
    delivery.attempt_token = None
    delivery.next_retry_at = None
    delivery.revision += 1
    delivery.updated_at = now
    _refresh_campaign_completion(
        db,
        campaign_id=delivery.campaign_id,
        now=now,
    )


def _deliver_notification_attempt_under_handoff(
    attempt: NotificationDeliveryAttempt,
) -> NotificationProviderResult | None:
    with hold_push_disclosure_handoff(
        provider=attempt.provider,
        digest=attempt.token_digest,
    ):
        now = datetime.now(UTC)
        with SessionLocal() as db:
            statement = select(NotificationDelivery).where(
                NotificationDelivery.id == attempt.delivery_id
            )
            if db.get_bind().dialect.name == "postgresql":
                statement = statement.with_for_update()
            delivery = db.scalar(statement)
            if (
                delivery is None
                or delivery.status != NotificationDeliveryStatus.RUNNING.value
                or delivery.revision != attempt.revision
                or delivery.attempt_token != attempt.attempt_token
            ):
                db.rollback()
                return None

            campaign = db.get(NotificationCampaign, delivery.campaign_id)
            message = db.get(NotificationMessage, delivery.message_id)
            device = db.get(Device, delivery.device_id)
            if campaign is None or message is None or device is None:
                _cancel_delivery_before_disclosure(
                    db,
                    delivery=delivery,
                    status=NotificationDeliveryStatus.CANCELLED,
                    error_code="NOTIFICATION_AUTHORITY_MISSING",
                    now=now,
                )
                db.commit()
                return None

            if campaign.status == NotificationCampaignStatus.CANCELLED.value:
                _cancel_delivery_before_disclosure(
                    db,
                    delivery=delivery,
                    status=NotificationDeliveryStatus.CANCELLED,
                    error_code="NOTIFICATION_CAMPAIGN_CANCELLED",
                    now=now,
                )
                db.commit()
                return None

            if message.expires_at is not None and _as_utc(message.expires_at) <= now:
                _cancel_delivery_before_disclosure(
                    db,
                    delivery=delivery,
                    status=NotificationDeliveryStatus.EXPIRED,
                    error_code="NOTIFICATION_EXPIRED",
                    now=now,
                )
                db.commit()
                return None

            current_authority = (
                device.user_id == delivery.owner_user_id
                and device.push_enabled
                and device.push_invalidated_at is None
                and device.push_token == attempt.raw_token
                and device.push_provider == attempt.provider
                and device.push_token_digest == attempt.token_digest
                and device.platform == attempt.platform
            )
            if not current_authority:
                _cancel_delivery_before_disclosure(
                    db,
                    delivery=delivery,
                    status=NotificationDeliveryStatus.CANCELLED,
                    error_code="DEVICE_PUSH_AUTHORITY_CHANGED",
                    now=now,
                )
                db.commit()
                return None
            db.rollback()

        adapter = resolve_notification_provider(
            platform=attempt.platform,
            provider=attempt.provider,
        )
        try:
            return adapter.deliver(
                NotificationProviderRequest(
                    delivery_id=attempt.delivery_id,
                    device_id=attempt.device_id,
                    platform=attempt.platform,
                    provider=attempt.provider,
                    raw_token=attempt.raw_token,
                    title=attempt.title,
                    body=attempt.body,
                    payload=attempt.payload,
                )
            )
        except Exception:
            return NotificationProviderResult.retryable_failure(
                "NOTIFICATION_PROVIDER_EXCEPTION"
            )


def process_notification_delivery_claim(claim: MaintenanceJobClaim) -> None:
    attempt = begin_notification_delivery_attempt(claim)
    if attempt is None:
        return

    result = _deliver_notification_attempt_under_handoff(attempt)
    if result is None:
        return

    if (
        not result.accepted
        and result.retryable
        and claim.attempt_count >= claim.max_attempts
    ):
        result = NotificationProviderResult.terminal_failure(
            "NOTIFICATION_ATTEMPTS_EXHAUSTED"
        )

    finalized, retry_after = finalize_notification_delivery_attempt(
        attempt=attempt,
        result=result,
    )
    if not finalized:
        return
    if not result.accepted and result.retryable:
        raise NotificationExecutionError(
            _safe_error_code(result.error_code),
            retryable=True,
            retry_after_seconds=retry_after,
        )
