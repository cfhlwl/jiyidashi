from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.main import app
from app.services.object_storage import (
    ObjectNotFound,
    PresignedTransfer,
    S3ObjectStorage,
    StoredObject,
    get_object_storage,
)


# [人工注释][S1-005][S1-006] 测试存储只模拟签名与 HEAD 元数据，不保存真实图片内容；
# Backend 回归重点是用户归属、短时能力票据、READY 门禁和 Evidence 关联，而不是 OCR/Vision。
class FakeObjectStorage:
    def __init__(self):
        self.objects: dict[str, StoredObject] = {}
        self.last_upload_key: str | None = None
        self.upload_sign_count = 0

    def sign_upload(self, object_key: str, content_type: str) -> PresignedTransfer:
        self.last_upload_key = object_key
        self.upload_sign_count += 1
        return PresignedTransfer(
            url=f"https://private-storage.test/upload/{object_key}?temporary=1",
            method="PUT",
            headers={"Content-Type": content_type},
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )

    def sign_download(self, object_key: str) -> PresignedTransfer:
        return PresignedTransfer(
            url=f"https://private-storage.test/download/{object_key}?temporary=1",
            method="GET",
            headers={},
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )

    def stat_object(self, object_key: str) -> StoredObject:
        if object_key not in self.objects:
            raise ObjectNotFound("missing")
        return self.objects[object_key]


@pytest.fixture
def fake_storage():
    storage = FakeObjectStorage()
    app.dependency_overrides[get_object_storage] = lambda: storage
    yield storage
    app.dependency_overrides.pop(get_object_storage, None)


async def _new_headers(client, nickname: str) -> dict[str, str]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _upload_payload(*, client_upload_id=None, size_bytes: int = 11) -> dict:
    return {
        "client_upload_id": str(client_upload_id or uuid4()),
        "kind": "IMAGE",
        "content_type": "image/jpeg",
        "size_bytes": size_bytes,
        "original_filename": "camera/photo.jpg",
    }


@pytest.mark.asyncio
async def test_verified_photo_becomes_queryable_media_evidence(
    client,
    auth_headers,
    fake_storage: FakeObjectStorage,
):
    # [人工注释][S1-005] 通用 Memory API 不再接受裸 USER_PHOTO，防止没有原始媒体也生成“图片证据”。
    naked = await client.post(
        "/v1/memories",
        headers=auth_headers,
        json={
            "memory_type": "PHOTO",
            "content": "这不是已验证图片",
            "capture_source": "USER_PHOTO",
        },
    )
    assert naked.status_code == 422

    upload = await client.post(
        "/v1/media/uploads",
        headers=auth_headers,
        json=_upload_payload(),
    )
    assert upload.status_code == 201
    upload_body = upload.json()
    assert upload_body["status"] == "PENDING"
    assert upload_body["upload"]["method"] == "PUT"
    assert upload_body["upload"]["headers"] == {"Content-Type": "image/jpeg"}
    assert "object_key" not in upload_body
    media_id = upload_body["id"]

    assert fake_storage.last_upload_key is not None
    fake_storage.objects[fake_storage.last_upload_key] = StoredObject(
        size_bytes=11,
        content_type="image/jpeg",
        etag="etag-1",
    )

    complete = await client.post(
        f"/v1/media/{media_id}/complete",
        headers=auth_headers,
    )
    assert complete.status_code == 200
    assert complete.json()["status"] == "READY"

    created = await client.post(
        f"/v1/media/{media_id}/memory",
        headers=auth_headers,
        json={"content": "红色文件夹里有旅行票据"},
    )
    assert created.status_code == 201
    memory_id = created.json()["memory"]["id"]
    assert created.json()["memory"]["source_type"] == "USER_PHOTO"

    # 同一 READY 图片重复提交必须复用已有 Memory，而不是制造第二条 confirmed fact。
    duplicate_memory = await client.post(
        f"/v1/media/{media_id}/memory",
        headers=auth_headers,
        json={"content": "重复请求不会新建另一条"},
    )
    assert duplicate_memory.status_code == 201
    assert duplicate_memory.json()["memory"]["id"] == memory_id

    query = await client.post(
        "/v1/memory/query",
        headers=auth_headers,
        json={"question": "旅行票据在哪"},
    )
    assert query.status_code == 200
    evidence = query.json()["evidence"]
    assert evidence
    assert evidence[0]["source_type"] == "USER_PHOTO"
    assert evidence[0]["media_id"] == media_id

    download = await client.post(
        f"/v1/media/{media_id}/download",
        headers=auth_headers,
    )
    assert download.status_code == 200
    assert download.json()["download"]["method"] == "GET"
    assert "temporary=1" in download.json()["download"]["url"]


