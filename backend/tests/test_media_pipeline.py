from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.core.config import Settings
from app.core.db import SessionLocal, get_db
from app.main import app
from app.media_models import MediaAsset, MediaStatus
from app.services.media_service import MediaError, _validate_image_signature
from app.services.object_storage import (
    ObjectNotFound,
    PresignedTransfer,
    S3ObjectStorage,
    StoredObject,
    get_object_storage,
)


def _jpeg_bytes(size: int) -> bytes:
    assert size >= 3
    return b"\xff\xd8\xff" + (b"\x00" * (size - 3))


# [人工注释][S1-005][S1-006] 测试存储模拟签名、HEAD、小范围文件头读取与
# staging -> final 晋升；不执行 OCR/Vision，回归重点是 READY 可信门禁与事务恢复。
class FakeObjectStorage:
    def __init__(self):
        self.objects: dict[str, StoredObject] = {}
        self.object_bytes: dict[str, bytes] = {}
        self.last_upload_key: str | None = None
        self.last_download_key: str | None = None
        self.promotions: list[tuple[str, str]] = []
        self.deletions: list[str] = []
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
        self.last_download_key = object_key
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

    def read_prefix(self, object_key: str, max_bytes: int) -> bytes:
        if object_key not in self.object_bytes:
            raise ObjectNotFound("missing")
        return self.object_bytes[object_key][:max_bytes]

    def promote_object(self, source_key: str, destination_key: str) -> None:
        if source_key not in self.objects or source_key not in self.object_bytes:
            raise ObjectNotFound("missing")
        self.objects[destination_key] = self.objects[source_key]
        self.object_bytes[destination_key] = self.object_bytes[source_key]
        self.promotions.append((source_key, destination_key))

    def delete_object(self, object_key: str) -> None:
        self.objects.pop(object_key, None)
        self.object_bytes.pop(object_key, None)
        self.deletions.append(object_key)


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


def _upload_payload(
    *,
    client_upload_id=None,
    size_bytes: int = 11,
    content_type: str = "image/jpeg",
) -> dict:
    return {
        "client_upload_id": str(client_upload_id or uuid4()),
        "kind": "IMAGE",
        "content_type": content_type,
        "size_bytes": size_bytes,
        "original_filename": "camera/photo.jpg",
    }


def _put_fake_object(
    storage: FakeObjectStorage,
    object_key: str,
    *,
    size_bytes: int,
    content_type: str,
    data: bytes,
    etag: str,
) -> None:
    storage.objects[object_key] = StoredObject(
        size_bytes=size_bytes,
        content_type=content_type,
        etag=etag,
    )
    storage.object_bytes[object_key] = data


