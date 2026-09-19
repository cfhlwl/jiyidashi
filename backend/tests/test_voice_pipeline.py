from datetime import UTC, datetime, timedelta
from math import log
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.main import app
from app.media_models import MediaAsset, MediaEvidenceLink, MediaStatus
from app.models import Memory, MemorySource, SourceType
from app.services.asr import (
    ASRProviderError,
    ASRResult,
    confidence_from_logprobs,
    get_asr_provider,
)
from app.services.object_storage import (
    ObjectNotFound,
    PresignedTransfer,
    StoredObject,
    get_object_storage,
)


# [人工注释][S1-004][S1-007] E 线测试存储同时覆盖 staging->final、文件头验证和
# READY final 音频的有界读取；测试不会调用真实云存储或真实 ASR provider。
class FakeObjectStorage:
    def __init__(self):
        self.objects: dict[str, StoredObject] = {}
        self.object_bytes: dict[str, bytes] = {}
        self.last_upload_key: str | None = None
        self.last_download_key: str | None = None
        self.promotions: list[tuple[str, str]] = []
        self.deletions: list[str] = []

    def sign_upload(self, object_key: str, content_type: str) -> PresignedTransfer:
        self.last_upload_key = object_key
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

    def read_object(self, object_key: str, max_bytes: int) -> bytes:
        if object_key not in self.object_bytes:
            raise ObjectNotFound("missing")
        data = self.object_bytes[object_key]
        if len(data) > max_bytes:
            raise RuntimeError("fake object exceeds bounded read")
        return data

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


class FakeASRProvider:
    def __init__(self):
        self.result = ASRResult(
            text="明天下午三点去医院复查",
            confidence=0.93,
            provider="fake",
            model="fake-asr-v1",
        )
        self.error_code: str | None = None
        self.calls = 0

    def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str,
        filename: str | None,
    ) -> ASRResult:
        self.calls += 1
        if content_type == "audio/mpeg":
            assert audio.startswith(b"ID3")
            assert filename == "voice.mp3"
        elif content_type == "audio/mp4":
            assert len(audio) >= 12 and audio[4:8] == b"ftyp"
            assert filename == "voice.m4a"
        else:
            raise AssertionError(f"unexpected audio content type: {content_type}")
        if self.error_code:
            raise ASRProviderError(self.error_code)
        return self.result


@pytest.fixture
def voice_dependencies():
    storage = FakeObjectStorage()
    asr = FakeASRProvider()
    app.dependency_overrides[get_object_storage] = lambda: storage
    app.dependency_overrides[get_asr_provider] = lambda: asr
    yield storage, asr
    app.dependency_overrides.pop(get_object_storage, None)
    app.dependency_overrides.pop(get_asr_provider, None)


async def _new_headers(client, nickname: str) -> dict[str, str]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _audio_payload(
    *,
    size_bytes: int,
    client_upload_id=None,
    content_type: str = "audio/mpeg",
    original_filename: str = "voice.mp3",
) -> dict:
    return {
        "client_upload_id": str(client_upload_id or uuid4()),
        "kind": "AUDIO",
        "content_type": content_type,
        "size_bytes": size_bytes,
        "original_filename": original_filename,
    }


def _put_audio(
    storage: FakeObjectStorage,
    key: str,
    data: bytes,
    *,
    content_type: str = "audio/mpeg",
) -> None:
    storage.objects[key] = StoredObject(
        size_bytes=len(data),
        content_type=content_type,
        etag="voice-etag",
    )
    storage.object_bytes[key] = data


async def _ready_audio(
    client,
    headers,
    storage: FakeObjectStorage,
    data: bytes,
    *,
    content_type: str = "audio/mpeg",
    original_filename: str = "voice.mp3",
) -> str:
    upload = await client.post(
        "/v1/media/uploads",
        headers=headers,
        json=_audio_payload(
            size_bytes=len(data),
            content_type=content_type,
            original_filename=original_filename,
        ),
    )
    assert upload.status_code == 201
    body = upload.json()
    assert body["kind"] == "AUDIO"
    assert body["status"] == "PENDING"
    assert body["upload"]["headers"] == {"Content-Type": content_type}
    media_id = body["id"]
    staging_key = storage.last_upload_key
    assert staging_key is not None
    _put_audio(storage, staging_key, data, content_type=content_type)

    complete = await client.post(f"/v1/media/{media_id}/complete", headers=headers)
    assert complete.status_code == 200
    assert complete.json()["status"] == "READY"
    return media_id


