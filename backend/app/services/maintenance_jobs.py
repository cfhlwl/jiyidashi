from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.export_models import UserExportJob, UserExportStatus
from app.maintenance_job_models import (
    MaintenanceJob,
    MaintenanceJobStatus,
    MaintenanceJobType,
)
from app.notification_models import (
    NotificationCampaign,
    NotificationCampaignStatus,
    NotificationDelivery,
    NotificationDeliveryStatus,
)
from app.security_models import SecurityAlert, SecurityAlertDeliveryStatus

DEFAULT_LEASE_SECONDS = 60
DEFAULT_MAX_ATTEMPTS = 5
MAX_LEASE_SECONDS = 15 * 60
BACKOFF_BASE_SECONDS = 5
BACKOFF_MAX_SECONDS = 5 * 60
MAX_RETRY_AFTER_SECONDS = 24 * 60 * 60
DIAGNOSTIC_COUNT_CAP = 1_000_000
KNOWN_JOB_TYPES = frozenset(item.value for item in MaintenanceJobType)


class MaintenanceJobError(RuntimeError):
    pass


class MaintenanceJobConflict(MaintenanceJobError):
    pass


class MaintenanceLeaseLost(MaintenanceJobError):
    pass


@dataclass(frozen=True)
class MaintenanceJobClaim:
    id: UUID
    job_type: str
    dedupe_key: str | None
    owner_user_id: UUID | None
    resource_key: str | None
    payload: dict
    attempt_count: int
    max_attempts: int
    claim_token: UUID
    claimed_by: str
    lease_expires_at: datetime


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _observed_now(now: datetime | None) -> datetime:
    return _as_utc(now or datetime.now(UTC))


def _normalize_job_type(value: str | MaintenanceJobType) -> str:
    normalized = value.value if isinstance(value, MaintenanceJobType) else value.strip()
    if normalized not in KNOWN_JOB_TYPES:
        raise ValueError("unsupported maintenance job type")
    return normalized


def _bounded_lease_seconds(value: int) -> int:
    if value < 1:
        raise ValueError("lease_seconds must be >= 1")
    return min(value, MAX_LEASE_SECONDS)


