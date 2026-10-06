from __future__ import annotations

import hashlib
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from app.core.db import SessionLocal
from app.export_models import UserExportJob, UserExportStatus
from app.main import app
from app.maintenance_adapters import (
    RetryableMaintenanceError,
    handle_export,
)
from app.maintenance_job_models import (
    MaintenanceJob,
    MaintenanceJobStatus,
    MaintenanceJobType,
)
from app.maintenance_worker import MaintenanceWorker
from app.media_models import MediaAsset, MediaKind, MediaStatus
from app.models import Memory, MemoryType, ObjectItem, SourceType
from app.services.maintenance_jobs import (
    claim_next_maintenance_job,
    complete_maintenance_job,
    enqueue_maintenance_job,
)
from app.services.object_storage import PresignedTransfer, StoredObject, get_object_storage


class FakeExportStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.meta: dict[str, tuple[str, str]] = {}

    def upload_file(self, local_path, object_key, content_type, sha256):
        data = Path(local_path).read_bytes()
        self.objects[object_key] = data
        self.meta[object_key] = (content_type, sha256)
        return StoredObject(len(data), content_type, "fixture", sha256)

    def stat_object(self, object_key):
        data = self.objects[object_key]
        content_type, sha256 = self.meta[object_key]
        return StoredObject(len(data), content_type, "fixture", sha256)

    def sign_download(self, object_key):
        assert object_key in self.objects
        return PresignedTransfer(
            url=f"https://download.example.invalid/{uuid4()}",
            method="GET",
            headers={},
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )

    def iter_object_keys(self, prefix):
        yield from sorted(key for key in self.objects if key.startswith(prefix))

    def delete_object(self, object_key):
        self.objects.pop(object_key, None)
        self.meta.pop(object_key, None)


async def _new_user(client, nickname: str) -> tuple[dict[str, str], UUID]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, UUID(body["user_id"])


@pytest.mark.asyncio
async def test_legacy_export_is_bounded_migration_response(client, auth_headers):
    response = await client.get("/v1/export/data", headers=auth_headers)
    assert response.status_code == 410
    assert response.json() == {
        "detail": "EXPORT_ASYNC_REQUIRED",
        "create_path": "/v1/export/jobs",
    }
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_export_job_requires_authentication_and_idempotency_key(client):
    key = str(uuid4())
    response = await client.post(
        "/v1/export/jobs",
        headers={"Idempotency-Key": key},
    )
    assert response.status_code in {401, 403}
    headers, _ = await _new_user(client, "export-idempotency")
    assert (await client.post("/v1/export/jobs", headers=headers)).status_code == 422


@pytest.mark.asyncio
async def test_export_create_retry_and_cross_owner_status_are_safe(client):
    headers_a, _ = await _new_user(client, "export-a")
    headers_b, _ = await _new_user(client, "export-b")
    key = str(uuid4())
    request_headers = {**headers_a, "Idempotency-Key": key}
    first = await client.post("/v1/export/jobs", headers=request_headers)
    second = await client.post("/v1/export/jobs", headers=request_headers)
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    job_id = UUID(first.json()["id"])
    assert "artifact_object_key" not in first.json()
    assert first.headers["cache-control"] == "no-store"

    assert (
        await client.get(f"/v1/export/jobs/{job_id}", headers=headers_b)
    ).status_code == 404
    assert (
        await client.get(f"/v1/export/jobs/{job_id}/download", headers=headers_b)
    ).status_code == 404

    with SessionLocal() as db:
        jobs = list(
            db.scalars(
                select(MaintenanceJob).where(
                    MaintenanceJob.job_type == MaintenanceJobType.EXPORT.value
                )
            )
        )
        assert sum(job.resource_key == f"user-export:{job_id}" for job in jobs) == 1