@pytest.mark.asyncio
async def test_verified_photo_becomes_queryable_media_evidence(
    client,
    auth_headers,
    fake_storage: FakeObjectStorage,
):
    # [人工注释][S1-005] 通用 Memory API 不再接受裸 USER_PHOTO，防止没有
    # 原始媒体也生成“图片证据”。
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
    assert "upload_object_key" not in upload_body
    assert "storage_etag" not in upload_body
    media_id = upload_body["id"]

    staging_key = fake_storage.last_upload_key
    assert staging_key is not None
    assert "/_staging/" in staging_key
    _put_fake_object(
        fake_storage,
        staging_key,
        size_bytes=11,
        content_type="image/jpeg",
        data=_jpeg_bytes(11),
        etag="etag-1",
    )

    complete = await client.post(
        f"/v1/media/{media_id}/complete",
        headers=auth_headers,
    )
    assert complete.status_code == 200
    assert complete.json()["status"] == "READY"
    assert "storage_etag" not in complete.json()
    assert len(fake_storage.promotions) == 1
    promoted_source, final_key = fake_storage.promotions[0]
    assert promoted_source == staging_key
    assert final_key != staging_key
    assert "/_staging/" not in final_key
    assert final_key in fake_storage.objects
    assert staging_key not in fake_storage.objects

    # [人工注释][S1-006] 模拟旧 PUT 签名在 READY 后重新写 staging；final Evidence
    # 对象必须保持不变，下载也只能签 final key。
    _put_fake_object(
        fake_storage,
        staging_key,
        size_bytes=999,
        content_type="image/png",
        data=b"late-overwrite",
        etag="late-overwrite",
    )
    assert fake_storage.objects[final_key].size_bytes == 11
    assert fake_storage.objects[final_key].content_type == "image/jpeg"

    original_payload = {
        "title": "旅行票据",
        "content": "红色文件夹里有旅行票据",
        "occurred_at": "2026-09-18T08:00:00+08:00",
    }
    created = await client.post(
        f"/v1/media/{media_id}/memory",
        headers=auth_headers,
        json=original_payload,
    )
    assert created.status_code == 201
    assert "storage_etag" not in created.json()["media"]
    memory_id = created.json()["memory"]["id"]
    assert created.json()["memory"]["source_type"] == "USER_PHOTO"

    # 模拟服务端已经 commit、客户端响应丢失后的重放：同 payload 必须返回原 Memory。
    duplicate_memory = await client.post(
        f"/v1/media/{media_id}/memory",
        headers=auth_headers,
        json=original_payload,
    )
    assert duplicate_memory.status_code == 201
    assert duplicate_memory.json()["memory"]["id"] == memory_id

    changed_content = await client.post(
        f"/v1/media/{media_id}/memory",
        headers=auth_headers,
        json={**original_payload, "content": "用户重试前改成了另一段内容"},
    )
    assert changed_content.status_code == 409
    assert changed_content.json()["detail"] == "MEDIA_MEMORY_IDEMPOTENCY_CONFLICT"

    changed_title = await client.post(
        f"/v1/media/{media_id}/memory",
        headers=auth_headers,
        json={**original_payload, "title": "另一标题"},
    )
    assert changed_title.status_code == 409
    assert changed_title.json()["detail"] == "MEDIA_MEMORY_IDEMPOTENCY_CONFLICT"

    changed_time = await client.post(
        f"/v1/media/{media_id}/memory",
        headers=auth_headers,
        json={**original_payload, "occurred_at": "2026-09-18T09:00:00+08:00"},
    )
    assert changed_time.status_code == 409
    assert changed_time.json()["detail"] == "MEDIA_MEMORY_IDEMPOTENCY_CONFLICT"

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
    assert fake_storage.last_download_key == final_key


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
    first_staging_key = fake_storage.last_upload_key
    assert first_staging_key is not None

    duplicate = await client.post("/v1/media/uploads", headers=owner_headers, json=payload)
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == first_id
    assert fake_storage.last_upload_key == first_staging_key

    conflict_payload = {**payload, "size_bytes": 18}
    conflict = await client.post(
        "/v1/media/uploads",
        headers=owner_headers,
        json=conflict_payload,
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "MEDIA_UPLOAD_ID_CONFLICT"

    # 相同 client_upload_id 只在单个用户域内幂等，另一用户得到不同媒体对象。
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

    _put_fake_object(
        fake_storage,
        first_staging_key,
        size_bytes=999,
        content_type="image/jpeg",
        data=_jpeg_bytes(17),
        etag="bad-size",
    )
    bad_size = await client.post(
        f"/v1/media/{first_id}/complete",
        headers=owner_headers,
    )
    assert bad_size.status_code == 409
    assert bad_size.json()["detail"] == "MEDIA_OBJECT_SIZE_MISMATCH"
    assert not fake_storage.promotions

    _put_fake_object(
        fake_storage,
        first_staging_key,
        size_bytes=17,
        content_type="image/png",
        data=b"\x89PNG\r\n\x1a\n",
        etag="bad-type",
    )
    bad_type = await client.post(
        f"/v1/media/{first_id}/complete",
        headers=owner_headers,
    )
    assert bad_type.status_code == 409
    assert bad_type.json()["detail"] == "MEDIA_OBJECT_TYPE_MISMATCH"
    assert not fake_storage.promotions

    # [人工注释][S1-005] MIME/size 即使匹配，非 JPEG 字节也不能进入 READY/Evidence。
    _put_fake_object(
        fake_storage,
        first_staging_key,
        size_bytes=17,
        content_type="image/jpeg",
        data=b"not-a-real-jpeg!!",
        etag="fake-jpeg",
    )
    bad_signature = await client.post(
        f"/v1/media/{first_id}/complete",
        headers=owner_headers,
    )
    assert bad_signature.status_code == 409
    assert bad_signature.json()["detail"] == "MEDIA_IMAGE_INVALID"
    assert not fake_storage.promotions
    with SessionLocal() as verify_db:
        asset = verify_db.get(MediaAsset, UUID(first_id))
        assert asset is not None
        assert asset.status == MediaStatus.PENDING

    _put_fake_object(
        fake_storage,
        first_staging_key,
        size_bytes=17,
        content_type="image/jpeg",
        data=_jpeg_bytes(17),
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
async def test_complete_commit_failure_keeps_staging_and_retry_recovers(
    client,
    auth_headers,
    fake_storage: FakeObjectStorage,
):
    # [人工注释][S1-006] READY commit 失败时 staging 必须仍存在；final 可已生成，
    # 但数据库回滚为 PENDING，随后相同 complete 应能重新晋升并成功恢复。
    upload = await client.post(
        "/v1/media/uploads",
        headers=auth_headers,
        json=_upload_payload(size_bytes=13),
    )
    assert upload.status_code == 201
    media_id = upload.json()["id"]
    staging_key = fake_storage.last_upload_key
    assert staging_key is not None
    _put_fake_object(
        fake_storage,
        staging_key,
        size_bytes=13,
        content_type="image/jpeg",
        data=_jpeg_bytes(13),
        etag="commit-retry",
    )

    failing_session = SessionLocal()

    def fail_commit() -> None:
        raise RuntimeError("synthetic commit failure")

    failing_session.commit = fail_commit  # type: ignore[method-assign]

    def failing_db():
        try:
            yield failing_session
        finally:
            failing_session.close()

    app.dependency_overrides[get_db] = failing_db
    try:
        with pytest.raises(RuntimeError, match="synthetic commit failure"):
            await client.post(
                f"/v1/media/{media_id}/complete",
                headers=auth_headers,
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert staging_key in fake_storage.objects
    assert staging_key not in fake_storage.deletions
    assert fake_storage.promotions
    final_key = fake_storage.promotions[-1][1]
    assert final_key in fake_storage.objects
    with SessionLocal() as verify_db:
        asset = verify_db.get(MediaAsset, UUID(media_id))
        assert asset is not None
        assert asset.status == MediaStatus.PENDING

    retry = await client.post(
        f"/v1/media/{media_id}/complete",
        headers=auth_headers,
    )
    assert retry.status_code == 200
    assert retry.json()["status"] == "READY"
    assert staging_key not in fake_storage.objects
    assert staging_key in fake_storage.deletions


@pytest.mark.parametrize(
    ("content_type", "prefix"),
    [
        ("image/jpeg", b"\xff\xd8\xff\xe0jpeg"),
        ("image/png", b"\x89PNG\r\n\x1a\nrest"),
        ("image/webp", b"RIFF\x10\x00\x00\x00WEBPVP8 "),
        ("image/heic", b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic"),
        ("image/heif", b"\x00\x00\x00\x18ftypmif1\x00\x00\x00\x00mif1heic"),
    ],
)
def test_supported_image_signatures_are_accepted(content_type: str, prefix: bytes):
    # [人工注释][S1-005] Stage 1 只做确定性的文件头真实性校验，不解析图片内容语义。
    _validate_image_signature(content_type, prefix)


def test_declared_jpeg_rejects_non_jpeg_bytes():
    with pytest.raises(MediaError) as caught:
        _validate_image_signature("image/jpeg", b"plain arbitrary bytes")
    assert caught.value.code == "MEDIA_IMAGE_INVALID"


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
    # [人工注释][S1-006] 过期由对象存储 SigV4 强制执行；这里锁定 ExpiresIn，
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
    transfer = storage.sign_upload("media/_staging/user/item", "image/jpeg")

    assert calls[0]["ExpiresIn"] == 120
    assert calls[0]["HttpMethod"] == "PUT"
    assert calls[0]["Params"]["Bucket"] == "private-bucket"
    assert calls[0]["Params"]["ContentType"] == "image/jpeg"
    assert before + timedelta(seconds=119) <= transfer.expires_at
    assert transfer.expires_at <= datetime.now(UTC) + timedelta(seconds=121)


def test_production_custom_storage_endpoint_requires_https():
    # [人工注释][S1-006] production 自定义 endpoint 不能把原图或 SigV4 能力票据降级到明文 HTTP。
    common = {
        "app_env": "production",
        "enable_dev_auth": False,
        "jwt_secret": "x" * 32,
        "storage_backend": "s3",
        "storage_bucket": "private-bucket",
        "storage_access_key_id": "test-key",
        "storage_secret_access_key": "test-secret",
    }
    with pytest.raises(ValueError, match="HTTPS"):
        Settings(**common, storage_endpoint_url="http://storage.example.com")

    secure = Settings(**common, storage_endpoint_url="https://storage.example.com")
    assert secure.storage_endpoint_url == "https://storage.example.com"

    development = Settings(
        app_env="development",
        storage_backend="s3",
        storage_bucket="private-bucket",
        storage_access_key_id="test-key",
        storage_secret_access_key="test-secret",
        storage_endpoint_url="http://127.0.0.1:9000",
    )
    assert development.storage_endpoint_url == "http://127.0.0.1:9000"
