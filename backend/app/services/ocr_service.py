from __future__ import annotations

import asyncio
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.media_models import MediaAsset, MediaKind, MediaStatus
from app.ocr_models import OCRBlock, OCRProvenance, OCRRequest, OCRResult
from app.services.ai_gateway import (
    AIGateway,
    AIGatewayError,
    AIImageInferenceRequest,
)
from app.services.object_storage import ObjectNotFound, ObjectStorage, ObjectStorageError

_OCR_PURPOSE = "ocr.extract"
_OCR_MAX_BLOCKS = 200
_OCR_MAX_BLOCK_CHARS = 4000
_OCR_MAX_TEXT_CHARS = 20000
_SUPPORTED_OCR_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}

_SYSTEM_INSTRUCTION = """You are an OCR extraction component.
Read only text that is visibly present in the supplied image.
Do not infer people, places, objects, events, intent, meaning, or missing words.
Do not summarize, translate, explain, normalize facts, or invent fallback text.
Return exactly one JSON object with this shape:
{"blocks":[{"text":"visible text in reading order"}]}
Return blocks in reading order. If no text is visible, return {"blocks":[]}.
Do not return markdown, confidence, IDs, coordinates, owner data, or extra fields.
"""


class OCRError(RuntimeError):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class OCRMediaSnapshot:
    object_key: str
    content_type: str
    size_bytes: int


class _ProviderOCRBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=_OCR_MAX_BLOCK_CHARS)


class _ProviderOCRPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    blocks: list[_ProviderOCRBlock] = Field(
        default_factory=list,
        max_length=_OCR_MAX_BLOCKS,
    )


def _normalize_content_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()


def _snapshot_image(
    db: Session,
    *,
    user_id,
    media_id,
    for_update: bool = False,
) -> OCRMediaSnapshot:
    # [人工注释][S3-006] OCR 只能按认证 owner + opaque media_id 读取既有媒体。
    # object_key 只来自数据库，客户端不能提交 URL/key/provider 来绕过私有存储边界。
    query = select(MediaAsset).where(
        MediaAsset.id == media_id,
        MediaAsset.user_id == user_id,
    )
    if for_update:
        query = query.with_for_update()

    with db.no_autoflush:
        asset = db.scalar(query)

    if asset is None:
        raise OCRError("MEDIA_NOT_FOUND", 404)
    if asset.status != MediaStatus.READY or asset.completed_at is None:
        raise OCRError("MEDIA_NOT_READY", 409)
    if asset.kind != MediaKind.IMAGE:
        raise OCRError("MEDIA_KIND_MISMATCH", 409)

    settings = get_settings()
    if asset.size_bytes > settings.media_max_image_bytes:
        raise OCRError("MEDIA_TOO_LARGE", 413)

    content_type = _normalize_content_type(asset.content_type)
    if content_type not in _SUPPORTED_OCR_CONTENT_TYPES:
        # Existing media may legitimately be HEIC/HEIF. Until a trusted server-side
        # conversion boundary exists, do not send an unsupported encoding to a model
        # and do not silently reinterpret its bytes as another image type.
        raise OCRError("OCR_CONTENT_TYPE_UNSUPPORTED", 415)

    return OCRMediaSnapshot(
        object_key=asset.object_key,
        content_type=content_type,
        size_bytes=asset.size_bytes,
    )


async def _read_image(
    storage: ObjectStorage,
    *,
    object_key: str,
    size_bytes: int,
) -> bytes:
    settings = get_settings()
    try:
        image = await asyncio.to_thread(
            storage.read_object,
            object_key,
            settings.media_max_image_bytes,
        )
    except ObjectNotFound as exc:
        raise OCRError("MEDIA_OBJECT_NOT_FOUND", 409) from exc
    except ObjectStorageError as exc:
        raise OCRError("MEDIA_STORAGE_UNAVAILABLE", 503) from exc

    # READY metadata was verified at upload completion, but the OCR read still checks
    # the exact byte length so a changed/missing final object cannot become model input.
    if len(image) != size_bytes:
        raise OCRError("MEDIA_OBJECT_SIZE_MISMATCH", 409)
    return image


