from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.main import app
from app.services.asr import ASRProviderError, ASRResult, get_asr_provider
from app.services.object_storage import (
    ObjectNotFound,
    PresignedTransfer,
    StoredObject,
    get_object_storage,
)


# [人工注释][S1-004][S1-007] 本文件只补 Issue #14 明确点名的边界：空文件、
# MIME 欺骗与 provider 通用失败。正常链/幂等/删除/跨用户由 test_voice_pipeline.py 覆盖。
class EdgeStorage:
    def __init__(self):
        self.objects: dict[str, StoredObject] = {}
        self.object_bytes: dict[str, bytes] = {}
        self.last_upload_key: str | None = None

    def sign_upload(self, object_key: str, content_type: str) -> PresignedTransfer:
        self.last_upload_key = object_key
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

    def read_prefix(self, object_key: str, max_bytes: int) -> bytes:
        if object_key not in self.object_bytes:
            raise ObjectNotFound("missing")
        return self.object_bytes[object_key][:max_bytes]

    def read_object(self, object_key: str, max_bytes: int) -> bytes:
        if object_key not in self.object_bytes:
            raise ObjectNotFound("missing")
        return self.object_bytes[object_key][:max_bytes]

    def promote_object(self, source_key: str, destination_key: str) -> None:
        if source_key not in self.objects or source_key not in self.object_bytes:
            raise ObjectNotFound("missing")
        self.objects[destination_key] = self.objects[source_key]
        self.object_bytes[destination_key] = self.object_bytes[source_key]

    def delete_object(self, object_key: str) -> None:
        self.objects.pop(object_key, None)
        self.object_bytes.pop(object_key, None)


class FailingASR:
    def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str,
        filename: str | None,
    ) -> ASRResult:
        del audio, content_type, filename
        raise ASRProviderError("ASR_PROVIDER_FAILED")


@pytest.fixture
def edge_dependencies():
    storage = EdgeStorage()
    app.dependency_overrides[get_object_storage] = lambda: storage
    yield storage
    app.dependency_overrides.pop(get_object_storage, None)
    app.dependency_overrides.pop(get_asr_provider, None)


def _audio_payload(size_bytes: int) -> dict:
    return {
        "client_upload_id": str(uuid4()),
        "kind": "AUDIO",
        "content_type": "audio/mpeg",
        "size_bytes": size_bytes,
        "original_filename": "voice.mp3",
    }


@pytest.mark.asyncio
async def test_empty_audio_is_rejected_before_media_asset(
    client,
    auth_headers,
    edge_dependencies,
):
    response = await client.post(
        "/v1/media/uploads",
        headers=auth_headers,
        json=_audio_payload(0),
    )
    assert response.status_code == 422
    assert edge_dependencies.last_upload_key is None


@pytest.mark.asyncio
async def test_audio_mime_spoof_is_rejected_at_ready(
    client,
    auth_headers,
    edge_dependencies,
):
    storage = edge_dependencies
    data = b"ID3" + (b"\x00" * 16)
    upload = await client.post(
        "/v1/media/uploads",
        headers=auth_headers,
        json=_audio_payload(len(data)),
    )
    assert upload.status_code == 201
    key = storage.last_upload_key
    assert key is not None
    # 声明/签名是 audio/mpeg，但对象存储 HEAD 返回 image/jpeg：
    # 服务端必须在文件头校验前先拒绝 MIME 欺骗。
    storage.objects[key] = StoredObject(
        size_bytes=len(data),
        content_type="image/jpeg",
        etag="spoof",
    )
    storage.object_bytes[key] = data

    complete = await client.post(
        f"/v1/media/{upload.json()['id']}/complete",
        headers=auth_headers,
    )
    assert complete.status_code == 409
    assert complete.json()["detail"] == "MEDIA_OBJECT_TYPE_MISMATCH"


@pytest.mark.asyncio
async def test_provider_failure_does_not_create_voice_memory(
    client,
    auth_headers,
    edge_dependencies,
):
    storage = edge_dependencies
    data = b"ID3" + (b"\x01" * 32)
    upload = await client.post(
        "/v1/media/uploads",
        headers=auth_headers,
        json=_audio_payload(len(data)),
    )
    assert upload.status_code == 201
    media_id = upload.json()["id"]
    key = storage.last_upload_key
    assert key is not None
    storage.objects[key] = StoredObject(
        size_bytes=len(data),
        content_type="audio/mpeg",
        etag="ok",
    )
    storage.object_bytes[key] = data
    complete = await client.post(f"/v1/media/{media_id}/complete", headers=auth_headers)
    assert complete.status_code == 200

    app.dependency_overrides[get_asr_provider] = lambda: FailingASR()
    failed = await client.post(
        f"/v1/media/{media_id}/voice-memory",
        headers=auth_headers,
        json={},
    )
    assert failed.status_code == 502
    assert failed.json()["detail"] == "ASR_PROVIDER_FAILED"

    query = await client.post(
        "/v1/memory/query",
        headers=auth_headers,
        json={"question": "这段不存在的转写"},
    )
    assert query.status_code == 200
    assert query.json()["can_answer"] is False
    assert query.json()["reason"] == "NO_EVIDENCE"
