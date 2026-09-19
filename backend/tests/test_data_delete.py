from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.auth_models import AuthIdentity, AuthProvider
from app.core.config import Settings
from app.core.db import SessionLocal
from app.data_deletion_models import (
    DataDeletionObject,
    DataDeletionOperation,
    DataDeletionStatus,
)
from app.idempotency_models import ClientMutation
from app.main import app
from app.media_models import (
    MediaASRClaim,
    MediaAsset,
    MediaEvidenceLink,
    MediaKind,
    MediaStatus,
)
from app.models import (
    Device,
    FamilyMember,
    FamilyPermission,
    LocationDerivationState,
    LocationIngestReceipt,
    LocationPoint,
    Memory,
    MemoryEdit,
    MemorySource,
    ObjectItem,
    ObjectLocation,
    Place,
    PrivacyPauseInterval,
    PrivacyState,
    Reminder,
    User,
    Visit,
)
from app.services import data_deletion_service
from app.services.object_storage import (
    ObjectStorageError,
    S3ObjectStorage,
    get_object_storage,
)


class DeleteTestStorage:
    """Small storage double with LIST, idempotent DELETE and injected failures."""

    def __init__(self) -> None:
        self.objects: set[str] = set()
        self.fail_once: set[str] = set()
        self.delete_calls: dict[str, int] = {}

    def iter_object_keys(self, prefix: str) -> Iterator[str]:
        yield from sorted(key for key in self.objects if key.startswith(prefix))

    def delete_object(self, object_key: str) -> None:
        self.delete_calls[object_key] = self.delete_calls.get(object_key, 0) + 1
        if object_key in self.fail_once:
            self.fail_once.remove(object_key)
            raise ObjectStorageError("synthetic delete failure")
        self.objects.discard(object_key)


@pytest.fixture
def delete_storage():
    storage = DeleteTestStorage()
    app.dependency_overrides[get_object_storage] = lambda: storage
    yield storage
    app.dependency_overrides.pop(get_object_storage, None)


async def _new_user(client, nickname: str) -> tuple[dict[str, str], UUID]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    payload = response.json()
    return (
        {"Authorization": f"Bearer {payload['access_token']}"},
        UUID(payload["user_id"]),
    )


def _count_for_user(db, model, user_id: UUID) -> int:
    return int(
        db.scalar(
            select(func.count()).select_from(model).where(model.user_id == user_id)
        )
        or 0
    )


