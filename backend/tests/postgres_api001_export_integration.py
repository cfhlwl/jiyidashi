"""Real PostgreSQL API-001 export authority gate."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import delete, inspect, select

from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.export_models import UserExportJob, UserExportStatus
from app.maintenance_job_models import MaintenanceJob, MaintenanceJobType
from app.models import Memory, MemoryType, SourceType, User
from app.services.export_service import (
    begin_export_attempt,
    generate_export_file,
    publish_export_artifact,
    remove_temp_file,
)
from app.services.maintenance_jobs import (
    ConcurrencyRejected if False else claim_next_maintenance_job,
    enqueue_maintenance_job,
)

DATABASE_URL = os.environ["DATABASE_URL"]


def _alembic(*args: str) -> None:
    subprocess.run(["alembic", *args], check=True)


def _migration_roundtrip() -> None:
    _alembic("downgrade", "0032_maintenance_jobs")
    inspector = inspect(engine)
    assert not inspector.has_table("user_export_jobs")
    _alembic("upgrade", "head")
    inspector = inspect(engine)
    assert inspector.has_table("user_export_jobs")


def _seed() -> tuple[UUID, UUID]:
    user_id = uuid4()
    export_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname="api001-postgres"))
        for index in range(5):
            db.add(
                Memory(
                    user_id=user_id,
                    memory_type=MemoryType.NOTE,
                    content=f"snapshot-{index}",
                    occurred_at=datetime.now(UTC),
                    source_type=SourceType.USER_TEXT,
                    confidence=1.0,
                    is_confirmed=True,
                )
            )
        db.add(
            UserExportJob(
                id=export_id,
                owner_user_id=user_id,
                idempotency_key=uuid4(),
            )
        )
        enqueue_maintenance_job(
            db,
            job_type=MaintenanceJobType.EXPORT,
            dedupe_key=f"export:{export_id}",
            owner_user_id=user_id,
            resource_key=f"user-export:{export_id}",
            payload={"action": "GENERATE", "export_job_id": str(export_id)},
            max_attempts=10,
        )
        db.commit()
    return user_id, export_id


def _prove_single_claim(export_id: UUID) -> None:
    with SessionLocal() as db:
        first = claim_next_maintenance_job(db, worker_id="api001-a", lease_seconds=30)
        assert first is not None
        assert first.job_type == MaintenanceJobType.EXPORT.value
        assert first.resource_key == f"user-export:{export_id}"
        db.commit()
    with SessionLocal() as db:
        second = claim_next_maintenance_job(db, worker_id="api001-b", lease_seconds=30)
        db.commit()
    assert second is None


def _prove_repeatable_read_snapshot_and_revision_fence(
    user_id: UUID,
    export_id: UUID,
) -> None:
    revision = begin_export_attempt(job_id=export_id, owner_user_id=user_id)
    assert revision is not None
    settings = get_settings().model_copy(
        update={"export_batch_size": 2, "export_artifact_max_bytes": 8 * 1024 * 1024}
    )
    inserted = False

    def authority_check() -> None:
        nonlocal inserted
        if inserted:
            return
        inserted = True
        with SessionLocal() as other:
            other.add(
                Memory(
                    user_id=user_id,
                    memory_type=MemoryType.NOTE,
                    content="late-after-snapshot",
                    occurred_at=datetime.now(UTC),
                    source_type=SourceType.USER_TEXT,
                    confidence=1.0,
                    is_confirmed=True,
                )
            )
            other.commit()

    generated = generate_export_file(
        owner_user_id=user_id,
        authority_check=authority_check,
        settings=settings,
    )
    try:
        payload = json.loads(Path(generated.path).read_text(encoding="utf-8"))
        contents = {row["content"] for row in payload["memories"]}
        assert contents == {f"snapshot-{index}" for index in range(5)}
        assert "late-after-snapshot" not in contents

        with SessionLocal() as db:
            job = db.get(UserExportJob, export_id)
            assert job is not None
            job.revision += 1
            db.commit()
        assert (
            publish_export_artifact(
                job_id=export_id,
                owner_user_id=user_id,
                revision=revision,
                object_key=f"media/_exports/{user_id}/{export_id}/stale.json",
                size_bytes=generated.size_bytes,
                sha256=generated.sha256,
                settings=settings,
            )
            is False
        )
    finally:
        remove_temp_file(generated.path)


def _cleanup(user_id: UUID) -> None:
    with SessionLocal() as db:
        db.execute(delete(MaintenanceJob).where(MaintenanceJob.owner_user_id == user_id))
        db.execute(delete(UserExportJob).where(UserExportJob.owner_user_id == user_id))
        db.execute(delete(User).where(User.id == user_id))
        db.commit()


def main() -> None:
    _migration_roundtrip()
    user_id, export_id = _seed()
    try:
        _prove_single_claim(export_id)
        _prove_repeatable_read_snapshot_and_revision_fence(user_id, export_id)
    finally:
        _cleanup(user_id)
    print("PostgreSQL API-001 export authority PASS")


if __name__ == "__main__":
    main()