def _provider_error(exc: AIGatewayError) -> OCRError:
    mapping = {
        "AI_PROVIDER_UNAVAILABLE": ("OCR_PROVIDER_UNAVAILABLE", 503),
        "AI_GATEWAY_TIMEOUT": ("OCR_TIMEOUT", 504),
        "AI_GATEWAY_TRANSPORT_ERROR": ("OCR_PROVIDER_UNAVAILABLE", 503),
        "AI_PROVIDER_FAILED": ("OCR_PROVIDER_FAILED", 502),
        "AI_PROVIDER_INCOMPLETE": ("OCR_PROVIDER_FAILED", 502),
        "AI_PROVIDER_INVALID_RESPONSE": ("OCR_PROVIDER_INVALID_RESPONSE", 502),
        "AI_PROVIDER_REFUSAL": ("OCR_PROVIDER_REFUSAL", 422),
        "AI_IMAGE_EMPTY": ("OCR_IMAGE_INVALID", 422),
        "AI_IMAGE_TOO_LARGE": ("MEDIA_TOO_LARGE", 413),
        "AI_IMAGE_TYPE_UNSUPPORTED": ("OCR_CONTENT_TYPE_UNSUPPORTED", 415),
    }
    code, status_code = mapping.get(exc.code, ("OCR_PROVIDER_FAILED", 502))
    return OCRError(code, status_code)


def _parse_provider_output(*, media_id, inference) -> OCRResult:
    try:
        payload = _ProviderOCRPayload.model_validate_json(inference.output_text)
    except (ValidationError, ValueError) as exc:
        raise OCRError("OCR_PROVIDER_INVALID_RESPONSE", 502) from exc

    blocks: list[OCRBlock] = []
    for index, raw in enumerate(payload.blocks):
        text = raw.text.strip()
        if not text:
            raise OCRError("OCR_PROVIDER_INVALID_RESPONSE", 502)
        blocks.append(OCRBlock(index=index, text=text))

    joined = "\n".join(block.text for block in blocks)
    if len(joined) > _OCR_MAX_TEXT_CHARS:
        raise OCRError("OCR_OUTPUT_TOO_LARGE", 502)

    return OCRResult(
        media_id=media_id,
        text=joined,
        blocks=blocks,
        provenance=OCRProvenance(
            source_media_id=media_id,
            gateway_request_id=inference.provenance.gateway_request_id,
            provider_request_id=inference.provenance.provider_request_id,
            provider=inference.provenance.provider,
            model=inference.provenance.model,
            purpose=_OCR_PURPOSE,
            trust_class="inference",
            input_tokens=inference.usage.input_tokens,
            output_tokens=inference.usage.output_tokens,
        ),
    )


async def extract_ocr(
    db: Session,
    *,
    user_id,
    request: OCRRequest,
    storage: ObjectStorage,
    gateway: AIGateway,
) -> OCRResult:
    # This endpoint is the user-trigger boundary. Merely uploading/completing a photo
    # never calls this function, and this function never writes Memory/Evidence/entities.
    #
    # Keep provider/storage I/O outside a database transaction. The authenticated request
    # holds a user-data admission lock, so Phase 1 takes a stable Media snapshot and commits
    # the read-only transaction before any slow I/O. Phase 3 re-locks and revalidates the
    # Media plus the deletion generation before the inference may be returned.
    snapshot = _snapshot_image(
        db,
        user_id=user_id,
        media_id=request.media_id,
        for_update=True,
    )
    db.commit()

    image = await _read_image(
        storage,
        object_key=snapshot.object_key,
        size_bytes=snapshot.size_bytes,
    )

    try:
        inference = await gateway.infer_image(
            AIImageInferenceRequest(
                purpose=_OCR_PURPOSE,
                system_instruction=_SYSTEM_INSTRUCTION,
                input_text=(
                    "Extract only the visible text from this user-selected image "
                    "using the required JSON blocks contract."
                ),
                image_bytes=image,
                content_type=snapshot.content_type,
                detail="high",
                max_output_tokens=None,
            )
        )
    except AIGatewayError as exc:
        raise _provider_error(exc) from exc

    result = _parse_provider_output(media_id=request.media_id, inference=inference)

    current = _snapshot_image(
        db,
        user_id=user_id,
        media_id=request.media_id,
        for_update=True,
    )
    if current != snapshot:
        db.rollback()
        raise OCRError("OCR_MEDIA_CHANGED_DURING_EXTRACTION", 409)

    # GuardedSession.commit() rechecks account/data-deletion generation. This is a
    # read-only commit: OCR still creates no Memory, Evidence, entity or other row.
    db.commit()
    return result