def _seed_full_owned_graph(owner_id: UUID, other_id: UUID) -> dict[str, UUID | str]:
    now = datetime.now(UTC)
    ids = {
        "device": uuid4(),
        "place": uuid4(),
        "memory": uuid4(),
        "memory_edit": uuid4(),
        "source": uuid4(),
        "location_point": uuid4(),
        "visit": uuid4(),
        "object": uuid4(),
        "object_location": uuid4(),
        "reminder": uuid4(),
        "pause": uuid4(),
        "media": uuid4(),
        "media_link": uuid4(),
        "family_member": uuid4(),
        "family_permission": uuid4(),
        "mutation": uuid4(),
    }
    upload_key = f"media/_staging/{owner_id}/{ids['media'].hex}/ticket"
    final_key = f"media/{owner_id}/{ids['media'].hex}"

    with SessionLocal() as db:
        db.add(
            AuthIdentity(
                user_id=owner_id,
                provider=AuthProvider.EMAIL_PASSWORD,
                subject=f"delete-{uuid4()}@example.test",
                secret_hash="kept-for-account-delete",
            )
        )
        db.add(
            Device(
                id=ids["device"],
                user_id=owner_id,
                client_uuid=str(uuid4()),
                platform="test",
                push_token="private-push-token",
            )
        )
        db.add(
            Place(
                id=ids["place"],
                user_id=owner_id,
                name="私密地点",
                address="private address",
            )
        )
        db.add(
            Memory(
                id=ids["memory"],
                user_id=owner_id,
                title="待删除记忆",
                content="private memory",
                place_id=ids["place"],
            )
        )
        db.add(
            MemorySource(
                id=ids["source"],
                memory_id=ids["memory"],
                source_type="USER_TEXT",
                raw_text="private evidence",
            )
        )
        db.add(
            MemoryEdit(
                id=ids["memory_edit"],
                memory_id=ids["memory"],
                user_id=owner_id,
                revision=1,
                previous_title="旧标题",
                previous_content="old private memory",
                new_title="待删除记忆",
                new_content="private memory",
                changed_title=True,
                changed_content=True,
                memory_source_id=ids["source"],
            )
        )
        db.add(
            LocationDerivationState(
                user_id=owner_id,
                finalized_through=now - timedelta(hours=1),
            )
        )
        db.add(
            LocationIngestReceipt(
                user_id=owner_id,
                client_uuid="delete-receipt",
                payload_hash="a" * 64,
                recorded_at=now,
            )
        )
        db.add(
            LocationPoint(
                id=ids["location_point"],
                user_id=owner_id,
                device_id=ids["device"],
                client_uuid=str(uuid4()),
                latitude=1.25,
                longitude=103.82,
                recorded_at=now,
            )
        )
        db.add(
            Visit(
                id=ids["visit"],
                user_id=owner_id,
                place_id=ids["place"],
                arrived_at=now,
            )
        )
        db.add(
            ObjectItem(
                id=ids["object"],
                user_id=owner_id,
                name="护照",
                normalized_name=f"passport-{uuid4()}",
            )
        )
        db.add(
            ObjectLocation(
                id=ids["object_location"],
                object_id=ids["object"],
                user_id=owner_id,
                memory_id=ids["memory"],
                location_text="保险箱",
                place_id=ids["place"],
            )
        )
        db.add(
            Reminder(
                id=ids["reminder"],
                user_id=owner_id,
                memory_id=ids["memory"],
                title="私人提醒",
                remind_at=now + timedelta(hours=1),
            )
        )
        db.add(
            PrivacyState(
                user_id=owner_id,
                recording_paused_since=now,
                recording_paused_until=now + timedelta(minutes=30),
            )
        )
        db.add(
            PrivacyPauseInterval(
                id=ids["pause"],
                user_id=owner_id,
                started_at=now,
                ended_at=now + timedelta(minutes=30),
            )
        )
        db.add(
            MediaAsset(
                id=ids["media"],
                user_id=owner_id,
                client_upload_id=uuid4(),
                kind=MediaKind.AUDIO,
                status=MediaStatus.READY,
                upload_object_key=upload_key,
                object_key=final_key,
                content_type="audio/mp4",
                size_bytes=8,
            )
        )
        db.add(
            MediaASRClaim(
                media_id=ids["media"],
                claim_token=uuid4(),
                lease_expires_at=now + timedelta(minutes=5),
            )
        )
        db.add(
            MediaEvidenceLink(
                id=ids["media_link"],
                media_id=ids["media"],
                memory_source_id=ids["source"],
            )
        )
        db.add(
            FamilyMember(
                id=ids["family_member"],
                owner_user_id=other_id,
                member_user_id=owner_id,
            )
        )
        db.add(
            FamilyPermission(
                id=ids["family_permission"],
                owner_user_id=other_id,
                member_user_id=owner_id,
                permission="MEMORY_READ",
                enabled=True,
            )
        )
        db.add(
            ClientMutation(
                id=ids["mutation"],
                user_id=owner_id,
                operation_type="memory.create",
                client_uuid=uuid4(),
                request_fingerprint="a" * 64,
                resource_type="memory",
                resource_id=ids["memory"],
            )
        )

        other_memory = Memory(
            user_id=other_id,
            title="另一用户",
            content="must survive",
        )
        db.add(other_memory)
        db.flush()
        ids["other_memory"] = other_memory.id
        other_memory_edit = MemoryEdit(
            memory_id=other_memory.id,
            user_id=other_id,
            revision=1,
            previous_title=None,
            previous_content="older other-user text",
            new_title="另一用户",
            new_content="must survive",
            changed_title=True,
            changed_content=True,
        )
        db.add(other_memory_edit)
        db.flush()
        ids["other_memory_edit"] = other_memory_edit.id
        db.commit()

    ids["upload_key"] = upload_key
    ids["final_key"] = final_key
    return ids