def retry_backoff_seconds(
    attempt_count: int,
    *,
    job_id: UUID | None = None,
) -> int:
    base = min(
        BACKOFF_BASE_SECONDS * (2 ** max(0, attempt_count - 1)),
        BACKOFF_MAX_SECONDS,
    )
    if job_id is None:
        return base
    # Stable bounded jitter prevents synchronized retries without process-local RNG.
    jitter_window = max(1, min(30, base // 5))
    jitter = int.from_bytes(job_id.bytes[-2:], "big") % (jitter_window + 1)
    return min(base + jitter, BACKOFF_MAX_SECONDS)


def _immutable_identity_matches(
    job: MaintenanceJob,
    *,
    owner_user_id: UUID | None,
    resource_key: str | None,
    payload: Mapping[str, object],
    max_attempts: int,
) -> bool:
    return (
        job.owner_user_id == owner_user_id
        and job.resource_key == resource_key
        and dict(job.payload_json or {}) == dict(payload)
        and job.max_attempts == max_attempts
    )


def enqueue_maintenance_job(
    db: Session,
    *,
    job_type: str | MaintenanceJobType,
    dedupe_key: str | None,
    owner_user_id: UUID | None = None,
    resource_key: str | None = None,
    payload: Mapping[str, object] | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    next_attempt_at: datetime | None = None,
    now: datetime | None = None,
) -> tuple[MaintenanceJob, bool]:
    normalized_type = _normalize_job_type(job_type)
    normalized_dedupe = dedupe_key.strip() if dedupe_key is not None else None
    if normalized_dedupe == "":
        normalized_dedupe = None
    if max_attempts < 1 or max_attempts > 100:
        raise ValueError("max_attempts must be between 1 and 100")

    frozen_payload = dict(payload or {})
    observed_at = _observed_now(now)
    due_at = _as_utc(next_attempt_at) if next_attempt_at is not None else observed_at

    if normalized_dedupe is not None:
        existing = db.scalar(
            select(MaintenanceJob).where(
                MaintenanceJob.job_type == normalized_type,
                MaintenanceJob.dedupe_key == normalized_dedupe,
            )
        )
        if existing is not None:
            if not _immutable_identity_matches(
                existing,
                owner_user_id=owner_user_id,
                resource_key=resource_key,
                payload=frozen_payload,
                max_attempts=max_attempts,
            ):
                raise MaintenanceJobConflict("MAINTENANCE_JOB_DEDUPE_CONFLICT")
            return existing, False

    job = MaintenanceJob(
        job_type=normalized_type,
        dedupe_key=normalized_dedupe,
        owner_user_id=owner_user_id,
        resource_key=resource_key,
        payload_json=frozen_payload,
        status=MaintenanceJobStatus.PENDING.value,
        attempt_count=0,
        max_attempts=max_attempts,
        next_attempt_at=due_at,
        created_at=observed_at,
        updated_at=observed_at,
    )

    try:
        with db.begin_nested():
            db.add(job)
            db.flush()
    except IntegrityError as exc:
        if normalized_dedupe is None:
            raise
        existing = db.scalar(
            select(MaintenanceJob).where(
                MaintenanceJob.job_type == normalized_type,
                MaintenanceJob.dedupe_key == normalized_dedupe,
            )
        )
        if existing is None:
            raise
        if not _immutable_identity_matches(
            existing,
            owner_user_id=owner_user_id,
            resource_key=resource_key,
            payload=frozen_payload,
            max_attempts=max_attempts,
        ):
            raise MaintenanceJobConflict(
                "MAINTENANCE_JOB_DEDUPE_CONFLICT"
            ) from exc
        return existing, False

    return job, True


def _notification_delivery_id_for_job(job: MaintenanceJob) -> UUID | None:
    if job.job_type != MaintenanceJobType.NOTIFICATION_DELIVERY.value:
        return None
    raw_delivery_id = (job.payload_json or {}).get("delivery_id")
    try:
        return UUID(str(raw_delivery_id))
    except (TypeError, ValueError, AttributeError):
        return None


def _notification_campaign_id_for_job(job: MaintenanceJob) -> UUID | None:
    if job.job_type != MaintenanceJobType.NOTIFICATION_FANOUT.value:
        return None
    raw_campaign_id = (job.payload_json or {}).get("campaign_id")
    try:
        return UUID(str(raw_campaign_id))
    except (TypeError, ValueError, AttributeError):
        return None


def _maybe_complete_notification_campaign(
    db: Session,
    *,
    campaign_id: UUID,
    now: datetime,
) -> None:
    campaign_statement = select(NotificationCampaign).where(
        NotificationCampaign.id == campaign_id
    )
    if db.get_bind().dialect.name == "postgresql":
        campaign_statement = campaign_statement.with_for_update()
    campaign = db.scalar(campaign_statement)
    if (
        campaign is None
        or campaign.status != NotificationCampaignStatus.DELIVERING.value
        or campaign.fanout_completed_at is None
    ):
        return

    active = int(
        db.scalar(
            select(func.count(NotificationDelivery.id)).where(
                NotificationDelivery.campaign_id == campaign.id,
                NotificationDelivery.status.in_(
                    (
                        NotificationDeliveryStatus.PENDING.value,
                        NotificationDeliveryStatus.RUNNING.value,
                        NotificationDeliveryStatus.RETRY_WAIT.value,
                    )
                ),
            )
        )
        or 0
    )
    if active == 0:
        campaign.status = NotificationCampaignStatus.COMPLETED.value
        campaign.completed_at = now
        campaign.error_code = None
        campaign.updated_at = now


def _sync_notification_delivery_failure(
    db: Session,
    *,
    job: MaintenanceJob,
    error_code: str,
    terminal: bool,
    now: datetime,
    retry_at: datetime | None = None,
) -> None:
    delivery_id = _notification_delivery_id_for_job(job)
    if delivery_id is None:
        return

    statement = select(NotificationDelivery).where(
        NotificationDelivery.id == delivery_id
    )
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    delivery = db.scalar(statement)
    if delivery is None or delivery.status in {
        NotificationDeliveryStatus.ACCEPTED.value,
        NotificationDeliveryStatus.TERMINAL_FAILURE.value,
        NotificationDeliveryStatus.CANCELLED.value,
        NotificationDeliveryStatus.EXPIRED.value,
    }:
        return

    # Provider-classified retry state has already finalized its public attempt.
    # Preserve that result on non-final MaintenanceJob retry.
    if (
        not terminal
        and delivery.status == NotificationDeliveryStatus.RETRY_WAIT.value
        and delivery.attempt_token is None
    ):
        return

    safe_error = (error_code.strip() or "MAINTENANCE_JOB_FAILED")[:80]
    delivery.attempt_token = None
    delivery.accepted_at = None
    delivery.error_code = safe_error
    delivery.revision += 1
    delivery.updated_at = now
    if terminal:
        delivery.status = NotificationDeliveryStatus.TERMINAL_FAILURE.value
        delivery.next_retry_at = None
        _maybe_complete_notification_campaign(
            db,
            campaign_id=delivery.campaign_id,
            now=now,
        )
    else:
        delivery.status = NotificationDeliveryStatus.RETRY_WAIT.value
        delivery.next_retry_at = retry_at


def _sync_notification_fanout_failure(
    db: Session,
    *,
    job: MaintenanceJob,
    error_code: str,
    terminal: bool,
    now: datetime,
) -> None:
    if not terminal:
        return
    campaign_id = _notification_campaign_id_for_job(job)
    if campaign_id is None:
        return

    statement = select(NotificationCampaign).where(
        NotificationCampaign.id == campaign_id
    )
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    campaign = db.scalar(statement)
    if campaign is None or campaign.status not in {
        NotificationCampaignStatus.SCHEDULED.value,
        NotificationCampaignStatus.FANOUT.value,
    }:
        return

    campaign.status = NotificationCampaignStatus.FAILED.value
    campaign.error_code = (error_code.strip() or "MAINTENANCE_JOB_FAILED")[:80]
    campaign.revision += 1
    campaign.updated_at = now


def _security_alert_id_for_job(job: MaintenanceJob) -> UUID | None:
    if job.job_type != MaintenanceJobType.SECURITY_ALERT_DELIVERY.value:
        return None
    raw_alert_id = (job.payload_json or {}).get("alert_id")
    try:
        return UUID(str(raw_alert_id))
    except (TypeError, ValueError, AttributeError):
        return None


def _sync_security_alert_delivery_failure(
    db: Session,
    *,
    job: MaintenanceJob,
    error_code: str,
    terminal: bool,
    now: datetime,
    retry_at: datetime | None = None,
) -> None:
    """Keep public SecurityAlert authority aligned with maintenance failure state."""

    alert_id = _security_alert_id_for_job(job)
    if alert_id is None:
        return

    statement = select(SecurityAlert).where(SecurityAlert.id == alert_id)
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    alert = db.scalar(statement)
    if alert is None or alert.delivery_status in {
        SecurityAlertDeliveryStatus.DELIVERED.value,
        SecurityAlertDeliveryStatus.TERMINAL_FAILURE.value,
    }:
        return

    # A classified provider retry may already have finalized the public attempt.
    # Preserve that provider result on a non-final maintenance retry. Raw failures
    # after begin_security_alert_delivery_attempt() retain a token and must be fenced.
    if (
        not terminal
        and alert.delivery_status == SecurityAlertDeliveryStatus.RETRYABLE_FAILURE.value
        and alert.delivery_attempt_token is None
    ):
        return

    safe_error = (error_code.strip() or "MAINTENANCE_JOB_FAILED")[:80]
    alert.delivery_attempt_token = None
    alert.delivery_error_code = safe_error
    alert.delivered_at = None
    alert.delivery_revision += 1
    alert.updated_at = now
    if terminal:
        alert.delivery_status = SecurityAlertDeliveryStatus.TERMINAL_FAILURE.value
        alert.next_retry_at = None
    else:
        alert.delivery_status = SecurityAlertDeliveryStatus.RETRYABLE_FAILURE.value
        alert.next_retry_at = retry_at


def _expire_exhausted_running_jobs(db: Session, *, now: datetime) -> int:
    statement = select(MaintenanceJob).where(
        MaintenanceJob.status == MaintenanceJobStatus.RUNNING.value,
        MaintenanceJob.lease_expires_at.is_not(None),
        MaintenanceJob.lease_expires_at <= now,
        MaintenanceJob.attempt_count >= MaintenanceJob.max_attempts,
    )
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    else:
        statement = statement.with_for_update()

    jobs = list(db.scalars(statement))
    for job in jobs:
        job.status = MaintenanceJobStatus.FAILED.value
        job.completed_at = now
        job.next_attempt_at = now
        job.claimed_by = None
        job.claim_token = None
        job.lease_expires_at = None
        job.last_error_code = "MAINTENANCE_ATTEMPTS_EXHAUSTED"
        job.updated_at = now

        _sync_security_alert_delivery_failure(
            db,
            job=job,
            error_code="MAINTENANCE_ATTEMPTS_EXHAUSTED",
            terminal=True,
            now=now,
        )
        _sync_notification_delivery_failure(
            db,
            job=job,
            error_code="MAINTENANCE_ATTEMPTS_EXHAUSTED",
            terminal=True,
            now=now,
        )
        _sync_notification_fanout_failure(
            db,
            job=job,
            error_code="MAINTENANCE_ATTEMPTS_EXHAUSTED",
            terminal=True,
            now=now,
        )

        if (
            job.job_type == MaintenanceJobType.EXPORT.value
            and job.owner_user_id is not None
        ):
            raw_export_id = (job.payload_json or {}).get("export_job_id")
            try:
                export_job_id = UUID(str(raw_export_id))
            except (TypeError, ValueError, AttributeError):
                continue
            export_statement = select(UserExportJob).where(
                UserExportJob.id == export_job_id,
                UserExportJob.owner_user_id == job.owner_user_id,
                UserExportJob.status.in_(
                    (
                        UserExportStatus.PENDING.value,
                        UserExportStatus.RUNNING.value,
                    )
                ),
            )
            if db.get_bind().dialect.name == "postgresql":
                export_statement = export_statement.with_for_update()
            export_job = db.scalar(export_statement)
            if export_job is not None:
                export_job.status = UserExportStatus.FAILED.value
                export_job.error_code = "MAINTENANCE_ATTEMPTS_EXHAUSTED"
                export_job.revision += 1
                export_job.updated_at = now

    db.flush()
    return len(jobs)


def _eligible_job_statement(now: datetime):
    retryable_due = and_(
        MaintenanceJob.status.in_(
            (
                MaintenanceJobStatus.PENDING.value,
                MaintenanceJobStatus.RETRY_WAIT.value,
            )
        ),
        MaintenanceJob.next_attempt_at <= now,
    )
    expired_lease = and_(
        MaintenanceJob.status == MaintenanceJobStatus.RUNNING.value,
        MaintenanceJob.lease_expires_at.is_not(None),
        MaintenanceJob.lease_expires_at <= now,
    )
    return (
        select(MaintenanceJob)
        .where(
            or_(retryable_due, expired_lease),
            MaintenanceJob.attempt_count < MaintenanceJob.max_attempts,
        )
        .order_by(
            MaintenanceJob.next_attempt_at.asc(),
            MaintenanceJob.created_at.asc(),
            MaintenanceJob.id.asc(),
        )
        .limit(1)
    )


def claim_next_maintenance_job(
    db: Session,
    *,
    worker_id: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    now: datetime | None = None,
) -> MaintenanceJobClaim | None:
    normalized_worker = worker_id.strip()
    if not normalized_worker:
        raise ValueError("worker_id is required")
    observed_at = _observed_now(now)
    bounded_lease = _bounded_lease_seconds(lease_seconds)

    _expire_exhausted_running_jobs(db, now=observed_at)
    statement = _eligible_job_statement(observed_at)
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    else:
        statement = statement.with_for_update()

    job = db.scalar(statement)
    if job is None:
        return None

    token = uuid4()
    job.status = MaintenanceJobStatus.RUNNING.value
    job.attempt_count += 1
    job.claimed_by = normalized_worker
    job.claim_token = token
    job.lease_expires_at = observed_at + timedelta(seconds=bounded_lease)
    job.started_at = job.started_at or observed_at
    job.updated_at = observed_at
    db.flush()

    return MaintenanceJobClaim(
        id=job.id,
        job_type=job.job_type,
        dedupe_key=job.dedupe_key,
        owner_user_id=job.owner_user_id,
        resource_key=job.resource_key,
        payload=dict(job.payload_json or {}),
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        claim_token=token,
        claimed_by=normalized_worker,
        lease_expires_at=_as_utc(job.lease_expires_at),
    )


def _locked_claimed_job(
    db: Session,
    *,
    job_id: UUID,
    claim_token: UUID,
    now: datetime,
) -> MaintenanceJob:
    statement = select(MaintenanceJob).where(MaintenanceJob.id == job_id)
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    job = db.scalar(statement)
    if (
        job is None
        or job.status != MaintenanceJobStatus.RUNNING.value
        or job.claim_token != claim_token
        or job.lease_expires_at is None
        or _as_utc(job.lease_expires_at) <= now
    ):
        raise MaintenanceLeaseLost("MAINTENANCE_LEASE_LOST")
    return job


def assert_maintenance_claim_current(
    db: Session,
    *,
    job_id: UUID,
    claim_token: UUID,
    now: datetime | None = None,
) -> MaintenanceJob:
    return _locked_claimed_job(
        db,
        job_id=job_id,
        claim_token=claim_token,
        now=_observed_now(now),
    )


def renew_maintenance_claim(
    db: Session,
    *,
    job_id: UUID,
    claim_token: UUID,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    now: datetime | None = None,
) -> datetime:
    observed_at = _observed_now(now)
    bounded_lease = _bounded_lease_seconds(lease_seconds)
    job = _locked_claimed_job(
        db,
        job_id=job_id,
        claim_token=claim_token,
        now=observed_at,
    )
    job.lease_expires_at = observed_at + timedelta(seconds=bounded_lease)
    job.updated_at = observed_at
    db.flush()
    return _as_utc(job.lease_expires_at)


def complete_maintenance_job(
    db: Session,
    *,
    job_id: UUID,
    claim_token: UUID,
    scrub_identity: bool = False,
    now: datetime | None = None,
) -> bool:
    observed_at = _observed_now(now)
    statement = select(MaintenanceJob).where(MaintenanceJob.id == job_id)
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    job = db.scalar(statement)
    if job is None:
        raise MaintenanceLeaseLost("MAINTENANCE_LEASE_LOST")
    if job.status == MaintenanceJobStatus.SUCCEEDED.value:
        return False
    if (
        job.status != MaintenanceJobStatus.RUNNING.value
        or job.claim_token != claim_token
        or job.lease_expires_at is None
        or _as_utc(job.lease_expires_at) <= observed_at
    ):
        raise MaintenanceLeaseLost("MAINTENANCE_LEASE_LOST")

    job.status = MaintenanceJobStatus.SUCCEEDED.value
    job.completed_at = observed_at
    job.next_attempt_at = observed_at
    job.claimed_by = None
    job.claim_token = None
    job.lease_expires_at = None
    job.last_error_code = None
    if scrub_identity:
        job.owner_user_id = None
        job.dedupe_key = None
        job.resource_key = None
        job.payload_json = {}
    job.updated_at = observed_at
    db.flush()
    return True


def fail_maintenance_job(
    db: Session,
    *,
    job_id: UUID,
    claim_token: UUID,
    error_code: str,
    terminal: bool = False,
    retry_after_seconds: int | None = None,
    now: datetime | None = None,
) -> str:
    observed_at = _observed_now(now)
    normalized_error = error_code.strip() or "MAINTENANCE_JOB_FAILED"
    if len(normalized_error) > 80:
        normalized_error = normalized_error[:80]

    job = _locked_claimed_job(
        db,
        job_id=job_id,
        claim_token=claim_token,
        now=observed_at,
    )
    exhausted = job.attempt_count >= job.max_attempts
    if terminal or exhausted:
        job.status = MaintenanceJobStatus.FAILED.value
        job.completed_at = observed_at
        job.next_attempt_at = observed_at
    else:
        if retry_after_seconds is not None:
            delay = min(
                max(1, retry_after_seconds),
                MAX_RETRY_AFTER_SECONDS,
            )
        else:
            delay = retry_backoff_seconds(
                job.attempt_count,
                job_id=job.id,
            )
        job.status = MaintenanceJobStatus.RETRY_WAIT.value
        job.next_attempt_at = observed_at + timedelta(seconds=delay)
        job.completed_at = None

    job.last_error_code = normalized_error
    job.claimed_by = None
    job.claim_token = None
    job.lease_expires_at = None
    job.updated_at = observed_at
    terminal_failure = job.status == MaintenanceJobStatus.FAILED.value
    retry_at = (
        None
        if terminal_failure
        else _as_utc(job.next_attempt_at)
    )
    _sync_security_alert_delivery_failure(
        db,
        job=job,
        error_code=normalized_error,
        terminal=terminal_failure,
        now=observed_at,
        retry_at=retry_at,
    )
    _sync_notification_delivery_failure(
        db,
        job=job,
        error_code=normalized_error,
        terminal=terminal_failure,
        now=observed_at,
        retry_at=retry_at,
    )
    _sync_notification_fanout_failure(
        db,
        job=job,
        error_code=normalized_error,
        terminal=terminal_failure,
        now=observed_at,
    )
    db.flush()
    return job.status


def fence_owner_maintenance_jobs_for_deletion(
    db: Session,
    *,
    owner_user_id: UUID,
    preserve_job_id: UUID | None = None,
    now: datetime | None = None,
) -> int:
    """Cancel stale owner work and erase its business identity in one transaction."""

    observed_at = _observed_now(now)
    active_filter = [
        MaintenanceJob.owner_user_id == owner_user_id,
        MaintenanceJob.status.in_(
            (
                MaintenanceJobStatus.PENDING.value,
                MaintenanceJobStatus.RUNNING.value,
                MaintenanceJobStatus.RETRY_WAIT.value,
            )
        ),
    ]
    identity_filter = [MaintenanceJob.owner_user_id == owner_user_id]
    if preserve_job_id is not None:
        active_filter.append(MaintenanceJob.id != preserve_job_id)
        identity_filter.append(MaintenanceJob.id != preserve_job_id)

    result = db.execute(
        update(MaintenanceJob)
        .where(*active_filter)
        .values(
            status=MaintenanceJobStatus.CANCELLED.value,
            completed_at=observed_at,
            next_attempt_at=observed_at,
            claimed_by=None,
            claim_token=None,
            lease_expires_at=None,
            last_error_code="SUPERSEDED_BY_DESTRUCTIVE_OPERATION",
            updated_at=observed_at,
        )
    )
    db.execute(
        update(MaintenanceJob)
        .where(*identity_filter)
        .values(
            owner_user_id=None,
            dedupe_key=None,
            resource_key=None,
            payload_json={},
            updated_at=observed_at,
        )
    )
    rowcount = getattr(result, "rowcount", 0)
    return int(rowcount) if isinstance(rowcount, int) and rowcount > 0 else 0


def scrub_maintenance_job_identity(
    db: Session,
    *,
    job_id: UUID,
    owner_user_id: UUID | None = None,
) -> bool:
    """Remove user/resource identity without changing execution authority or outcome."""

    statement = select(MaintenanceJob).where(MaintenanceJob.id == job_id)
    if owner_user_id is not None:
        statement = statement.where(MaintenanceJob.owner_user_id == owner_user_id)
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    job = db.scalar(statement)
    if job is None:
        return False
    job.owner_user_id = None
    job.dedupe_key = None
    job.resource_key = None
    job.payload_json = {}
    job.updated_at = datetime.now(UTC)
    db.flush()
    return True


def cancel_maintenance_job(
    db: Session,
    *,
    job_id: UUID,
    now: datetime | None = None,
) -> bool:
    observed_at = _observed_now(now)
    statement = select(MaintenanceJob).where(MaintenanceJob.id == job_id)
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update()
    job = db.scalar(statement)
    if job is None:
        return False
    if job.status in {
        MaintenanceJobStatus.SUCCEEDED.value,
        MaintenanceJobStatus.FAILED.value,
        MaintenanceJobStatus.CANCELLED.value,
    }:
        return False
    job.status = MaintenanceJobStatus.CANCELLED.value
    job.completed_at = observed_at
    job.next_attempt_at = observed_at
    job.claimed_by = None
    job.claim_token = None
    job.lease_expires_at = None
    job.updated_at = observed_at
    db.flush()
    return True


def maintenance_job_diagnostics(
    db: Session,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    observed_at = _observed_now(now)
    counts = {
        status: min(int(count), DIAGNOSTIC_COUNT_CAP)
        for status, count in db.execute(
            select(MaintenanceJob.status, func.count(MaintenanceJob.id)).group_by(
                MaintenanceJob.status
            )
        ).all()
    }
    due_count = int(
        db.scalar(
            select(func.count(MaintenanceJob.id)).where(
                or_(
                    and_(
                        MaintenanceJob.status.in_(
                            (
                                MaintenanceJobStatus.PENDING.value,
                                MaintenanceJobStatus.RETRY_WAIT.value,
                            )
                        ),
                        MaintenanceJob.next_attempt_at <= observed_at,
                        MaintenanceJob.attempt_count < MaintenanceJob.max_attempts,
                    ),
                    and_(
                        MaintenanceJob.status == MaintenanceJobStatus.RUNNING.value,
                        MaintenanceJob.lease_expires_at.is_not(None),
                        MaintenanceJob.lease_expires_at <= observed_at,
                        MaintenanceJob.attempt_count < MaintenanceJob.max_attempts,
                    ),
                )
            )
        )
        or 0
    )
    return {
        "counts": counts,
        "due": min(due_count, DIAGNOSTIC_COUNT_CAP),
    }
