"""Real PostgreSQL concurrency gate for OPS-002 durable maintenance jobs."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

from sqlalchemy import delete

from app.core.db import SessionLocal
from app.maintenance_job_models import (
    MaintenanceJob,
    MaintenanceJobStatus,
    MaintenanceJobType,
)
from app.services.maintenance_jobs import (
    MaintenanceLeaseLost,
    claim_next_maintenance_job,
    complete_maintenance_job,
    enqueue_maintenance_job,
)


def _delete_jobs(prefix: str) -> None:
    with SessionLocal() as db:
        db.execute(
            delete(MaintenanceJob).where(MaintenanceJob.dedupe_key.like(f"{prefix}%"))
        )
        db.commit()


def _assert_two_workers_single_claim(base: datetime, prefix: str) -> None:
    key = f"{prefix}:race"
    with SessionLocal() as db:
        job, created = enqueue_maintenance_job(
            db,
            job_type=MaintenanceJobType.ANALYTICS_RETENTION,
            dedupe_key=key,
            payload={"scope": "postgres-race"},
            now=base,
        )
        assert created
        job_id = job.id
        db.commit()

    gate = Barrier(2)

    def claim(worker_id: str):
        with SessionLocal() as db:
            gate.wait(timeout=10)
            claim = claim_next_maintenance_job(
                db,
                worker_id=worker_id,
                lease_seconds=30,
                now=base,
            )
            if claim is not None:
                # Hold the row lock briefly so the peer must exercise SKIP LOCKED.
                time.sleep(0.2)
            db.commit()
            return claim

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(claim, ("worker-a", "worker-b")))

    winners = [claim for claim in claims if claim is not None]
    assert len(winners) == 1, claims
    assert winners[0].id == job_id

    with SessionLocal() as db:
        complete_maintenance_job(
            db,
            job_id=job_id,
            claim_token=winners[0].claim_token,
            now=base + timedelta(seconds=1),
        )
        db.commit()


def _assert_concurrent_enqueue_is_idempotent(base: datetime, prefix: str) -> None:
    key = f"{prefix}:dedupe"
    gate = Barrier(2)

    # Use one canonical immutable payload across both racing transactions.
    operation_id = str(uuid4())

    def canonical_enqueue(_: int):
        with SessionLocal() as db:
            gate.wait(timeout=10)
            job, created = enqueue_maintenance_job(
                db,
                job_type=MaintenanceJobType.DATA_DELETE,
                dedupe_key=key,
                resource_key="postgres-dedupe",
                payload={"operation_id": operation_id},
                now=base,
            )
            db.commit()
            return job.id, created

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(canonical_enqueue, (1, 2)))

    assert results[0][0] == results[1][0], results
    assert sum(int(created) for _, created in results) == 1, results


def _assert_expiry_reclaim_and_stale_token(base: datetime, prefix: str) -> None:
    with SessionLocal() as db:
        job, _ = enqueue_maintenance_job(
            db,
            job_type=MaintenanceJobType.LOCATION_RETENTION,
            dedupe_key=f"{prefix}:reclaim",
            max_attempts=3,
            now=base,
        )
        job_id = job.id
        db.commit()

    with SessionLocal() as db:
        first = claim_next_maintenance_job(
            db,
            worker_id="worker-old",
            lease_seconds=1,
            now=base,
        )
        assert first is not None
        db.commit()

    with SessionLocal() as db:
        second = claim_next_maintenance_job(
            db,
            worker_id="worker-new",
            lease_seconds=30,
            now=base + timedelta(seconds=2),
        )
        assert second is not None
        assert second.id == job_id
        assert second.claim_token != first.claim_token
        db.commit()

    with SessionLocal() as db:
        try:
            complete_maintenance_job(
                db,
                job_id=job_id,
                claim_token=first.claim_token,
                now=base + timedelta(seconds=3),
            )
            raise AssertionError("stale worker unexpectedly committed")
        except MaintenanceLeaseLost:
            db.rollback()

    with SessionLocal() as db:
        complete_maintenance_job(
            db,
            job_id=job_id,
            claim_token=second.claim_token,
            now=base + timedelta(seconds=3),
        )
        db.commit()


def _assert_crashed_final_attempt_terminalizes(base: datetime, prefix: str) -> None:
    with SessionLocal() as db:
        job, _ = enqueue_maintenance_job(
            db,
            job_type=MaintenanceJobType.SECURITY_ALERT_DELIVERY,
            dedupe_key=f"{prefix}:final-crash",
            max_attempts=1,
            now=base,
        )
        job_id = job.id
        db.commit()

    with SessionLocal() as db:
        claim = claim_next_maintenance_job(
            db,
            worker_id="worker-crash",
            lease_seconds=1,
            now=base,
        )
        assert claim is not None
        assert claim.attempt_count == 1
        db.commit()

    with SessionLocal() as db:
        assert (
            claim_next_maintenance_job(
                db,
                worker_id="worker-reaper",
                now=base + timedelta(seconds=2),
            )
            is None
        )
        db.commit()

    with SessionLocal() as db:
        saved = db.get(MaintenanceJob, job_id)
        assert saved is not None
        assert saved.status == MaintenanceJobStatus.FAILED.value
        assert saved.last_error_code == "MAINTENANCE_ATTEMPTS_EXHAUSTED"
        assert saved.claim_token is None
        assert saved.lease_expires_at is None
        db.rollback()


def main() -> None:
    prefix = f"ops002-{uuid4().hex}"
    base = datetime.now(UTC).replace(microsecond=0)
    try:
        _assert_two_workers_single_claim(base, prefix)
        _assert_concurrent_enqueue_is_idempotent(base + timedelta(minutes=1), prefix)
        _assert_expiry_reclaim_and_stale_token(base + timedelta(minutes=2), prefix)
        _assert_crashed_final_attempt_terminalizes(base + timedelta(minutes=3), prefix)
    finally:
        _delete_jobs(prefix)


if __name__ == "__main__":
    main()
