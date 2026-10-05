"""Real PostgreSQL concurrency gate for OPS-002 durable maintenance jobs."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

from sqlalchemy import delete, select

from app.account_deletion_models import AccountDeletionOperation
from app.core.db import SessionLocal
from app.data_deletion_models import DataDeletionOperation
from app.maintenance_adapters import ClaimAuthority, _cancel_other_owner_jobs
from app.maintenance_job_models import (
    MaintenanceJob,
    MaintenanceJobStatus,
    MaintenanceJobType,
)
from app.models import User
from app.services.account_deletion_service import (
    AccountDeletionError,
    progress_prepared_account_deletion,
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
                # This case proves only concurrent enqueue idempotency. Keep the
                # resulting job outside later claim/reclaim scenarios so the gate
                # does not depend on subtest execution order.
                next_attempt_at=base + timedelta(days=1),
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


class EmptyStorage:
    def iter_object_keys(self, prefix: str):
        return iter(())

    def delete_object(self, object_key: str) -> None:
        return None


def _assert_account_delete_requires_local_cleanup_proof() -> None:
    user_id = uuid4()
    operation_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname="ops002-account-boundary"))
        # The models intentionally do not expose an ORM relationship. Flush the
        # canonical FK parent explicitly so the PostgreSQL gate proves the deletion
        # boundary rather than relying on unit-of-work insert ordering.
        db.flush()
        db.add(
            AccountDeletionOperation(
                id=operation_id,
                user_id=user_id,
                request_id=uuid4(),
                data_deletion_request_id=uuid4(),
            )
        )
        db.commit()

    try:
        with SessionLocal() as db:
            try:
                progress_prepared_account_deletion(
                    db,
                    user_id=user_id,
                    operation_id=operation_id,
                    storage=EmptyStorage(),
                )
                raise AssertionError("worker bypassed local_cleanup_ready proof")
            except AccountDeletionError as exc:
                assert exc.code == "ACCOUNT_DELETION_LOCAL_CLEANUP_NOT_READY"
                assert exc.status_code == 409

        with SessionLocal() as db:
            assert (
                db.scalar(
                    select(DataDeletionOperation.id)
                    .where(DataDeletionOperation.user_id == user_id)
                    .limit(1)
                )
                is None
            )
            db.rollback()
    finally:
        with SessionLocal() as db:
            db.execute(
                delete(AccountDeletionOperation).where(
                    AccountDeletionOperation.user_id == user_id
                )
            )
            db.execute(delete(User).where(User.id == user_id))
            db.commit()


def _assert_destructive_fence_invalidates_old_claim(
    base: datetime,
    prefix: str,
) -> None:
    user_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname="ops002-destructive-fence"))
        db.flush()
        old_job, _ = enqueue_maintenance_job(
            db,
            job_type=MaintenanceJobType.LOCATION_RETENTION,
            dedupe_key=f"{prefix}:old-owner-work",
            owner_user_id=user_id,
            now=base,
        )
        destructive_job, _ = enqueue_maintenance_job(
            db,
            job_type=MaintenanceJobType.DATA_DELETE,
            dedupe_key=f"{prefix}:destructive",
            owner_user_id=user_id,
            payload={"operation_id": str(uuid4())},
            next_attempt_at=base + timedelta(seconds=30),
            now=base,
        )
        old_job_id = old_job.id
        destructive_job_id = destructive_job.id
        db.commit()

    with SessionLocal() as db:
        old_claim = claim_next_maintenance_job(
            db,
            worker_id="old-owner-worker",
            lease_seconds=60,
            now=base,
        )
        assert old_claim is not None
        assert old_claim.id == old_job_id
        db.commit()

    cancelled = _cancel_other_owner_jobs(
        owner_user_id=user_id,
        current_job_id=destructive_job_id,
    )
    assert cancelled == 1

    try:
        ClaimAuthority(old_claim).check()
        raise AssertionError("cancelled stale claim remained authoritative")
    except MaintenanceLeaseLost:
        pass

    with SessionLocal() as db:
        saved = db.get(MaintenanceJob, old_job_id)
        assert saved is not None
        assert saved.status == MaintenanceJobStatus.CANCELLED.value
        assert saved.claim_token is None
        db.execute(delete(MaintenanceJob).where(MaintenanceJob.owner_user_id == user_id))
        db.execute(delete(User).where(User.id == user_id))
        db.commit()


def main() -> None:
    prefix = f"ops002-{uuid4().hex}"
    base = datetime.now(UTC).replace(microsecond=0)
    try:
        _assert_two_workers_single_claim(base, prefix)
        _assert_concurrent_enqueue_is_idempotent(base + timedelta(minutes=1), prefix)
        _assert_expiry_reclaim_and_stale_token(base + timedelta(minutes=2), prefix)
        _assert_crashed_final_attempt_terminalizes(base + timedelta(minutes=3), prefix)
        _assert_account_delete_requires_local_cleanup_proof()
        _assert_destructive_fence_invalidates_old_claim(
            base + timedelta(minutes=4),
            prefix,
        )
    finally:
        _delete_jobs(prefix)


if __name__ == "__main__":
    main()