@pytest.mark.asyncio
async def test_worker_builds_private_verified_export_and_signed_download(client, monkeypatch):
    with SessionLocal() as db:
        db.execute(delete(MaintenanceJob))
        db.commit()
    headers, user_id = await _new_user(client, "export-worker")
    storage = FakeExportStorage()
    now = datetime.now(UTC)
    with SessionLocal() as db:
        db.add(
            Memory(
                user_id=user_id,
                memory_type=MemoryType.NOTE,
                content="portable-memory",
                occurred_at=now,
                source_type=SourceType.USER_TEXT,
                confidence=1.0,
                is_confirmed=True,
            )
        )
        db.add(ObjectItem(user_id=user_id, name="护照", normalized_name="护照"))
        db.add(
            MediaAsset(
                user_id=user_id,
                client_upload_id=uuid4(),
                kind=MediaKind.IMAGE,
                status=MediaStatus.READY,
                upload_object_key=f"media/_staging/{user_id}/secret-upload",
                object_key=f"media/{user_id}/secret-final",
                content_type="image/jpeg",
                size_bytes=123,
                original_filename="photo.jpg",
                storage_etag="secret-etag",
                completed_at=now,
            )
        )
        db.commit()

    created = await client.post(
        "/v1/export/jobs",
        headers={**headers, "Idempotency-Key": str(uuid4())},
    )
    assert created.status_code == 202
    job_id = UUID(created.json()["id"])
    monkeypatch.setattr("app.maintenance_adapters.get_object_storage", lambda: storage)

    with SessionLocal() as db:
        claim = claim_next_maintenance_job(
            db,
            worker_id="api001-export-worker",
            lease_seconds=60,
        )
        assert claim is not None
        assert claim.job_type == MaintenanceJobType.EXPORT.value
        db.commit()
    handle_export(claim)

    with SessionLocal() as db:
        job = db.get(UserExportJob, job_id)
        assert job is not None
        assert job.status == UserExportStatus.COMPLETED.value
        artifact = storage.objects[job.artifact_object_key]
        assert len(artifact) == job.artifact_size_bytes
        assert hashlib.sha256(artifact).hexdigest() == job.artifact_sha256

    decoded = artifact.decode()
    for expected in ("portable-memory", "护照"):
        assert expected in decoded
    for forbidden in ("secret-upload", "secret-final", "secret-etag"):
        assert forbidden not in decoded

    app.dependency_overrides[get_object_storage] = lambda: storage
    try:
        status_response = await client.get(f"/v1/export/jobs/{job_id}", headers=headers)
        assert status_response.status_code == 200
        assert status_response.headers["cache-control"] == "no-store"
        download = await client.get(
            f"/v1/export/jobs/{job_id}/download",
            headers=headers,
        )
        assert download.status_code == 200
        assert download.json()["artifact_sha256"] == hashlib.sha256(artifact).hexdigest()
        assert download.headers["cache-control"] == "no-store"
    finally:
        app.dependency_overrides.pop(get_object_storage, None)


@pytest.mark.asyncio
async def test_expired_export_download_fails_closed(client):
    headers, user_id = await _new_user(client, "export-expired")
    job_id = uuid4()
    with SessionLocal() as db:
        db.add(
            UserExportJob(
                id=job_id,
                owner_user_id=user_id,
                idempotency_key=uuid4(),
                status=UserExportStatus.COMPLETED.value,
                artifact_object_key=f"media/_exports/{user_id}/{job_id}/artifact.json",
                artifact_size_bytes=10,
                artifact_sha256="a" * 64,
                completed_at=datetime.now(UTC) - timedelta(hours=2),
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
        db.commit()
    response = await client.get(f"/v1/export/jobs/{job_id}/download", headers=headers)
    assert response.status_code == 410
    assert response.json()["detail"] == "EXPORT_EXPIRED"


class BlockingExportStorage(FakeExportStorage):
    def __init__(self):
        super().__init__()
        self.upload_started = threading.Event()
        self.release_upload = threading.Event()
        self.upload_calls = 0

    def upload_file(self, local_path, object_key, content_type, sha256):
        self.upload_calls += 1
        self.upload_started.set()
        assert self.release_upload.wait(timeout=10)
        return super().upload_file(local_path, object_key, content_type, sha256)


def _seed_export_execution(*, max_attempts: int = 10):
    user_id = uuid4()
    export_id = uuid4()
    with SessionLocal() as db:
        db.add(UserExportJob(
            id=export_id,
            owner_user_id=user_id,
            idempotency_key=uuid4(),
        ))
        from app.models import User
        db.add(User(id=user_id, nickname=f"export-lifecycle-{uuid4().hex[:8]}"))
        db.flush()
        job, created = enqueue_maintenance_job(
            db,
            job_type=MaintenanceJobType.EXPORT,
            dedupe_key=f"export:{export_id}",
            owner_user_id=user_id,
            resource_key=f"user-export:{export_id}",
            payload={"action": "GENERATE", "export_job_id": str(export_id)},
            max_attempts=max_attempts,
        )
        assert created
        maintenance_id = job.id
        db.commit()
    return user_id, export_id, maintenance_id


def test_export_upload_heartbeats_short_lease_and_blocks_reclaim(monkeypatch):
    with SessionLocal() as db:
        db.execute(delete(MaintenanceJob))
        db.commit()

    user_id = uuid4()
    export_id = uuid4()
    from app.models import User
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname="export-heartbeat"))
        db.flush()
        db.add(UserExportJob(
            id=export_id,
            owner_user_id=user_id,
            idempotency_key=uuid4(),
        ))
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

    storage = BlockingExportStorage()
    monkeypatch.setattr("app.maintenance_adapters.get_object_storage", lambda: storage)

    with SessionLocal() as db:
        claim = claim_next_maintenance_job(
            db,
            worker_id="heartbeat-worker-a",
            lease_seconds=1,
        )
        assert claim is not None
        db.commit()

    failures: list[BaseException] = []

    def run_handler():
        try:
            handle_export(claim)
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=run_handler)
    thread.start()
    assert storage.upload_started.wait(timeout=10)
    time.sleep(1.3)

    with SessionLocal() as db:
        second = claim_next_maintenance_job(
            db,
            worker_id="heartbeat-worker-b",
            lease_seconds=1,
        )
        db.rollback()
    assert second is None

    storage.release_upload.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert failures == []
    assert storage.upload_calls == 1

    with SessionLocal() as db:
        complete_maintenance_job(
            db,
            job_id=claim.id,
            claim_token=claim.claim_token,
        )
        export = db.get(UserExportJob, export_id)
        assert export is not None
        assert export.status == UserExportStatus.COMPLETED.value
        maintenance = db.get(MaintenanceJob, claim.id)
        assert maintenance is not None
        db.commit()


