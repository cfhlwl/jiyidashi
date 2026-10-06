"""Real PostgreSQL API-001 export authority gate."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import delete, func, inspect, select
from sqlalchemy.exc import IntegrityError

from app import maintenance_adapters
from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.data_deletion_models import DataDeletionOperation
from app.export_models import UserExportJob
from app.maintenance_adapters import handle_export
from app.maintenance_job_models import MaintenanceJob, MaintenanceJobType
from app.models import Memory, MemoryType, ObjectItem, SourceType, User
from app.services.data_deletion_service import delete_all_user_data
from app.services.export_service import (
    begin_export_attempt,
    generate_export_file,
    publish_export_artifact,
    remove_temp_file,
)
from app.services.maintenance_jobs import (
    MaintenanceLeaseLost,
    claim_next_maintenance_job,
    enqueue_maintenance_job,
)
from app.services.object_storage import StoredObject

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

    # API-001 legacy-owner migration must fail closed instead of silently truncating.
    _alembic("downgrade", "0033_api001_export_jobs")
    over_limit_user = uuid4()
    with SessionLocal() as db:
        db.add(User(id=over_limit_user, nickname="api001-over-limit-migration"))
        db.flush()
        db.add_all(
            ObjectItem(
                user_id=over_limit_user,
                name=f"legacy-over-{index:03d}",
                normalized_name=f"legacy-over-{index:03d}",
            )
            for index in range(501)
        )
        db.commit()

    failed = subprocess.run(
        ["alembic", "upgrade", "head"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert failed.returncode != 0
    assert "OBJECT_OWNER_CAPACITY_EXISTING_DATA_EXCEEDED" in (
        failed.stdout + failed.stderr
    )

    with SessionLocal() as db:
        db.execute(delete(User).where(User.id == over_limit_user))
        db.commit()
    _alembic("upgrade", "head")


def _seed() -> tuple[UUID, UUID]:
    user_id = uuid4()
    export_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname="api001-postgres"))
        db.flush()
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




class BlockingExportStorage:
    def __init__(self):
        self.objects: set[str] = set()
        self.upload_started = threading.Event()
        self.release_upload = threading.Event()

    def upload_file(self, local_path, object_key, content_type, sha256):
        self.upload_started.set()
        if not self.release_upload.wait(timeout=15):
            raise AssertionError("blocked export upload was not released")
        size = Path(local_path).stat().st_size
        self.objects.add(object_key)
        return StoredObject(
            size_bytes=size,
            content_type=content_type,
            etag="api001-race",
            sha256=sha256,
        )

    def iter_object_keys(self, prefix):
        yield from sorted(key for key in self.objects if key.startswith(prefix))

    def delete_object(self, object_key):
        self.objects.discard(object_key)


def _prove_export_delete_handoff_serializes_upload() -> None:
    user_id = uuid4()
    export_id = uuid4()
    request_id = uuid4()
    storage = BlockingExportStorage()

    with SessionLocal() as db:
        db.add(User(id=user_id, nickname="api001-delete-race"))
        db.flush()
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
            max_attempts=3,
        )
        db.commit()

    with SessionLocal() as db:
        claim = claim_next_maintenance_job(
            db,
            worker_id="api001-delete-race-export",
            lease_seconds=2,
        )
        assert claim is not None
        db.commit()

    original_storage = maintenance_adapters.get_object_storage
    maintenance_adapters.get_object_storage = lambda: storage
    export_errors: list[BaseException] = []
    delete_errors: list[BaseException] = []
    delete_results = []
    delete_done = threading.Event()

    def run_export() -> None:
        try:
            handle_export(claim)
        except BaseException as exc:
            export_errors.append(exc)

    def run_delete() -> None:
        try:
            with SessionLocal() as deleting:
                delete_results.append(
                    delete_all_user_data(
                        deleting,
                        user_id=user_id,
                        request_id=request_id,
                        storage=storage,
                    )
                )
        except BaseException as exc:
            delete_errors.append(exc)
        finally:
            delete_done.set()

    export_thread = threading.Thread(target=run_export, name="api001-export-upload")
    delete_thread = threading.Thread(target=run_delete, name="api001-data-delete")
    try:
        export_thread.start()
        assert storage.upload_started.wait(timeout=15)
        delete_thread.start()

        # The destructive gate must not commit while the export owns the shared handoff.
        assert not delete_done.wait(timeout=0.4)

        storage.release_upload.set()
        export_thread.join(timeout=15)
        delete_thread.join(timeout=15)
        assert not export_thread.is_alive()
        assert not delete_thread.is_alive()
        if export_errors:
            raise export_errors[0]
        if delete_errors:
            raise delete_errors[0]
        assert delete_results
        assert not storage.objects

        # Export presence restarts the storage quiet window. Advance only the durable
        # test fixture deadline, then converge the canonical Data Delete state machine.
        with SessionLocal() as db:
            operation = db.scalar(
                select(DataDeletionOperation).where(
                    DataDeletionOperation.user_id == user_id,
                    DataDeletionOperation.request_id == request_id,
                )
            )
            assert operation is not None
            operation.storage_quiet_until = datetime.now(UTC) - timedelta(seconds=1)
            operation.storage_capability_expires_at = None
            db.commit()

        with SessionLocal() as db:
            result = delete_all_user_data(
                db,
                user_id=user_id,
                request_id=request_id,
                storage=storage,
            )
            assert result.completed is True

        with SessionLocal() as db:
            assert db.get(UserExportJob, export_id) is None
            assert not list(
                db.scalars(
                    select(UserExportJob).where(
                        UserExportJob.owner_user_id == user_id
                    )
                )
            )
            db.rollback()
        assert not storage.objects

        try:
            handle_export(claim)
            raise AssertionError("stale export claim rebuilt after Data Delete")
        except MaintenanceLeaseLost:
            pass
    finally:
        storage.release_upload.set()
        export_thread.join(timeout=2)
        delete_thread.join(timeout=2)
        maintenance_adapters.get_object_storage = original_storage
        with SessionLocal() as db:
            db.execute(
                delete(MaintenanceJob).where(
                    MaintenanceJob.id == claim.id
                )
            )
            db.execute(delete(User).where(User.id == user_id))
            db.commit()



def _prove_object_owner_capacity_trigger_serializes_concurrent_inserts() -> None:
    user_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname="api001-object-capacity"))
        db.flush()
        db.add_all(
            ObjectItem(
                user_id=user_id,
                name=f"capacity-{index:03d}",
                normalized_name=f"capacity-{index:03d}",
            )
            for index in range(499)
        )
        db.commit()

    start = threading.Barrier(2)
    successes: list[str] = []
    rejected: list[str] = []
    errors: list[BaseException] = []

    def insert_one(name: str) -> None:
        try:
            with SessionLocal() as db:
                db.add(
                    ObjectItem(
                        user_id=user_id,
                        name=name,
                        normalized_name=name,
                    )
                )
                start.wait(timeout=15)
                try:
                    db.commit()
                    successes.append(name)
                except IntegrityError as exc:
                    db.rollback()
                    assert "OBJECT_OWNER_CAPACITY_EXCEEDED" in str(exc.orig)
                    rejected.append(name)
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=insert_one, args=("capacity-race-a",))
    second = threading.Thread(target=insert_one, args=("capacity-race-b",))
    first.start()
    second.start()
    first.join(timeout=20)
    second.join(timeout=20)
    assert not first.is_alive()
    assert not second.is_alive()
    if errors:
        raise errors[0]

    assert len(successes) == 1
    assert len(rejected) == 1
    with SessionLocal() as db:
        count = int(
            db.scalar(
                select(func.count(ObjectItem.id)).where(
                    ObjectItem.user_id == user_id
                )
            )
            or 0
        )
        assert count == 500
        db.execute(delete(User).where(User.id == user_id))
        db.commit()

def main() -> None:
    _migration_roundtrip()
    _prove_object_owner_capacity_trigger_serializes_concurrent_inserts()
    user_id, export_id = _seed()
    try:
        _prove_single_claim(export_id)
        _prove_repeatable_read_snapshot_and_revision_fence(user_id, export_id)
        _prove_export_delete_handoff_serializes_upload()
    finally:
        _cleanup(user_id)
    print("PostgreSQL API-001 export authority PASS")


if __name__ == "__main__":
    main()
