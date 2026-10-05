from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from uuid import uuid4

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.core.db import SessionLocal, engine
from app.core.observability import emit_operational_event
from app.maintenance_adapters import (
    RetryableMaintenanceError,
    TerminalMaintenanceError,
    default_maintenance_handlers,
    discover_and_enqueue_maintenance_jobs,
)
from app.maintenance_job_models import MaintenanceJobType
from app.services.maintenance_jobs import (
    DEFAULT_LEASE_SECONDS,
    MaintenanceJobClaim,
    MaintenanceLeaseLost,
    claim_next_maintenance_job,
    complete_maintenance_job,
    fail_maintenance_job,
    maintenance_job_diagnostics,
)

MaintenanceHandler = Callable[[MaintenanceJobClaim], None]


@dataclass(frozen=True)
class MaintenanceRunResult:
    claimed: bool
    job_id: str | None = None
    job_type: str | None = None
    outcome: str | None = None


def assert_worker_schema_current() -> str:
    config = Config("alembic.ini")
    expected = ScriptDirectory.from_config(config).get_current_head()
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    if current != expected:
        raise RuntimeError("MAINTENANCE_SCHEMA_NOT_CURRENT")
    return str(current)


def worker_health_snapshot() -> dict[str, object]:
    revision = assert_worker_schema_current()
    with SessionLocal() as db:
        diagnostics = maintenance_job_diagnostics(db)
        db.rollback()
    return {
        "status": "ready",
        "schema": "current",
        "revision": revision,
        "queue": diagnostics,
    }


class MaintenanceWorker:
    def __init__(
        self,
        *,
        worker_id: str,
        handlers: Mapping[str, MaintenanceHandler],
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ):
        normalized_worker = worker_id.strip()
        if not normalized_worker:
            raise ValueError("worker_id is required")
        self.worker_id = normalized_worker
        self.handlers = dict(handlers)
        self.lease_seconds = lease_seconds

    def run_once(self) -> MaintenanceRunResult:
        with SessionLocal() as db:
            claim = claim_next_maintenance_job(
                db,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
            )
            if claim is None:
                # Claim performs durable housekeeping such as terminalizing a crashed
                # final attempt. Empty-queue callers must commit that maintenance.
                db.commit()
                return MaintenanceRunResult(claimed=False)
            db.commit()

        handler = self.handlers.get(claim.job_type)
        if handler is None:
            with SessionLocal() as db:
                try:
                    fail_maintenance_job(
                        db,
                        job_id=claim.id,
                        claim_token=claim.claim_token,
                        error_code="UNSUPPORTED_MAINTENANCE_JOB_TYPE",
                        terminal=True,
                    )
                    db.commit()
                except MaintenanceLeaseLost:
                    db.rollback()
            return MaintenanceRunResult(
                claimed=True,
                job_id=str(claim.id),
                job_type=claim.job_type,
                outcome="FAILED",
            )

        try:
            handler(claim)
        except TerminalMaintenanceError as exc:
            with SessionLocal() as db:
                try:
                    fail_maintenance_job(
                        db,
                        job_id=claim.id,
                        claim_token=claim.claim_token,
                        error_code=exc.code,
                        terminal=True,
                    )
                    db.commit()
                except MaintenanceLeaseLost:
                    db.rollback()
                    return MaintenanceRunResult(
                        claimed=True,
                        job_id=str(claim.id),
                        job_type=claim.job_type,
                        outcome="LEASE_LOST",
                    )
            return MaintenanceRunResult(
                claimed=True,
                job_id=str(claim.id),
                job_type=claim.job_type,
                outcome="FAILED",
            )
        except RetryableMaintenanceError as exc:
            with SessionLocal() as db:
                try:
                    fail_maintenance_job(
                        db,
                        job_id=claim.id,
                        claim_token=claim.claim_token,
                        error_code=exc.code,
                        retry_after_seconds=exc.retry_after_seconds,
                    )
                    db.commit()
                except MaintenanceLeaseLost:
                    db.rollback()
                    return MaintenanceRunResult(
                        claimed=True,
                        job_id=str(claim.id),
                        job_type=claim.job_type,
                        outcome="LEASE_LOST",
                    )
            return MaintenanceRunResult(
                claimed=True,
                job_id=str(claim.id),
                job_type=claim.job_type,
                outcome="RETRY_WAIT",
            )
        except Exception:
            # Raw exception text may contain provider/user content. Persist only a
            # bounded category; canonical business state remains the source of truth.
            with SessionLocal() as db:
                try:
                    fail_maintenance_job(
                        db,
                        job_id=claim.id,
                        claim_token=claim.claim_token,
                        error_code="UNEXPECTED_MAINTENANCE_FAILURE",
                    )
                    db.commit()
                except MaintenanceLeaseLost:
                    db.rollback()
                    return MaintenanceRunResult(
                        claimed=True,
                        job_id=str(claim.id),
                        job_type=claim.job_type,
                        outcome="LEASE_LOST",
                    )
            return MaintenanceRunResult(
                claimed=True,
                job_id=str(claim.id),
                job_type=claim.job_type,
                outcome="RETRY_WAIT",
            )

        with SessionLocal() as db:
            try:
                complete_maintenance_job(
                    db,
                    job_id=claim.id,
                    claim_token=claim.claim_token,
                    scrub_identity=(
                        claim.job_type == MaintenanceJobType.ACCOUNT_DELETE.value
                    ),
                )
                db.commit()
            except MaintenanceLeaseLost:
                db.rollback()
                return MaintenanceRunResult(
                    claimed=True,
                    job_id=str(claim.id),
                    job_type=claim.job_type,
                    outcome="LEASE_LOST",
                )
        return MaintenanceRunResult(
            claimed=True,
            job_id=str(claim.id),
            job_type=claim.job_type,
            outcome="SUCCEEDED",
        )


