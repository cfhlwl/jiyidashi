from __future__ import annotations

import argparse
import os
import socket
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from uuid import uuid4

from app.core.db import SessionLocal
from app.services.maintenance_jobs import (
    DEFAULT_LEASE_SECONDS,
    MaintenanceJobClaim,
    MaintenanceLeaseLost,
    claim_next_maintenance_job,
    complete_maintenance_job,
    fail_maintenance_job,
)


class RetryableMaintenanceError(RuntimeError):
    def __init__(self, code: str, *, retry_after_seconds: int | None = None):
        super().__init__(code)
        self.code = code
        self.retry_after_seconds = retry_after_seconds


class TerminalMaintenanceError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


MaintenanceHandler = Callable[[MaintenanceJobClaim], None]


@dataclass(frozen=True)
class MaintenanceRunResult:
    claimed: bool
    job_id: str | None = None
    job_type: str | None = None
    outcome: str | None = None


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
                db.rollback()
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
            # bounded category and let the canonical business state remain authoritative.
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
    # Phase-1 business adapters are registered explicitly as they are migrated.
    # Keeping an empty default registry makes unknown jobs fail closed instead of
    # pretending that a maintenance obligation was completed.
    return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run PostgreSQL-authoritative durable maintenance jobs.",
    )
    parser.add_argument("--once", action="store_true", help="Process at most one job.")
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=2.0,
        help="Idle polling interval for the long-running worker.",
    )
    parser.add_argument(
        "--lease-seconds",
        type=int,
        default=DEFAULT_LEASE_SECONDS,
        help="Claim lease duration. Business handlers must finish or renew before expiry.",
    )
    parser.add_argument("--worker-id", default=default_worker_id())
    args = parser.parse_args(argv)

    if args.poll_seconds < 0.1 or args.poll_seconds > 60:
        parser.error("--poll-seconds must be between 0.1 and 60")

    worker = MaintenanceWorker(
        worker_id=args.worker_id,
        handlers=default_handlers(),
        lease_seconds=args.lease_seconds,
    )
    if args.once:
        worker.run_once()
        return 0

    while True:
        result = worker.run_once()
        if not result.claimed:
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
