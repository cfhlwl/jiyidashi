from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Mapping
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.maintenance_job_models import MaintenanceJob, MaintenanceJobStatus


DEFAULT_LEASE_SECONDS = 60
DEFAULT_MAX_ATTEMPTS = 5
MAX_LEASE_SECONDS = 15 * 60
BACKOFF_BASE_SECONDS = 5
BACKOFF_MAX_SECONDS = 5 * 60


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


def _bounded_lease_seconds(value: int) -> int:
    if value < 1:
        raise ValueError("lease_seconds must be >= 1")
    return min(value, MAX_LEASE_SECONDS)


def retry_backoff_seconds(attempt_count: int) -> int:
    return min(
        BACKOFF_BASE_SECONDS * (2 ** max(0, attempt_count - 1)),
        BACKOFF_MAX_SECONDS,
    )


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
    job_type: str,
    dedupe_key: str | None,
    owner_user_id: UUID | None = None,
    resource_key: str | None = None,
    payload: Mapping[str, object] | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    next_attempt_at: datetime | None = None,
    now: datetime | None = None,
) -> tuple[MaintenanceJob, bool]:
    normalized_type = job_type.strip()
    if not normalized_type:
        raise ValueError("job_type is required")
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
    except IntegrityError:
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
            raise MaintenanceJobConflict("MAINTENANCE_JOB_DEDUPE_CONFLICT")
        return existing, False

    return job, True


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
    observed_at = _observed_now(now)
    return _locked_claimed_job(
        db,
        job_id=job_id,
        claim_token=claim_token,
        now=observed_at,
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
    now: datetime | None = None,
) -> None:
    observed_at = _observed_now(now)
    job = _locked_claimed_job(
        db,
        job_id=job_id,
        claim_token=claim_token,
        now=observed_at,
    )
    job.status = MaintenanceJobStatus.SUCCEEDED.value
    job.completed_at = observed_at
    job.next_attempt_at = observed_at
    job.claimed_by = None
    job.claim_token = None
    job.lease_expires_at = None
    job.last_error_code = None
    job.updated_at = observed_at
    db.flush()


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
        delay = (
            max(1, retry_after_seconds)
            if retry_after_seconds is not None
            else retry_backoff_seconds(job.attempt_count)
        )
        delay = min(delay, BACKOFF_MAX_SECONDS)
        job.status = MaintenanceJobStatus.RETRY_WAIT.value
        job.next_attempt_at = observed_at + timedelta(seconds=delay)
        job.completed_at = None

    job.last_error_code = normalized_error
    job.claimed_by = None
    job.claim_token = None
    job.lease_expires_at = None
    job.updated_at = observed_at
    db.flush()
    return job.status


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