def default_worker_id() -> str:
    suffix = uuid4().hex[:12]
    return f"{socket.gethostname()}:{os.getpid()}:{suffix}"[:120]


def default_handlers() -> dict[str, MaintenanceHandler]:
    return default_maintenance_handlers()


def _install_signal_handlers(stop_event: threading.Event) -> None:
    def request_stop(signum, _frame) -> None:
        emit_operational_event(
            event="maintenance.worker.stop_requested",
            signal=int(signum),
        )
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run PostgreSQL-authoritative durable maintenance jobs.",
    )
    parser.add_argument("--once", action="store_true", help="Process at most one job.")
    parser.add_argument(
        "--health",
        action="store_true",
        help="Validate schema/database and print bounded queue diagnostics.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=2.0,
        help="Idle polling interval for the long-running worker.",
    )
    parser.add_argument(
        "--schedule-seconds",
        type=float,
        default=15.0,
        help="Interval for bounded discovery/enqueue scans.",
    )
    parser.add_argument(
        "--lease-seconds",
        type=int,
        default=DEFAULT_LEASE_SECONDS,
        help="Claim lease duration; handlers renew around external/commit boundaries.",
    )
    parser.add_argument("--worker-id", default=default_worker_id())
    args = parser.parse_args(argv)

    if args.poll_seconds < 0.1 or args.poll_seconds > 60:
        parser.error("--poll-seconds must be between 0.1 and 60")
    if args.schedule_seconds < 1 or args.schedule_seconds > 300:
        parser.error("--schedule-seconds must be between 1 and 300")

    if args.health:
        print(json.dumps(worker_health_snapshot(), sort_keys=True))
        return 0

    assert_worker_schema_current()
    worker = MaintenanceWorker(
        worker_id=args.worker_id,
        handlers=default_handlers(),
        lease_seconds=args.lease_seconds,
    )

    if args.once:
        discover_and_enqueue_maintenance_jobs()
        worker.run_once()
        return 0

    stop_event = threading.Event()
    _install_signal_handlers(stop_event)
    last_schedule = 0.0

    while not stop_event.is_set():
        monotonic_now = time.monotonic()
        if monotonic_now - last_schedule >= args.schedule_seconds:
            try:
                result = discover_and_enqueue_maintenance_jobs()
                emit_operational_event(
                    event="maintenance.scheduler.completed",
                    enqueued=result.enqueued,
                    existing=result.existing,
                )
            except Exception:
                emit_operational_event(
                    event="maintenance.scheduler.failed",
                    level="ERROR",
                    error_code="MAINTENANCE_SCHEDULER_FAILED",
                )
            last_schedule = monotonic_now

        try:
            result = worker.run_once()
        except Exception:
            emit_operational_event(
                event="maintenance.worker.iteration_failed",
                level="ERROR",
                error_code="MAINTENANCE_WORKER_ITERATION_FAILED",
            )
            stop_event.wait(args.poll_seconds)
            continue

        if not result.claimed:
            stop_event.wait(args.poll_seconds)

    emit_operational_event(event="maintenance.worker.stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