def test_export_oserror_terminalizes_public_job_on_final_attempt(monkeypatch):
    with SessionLocal() as db:
        db.execute(delete(MaintenanceJob))
        db.commit()

    user_id = uuid4()
    export_id = uuid4()
    from app.models import User
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname="export-enospc"))
        db.flush()
        db.add(UserExportJob(
            id=export_id,
            owner_user_id=user_id,
            idempotency_key=uuid4(),
        ))
        enqueue_maintenance_job(
            db,
            job_type=MaintenanceJobType.EXPORT,
            dedupe_key=f"export:{export_id}",
            owner_user_id=user_id,
            resource_key=f"user-export:{export_id}",
            payload={"action": "GENERATE", "export_job_id": str(export_id)},
            max_attempts=1,
        )
        db.commit()

    monkeypatch.setattr(
        "app.maintenance_adapters.generate_export_file",
        lambda **_: (_ for _ in ()).throw(OSError(28, "No space left on device")),
    )
    worker = MaintenanceWorker(
        worker_id="export-enospc-worker",
        handlers={MaintenanceJobType.EXPORT.value: handle_export},
        lease_seconds=5,
    )
    result = worker.run_once()
    assert result.outcome == "FAILED"

    with SessionLocal() as db:
        export = db.get(UserExportJob, export_id)
        assert export is not None
        assert export.status == UserExportStatus.FAILED.value
        assert export.error_code == "EXPORT_LOCAL_IO_FAILED"
        maintenance = db.scalar(
            select(MaintenanceJob).where(
                MaintenanceJob.resource_key == f"user-export:{export_id}"
            )
        )
        assert maintenance is not None
        assert maintenance.status == MaintenanceJobStatus.FAILED.value


def test_export_final_crashed_lease_exhaustion_converges_public_job():
    with SessionLocal() as db:
        db.execute(delete(MaintenanceJob))
        db.commit()

    user_id = uuid4()
    export_id = uuid4()
    from app.models import User
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname="export-crash-final"))
        db.flush()
        db.add(UserExportJob(
            id=export_id,
            owner_user_id=user_id,
            idempotency_key=uuid4(),
            status=UserExportStatus.RUNNING.value,
            revision=1,
        ))
        enqueue_maintenance_job(
            db,
            job_type=MaintenanceJobType.EXPORT,
            dedupe_key=f"export:{export_id}",
            owner_user_id=user_id,
            resource_key=f"user-export:{export_id}",
            payload={"action": "GENERATE", "export_job_id": str(export_id)},
            max_attempts=1,
        )
        db.commit()

    with SessionLocal() as db:
        claim = claim_next_maintenance_job(
            db,
            worker_id="export-crashed-worker",
            lease_seconds=1,
        )
        assert claim is not None
        maintenance_id = claim.id
        job = db.get(MaintenanceJob, maintenance_id)
        assert job is not None
        job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    with SessionLocal() as db:
        assert claim_next_maintenance_job(
            db,
            worker_id="export-reaper",
            lease_seconds=1,
        ) is None
        db.commit()

    with SessionLocal() as db:
        maintenance = db.get(MaintenanceJob, maintenance_id)
        export = db.get(UserExportJob, export_id)
        assert maintenance is not None
        assert maintenance.status == MaintenanceJobStatus.FAILED.value
        assert maintenance.last_error_code == "MAINTENANCE_ATTEMPTS_EXHAUSTED"
        assert export is not None
        assert export.status == UserExportStatus.FAILED.value
        assert export.error_code == "MAINTENANCE_ATTEMPTS_EXHAUSTED"