@pytest.mark.asyncio
async def test_media_idempotency_owner_isolation_and_invalid_object_rejection(
    client,
    fake_storage: FakeObjectStorage,
):
    owner_headers = await _new_headers(client, "owner")
    other_headers = await _new_headers(client, "other")
    client_upload_id = uuid4()
    payload = _upload_payload(client_upload_id=client_upload_id, size_bytes=17)

    first = await client.post("/v1/media/uploads", headers=owner_headers, json=payload)
    assert first.status_code == 201
    first_id = first.json()["id"]
    first_key = fake_storage.last_upload_key
    assert first_key is not None

    duplicate = await client.post("/v1/media/uploads", headers=owner_headers, json=payload)
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == first_id

    conflict_payload = {**payload, "size_bytes": 18}
    conflict = await client.post(
        "/v1/media/uploads",
        headers=owner_headers,
        json=conflict_payload,
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "MEDIA_UPLOAD_ID_CONFLICT"

    # 相同 client_upload_id 只在单个用户域内幂等，另一用户得到完全不同的媒体对象。
    other_upload = await client.post(
        "/v1/media/uploads",
        headers=other_headers,
        json=payload,
    )
    assert other_upload.status_code == 201
    assert other_upload.json()["id"] != first_id

    cross_user = await client.post(
        f"/v1/media/{first_id}/complete",
        headers=other_headers,
    )
    assert cross_user.status_code == 404
    assert cross_user.json()["detail"] == "MEDIA_NOT_FOUND"

    missing = await client.post(
        f"/v1/media/{first_id}/complete",
        headers=owner_headers,
    )
    assert missing.status_code == 409
    assert missing.json()["detail"] == "MEDIA_OBJECT_NOT_FOUND"

    fake_storage.objects[first_key] = StoredObject(
        size_bytes=999,
        content_type="image/jpeg",
        etag="bad-size",
    )
    bad_size = await client.post(
        f"/v1/media/{first_id}/complete",
        headers=owner_headers,
    )
    assert bad_size.status_code == 409
    assert bad_size.json()["detail"] == "MEDIA_OBJECT_SIZE_MISMATCH"

    fake_storage.objects[first_key] = StoredObject(
        size_bytes=17,
        content_type="image/png",
        etag="bad-type",
    )
    bad_type = await client.post(
        f"/v1/media/{first_id}/complete",
        headers=owner_headers,
    )
    assert bad_type.status_code == 409
    assert bad_type.json()["detail"] == "MEDIA_OBJECT_TYPE_MISMATCH"

    fake_storage.objects[first_key] = StoredObject(
        size_bytes=17,
        content_type="image/jpeg",
        etag="ok",
    )
    ready = await client.post(
        f"/v1/media/{first_id}/complete",
        headers=owner_headers,
    )
    assert ready.status_code == 200

    cross_download = await client.post(
        f"/v1/media/{first_id}/download",
        headers=other_headers,
    )
    assert cross_download.status_code == 404

    cross_memory = await client.post(
        f"/v1/media/{first_id}/memory",
        headers=other_headers,
        json={"content": "不允许绑定别人的图片"},
    )
    assert cross_memory.status_code == 404


@pytest.mark.asyncio
async def test_unverified_photo_object_location_is_rejected(client, auth_headers):
    created = await client.post(
        "/v1/objects",
        headers=auth_headers,
        json={"name": "护照"},
    )
    assert created.status_code == 201
    object_id = created.json()["id"]

    response = await client.post(
        f"/v1/objects/{object_id}/locations",
        headers=auth_headers,
        json={
            "location_text": "抽屉",
            "capture_source": "USER_PHOTO",
        },
    )
    assert response.status_code == 422


def test_s3_presigned_upload_is_short_lived(monkeypatch):
    # [人工注释][S1-006] 过期由对象存储 SigV4 强制执行；这里锁定服务端 ExpiresIn，
    # 防止未来误改成永久 URL 或超长签名。
    calls: list[dict] = []

    class StubClient:
        def generate_presigned_url(self, **kwargs):
            calls.append(kwargs)
            return "https://private-storage.test/signed"

    monkeypatch.setattr(
        "app.services.object_storage.boto3.client",
        lambda *args, **kwargs: StubClient(),
    )
    settings = Settings(
        app_env="test",
        storage_backend="s3",
        storage_bucket="private-bucket",
        storage_region="ap-test",
        storage_access_key_id="test-key",
        storage_secret_access_key="test-secret",
        storage_presign_ttl_seconds=120,
    )
    storage = S3ObjectStorage(settings)
    before = datetime.now(UTC)
    transfer = storage.sign_upload("media/user/item", "image/jpeg")

    assert calls[0]["ExpiresIn"] == 120
    assert calls[0]["HttpMethod"] == "PUT"
    assert calls[0]["Params"]["Bucket"] == "private-bucket"
    assert calls[0]["Params"]["ContentType"] == "image/jpeg"
    assert before + timedelta(seconds=119) <= transfer.expires_at
    assert transfer.expires_at <= datetime.now(UTC) + timedelta(seconds=121)
