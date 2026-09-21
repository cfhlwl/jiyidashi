import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.db import SessionLocal
from app.data_deletion_models import DataDeletionOperation, DataDeletionStatus
from app.main import app
from app.media_models import MediaAsset, MediaKind, MediaStatus
from app.models import Memory, MemorySource, ObjectItem, Place, Reminder, Visit
from app.services.ai_gateway import (
    AIGateway,
    AIImageInferenceRequest,
    AIInferenceRequest,
    AIProviderError,
    AIProviderResult,
    DeterministicAIProvider,
    get_ai_gateway,
)
from app.services.object_storage import (
    ObjectNotFound,
    ObjectStorageError,
    get_object_storage,
)


class FakeVisionStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.reads: list[tuple[str, int]] = []

    def read_object(self, object_key: str, max_bytes: int) -> bytes:
        self.reads.append((object_key, max_bytes))
        if object_key not in self.objects:
            raise ObjectNotFound("missing")
        data = self.objects[object_key]
        if len(data) > max_bytes:
            raise ObjectStorageError("object exceeds bounded read")
        return data


def _gateway_settings(**overrides) -> Settings:
    values = {
        "app_env": "test",
        "ai_provider": "disabled",
        "ai_timeout_seconds": 1.0,
        "ai_max_input_chars": 10000,
        "ai_max_output_tokens": 1024,
        "media_max_image_bytes": 1024 * 1024,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def vision_dependencies():
    storage = FakeVisionStorage()
    provider = DeterministicAIProvider(
        output_text=json.dumps(
            {
                "observations": [
                    {"kind": "SCENE", "code": "INDOOR"},
                    {"kind": "OBJECT", "code": "BAG"},
                    {"kind": "ACTIVITY", "code": "PERSON_SITTING"},
                ]
            }
        )
    )
    gateway = AIGateway(_gateway_settings(), provider)
    app.dependency_overrides[get_object_storage] = lambda: storage
    app.dependency_overrides[get_ai_gateway] = lambda: gateway
    yield storage, provider, gateway
    app.dependency_overrides.pop(get_object_storage, None)
    app.dependency_overrides.pop(get_ai_gateway, None)


async def _new_user(client, nickname: str) -> tuple[UUID, dict[str, str]]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    body = response.json()
    return UUID(body["user_id"]), {"Authorization": f"Bearer {body['access_token']}"}


def _insert_media(
    storage: FakeVisionStorage,
    *,
    user_id: UUID,
    kind: MediaKind = MediaKind.IMAGE,
    status: MediaStatus = MediaStatus.READY,
    content_type: str = "image/jpeg",
    data: bytes = b"\xff\xd8\xffvision-test-image",
    completed: bool = True,
    recorded_size: int | None = None,
) -> UUID:
    media_id = uuid4()
    object_key = f"media/{user_id}/{media_id.hex}"
    asset = MediaAsset(
        id=media_id,
        user_id=user_id,
        client_upload_id=uuid4(),
        kind=kind,
        status=status,
        upload_object_key=f"media/_staging/{user_id}/{media_id.hex}/{uuid4().hex}",
        object_key=object_key,
        content_type=content_type,
        size_bytes=len(data) if recorded_size is None else recorded_size,
        original_filename="selected-image.jpg",
        storage_etag="vision-test-etag",
        completed_at=(
            datetime.now(UTC)
            if completed and status == MediaStatus.READY
            else None
        ),
    )
    with SessionLocal() as db:
        db.add(asset)
        db.commit()
    storage.objects[object_key] = data
    return media_id


def _owner_counts(user_id: UUID) -> dict[str, int]:
    with SessionLocal() as db:
        return {
            "memories": db.scalar(
                select(func.count()).select_from(Memory).where(Memory.user_id == user_id)
            ),
            "sources": db.scalar(
                select(func.count())
                .select_from(MemorySource)
                .join(Memory, Memory.id == MemorySource.memory_id)
                .where(Memory.user_id == user_id)
            ),
            "objects": db.scalar(
                select(func.count()).select_from(ObjectItem).where(ObjectItem.user_id == user_id)
            ),
            "places": db.scalar(
                select(func.count()).select_from(Place).where(Place.user_id == user_id)
            ),
            "visits": db.scalar(
                select(func.count()).select_from(Visit).where(Visit.user_id == user_id)
            ),
            "reminders": db.scalar(
                select(func.count()).select_from(Reminder).where(Reminder.user_id == user_id)
            ),
        }


@pytest.mark.asyncio
async def test_explicit_vision_returns_server_owned_labels_without_persistence(
    client,
    vision_dependencies,
):
    storage, provider, _ = vision_dependencies
    user_id, headers = await _new_user(client, "vision-owner")
    image = b"\xff\xd8\xffprivate-vision-image"
    media_id = _insert_media(storage, user_id=user_id, data=image)
    before = _owner_counts(user_id)

    response = await client.post(
        f"/v1/media/{media_id}/vision",
        headers=headers,
        json={
            "object_key": "attacker-controlled",
            "provider": "attacker-provider",
            "trust_class": "confirmed",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["media_id"] == str(media_id)
    assert body["observations"] == [
        {
            "index": 0,
            "kind": "SCENE",
            "code": "INDOOR",
            "label": "indoor scene",
            "trust_class": "inference",
        },
        {
            "index": 1,
            "kind": "OBJECT",
            "code": "BAG",
            "label": "bag",
            "trust_class": "inference",
        },
        {
            "index": 2,
            "kind": "ACTIVITY",
            "code": "PERSON_SITTING",
            "label": "person sitting",
            "trust_class": "inference",
        },
    ]
    assert body["provenance"]["source_media_id"] == str(media_id)
    assert body["provenance"]["purpose"] == "vision.observe"
    assert body["provenance"]["trust_class"] == "inference"
    assert body["provenance"]["provider"] == "deterministic"
    assert body["provenance"]["model"] == "fixture"

    assert len(provider.image_requests) == 1
    request = provider.image_requests[0]
    assert request.purpose == "vision.observe"
    assert request.image_bytes == image
    assert request.content_type == "image/jpeg"
    assert request.detail == "high"
    assert request.max_output_tokens == 512
    assert "Do not perform OCR" in request.system_instruction
    assert "Do not identify people" in request.system_instruction
    assert storage.reads and storage.reads[0][0].endswith(media_id.hex)

    assert _owner_counts(user_id) == before
    query = await client.post(
        "/v1/memory/query",
        headers=headers,
        json={"question": "bag"},
    )
    assert query.status_code == 200
    assert query.json()["can_answer"] is False
    assert query.json()["reason"] == "NO_EVIDENCE"
    assert query.json()["memory_ids"] == []


@pytest.mark.asyncio
async def test_vision_cross_owner_is_not_an_existence_oracle(
    client,
    vision_dependencies,
):
    storage, provider, _ = vision_dependencies
    owner_id, _ = await _new_user(client, "vision-owner-a")
    _, other_headers = await _new_user(client, "vision-owner-b")
    media_id = _insert_media(storage, user_id=owner_id)

    response = await client.post(f"/v1/media/{media_id}/vision", headers=other_headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "MEDIA_NOT_FOUND"
    assert provider.image_requests == []
    assert storage.reads == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "status", "completed", "expected_detail"),
    [
        (MediaKind.IMAGE, MediaStatus.PENDING, False, "MEDIA_NOT_READY"),
        (MediaKind.IMAGE, MediaStatus.READY, False, "MEDIA_NOT_READY"),
        (MediaKind.AUDIO, MediaStatus.READY, True, "MEDIA_KIND_MISMATCH"),
    ],
)
async def test_vision_rejects_invalid_media_state_before_io(
    client,
    vision_dependencies,
    kind,
    status,
    completed,
    expected_detail,
):
    storage, provider, _ = vision_dependencies
    user_id, headers = await _new_user(client, f"vision-state-{uuid4()}")
    media_id = _insert_media(
        storage,
        user_id=user_id,
        kind=kind,
        status=status,
        content_type="audio/mpeg" if kind == MediaKind.AUDIO else "image/jpeg",
        completed=completed,
    )

    response = await client.post(f"/v1/media/{media_id}/vision", headers=headers)

    assert response.status_code == 409
    assert response.json()["detail"] == expected_detail
    assert provider.image_requests == []
    assert storage.reads == []


@pytest.mark.asyncio
async def test_vision_rejects_heic_before_storage_or_provider(
    client,
    vision_dependencies,
):
    storage, provider, _ = vision_dependencies
    user_id, headers = await _new_user(client, "vision-heic")
    media_id = _insert_media(
        storage,
        user_id=user_id,
        content_type="image/heic",
        data=b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic",
    )

    response = await client.post(f"/v1/media/{media_id}/vision", headers=headers)

    assert response.status_code == 415
    assert response.json()["detail"] == "VISION_CONTENT_TYPE_UNSUPPORTED"
    assert provider.image_requests == []
    assert storage.reads == []


@pytest.mark.asyncio
async def test_vision_rechecks_final_object_size_before_provider(
    client,
    vision_dependencies,
):
    storage, provider, _ = vision_dependencies
    user_id, headers = await _new_user(client, "vision-size-mismatch")
    data = b"\xff\xd8\xffactual"
    media_id = _insert_media(
        storage,
        user_id=user_id,
        data=data,
        recorded_size=len(data) + 1,
    )

    response = await client.post(f"/v1/media/{media_id}/vision", headers=headers)

    assert response.status_code == 409
    assert response.json()["detail"] == "MEDIA_OBJECT_SIZE_MISMATCH"
    assert provider.image_requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_output",
    [
        "not-json",
        json.dumps({"scene": "room"}),
        json.dumps({"observations": "room"}),
        json.dumps({"observations": [{"kind": "PERSON", "code": "PERSON"}]}),
        json.dumps({"observations": [{"kind": "OBJECT", "code": "ALICE"}]}),
        json.dumps(
            {
                "observations": [
                    {"kind": "OBJECT", "code": "PERSON", "identity": "Alice"}
                ]
            }
        ),
        json.dumps(
            {
                "observations": [
                    {"kind": "SCENE", "code": "STREET_LIKE", "address": "123 Main St"}
                ]
            }
        ),
        json.dumps(
            {
                "observations": [
                    {"kind": "OBJECT", "code": "PERSON", "confidence": 0.99}
                ]
            }
        ),
        json.dumps({"observations": [{"kind": "OBJECT", "code": "INDOOR"}]}),
    ],
)
async def test_vision_rejects_untrusted_or_extra_provider_semantics(
    client,
    vision_dependencies,
    provider_output,
):
    storage, provider, _ = vision_dependencies
    user_id, headers = await _new_user(client, f"vision-malformed-{uuid4()}")
    media_id = _insert_media(storage, user_id=user_id)
    provider.output_text = provider_output

    response = await client.post(f"/v1/media/{media_id}/vision", headers=headers)

    assert response.status_code == 502
    assert response.json()["detail"] == "VISION_PROVIDER_INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_vision_rejects_duplicate_observations(client, vision_dependencies):
    storage, provider, _ = vision_dependencies
    user_id, headers = await _new_user(client, "vision-duplicates")
    media_id = _insert_media(storage, user_id=user_id)
    provider.output_text = json.dumps(
        {
            "observations": [
                {"kind": "OBJECT", "code": "BAG"},
                {"kind": "OBJECT", "code": "BAG"},
            ]
        }
    )

    response = await client.post(f"/v1/media/{media_id}/vision", headers=headers)

    assert response.status_code == 502
    assert response.json()["detail"] == "VISION_PROVIDER_INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_vision_provider_output_is_bounded(client, vision_dependencies):
    storage, provider, _ = vision_dependencies
    user_id, headers = await _new_user(client, "vision-output-bound")
    media_id = _insert_media(storage, user_id=user_id)
    provider.output_text = json.dumps(
        {
            "observations": [
                {"kind": "OBJECT", "code": "X" * 13000}
            ]
        }
    )

    response = await client.post(f"/v1/media/{media_id}/vision", headers=headers)

    assert response.status_code == 502
    assert response.json()["detail"] == "VISION_OUTPUT_TOO_LARGE"


class _FailingImageProvider:
    async def infer(self, request: AIInferenceRequest) -> AIProviderResult:
        del request
        raise AssertionError("text inference is not used by Vision")

    async def infer_image(self, request: AIImageInferenceRequest) -> AIProviderResult:
        del request
        raise AIProviderError("AI_PROVIDER_FAILED", status_code=500, retryable=True)


class _TimeoutImageProvider:
    async def infer(self, request: AIInferenceRequest) -> AIProviderResult:
        del request
        raise AssertionError("text inference is not used by Vision")

    async def infer_image(self, request: AIImageInferenceRequest) -> AIProviderResult:
        del request
        await asyncio.sleep(2)
        raise AssertionError("unreachable")


class _MutatingImageProvider:
    def __init__(self, media_id: UUID):
        self.media_id = media_id

    async def infer(self, request: AIInferenceRequest) -> AIProviderResult:
        del request
        raise AssertionError("text inference is not used by Vision")

    async def infer_image(self, request: AIImageInferenceRequest) -> AIProviderResult:
        del request
        with SessionLocal() as db:
            asset = db.get(MediaAsset, self.media_id)
            assert asset is not None
            asset.size_bytes += 1
            db.commit()
        return AIProviderResult(
            output_text='{"observations":[{"kind":"OBJECT","code":"BAG"}]}',
            provider="mutating-test",
            model="fixture",
            provider_request_id="mutating-request",
        )


class _DeletionGenerationProvider:
    def __init__(self, user_id: UUID):
        self.user_id = user_id

    async def infer(self, request: AIInferenceRequest) -> AIProviderResult:
        del request
        raise AssertionError("text inference is not used by Vision")

    async def infer_image(self, request: AIImageInferenceRequest) -> AIProviderResult:
        del request
        with SessionLocal() as db:
            db.add(
                DataDeletionOperation(
                    user_id=self.user_id,
                    request_id=uuid4(),
                    status=DataDeletionStatus.COMPLETED,
                    deleted_counts={},
                    completed_at=datetime.now(UTC),
                )
            )
            db.commit()
        return AIProviderResult(
            output_text='{"observations":[{"kind":"OBJECT","code":"BAG"}]}',
            provider="generation-test",
            model="fixture",
            provider_request_id="generation-request",
        )


@pytest.mark.asyncio
async def test_vision_provider_failure_is_fail_closed(client, vision_dependencies):
    storage, _, _ = vision_dependencies
    user_id, headers = await _new_user(client, "vision-provider-failure")
    media_id = _insert_media(storage, user_id=user_id)
    app.dependency_overrides[get_ai_gateway] = lambda: AIGateway(
        _gateway_settings(),
        _FailingImageProvider(),
    )

    response = await client.post(f"/v1/media/{media_id}/vision", headers=headers)

    assert response.status_code == 502
    assert response.json()["detail"] == "VISION_PROVIDER_FAILED"


@pytest.mark.asyncio
async def test_vision_timeout_is_fail_closed(client, vision_dependencies):
    storage, _, _ = vision_dependencies
    user_id, headers = await _new_user(client, "vision-timeout")
    media_id = _insert_media(storage, user_id=user_id)
    app.dependency_overrides[get_ai_gateway] = lambda: AIGateway(
        _gateway_settings(ai_timeout_seconds=1.0),
        _TimeoutImageProvider(),
    )

    response = await client.post(f"/v1/media/{media_id}/vision", headers=headers)

    assert response.status_code == 504
    assert response.json()["detail"] == "VISION_TIMEOUT"


@pytest.mark.asyncio
async def test_media_change_during_vision_fails_closed(
    client,
    vision_dependencies,
):
    storage, _, _ = vision_dependencies
    user_id, headers = await _new_user(client, "vision-media-race")
    media_id = _insert_media(storage, user_id=user_id)
    before = _owner_counts(user_id)
    app.dependency_overrides[get_ai_gateway] = lambda: AIGateway(
        _gateway_settings(),
        _MutatingImageProvider(media_id),
    )

    response = await client.post(f"/v1/media/{media_id}/vision", headers=headers)

    assert response.status_code == 409
    assert response.json()["detail"] == "VISION_MEDIA_CHANGED_DURING_INFERENCE"
    assert _owner_counts(user_id) == before


@pytest.mark.asyncio
async def test_deletion_generation_change_blocks_vision_result(
    client,
    vision_dependencies,
):
    storage, _, _ = vision_dependencies
    user_id, headers = await _new_user(client, "vision-deletion-generation")
    media_id = _insert_media(storage, user_id=user_id)
    app.dependency_overrides[get_ai_gateway] = lambda: AIGateway(
        _gateway_settings(),
        _DeletionGenerationProvider(user_id),
    )

    response = await client.post(f"/v1/media/{media_id}/vision", headers=headers)

    assert response.status_code == 409
    assert response.json()["detail"] == "DATA_DELETION_REQUEST_STALE"