@pytest.mark.asyncio
async def test_full_delete_converges_after_presigned_put_expiry_and_is_owner_isolated(
    client,
    delete_storage: DeleteTestStorage,
):
    owner_headers, owner_id = await _new_user(client, "delete-owner")
    _, other_id = await _new_user(client, "delete-other")
    ids = _seed_full_owned_graph(owner_id, other_id)

    orphan_key = f"media/{owner_id}/orphan-without-db-row"
    other_key = f"media/{other_id}/must-survive"
    delete_storage.objects.update(
        {str(ids["upload_key"]), str(ids["final_key"]), orphan_key, other_key}
    )
    request_id = uuid4()

    first = await client.post(
        "/v1/data/delete",
        headers=owner_headers,
        json={"request_id": str(request_id), "confirmation": "DELETE_MY_DATA"},
    )
    assert first.status_code == 202
    assert first.json()["status"] == "WAITING_STORAGE_EXPIRY"
    assert first.json()["completed"] is False
    assert str(ids["upload_key"]) not in delete_storage.objects
    assert str(ids["final_key"]) not in delete_storage.objects
    assert orphan_key not in delete_storage.objects
    assert other_key in delete_storage.objects

    blocked = await client.get("/v1/user", headers=owner_headers)
    assert blocked.status_code == 423
    assert blocked.json()["detail"] == "DATA_DELETION_IN_PROGRESS"

    # [人工注释][S1-021-FIX-002] 先推进到 capability 已过期、但真实 quiet window
    # 尚未结束的阶段。第一次 LIST 为空也只能 202，不能立即 COMPLETED。
    late_upload_key = str(ids["upload_key"])
    with SessionLocal() as db:
        operation = db.scalar(
            select(DataDeletionOperation).where(
                DataDeletionOperation.user_id == owner_id,
                DataDeletionOperation.request_id == request_id,
            )
        )
        assert operation is not None
        operation.storage_capability_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        operation.storage_quiet_until = datetime.now(UTC) + timedelta(minutes=5)
        db.commit()

    quiet = await client.post(
        "/v1/data/delete",
        headers=owner_headers,
        json={"request_id": str(request_id), "confirmation": "DELETE_MY_DATA"},
    )
    assert quiet.status_code == 202
    assert quiet.json()["status"] == "WAITING_STORAGE_QUIET"
    assert quiet.json()["completed"] is False

    # 模拟旧 Presigned PUT 在 expiry 前开始、expiry 后才完成：对象在 quiet 阶段
    # 第一次空 LIST 之后出现。下一次 retry 必须发现并删除它，同时重新开始 quiet。
    delete_storage.objects.add(late_upload_key)
    late = await client.post(
        "/v1/data/delete",
        headers=owner_headers,
        json={"request_id": str(request_id), "confirmation": "DELETE_MY_DATA"},
    )
    assert late.status_code == 202
    assert late.json()["status"] == "WAITING_STORAGE_QUIET"
    assert late_upload_key not in delete_storage.objects

    with SessionLocal() as db:
        operation = db.scalar(
            select(DataDeletionOperation).where(
                DataDeletionOperation.user_id == owner_id,
                DataDeletionOperation.request_id == request_id,
            )
        )
        assert operation is not None
        operation.storage_quiet_until = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    retry = await client.post(
        "/v1/data/delete",
        headers=owner_headers,
        json={"request_id": str(request_id), "confirmation": "DELETE_MY_DATA"},
    )
    assert retry.status_code == 200
    assert retry.json()["status"] == "COMPLETED"
    assert retry.json()["completed"] is True
    assert retry.json()["deleted_counts"]["memory_edits"] == 1
    assert other_key in delete_storage.objects

    with SessionLocal() as db:
        assert db.get(User, owner_id) is not None
        assert db.scalar(select(AuthIdentity).where(AuthIdentity.user_id == owner_id)) is not None
        assert _count_for_user(db, Device, owner_id) == 0
        assert _count_for_user(db, Place, owner_id) == 0
        assert _count_for_user(db, Visit, owner_id) == 0
        assert _count_for_user(db, Memory, owner_id) == 0
        assert _count_for_user(db, LocationPoint, owner_id) == 0
        assert db.get(LocationDerivationState, owner_id) is None
        assert db.scalar(
            select(func.count())
            .select_from(LocationIngestReceipt)
            .where(LocationIngestReceipt.user_id == owner_id)
        ) == 0
        assert _count_for_user(db, ObjectItem, owner_id) == 0
        assert _count_for_user(db, ObjectLocation, owner_id) == 0
        assert _count_for_user(db, Reminder, owner_id) == 0
        assert _count_for_user(db, MediaAsset, owner_id) == 0
        assert db.get(PrivacyState, owner_id) is None
        assert db.get(MemoryEdit, ids["memory_edit"]) is None
        assert db.get(MemorySource, ids["source"]) is None
        assert db.get(PrivacyPauseInterval, ids["pause"]) is None
        assert db.get(MediaASRClaim, ids["media"]) is None
        assert db.get(MediaEvidenceLink, ids["media_link"]) is None
        assert db.get(ClientMutation, ids["mutation"]) is None
        assert db.get(FamilyMember, ids["family_member"]) is None
        assert db.get(FamilyPermission, ids["family_permission"]) is None
        assert db.get(Memory, ids["other_memory"]) is not None
        assert db.get(MemoryEdit, ids["other_memory_edit"]) is not None
        assert db.scalar(
            select(func.count())
            .select_from(DataDeletionObject)
            .where(DataDeletionObject.deletion_id == select(DataDeletionOperation.id).where(
                DataDeletionOperation.user_id == owner_id,
                DataDeletionOperation.request_id == request_id,
            ).scalar_subquery())
        ) == 0

    exported = await client.get("/v1/export/data", headers=owner_headers)
    assert exported.status_code == 200
    body = exported.json()
    assert body["profile"]["id"] == str(owner_id)
    assert body["memories"] == []
    assert body["memory_sources"] == []
    assert body["memory_edits"] == []
    assert body["objects"] == []
    assert body["object_locations"] == []
    assert body["location"]["points"] == []
    assert body["location"]["visits"] == []
    assert body["location"]["places"] == []
    assert body["location"]["finalized_through"] is None
    assert body["privacy"]["state"] is None
    assert body["privacy"]["pause_intervals"] == []
    assert body["media"]["assets"] == []
    assert body["media"]["evidence_links"] == []

    query = await client.post(
        "/v1/memory/query",
        headers=owner_headers,
        json={"question": "我刚才保存了什么？"},
    )
    assert query.status_code == 200
    assert query.json()["can_answer"] is False
    assert query.json()["evidence"] == []

    # A response-loss retry of an already-completed request is a receipt lookup, not a new wipe.
    with SessionLocal() as db:
        new_memory = Memory(user_id=owner_id, content="created after the completed deletion")
        db.add(new_memory)
        db.commit()
        new_memory_id = new_memory.id

    replay = await client.post(
        "/v1/data/delete",
        headers=owner_headers,
        json={"request_id": str(request_id), "confirmation": "DELETE_MY_DATA"},
    )
    assert replay.status_code == 200
    assert replay.json()["status"] == "COMPLETED"
    with SessionLocal() as db:
        assert db.get(Memory, new_memory_id) is not None


