"""Real PostgreSQL SEC-017 delivery authority gate."""

from __future__ import annotations

import os
import subprocess
import threading
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from app.core.db import SessionLocal, engine
from app.maintenance_adapters import handle_security_alert_delivery
from app.maintenance_worker import MaintenanceWorker
from app.maintenance_job_models import (
    MaintenanceJob,
    MaintenanceJobStatus,
    MaintenanceJobType,
)
from app.security_models import (
    SecurityAlert,
    SecurityAlertDeliveryStatus,
    SecuritySeverity,
    SecuritySignalCode,
)
from app.services import security_alerting
from app.services.maintenance_jobs import (
    claim_next_maintenance_job,
    complete_maintenance_job,
    enqueue_maintenance_job,
)
from app.services.security_alert_human_delivery import (
    HumanDeliveryResult,
    SecurityAlertHumanMessage,
)
from app.services.security_alerting import (
    SecurityScope,
    begin_security_alert_delivery_attempt,
    finalize_security_alert_delivery_attempt,
)


DATABASE_URL = os.environ["DATABASE_URL"]


def _alembic(*args: str) -> None:
    subprocess.run(["alembic", *args], check=True)


def _prove_legacy_sec015_migration_transition() -> None:
    _alembic("downgrade", "0034_api001_object_capacity")
    now = datetime.now(UTC).replace(microsecond=0)
    rows = {
        "delivered": (uuid4(), "HIGH", "DELIVERED", 3, None, now),
        "retryable": (
            uuid4(),
            "HIGH",
            "RETRYABLE_FAILURE",
            4,
            now + timedelta(minutes=5),
            None,
        ),
        "terminal": (uuid4(), "CRITICAL", "TERMINAL_FAILURE", 5, None, None),
        "medium": (uuid4(), "MEDIUM", "DELIVERED", 2, None, now),
    }
    with engine.begin() as connection:
        for label, (alert_id, severity, status, attempts, retry_at, delivered_at) in rows.items():
            connection.execute(
                text(
                    """
                    INSERT INTO security_alerts (
                        id, dedupe_key, rule_code, severity, correlation_digest,
                        scope, window_started_at, window_seconds, signal_count,
                        delivery_status, delivery_attempts, next_retry_at,
                        delivered_at, created_at, updated_at
                    ) VALUES (
                        :id, :dedupe_key, :rule_code, :severity, :correlation_digest,
                        :scope, :window_started_at, 900, 5,
                        :delivery_status, :delivery_attempts, :next_retry_at,
                        :delivered_at, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "id": alert_id,
                    "dedupe_key": uuid4().hex + uuid4().hex,
                    "rule_code": SecuritySignalCode.AUTH_LOGIN_FAILURE_BURST.value,
                    "severity": severity,
                    "correlation_digest": (label[0] * 64)[:64],
                    "scope": SecurityScope.AUTH_LOGIN_ACCOUNT_IP.value,
                    "window_started_at": now,
                    "delivery_status": status,
                    "delivery_attempts": attempts,
                    "next_retry_at": retry_at,
                    "delivered_at": delivered_at,
                    "created_at": now,
                    "updated_at": now,
                },
            )

    _alembic("upgrade", "head")

    with engine.begin() as connection:
        migrated = {}
        for label, (alert_id, *_rest) in rows.items():
            migrated[label] = connection.execute(
                text(
                    """
                    SELECT delivery_status, delivery_attempts, next_retry_at,
                           delivered_at, delivery_revision, delivery_attempt_token,
                           delivery_provider, delivery_error_code
                    FROM security_alerts
                    WHERE id = :id
                    """
                ),
                {"id": alert_id},
            ).mappings().one()

        for label in ("delivered", "retryable", "terminal"):
            current = migrated[label]
            assert current.delivery_status == SecurityAlertDeliveryStatus.PENDING.value
            assert current.delivery_attempts == 0
            assert current.next_retry_at is None
            assert current.delivered_at is None
            assert current.delivery_revision == 0
            assert current.delivery_attempt_token is None
            assert current.delivery_provider is None
            assert current.delivery_error_code is None

        medium = migrated["medium"]
        assert medium.delivery_status == SecurityAlertDeliveryStatus.DELIVERED.value
        assert medium.delivery_attempts == 2
        assert medium.delivered_at is not None
        assert medium.delivery_revision == 0
        assert medium.delivery_provider is None

        for alert_id, *_rest in rows.values():
            connection.execute(
                text("DELETE FROM security_alerts WHERE id = :id"),
                {"id": alert_id},
            )


class BlockingAdapter:
    provider_name = "feishu"

    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.messages: list[SecurityAlertHumanMessage] = []

    def deliver(self, message: SecurityAlertHumanMessage) -> HumanDeliveryResult:
        self.messages.append(message)
        self.started.set()
        if not self.release.wait(timeout=15):
            raise AssertionError("provider fixture was not released")
        return HumanDeliveryResult(delivered=True, retryable=False)


def _seed_alert(*, max_attempts: int = 5) -> tuple[SecurityAlert, MaintenanceJob]:
    now = datetime.now(UTC)
    alert = SecurityAlert(
        dedupe_key=uuid4().hex + uuid4().hex,
        rule_code=SecuritySignalCode.AUTH_LOGIN_FAILURE_BURST.value,
        severity=SecuritySeverity.HIGH.value,
        correlation_digest="9" * 64,
        scope=SecurityScope.AUTH_LOGIN_ACCOUNT_IP.value,
        window_started_at=now,
        window_seconds=900,
        signal_count=5,
        delivery_status=SecurityAlertDeliveryStatus.PENDING.value,
        delivery_attempts=0,
        delivery_revision=0,
        created_at=now,
        updated_at=now,
    )
    with SessionLocal() as db:
        db.add(alert)
        db.flush()
        job, created = enqueue_maintenance_job(
            db,
            job_type=MaintenanceJobType.SECURITY_ALERT_DELIVERY,
            dedupe_key=f"security-alert:{alert.id}",
            resource_key=f"security-alert:{alert.id}",
            payload={"alert_id": str(alert.id)},
            max_attempts=max_attempts,
            next_attempt_at=now,
        )
        assert created
        db.commit()
        db.refresh(alert)
        db.refresh(job)
        db.expunge(alert)
        db.expunge(job)
    return alert, job


def _cleanup(alert_id) -> None:
    with SessionLocal() as db:
        db.execute(
            delete(MaintenanceJob).where(
                MaintenanceJob.resource_key == f"security-alert:{alert_id}"
            )
        )
        db.execute(delete(SecurityAlert).where(SecurityAlert.id == alert_id))
        db.commit()


def _prove_provider_io_has_no_alert_row_transaction() -> None:
    alert, _ = _seed_alert()
    adapter = BlockingAdapter()
    original = security_alerting.get_security_alert_human_adapter
    security_alerting.get_security_alert_human_adapter = lambda: adapter
    failures: list[BaseException] = []

    with SessionLocal() as db:
        claim = claim_next_maintenance_job(
            db,
            worker_id="sec017-worker-a",
            lease_seconds=60,
        )
        assert claim is not None
        assert claim.resource_key == f"security-alert:{alert.id}"
        db.commit()

    def run() -> None:
        try:
            handle_security_alert_delivery(claim)
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=run, name="sec017-blocked-provider")
    try:
        thread.start()
        assert adapter.started.wait(timeout=15)

        # Provider I/O is in progress. A second transaction must be able to take the
        # SecurityAlert row lock immediately, proving claim transaction already committed.
        with Session(engine) as db:
            locked = db.scalar(
                select(SecurityAlert)
                .where(SecurityAlert.id == alert.id)
                .with_for_update(nowait=True)
            )
            assert locked is not None
            db.rollback()

        # OPS-002 claim authority still prevents a second worker from consuming the
        # same maintenance attempt while the first lease is live.
        with SessionLocal() as db:
            second = claim_next_maintenance_job(
                db,
                worker_id="sec017-worker-b",
                lease_seconds=60,
            )
            db.rollback()
        assert second is None

        adapter.release.set()
        thread.join(timeout=15)
        assert not thread.is_alive()
        if failures:
            raise failures[0]

        with SessionLocal() as db:
            complete_maintenance_job(
                db,
                job_id=claim.id,
                claim_token=claim.claim_token,
            )
            db.commit()

        with SessionLocal() as db:
            current = db.get(SecurityAlert, alert.id)
            assert current is not None
            assert current.delivery_status == SecurityAlertDeliveryStatus.DELIVERED.value
            assert current.delivery_attempts == 1
            assert current.delivery_attempt_token is None
        assert len(adapter.messages) == 1
        assert adapter.messages[0].alert_id == str(alert.id)
    finally:
        adapter.release.set()
        thread.join(timeout=2)
        security_alerting.get_security_alert_human_adapter = original
        _cleanup(alert.id)


def _prove_crash_reclaim_and_stale_attempt_fencing() -> None:
    alert, job = _seed_alert(max_attempts=3)
    try:
        with SessionLocal() as db:
            claim_a = claim_next_maintenance_job(
                db,
                worker_id="sec017-crash-a",
                lease_seconds=1,
            )
            assert claim_a is not None
            db.commit()

        attempt_a = begin_security_alert_delivery_attempt(
            engine,
            alert_id=alert.id,
        )
        assert attempt_a is not None

        with SessionLocal() as db:
            db.execute(
                update(MaintenanceJob)
                .where(MaintenanceJob.id == job.id)
                .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            db.commit()

        with SessionLocal() as db:
            claim_b = claim_next_maintenance_job(
                db,
                worker_id="sec017-crash-b",
                lease_seconds=60,
            )
            assert claim_b is not None
            assert claim_b.claim_token != claim_a.claim_token
            db.commit()

        attempt_b = begin_security_alert_delivery_attempt(
            engine,
            alert_id=alert.id,
        )
        assert attempt_b is not None
        assert attempt_b.revision == attempt_a.revision + 1
        assert attempt_b.token != attempt_a.token

        assert not finalize_security_alert_delivery_attempt(
            engine,
            attempt=attempt_a,
            result=HumanDeliveryResult(delivered=True, retryable=False),
        )
        assert finalize_security_alert_delivery_attempt(
            engine,
            attempt=attempt_b,
            result=HumanDeliveryResult(delivered=True, retryable=False),
        )
        with SessionLocal() as db:
            current = db.get(SecurityAlert, alert.id)
            assert current is not None
            assert current.delivery_status == SecurityAlertDeliveryStatus.DELIVERED.value
            assert current.delivery_attempts == 2
    finally:
        _cleanup(alert.id)


def _prove_exhausted_crash_terminalizes_public_alert() -> None:
    alert, job = _seed_alert(max_attempts=1)
    try:
        with SessionLocal() as db:
            claim = claim_next_maintenance_job(
                db,
                worker_id="sec017-final-crash",
                lease_seconds=1,
            )
            assert claim is not None
            db.commit()
        attempt = begin_security_alert_delivery_attempt(engine, alert_id=alert.id)
        assert attempt is not None

        with SessionLocal() as db:
            db.execute(
                update(MaintenanceJob)
                .where(MaintenanceJob.id == job.id)
                .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            db.commit()

        with SessionLocal() as db:
            assert claim_next_maintenance_job(
                db,
                worker_id="sec017-reaper",
                lease_seconds=60,
            ) is None
            db.commit()

        with SessionLocal() as db:
            maintenance = db.get(MaintenanceJob, job.id)
            current = db.get(SecurityAlert, alert.id)
            assert maintenance is not None
            assert maintenance.status == MaintenanceJobStatus.FAILED.value
            assert maintenance.last_error_code == "MAINTENANCE_ATTEMPTS_EXHAUSTED"
            assert current is not None
            assert (
                current.delivery_status
                == SecurityAlertDeliveryStatus.TERMINAL_FAILURE.value
            )
            assert current.delivery_error_code == "MAINTENANCE_ATTEMPTS_EXHAUSTED"
            assert current.delivery_attempt_token is None

        assert not finalize_security_alert_delivery_attempt(
            engine,
            attempt=attempt,
            result=HumanDeliveryResult(delivered=True, retryable=False),
        )
    finally:
        _cleanup(alert.id)


def _prove_unexpected_final_worker_failure_terminalizes_public_alert() -> None:
    alert, job = _seed_alert(max_attempts=1)
    attempts = []

    def explode(_claim) -> None:
        attempt = begin_security_alert_delivery_attempt(engine, alert_id=alert.id)
        assert attempt is not None
        attempts.append(attempt)
        raise RuntimeError("UNCLASSIFIED_PROVIDER_RUNTIME_SENTINEL")

    try:
        worker = MaintenanceWorker(
            worker_id="sec017-final-runtime-error",
            handlers={MaintenanceJobType.SECURITY_ALERT_DELIVERY.value: explode},
            lease_seconds=60,
        )
        result = worker.run_once()
        assert result.outcome == MaintenanceJobStatus.FAILED.value
        assert len(attempts) == 1
        abandoned = attempts[0]

        with SessionLocal() as db:
            maintenance = db.get(MaintenanceJob, job.id)
            current = db.get(SecurityAlert, alert.id)
            assert maintenance is not None
            assert maintenance.status == MaintenanceJobStatus.FAILED.value
            assert maintenance.last_error_code == "UNEXPECTED_MAINTENANCE_FAILURE"
            assert current is not None
            assert current.delivery_status == SecurityAlertDeliveryStatus.TERMINAL_FAILURE.value
            assert current.delivery_attempt_token is None
            assert current.next_retry_at is None
            assert current.delivery_error_code == "UNEXPECTED_MAINTENANCE_FAILURE"
            assert current.delivery_revision == abandoned.revision + 1

        assert not finalize_security_alert_delivery_attempt(
            engine,
            attempt=abandoned,
            result=HumanDeliveryResult(delivered=True, retryable=False),
        )
    finally:
        _cleanup(alert.id)


def main() -> None:
    _prove_legacy_sec015_migration_transition()
    _prove_provider_io_has_no_alert_row_transaction()
    _prove_crash_reclaim_and_stale_attempt_fencing()
    _prove_exhausted_crash_terminalizes_public_alert()
    _prove_unexpected_final_worker_failure_terminalizes_public_alert()
    print("PostgreSQL SEC-017 human security alert delivery PASS")


if __name__ == "__main__":
    main()
