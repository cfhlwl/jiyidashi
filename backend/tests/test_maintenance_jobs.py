from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.maintenance_job_models import MaintenanceJob, MaintenanceJobStatus
from app.services.maintenance_jobs import (
    MaintenanceJobConflict,
    MaintenanceLeaseLost,
    cancel_maintenance_job,
    claim_next_maintenance_job,
    complete_maintenance_job,
    enqueue_maintenance_job,
    fail_maintenance_job,
)


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    MaintenanceJob.__table__.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def test_dedupe_replay_returns_same_job_and_conflict_fails_closed(session_factory):
    now = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)
    with session_factory() as db:
        first, created = enqueue_maintenance_job(
            db,
            job_type="DATA_DELETE",
            dedupe_key="owner-a:req-1",
            resource_key="request:req-1",
            payload={"request_id": "req-1"},
            now=now,
        )
        db.commit()
        first_id = first.id

    with session_factory() as db:
        replay, created = enqueue_maintenance_job(
            db,
            job_type="DATA_DELETE",
            dedupe_key="owner-a:req-1",
            resource_key="request:req-1",
            payload={"request_id": "req-1"},
            now=now + timedelta(seconds=1),
        )
        assert created is False
        assert replay.id == first_id
        db.rollback()

    with session_factory() as db:
        with pytest.raises(MaintenanceJobConflict):
            enqueue_maintenance_job(
                db,
                job_type="DATA_DELETE",
                dedupe_key="owner-a:req-1",
                resource_key="request:req-1",
                payload={"request_id": "different"},
                now=now + timedelta(seconds=2),
            )


def test_expired_lease_is_reclaimed_and_stale_worker_cannot_commit(session_factory):
    now = datetime(2026, 10, 5, 8, 30, tzinfo=UTC)
    with session_factory() as db:
        job, _ = enqueue_maintenance_job(
            db,
            job_type="LOCATION_RETENTION",
            dedupe_key="sweep:2026-10-05T08:30",
            now=now,
            max_attempts=3,
        )
        db.commit()
        job_id = job.id

    with session_factory() as db:
        first = claim_next_maintenance_job(
            db,
            worker_id="worker-a",
            lease_seconds=10,
            now=now,
        )
        assert first is not None
        assert first.id == job_id
        assert first.attempt_count == 1
        db.commit()

    with session_factory() as db:
        assert (
            claim_next_maintenance_job(
                db,
                worker_id="worker-b",
                lease_seconds=10,
                now=now + timedelta(seconds=9),
            )
            is None
        )
        db.rollback()

    with session_factory() as db:
        second = claim_next_maintenance_job(
            db,
            worker_id="worker-b",
            lease_seconds=10,
            now=now + timedelta(seconds=11),
        )
        assert second is not None
        assert second.id == job_id
        assert second.attempt_count == 2
        assert second.claim_token != first.claim_token
        db.commit()

    with session_factory() as db:
        with pytest.raises(MaintenanceLeaseLost):
            complete_maintenance_job(
                db,
                job_id=job_id,
                claim_token=first.claim_token,
                now=now + timedelta(seconds=12),
            )
        db.rollback()

    with session_factory() as db:
        complete_maintenance_job(
            db,
            job_id=job_id,
            claim_token=second.claim_token,
            now=now + timedelta(seconds=12),
        )
        db.commit()

    with session_factory() as db:
        saved = db.get(MaintenanceJob, job_id)
        assert saved is not None
        assert saved.status == MaintenanceJobStatus.SUCCEEDED.value
        assert saved.attempt_count == 2
        assert saved.claim_token is None
        assert saved.lease_expires_at is None


def test_retry_wait_is_bounded_and_not_claimable_before_due(session_factory):
    now = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
    with session_factory() as db:
        job, _ = enqueue_maintenance_job(
            db,
            job_type="SECURITY_ALERT_DELIVERY",
            dedupe_key="alert:1",
            now=now,
            max_attempts=4,
        )
        db.commit()
        job_id = job.id

    with session_factory() as db:
        claim = claim_next_maintenance_job(
            db,
            worker_id="worker-a",
            now=now,
        )
        assert claim is not None
        status = fail_maintenance_job(
            db,
            job_id=claim.id,
            claim_token=claim.claim_token,
            error_code="DELIVERY_TEMPORARY_FAILURE",
            retry_after_seconds=30,
            now=now + timedelta(seconds=1),
        )
        assert status == MaintenanceJobStatus.RETRY_WAIT.value
        db.commit()

    with session_factory() as db:
        assert (
            claim_next_maintenance_job(
                db,
                worker_id="worker-b",
                now=now + timedelta(seconds=30),
            )
            is None
        )
        db.rollback()

    with session_factory() as db:
        retry = claim_next_maintenance_job(
            db,
            worker_id="worker-b",
            now=now + timedelta(seconds=31),
        )
        assert retry is not None
        assert retry.id == job_id
        assert retry.attempt_count == 2
        db.rollback()