@pytest.mark.asyncio
async def test_storage_failure_keeps_database_and_retry_converges(
    client,
    delete_storage: DeleteTestStorage,
):
    headers, user_id = await _new_user(client, "storage-retry")
    with SessionLocal() as db:
        memory = Memory(user_id=user_id, content="must survive failed storage cleanup")
        db.add(memory)
        db.commit()
        memory_id = memory.id

    orphan = f"media/{user_id}/orphan"
    delete_storage.objects.add(orphan)
    delete_storage.fail_once.add(orphan)
    request_id = uuid4()

    failed = await client.post(
        "/v1/data/delete",
        headers=headers,
        json={"request_id": str(request_id), "confirmation": "DELETE_MY_DATA"},
    )
    assert failed.status_code == 503
    assert failed.json()["detail"] == "DATA_DELETION_STORAGE_UNAVAILABLE"
    with SessionLocal() as db:
        assert db.get(Memory, memory_id) is not None
        operation = db.scalar(
            select(DataDeletionOperation).where(
                DataDeletionOperation.user_id == user_id,
                DataDeletionOperation.request_id == request_id,
            )
        )
        assert operation is not None
        assert operation.status == DataDeletionStatus.STORAGE_FAILED

    different_request = await client.post(
        "/v1/data/delete",
        headers=headers,
        json={"request_id": str(uuid4()), "confirmation": "DELETE_MY_DATA"},
    )
    assert different_request.status_code == 409
    assert different_request.json()["detail"] == "DATA_DELETION_ALREADY_IN_PROGRESS"

    retry = await client.post(
        "/v1/data/delete",
        headers=headers,
        json={"request_id": str(request_id), "confirmation": "DELETE_MY_DATA"},
    )
    assert retry.status_code == 202
    assert retry.json()["status"] == "WAITING_STORAGE_QUIET"
    assert orphan not in delete_storage.objects
    assert delete_storage.delete_calls[orphan] == 2

    with SessionLocal() as db:
        operation = db.scalar(
            select(DataDeletionOperation).where(
                DataDeletionOperation.user_id == user_id,
                DataDeletionOperation.request_id == request_id,
            )
        )
        assert operation is not None
        operation.storage_quiet_until = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    completed = await client.post(
        "/v1/data/delete",
        headers=headers,
        json={"request_id": str(request_id), "confirmation": "DELETE_MY_DATA"},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"
    with SessionLocal() as db:
        assert db.get(Memory, memory_id) is None


@pytest.mark.asyncio
async def test_database_failure_rolls_back_and_same_request_can_retry(
    client,
    delete_storage: DeleteTestStorage,
    monkeypatch,
):
    headers, user_id = await _new_user(client, "db-retry")
    with SessionLocal() as db:
        memory = Memory(user_id=user_id, content="must rollback as a unit")
        db.add(memory)
        db.commit()
        memory_id = memory.id

    original = data_deletion_service._delete_owned_database_rows

    def fail_database_cleanup(db, target_user_id):
        raise RuntimeError("synthetic database failure")

    monkeypatch.setattr(
        data_deletion_service,
        "_delete_owned_database_rows",
        fail_database_cleanup,
    )
    request_id = uuid4()
    failed = await client.post(
        "/v1/data/delete",
        headers=headers,
        json={"request_id": str(request_id), "confirmation": "DELETE_MY_DATA"},
    )
    assert failed.status_code == 503
    assert failed.json()["detail"] == "DATA_DELETION_DATABASE_FAILED"
    with SessionLocal() as db:
        assert db.get(Memory, memory_id) is not None
        operation = db.scalar(
            select(DataDeletionOperation).where(
                DataDeletionOperation.user_id == user_id,
                DataDeletionOperation.request_id == request_id,
            )
        )
        assert operation is not None
        assert operation.status == DataDeletionStatus.DB_FAILED

    monkeypatch.setattr(
        data_deletion_service,
        "_delete_owned_database_rows",
        original,
    )
    retry = await client.post(
        "/v1/data/delete",
        headers=headers,
        json={"request_id": str(request_id), "confirmation": "DELETE_MY_DATA"},
    )
    assert retry.status_code == 200
    assert retry.json()["status"] == "COMPLETED"
    with SessionLocal() as db:
        assert db.get(Memory, memory_id) is None


@pytest.mark.asyncio
async def test_delete_requires_exact_confirmation_before_mutation(
    client,
    delete_storage: DeleteTestStorage,
):
    headers, user_id = await _new_user(client, "confirmation")
    with SessionLocal() as db:
        memory = Memory(user_id=user_id, content="must remain")
        db.add(memory)
        db.commit()
        memory_id = memory.id

    rejected = await client.post(
        "/v1/data/delete",
        headers=headers,
        json={"request_id": str(uuid4()), "confirmation": "yes"},
    )
    assert rejected.status_code == 422
    with SessionLocal() as db:
        assert db.get(Memory, memory_id) is not None
        assert db.scalar(
            select(DataDeletionOperation.id).where(DataDeletionOperation.user_id == user_id)
        ) is None


def test_s3_object_inventory_is_paginated(monkeypatch):
    class StubPaginator:
        def paginate(self, **kwargs):
            assert kwargs == {"Bucket": "private-bucket", "Prefix": "media/user/"}
            return [
                {"Contents": [{"Key": "media/user/a"}]},
                {"Contents": [{"Key": "media/user/b"}, {"Key": None}]},
            ]

    class StubClient:
        def get_paginator(self, name):
            assert name == "list_objects_v2"
            return StubPaginator()

    monkeypatch.setattr(
        "app.services.object_storage.boto3.client",
        lambda *args, **kwargs: StubClient(),
    )
    storage = S3ObjectStorage(
        Settings(
            app_env="test",
            storage_backend="s3",
            storage_bucket="private-bucket",
            storage_access_key_id="key",
            storage_secret_access_key="secret",
        )
    )
    assert list(storage.iter_object_keys("media/user/")) == [
        "media/user/a",
        "media/user/b",
    ]


def test_s3_object_inventory_failure_is_fail_closed(monkeypatch):
    class StubClient:
        def get_paginator(self, name):
            raise RuntimeError("listing unavailable")

    monkeypatch.setattr(
        "app.services.object_storage.boto3.client",
        lambda *args, **kwargs: StubClient(),
    )
    storage = S3ObjectStorage(
        Settings(
            app_env="test",
            storage_backend="s3",
            storage_bucket="private-bucket",
            storage_access_key_id="key",
            storage_secret_access_key="secret",
        )
    )
    with pytest.raises(ObjectStorageError, match="failed to list objects"):
        list(storage.iter_object_keys("media/user/"))


@pytest.mark.asyncio
async def test_corrupt_media_key_cannot_delete_another_users_object(
    client,
    delete_storage: DeleteTestStorage,
):
    headers, user_id = await _new_user(client, "owner-corrupt-key")
    _, other_id = await _new_user(client, "foreign-key-owner")
    media_id = uuid4()
    own_staging = f"media/_staging/{user_id}/{media_id.hex}/ticket"
    foreign_final = f"media/{other_id}/must-never-delete"

    with SessionLocal() as db:
        db.add(
            MediaAsset(
                id=media_id,
                user_id=user_id,
                client_upload_id=uuid4(),
                kind=MediaKind.AUDIO,
                status=MediaStatus.PENDING,
                upload_object_key=own_staging,
                object_key=foreign_final,
                content_type="audio/mp4",
                size_bytes=8,
            )
        )
        db.commit()

    delete_storage.objects.update({own_staging, foreign_final})
    response = await client.post(
        "/v1/data/delete",
        headers=headers,
        json={"request_id": str(uuid4()), "confirmation": "DELETE_MY_DATA"},
    )
    assert response.status_code == 500
    assert response.json()["detail"] == "DATA_DELETION_STORAGE_OWNERSHIP_INVALID"
    assert delete_storage.objects == {own_staging, foreign_final}
    assert delete_storage.delete_calls == {}

    with SessionLocal() as db:
        assert db.get(MediaAsset, media_id) is not None
        assert db.scalar(
            select(DataDeletionOperation.id).where(DataDeletionOperation.user_id == user_id)
        ) is None


@pytest.mark.asyncio
async def test_orphan_staging_establishes_expiry_and_quiet_windows(
    client,
    delete_storage: DeleteTestStorage,
):
    headers, user_id = await _new_user(client, "orphan-staging")
    orphan_staging = f"media/_staging/{user_id}/{uuid4().hex}/lost-db-row"
    delete_storage.objects.add(orphan_staging)
    request_id = uuid4()

    response = await client.post(
        "/v1/data/delete",
        headers=headers,
        json={"request_id": str(request_id), "confirmation": "DELETE_MY_DATA"},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "WAITING_STORAGE_EXPIRY"
    assert orphan_staging not in delete_storage.objects

    with SessionLocal() as db:
        operation = db.scalar(
            select(DataDeletionOperation).where(
                DataDeletionOperation.user_id == user_id,
                DataDeletionOperation.request_id == request_id,
            )
        )
        assert operation is not None
        assert operation.storage_capability_expires_at is not None
        assert operation.storage_quiet_until is not None
        assert operation.storage_quiet_until > operation.storage_capability_expires_at
