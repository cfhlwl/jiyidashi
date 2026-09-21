import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.db import SessionLocal
from app.main import app
from app.media_models import MediaAsset, MediaKind, MediaStatus
from app.models import Memory, MemorySource, ObjectItem, Place, Reminder, Visit
from app.services.ai_gateway import (
    AIGateway,
    AIImageInferenceRequest,
    AIInferenceRequest,
    AIPolicyError,
    AIProviderError,
    AIProviderResult,
    AITransportError,
    DeterministicAIProvider,
    OpenAIResponsesProvider,
    get_ai_gateway,
)
from app.services.object_storage import (
    ObjectNotFound,
    ObjectStorageError,
    get_object_storage,
)


class FakeOCRStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.reads: list[tuple[str, int]] = []
        self.fail = False

    def read_object(self, object_key: str, max_bytes: int) -> bytes:
        self.reads.append((object_key, max_bytes))
        if self.fail:
            raise ObjectStorageError("synthetic storage failure")
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
def ocr_dependencies():
    storage = FakeOCRStorage()
    provider = DeterministicAIProvider(
        output_text=json.dumps(
            {
                "blocks": [
                    {"text": "银行卡在书房抽屉"},
                    {"text": "仅供 OCR 测试"},
                ]
            },
            ensure_ascii=False,
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
    storage: FakeOCRStorage,
    *,
    user_id: UUID,
    kind: MediaKind = MediaKind.IMAGE,
    status: MediaStatus = MediaStatus.READY,
    content_type: str = "image/jpeg",
    data: bytes = b"\xff\xd8\xffocr-test-image",
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
        storage_etag="ocr-test-etag",
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
async def test_explicit_ocr_returns_inference_provenance_without_persistence(
    client,
    ocr_dependencies,
):
    storage, provider, _ = ocr_dependencies
    user_id, headers = await _new_user(client, "ocr-owner")
    image = b"\xff\xd8\xffprivate-image-bytes"
    media_id = _insert_media(storage, user_id=user_id, data=image)
    before = _owner_counts(user_id)

    assert provider.image_requests == []
    response = await client.post(f"/v1/media/{media_id}/ocr", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["media_id"] == str(media_id)
    assert body["text"] == "银行卡在书房抽屉\n仅供 OCR 测试"
    assert body["blocks"] == [
        {"index": 0, "text": "银行卡在书房抽屉"},
        {"index": 1, "text": "仅供 OCR 测试"},
    ]
    assert body["provenance"]["source_media_id"] == str(media_id)
    assert body["provenance"]["purpose"] == "ocr.extract"
    assert body["provenance"]["trust_class"] == "inference"
    assert body["provenance"]["provider"] == "deterministic"
    assert body["provenance"]["model"] == "fixture"
    assert body["provenance"]["provider_request_id"] == "deterministic-image-request"
    assert body["provenance"]["gateway_request_id"]

    assert len(provider.image_requests) == 1
    request = provider.image_requests[0]
    assert request.purpose == "ocr.extract"
    assert request.image_bytes == image
    assert request.content_type == "image/jpeg"
    assert request.detail == "high"
    assert storage.reads and storage.reads[0][0].endswith(media_id.hex)

    assert _owner_counts(user_id) == before
    query = await client.post(
        "/v1/memory/query",
        headers=headers,
        json={"question": "银行卡抽屉"},
    )
    assert query.status_code == 200
    query_body = query.json()
    assert query_body["can_answer"] is False
    assert query_body["reason"] == "NO_EVIDENCE"
    assert query_body["memory_ids"] == []


@pytest.mark.asyncio
async def test_ocr_is_owner_scoped_and_cross_owner_is_not_an_existence_oracle(
    client,
    ocr_dependencies,
):
    storage, provider, _ = ocr_dependencies
    owner_id, _ = await _new_user(client, "ocr-owner-a")
    _, other_headers = await _new_user(client, "ocr-owner-b")
    media_id = _insert_media(storage, user_id=owner_id)

    response = await client.post(f"/v1/media/{media_id}/ocr", headers=other_headers)

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
async def test_ocr_rejects_invalid_media_state_before_storage_or_provider(
    client,
    ocr_dependencies,
    kind,
    status,
    completed,
    expected_detail,
):
    storage, provider, _ = ocr_dependencies
    user_id, headers = await _new_user(client, f"ocr-state-{uuid4()}")
    media_id = _insert_media(
        storage,
        user_id=user_id,
        kind=kind,
        status=status,
        content_type="audio/mpeg" if kind == MediaKind.AUDIO else "image/jpeg",
        completed=completed,
    )

    response = await client.post(f"/v1/media/{media_id}/ocr", headers=headers)

    assert response.status_code == 409
    assert response.json()["detail"] == expected_detail
    assert provider.image_requests == []
    assert storage.reads == []


@pytest.mark.asyncio
async def test_ocr_rejects_heic_until_a_trusted_server_conversion_boundary_exists(
    client,
    ocr_dependencies,
):
    storage, provider, _ = ocr_dependencies
    user_id, headers = await _new_user(client, "ocr-heic")
    media_id = _insert_media(
        storage,
        user_id=user_id,
        content_type="image/heic",
        data=b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic",
    )

    response = await client.post(f"/v1/media/{media_id}/ocr", headers=headers)

    assert response.status_code == 415
    assert response.json()["detail"] == "OCR_CONTENT_TYPE_UNSUPPORTED"
    assert provider.image_requests == []
    assert storage.reads == []


@pytest.mark.asyncio
async def test_ocr_rechecks_final_object_size_before_model_input(
    client,
    ocr_dependencies,
):
    storage, provider, _ = ocr_dependencies
    user_id, headers = await _new_user(client, "ocr-size-mismatch")
    data = b"\xff\xd8\xffactual"
    media_id = _insert_media(
        storage,
        user_id=user_id,
        data=data,
        recorded_size=len(data) + 5,
    )

    response = await client.post(f"/v1/media/{media_id}/ocr", headers=headers)

    assert response.status_code == 409
    assert response.json()["detail"] == "MEDIA_OBJECT_SIZE_MISMATCH"
    assert provider.image_requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_output",
    [
        "not-json",
        json.dumps({"text": "not the contract"}),
        json.dumps({"blocks": [{"text": "visible", "confidence": 0.99}]}),
        json.dumps({"blocks": [{"text": "   "}]}),
        json.dumps({"blocks": "visible"}),
    ],
)
async def test_malformed_ocr_provider_output_fails_closed(
    client,
    ocr_dependencies,
    provider_output,
):
    storage, provider, _ = ocr_dependencies
    user_id, headers = await _new_user(client, f"ocr-malformed-{uuid4()}")
    media_id = _insert_media(storage, user_id=user_id)
    provider.output_text = provider_output

    response = await client.post(f"/v1/media/{media_id}/ocr", headers=headers)

    assert response.status_code == 502
    assert response.json()["detail"] == "OCR_PROVIDER_INVALID_RESPONSE"


@pytest.mark.asyncio
async def test_empty_ocr_result_is_explicit_and_never_fabricates_fallback_text(
    client,
    ocr_dependencies,
):
    storage, provider, _ = ocr_dependencies
    user_id, headers = await _new_user(client, "ocr-empty")
    media_id = _insert_media(storage, user_id=user_id)
    provider.output_text = json.dumps({"blocks": []})

    response = await client.post(f"/v1/media/{media_id}/ocr", headers=headers)

    assert response.status_code == 200
    assert response.json()["text"] == ""
    assert response.json()["blocks"] == []
    assert response.json()["provenance"]["trust_class"] == "inference"


@pytest.mark.asyncio
async def test_ocr_combined_output_is_bounded(
    client,
    ocr_dependencies,
):
    storage, provider, _ = ocr_dependencies
    user_id, headers = await _new_user(client, "ocr-output-bound")
    media_id = _insert_media(storage, user_id=user_id)
    provider.output_text = json.dumps(
        {"blocks": [{"text": "x" * 3500} for _ in range(6)]}
    )

    response = await client.post(f"/v1/media/{media_id}/ocr", headers=headers)

    assert response.status_code == 502
    assert response.json()["detail"] == "OCR_OUTPUT_TOO_LARGE"


class _FailingImageProvider:
    async def infer(self, request: AIInferenceRequest) -> AIProviderResult:
        del request
        raise AssertionError("text inference is not used by OCR")

    async def infer_image(self, request: AIImageInferenceRequest) -> AIProviderResult:
        del request
        raise AIProviderError("AI_PROVIDER_FAILED", status_code=500, retryable=True)


class _TimeoutImageProvider:
    async def infer(self, request: AIInferenceRequest) -> AIProviderResult:
        del request
        raise AssertionError("text inference is not used by OCR")

    async def infer_image(self, request: AIImageInferenceRequest) -> AIProviderResult:
        del request
        await asyncio.sleep(2)
        raise AssertionError("unreachable")


class _MutatingImageProvider:
    def __init__(self, media_id: UUID):
        self.media_id = media_id

    async def infer(self, request: AIInferenceRequest) -> AIProviderResult:
        del request
        raise AssertionError("text inference is not used by OCR")

    async def infer_image(self, request: AIImageInferenceRequest) -> AIProviderResult:
        del request
        with SessionLocal() as db:
            asset = db.get(MediaAsset, self.media_id)
            assert asset is not None
            asset.size_bytes += 1
            db.commit()
        return AIProviderResult(
            output_text='{"blocks":[{"text":"stale result"}]}',
            provider="mutating-test",
            model="fixture",
            provider_request_id="mutating-request",
        )


@pytest.mark.asyncio
async def test_ocr_provider_failure_is_fail_closed(
    client,
    ocr_dependencies,
):
    storage, _, _ = ocr_dependencies
    user_id, headers = await _new_user(client, "ocr-provider-failure")
    media_id = _insert_media(storage, user_id=user_id)
    gateway = AIGateway(_gateway_settings(), _FailingImageProvider())
    app.dependency_overrides[get_ai_gateway] = lambda: gateway

    response = await client.post(f"/v1/media/{media_id}/ocr", headers=headers)

    assert response.status_code == 502
    assert response.json()["detail"] == "OCR_PROVIDER_FAILED"


@pytest.mark.asyncio
async def test_image_gateway_enforces_wall_clock_timeout_for_provider_seams():
    gateway = AIGateway(_gateway_settings(ai_timeout_seconds=1.0), _TimeoutImageProvider())

    with pytest.raises(AITransportError, match="AI_GATEWAY_TIMEOUT"):
        await gateway.infer_image(
            AIImageInferenceRequest(
                purpose="ocr.extract",
                system_instruction="Return OCR JSON.",
                input_text="Read visible text.",
                image_bytes=b"\xff\xd8\xffimage",
                content_type="image/jpeg",
            )
        )


@pytest.mark.asyncio
async def test_image_gateway_rejects_oversized_input_before_provider():
    provider = DeterministicAIProvider(output_text='{"blocks":[]}')
    gateway = AIGateway(
        _gateway_settings(media_max_image_bytes=4),
        provider,
    )

    with pytest.raises(AIPolicyError, match="AI_IMAGE_TOO_LARGE"):
        await gateway.infer_image(
            AIImageInferenceRequest(
                purpose="ocr.extract",
                system_instruction="Return OCR JSON.",
                input_text="Read visible text.",
                image_bytes=b"12345",
                content_type="image/jpeg",
            )
        )

    assert provider.image_requests == []


@pytest.mark.asyncio
async def test_media_change_during_ocr_fails_closed_on_final_revalidation(
    client,
    ocr_dependencies,
):
    storage, _, _ = ocr_dependencies
    user_id, headers = await _new_user(client, "ocr-media-race")
    media_id = _insert_media(storage, user_id=user_id)
    before = _owner_counts(user_id)
    gateway = AIGateway(_gateway_settings(), _MutatingImageProvider(media_id))
    app.dependency_overrides[get_ai_gateway] = lambda: gateway

    response = await client.post(f"/v1/media/{media_id}/ocr", headers=headers)

    assert response.status_code == 409
    assert response.json()["detail"] == "OCR_MEDIA_CHANGED_DURING_EXTRACTION"
    assert _owner_counts(user_id) == before


@pytest.mark.asyncio
async def test_openai_image_adapter_keeps_image_and_credentials_inside_gateway():
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "resp_ocr_123",
                "model": "vision-model-2026-09",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"blocks":[{"text":"发票号码 123"}]}',
                            }
                        ],
                    }
                ],
                "usage": {"input_tokens": 30, "output_tokens": 12},
            },
            request=request,
        )

    settings = _gateway_settings(
        ai_provider="openai",
        ai_api_key="server-only-test-key",
        ai_model="vision-model",
        ai_base_url="https://api.openai.test/v1",
    )
    provider = OpenAIResponsesProvider(
        settings,
        transport=httpx.MockTransport(handler),
    )
    gateway = AIGateway(settings, provider)

    result = await gateway.infer_image(
        AIImageInferenceRequest(
            purpose="ocr.extract",
            system_instruction="Return OCR JSON only.",
            input_text="Read visible text.",
            image_bytes=b"\xff\xd8\xffprivate",
            content_type="image/jpeg",
            detail="high",
            max_output_tokens=128,
        )
    )

    assert seen["authorization"] == "Bearer server-only-test-key"
    body = seen["body"]
    assert body["store"] is False
    assert body["model"] == "vision-model"
    assert body["input"][0]["content"][0] == {
        "type": "input_text",
        "text": "Read visible text.",
    }
    image_part = body["input"][0]["content"][1]
    assert image_part["type"] == "input_image"
    assert image_part["detail"] == "high"
    assert image_part["image_url"].startswith("data:image/jpeg;base64,")
    assert result.output_text == '{"blocks":[{"text":"发票号码 123"}]}'
    assert result.trust_class == "inference"
    assert result.provenance.provider == "openai"
    assert result.provenance.provider_request_id == "resp_ocr_123"