@pytest.mark.asyncio
async def test_m4a_audio_container_is_supported_and_transcribed(
    client,
    auth_headers,
    voice_dependencies,
):
    storage, asr = voice_dependencies
    audio = (
        b"\x00\x00\x00\x20ftypM4A "
        b"\x00\x00\x00\x00M4A mp42isom"
        + (b"\x00" * 80)
    )
    media_id = await _ready_audio(
        client,
        auth_headers,
        storage,
        audio,
        content_type="audio/mp4",
        original_filename="voice.m4a",
    )

    created = await client.post(
        f"/v1/media/{media_id}/voice-memory",
        headers=auth_headers,
        json={"title": "Flutter 语音"},
    )
    assert created.status_code == 201
    assert created.json()["memory"]["source_type"] == "USER_VOICE"
    assert created.json()["memory"]["content"] == "明天下午三点去医院复查"
    assert asr.calls == 1


@pytest.mark.asyncio
async def test_voice_requires_verified_audio_and_server_asr(
    client,
    auth_headers,
    voice_dependencies,
):
    storage, asr = voice_dependencies

    # [人工注释][S1-007] 裸 USER_VOICE 与裸 USER_PHOTO 一样必须在 schema 层拒绝；
    # 客户端提交的“转写文字”不能绕过原始音频 Evidence。
    naked = await client.post(
        "/v1/memories",
        headers=auth_headers,
        json={
            "memory_type": "VOICE",
            "content": "客户端伪造的转写",
            "capture_source": "USER_VOICE",
        },
    )
    assert naked.status_code == 422

    audio = b"ID3" + (b"\x00" * 97)
    media_id = await _ready_audio(client, auth_headers, storage, audio)

    created = await client.post(
        f"/v1/media/{media_id}/voice-memory",
        headers=auth_headers,
        json={"title": "复查安排"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["media"]["id"] == media_id
    assert body["media"]["kind"] == "AUDIO"
    assert body["memory"]["memory_type"] == "VOICE"
    assert body["memory"]["source_type"] == "USER_VOICE"
    assert body["memory"]["content"] == "明天下午三点去医院复查"
    assert body["memory"]["confidence"] == pytest.approx(0.93)
    memory_id = body["memory"]["id"]

    # 同一 READY 音频重复请求直接复用既有 Evidence/Memory，不再次调用 provider。
    duplicate = await client.post(
        f"/v1/media/{media_id}/voice-memory",
        headers=auth_headers,
        json={"title": "复查安排"},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["memory"]["id"] == memory_id
    assert asr.calls == 1

    changed_title = await client.post(
        f"/v1/media/{media_id}/voice-memory",
        headers=auth_headers,
        json={"title": "用户重试时改了标题"},
    )
    assert changed_title.status_code == 409
    assert changed_title.json()["detail"] == "MEDIA_MEMORY_IDEMPOTENCY_CONFLICT"
    assert asr.calls == 1

    changed_time = await client.post(
        f"/v1/media/{media_id}/voice-memory",
        headers=auth_headers,
        json={
            "title": "复查安排",
            "occurred_at": "2026-09-18T09:00:00+08:00",
        },
    )
    assert changed_time.status_code == 409
    assert changed_time.json()["detail"] == "MEDIA_MEMORY_IDEMPOTENCY_CONFLICT"
    assert asr.calls == 1

    query = await client.post(
        "/v1/memory/query",
        headers=auth_headers,
        json={"question": "医院复查"},
    )
    assert query.status_code == 200
    evidence = query.json()["evidence"]
    assert evidence
    assert evidence[0]["source_type"] == "USER_VOICE"
    assert evidence[0]["media_id"] == media_id
    assert evidence[0]["confidence"] == pytest.approx(0.93)

    # 软删除后 MediaEvidenceLink 继续作为幂等水位，不能重跑 ASR 把同一事实“复活”。
    deleted = await client.delete(f"/v1/memories/{memory_id}", headers=auth_headers)
    assert deleted.status_code == 204
    retry_deleted = await client.post(
        f"/v1/media/{media_id}/voice-memory",
        headers=auth_headers,
        json={},
    )
    assert retry_deleted.status_code == 409
    assert retry_deleted.json()["detail"] == "MEDIA_MEMORY_DELETED"
    assert asr.calls == 1


@pytest.mark.asyncio
async def test_voice_invalid_audio_owner_isolation_and_unverified_location_rejected(
    client,
    voice_dependencies,
):
    storage, _ = voice_dependencies
    owner_headers = await _new_headers(client, "voice-owner")
    other_headers = await _new_headers(client, "voice-other")

    invalid = b"this-is-not-mp3"
    upload = await client.post(
        "/v1/media/uploads",
        headers=owner_headers,
        json=_audio_payload(size_bytes=len(invalid)),
    )
    assert upload.status_code == 201
    media_id = upload.json()["id"]
    staging_key = storage.last_upload_key
    assert staging_key is not None
    _put_audio(storage, staging_key, invalid)

    complete = await client.post(f"/v1/media/{media_id}/complete", headers=owner_headers)
    assert complete.status_code == 409
    assert complete.json()["detail"] == "MEDIA_AUDIO_INVALID"
    with SessionLocal() as db:
        asset = db.get(MediaAsset, UUID(media_id))
        assert asset is not None
        assert asset.status == MediaStatus.PENDING

    valid_media_id = await _ready_audio(
        client,
        owner_headers,
        storage,
        b"ID3" + (b"\x01" * 64),
    )
    cross_memory = await client.post(
        f"/v1/media/{valid_media_id}/voice-memory",
        headers=other_headers,
        json={},
    )
    assert cross_memory.status_code == 404
    cross_download = await client.post(
        f"/v1/media/{valid_media_id}/download",
        headers=other_headers,
    )
    assert cross_download.status_code == 404

    # 没有 verified audio -> ASR 派生链时，对象位置也不能仅靠 USER_VOICE 字符串伪造来源。
    object_response = await client.post(
        "/v1/objects",
        headers=owner_headers,
        json={"name": "钥匙"},
    )
    assert object_response.status_code == 201
    location = await client.post(
        f"/v1/objects/{object_response.json()['id']}/locations",
        headers=owner_headers,
        json={
            "location_text": "玄关抽屉",
            "capture_source": "USER_VOICE",
        },
    )
    assert location.status_code == 422


@pytest.mark.asyncio
async def test_asr_failures_are_fail_closed_and_retry_is_idempotent(
    client,
    auth_headers,
    voice_dependencies,
):
    storage, asr = voice_dependencies
    media_id = await _ready_audio(
        client,
        auth_headers,
        storage,
        b"ID3" + (b"\x02" * 80),
    )

    asr.result = ASRResult(
        text="低置信转写",
        confidence=0.20,
        provider="fake",
        model="fake-asr-v1",
    )
    low = await client.post(
        f"/v1/media/{media_id}/voice-memory",
        headers=auth_headers,
        json={},
    )
    assert low.status_code == 422
    assert low.json()["detail"] == "ASR_LOW_CONFIDENCE"

    asr.result = ASRResult(
        text="   ",
        confidence=0.95,
        provider="fake",
        model="fake-asr-v1",
    )
    empty = await client.post(
        f"/v1/media/{media_id}/voice-memory",
        headers=auth_headers,
        json={},
    )
    assert empty.status_code == 422
    assert empty.json()["detail"] == "ASR_EMPTY_RESULT"

    asr.error_code = "ASR_TIMEOUT"
    timeout = await client.post(
        f"/v1/media/{media_id}/voice-memory",
        headers=auth_headers,
        json={},
    )
    assert timeout.status_code == 504
    assert timeout.json()["detail"] == "ASR_TIMEOUT"

    # 失败阶段没有任何 Memory/MediaEvidenceLink；恢复 provider 后同一个 media 可安全重试。
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count(MediaEvidenceLink.id)).where(
                    MediaEvidenceLink.media_id == UUID(media_id)
                )
            )
            == 0
        )
        source_count = db.scalar(
            select(func.count(MemorySource.id)).where(
                MemorySource.source_type == SourceType.USER_VOICE,
                MemorySource.source_id == media_id,
            )
        )
        assert source_count == 0

    asr.error_code = None
    asr.result = ASRResult(
        text="晚上八点给妈妈打电话",
        confidence=0.88,
        provider="fake",
        model="fake-asr-v1",
    )
    recovered = await client.post(
        f"/v1/media/{media_id}/voice-memory",
        headers=auth_headers,
        json={},
    )
    assert recovered.status_code == 201
    memory_id = recovered.json()["memory"]["id"]

    again = await client.post(
        f"/v1/media/{media_id}/voice-memory",
        headers=auth_headers,
        json={},
    )
    assert again.status_code == 201
    assert again.json()["memory"]["id"] == memory_id
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count(MediaEvidenceLink.id)).where(
                    MediaEvidenceLink.media_id == UUID(media_id)
                )
            )
            == 1
        )
        assert db.scalar(
            select(func.count(Memory.id)).where(Memory.id == UUID(memory_id))
        ) == 1


def test_asr_logprob_confidence_is_server_derived():
    value = confidence_from_logprobs(
        [
            {"token": "明天", "logprob": log(0.90)},
            {"token": "复查", "logprob": log(0.81)},
        ]
    )
    assert value == pytest.approx((0.90 * 0.81) ** 0.5)

    with pytest.raises(ASRProviderError, match="ASR_CONFIDENCE_MISSING"):
        confidence_from_logprobs([])