def test_terminal_failure_and_cancel_are_not_reclaimed(session_factory):
    now = datetime(2026, 10, 5, 9, 30, tzinfo=UTC)
    with session_factory() as db:
        first, _ = enqueue_maintenance_job(
            db,
            job_type="ANALYTICS_RETENTION",
            dedupe_key="terminal:1",
            now=now,
        )
        second, _ = enqueue_maintenance_job(
            db,
            job_type="MEDIA_PENDING_CLEANUP",
            dedupe_key="cancel:1",
            now=now + timedelta(seconds=1),
        )
        db.commit()
        first_id = first.id
        second_id = second.id

    with session_factory() as db:
        claim = claim_next_maintenance_job(
            db,
            worker_id="worker-a",
            now=now,
        )
        assert claim is not None
        assert claim.id == first_id
        status = fail_maintenance_job(
            db,
            job_id=claim.id,
            claim_token=claim.claim_token,
            error_code="INVALID_RESOURCE",
            terminal=True,
            now=now + timedelta(seconds=1),
        )
        assert status == MaintenanceJobStatus.FAILED.value
        db.commit()

    with session_factory() as db:
        assert cancel_maintenance_job(
            db,
            job_id=second_id,
            now=now + timedelta(seconds=2),
        )
        db.commit()

    with session_factory() as db:
        rows = {
            item.id: item.status
            for item in db.scalars(
                select(MaintenanceJob).where(
                    MaintenanceJob.id.in_((first_id, second_id))
                )
            )
        }
        assert rows[first_id] == MaintenanceJobStatus.FAILED.value
        assert rows[second_id] == MaintenanceJobStatus.CANCELLED.value
        assert (
            claim_next_maintenance_job(
                db,
                worker_id="worker-c",
                now=now + timedelta(hours=1),
            )
            is None
        )



def test_unknown_job_type_is_rejected(session_factory):
    with session_factory() as db:
        with pytest.raises(ValueError, match="unsupported maintenance job type"):
            enqueue_maintenance_job(
                db,
                job_type="ARBITRARY_BACKGROUND_CODE",
                dedupe_key="unsupported:1",
            )


def test_expired_final_attempt_is_terminalized_after_worker_crash(session_factory):
    now = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)
    with session_factory() as db:
        job, _ = enqueue_maintenance_job(
            db,
            job_type="ANALYTICS_RETENTION",
            dedupe_key="analytics:final-attempt",
            now=now,
            max_attempts=1,
        )
        db.commit()
        job_id = job.id

    with session_factory() as db:
        claim = claim_next_maintenance_job(
            db,
            worker_id="crashing-worker",
            lease_seconds=5,
            now=now,
        )
        assert claim is not None
        assert claim.attempt_count == 1
        db.commit()

    with session_factory() as db:
        assert (
            claim_next_maintenance_job(
                db,
                worker_id="reaper-worker",
                now=now + timedelta(seconds=6),
            )
            is None
        )
        # The no-work path still has durable housekeeping to commit.
        db.commit()

    with session_factory() as db:
        saved = db.get(MaintenanceJob, job_id)
        assert saved is not None
        assert saved.status == MaintenanceJobStatus.FAILED.value
        assert saved.last_error_code == "MAINTENANCE_ATTEMPTS_EXHAUSTED"
        assert saved.claim_token is None
        assert saved.lease_expires_at is None


def test_terminal_success_replay_is_idempotent(session_factory):
    now = datetime(2026, 10, 5, 10, 30, tzinfo=UTC)
    with session_factory() as db:
        job, _ = enqueue_maintenance_job(
            db,
            job_type="LOCATION_RETENTION",
            dedupe_key="location:success-replay",
            now=now,
        )
        db.commit()
        job_id = job.id

    with session_factory() as db:
        claim = claim_next_maintenance_job(
            db,
            worker_id="worker-a",
            now=now,
        )
        assert claim is not None
        assert complete_maintenance_job(
            db,
            job_id=job_id,
            claim_token=claim.claim_token,
            now=now + timedelta(seconds=1),
        )
        db.commit()
        token = claim.claim_token

    with session_factory() as db:
        assert (
            complete_maintenance_job(
                db,
                job_id=job_id,
                claim_token=token,
                now=now + timedelta(seconds=2),
            )
            is False
        )
        db.rollback()
