from __future__ import annotations

import asyncio
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.media_models import MediaAsset, MediaKind, MediaStatus
from app.services.ai_gateway import (
    AIGateway,
    AIGatewayError,
    AIImageInferenceRequest,
)
from app.services.object_storage import ObjectNotFound, ObjectStorage, ObjectStorageError
from app.vision_models import (
    VisionObservation,
    VisionObservationCode,
    VisionObservationKind,
    VisionProvenance,
    VisionRequest,
    VisionResult,
)

_VISION_PURPOSE = "vision.observe"
_VISION_MAX_OBSERVATIONS = 50
_VISION_MAX_PROVIDER_CHARS = 12000
_SUPPORTED_VISION_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}

# The provider can choose only from these coarse, non-identifying visual categories.
# Public labels are server-owned static text; model output has no free-text field where
# identity, precise location, OCR text, motives, relationships or sensitive traits can hide.
_OBSERVATION_LABELS: dict[str, dict[str, str]] = {
    "SCENE": {
        "INDOOR": "indoor scene",
        "OUTDOOR": "outdoor scene",
        "ROOM": "room",
        "OFFICE_LIKE": "office-like scene",
        "KITCHEN_LIKE": "kitchen-like scene",
        "STREET_LIKE": "street-like scene",
        "VEHICLE_INTERIOR": "vehicle interior",
        "NATURE": "natural outdoor scene",
        "RETAIL_LIKE": "retail-like scene",
        "OTHER_VISIBLE_SCENE": "other visible scene",
    },
    "OBJECT": {
        "PERSON": "person",
        "ANIMAL": "animal",
        "VEHICLE": "vehicle",
        "FURNITURE": "furniture",
        "ELECTRONIC_DEVICE": "electronic device",
        "BAG": "bag",
        "BOOK_OR_DOCUMENT": "book or document",
        "CONTAINER": "container",
        "FOOD_OR_DRINK": "food or drink",
        "TOOL": "tool",
        "CLOTHING": "clothing",
        "PLANT": "plant",
        "SIGN_OR_DISPLAY": "sign or display",
        "OTHER_VISIBLE_OBJECT": "other visible object",
    },
    "ACTIVITY": {
        "PERSON_STANDING": "person standing",
        "PERSON_SITTING": "person sitting",
        "PERSON_WALKING": "person walking",
        "PERSON_RUNNING": "person running",
        "PERSON_EATING_OR_DRINKING": "person eating or drinking",
        "PERSON_READING": "person reading",
        "PERSON_WRITING": "person writing",
        "PERSON_COOKING": "person cooking",
        "PERSON_DRIVING": "person driving",
        "PERSON_CYCLING": "person cycling",
        "PERSON_USING_DEVICE": "person using a device",
        "PERSON_HOLDING_OBJECT": "person holding an object",
        "PERSON_INTERACTING_WITH_OBJECT": "person interacting with an object",
        "OTHER_VISIBLE_ACTIVITY": "other directly visible activity",
    },
}

_SYSTEM_INSTRUCTION = """You are a privacy-preserving visible-scene classifier.
Return only coarse candidate observations directly supported by the supplied image.
Never claim that an observation is confirmed truth.
Every observation must use exactly one allowed kind/code pair listed below.

SCENE codes:
INDOOR, OUTDOOR, ROOM, OFFICE_LIKE, KITCHEN_LIKE, STREET_LIKE,
VEHICLE_INTERIOR, NATURE, RETAIL_LIKE, OTHER_VISIBLE_SCENE.

OBJECT codes:
PERSON, ANIMAL, VEHICLE, FURNITURE, ELECTRONIC_DEVICE, BAG, BOOK_OR_DOCUMENT,
CONTAINER, FOOD_OR_DRINK, TOOL, CLOTHING, PLANT, SIGN_OR_DISPLAY,
OTHER_VISIBLE_OBJECT.

ACTIVITY codes:
PERSON_STANDING, PERSON_SITTING, PERSON_WALKING, PERSON_RUNNING,
PERSON_EATING_OR_DRINKING, PERSON_READING, PERSON_WRITING, PERSON_COOKING,
PERSON_DRIVING, PERSON_CYCLING, PERSON_USING_DEVICE, PERSON_HOLDING_OBJECT,
PERSON_INTERACTING_WITH_OBJECT, OTHER_VISIBLE_ACTIVITY.

Do not identify people. Do not infer precise location/address, intent, motive,
relationship, medical condition, political affiliation, religion, race/ethnicity,
sexual orientation, or any other sensitive trait.
Do not perform OCR or report/transcribe visible text; OCR is a separate feature.
Do not create new codes to express details outside the safe vocabulary.
Return exactly:
{"observations":[{"kind":"OBJECT","code":"BAG"}]}
Each item must contain exactly kind and code. If nothing safe is visible, return
{"observations":[]}. Do not return labels, prose, markdown, confidence, IDs,
coordinates, owner data, trust fields, explanations, or extra fields.
"""


class VisionError(RuntimeError):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class VisionMediaSnapshot:
    object_key: str
    content_type: str
    size_bytes: int


class _ProviderVisionObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: VisionObservationKind
    code: VisionObservationCode


class _ProviderVisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observations: list[_ProviderVisionObservation] = Field(
        default_factory=list,
        max_length=_VISION_MAX_OBSERVATIONS,
    )


def _normalize_content_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()


def _snapshot_image(
    db: Session,
    *,
    user_id,
    media_id,
    for_update: bool = False,
) -> VisionMediaSnapshot:
    # Vision only accepts authenticated owner + opaque media_id. The private object key
    # comes from the authoritative Media row; client input never selects storage/provider.
    query = select(MediaAsset).where(
        MediaAsset.id == media_id,
        MediaAsset.user_id == user_id,
    )
    if for_update:
        query = query.with_for_update()

    with db.no_autoflush:
        asset = db.scalar(query)

    if asset is None:
        raise VisionError("MEDIA_NOT_FOUND", 404)
    if asset.status != MediaStatus.READY or asset.completed_at is None:
        raise VisionError("MEDIA_NOT_READY", 409)
    if asset.kind != MediaKind.IMAGE:
        raise VisionError("MEDIA_KIND_MISMATCH", 409)

    settings = get_settings()
    if asset.size_bytes > settings.media_max_image_bytes:
        raise VisionError("MEDIA_TOO_LARGE", 413)

    content_type = _normalize_content_type(asset.content_type)
    if content_type not in _SUPPORTED_VISION_CONTENT_TYPES:
        # HEIC/HEIF remain fail-closed until a trusted server-side conversion boundary
        # exists. Reinterpreting unsupported bytes would weaken both media and AI gates.
        raise VisionError("VISION_CONTENT_TYPE_UNSUPPORTED", 415)

    return VisionMediaSnapshot(
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
        raise VisionError("MEDIA_OBJECT_NOT_FOUND", 409) from exc
    except ObjectStorageError as exc:
        raise VisionError("MEDIA_STORAGE_UNAVAILABLE", 503) from exc

    # READY metadata is not enough by itself: validate the final private object's exact
    # size again before its bytes can cross into the model boundary.
    if len(image) != size_bytes:
        raise VisionError("MEDIA_OBJECT_SIZE_MISMATCH", 409)
    return image


def _provider_error(exc: AIGatewayError) -> VisionError:
    mapping = {
        "AI_PROVIDER_UNAVAILABLE": ("VISION_PROVIDER_UNAVAILABLE", 503),
        "AI_GATEWAY_TIMEOUT": ("VISION_TIMEOUT", 504),
        "AI_GATEWAY_TRANSPORT_ERROR": ("VISION_PROVIDER_UNAVAILABLE", 503),
        "AI_PROVIDER_FAILED": ("VISION_PROVIDER_FAILED", 502),
        "AI_PROVIDER_INCOMPLETE": ("VISION_PROVIDER_FAILED", 502),
        "AI_PROVIDER_INVALID_RESPONSE": ("VISION_PROVIDER_INVALID_RESPONSE", 502),
        "AI_PROVIDER_REFUSAL": ("VISION_PROVIDER_REFUSAL", 422),
        "AI_IMAGE_EMPTY": ("VISION_IMAGE_INVALID", 422),
        "AI_IMAGE_TOO_LARGE": ("MEDIA_TOO_LARGE", 413),
        "AI_IMAGE_TYPE_UNSUPPORTED": ("VISION_CONTENT_TYPE_UNSUPPORTED", 415),
    }
    code, status_code = mapping.get(exc.code, ("VISION_PROVIDER_FAILED", 502))
    return VisionError(code, status_code)


def _parse_provider_output(*, media_id, inference) -> VisionResult:
    if len(inference.output_text) > _VISION_MAX_PROVIDER_CHARS:
        raise VisionError("VISION_OUTPUT_TOO_LARGE", 502)
    try:
        payload = _ProviderVisionPayload.model_validate_json(inference.output_text)
    except (ValidationError, ValueError) as exc:
        raise VisionError("VISION_PROVIDER_INVALID_RESPONSE", 502) from exc
    if len(payload.observations) > _VISION_MAX_OBSERVATIONS:
        raise VisionError("VISION_OUTPUT_TOO_LARGE", 502)

    observations: list[VisionObservation] = []
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(payload.observations):
        labels_for_kind = _OBSERVATION_LABELS.get(raw.kind)
        label = None if labels_for_kind is None else labels_for_kind.get(raw.code)
        if label is None:
            # A code valid for a different kind is still invalid. The provider cannot
            # repurpose a safe token to smuggle a new semantic category.
            raise VisionError("VISION_PROVIDER_INVALID_RESPONSE", 502)

        key = (raw.kind, raw.code)
        if key in seen:
            raise VisionError("VISION_PROVIDER_INVALID_RESPONSE", 502)
        seen.add(key)

        observations.append(
            VisionObservation(
                index=index,
                kind=raw.kind,
                code=raw.code,
                label=label,
                trust_class="inference",
            )
        )

    return VisionResult(
        media_id=media_id,
        observations=observations,
        provenance=VisionProvenance(
            source_media_id=media_id,
            gateway_request_id=inference.provenance.gateway_request_id,
            provider_request_id=inference.provenance.provider_request_id,
            provider=inference.provenance.provider,
            model=inference.provenance.model,
            purpose=_VISION_PURPOSE,
            trust_class="inference",
            input_tokens=inference.usage.input_tokens,
            output_tokens=inference.usage.output_tokens,
        ),
    )


async def observe_vision(
    db: Session,
    *,
    user_id,
    request: VisionRequest,
    storage: ObjectStorage,
    gateway: AIGateway,
) -> VisionResult:
    # This is the explicit user-trigger boundary. Upload/complete never starts Vision,
    # and this function has no persistence path into Memory/Evidence/Entity/Visit/Reminder.
    #
    # Keep storage/provider I/O outside the DB transaction. Phase 1 snapshots authoritative
    # Media state; Phase 3 re-locks it and the guarded commit rechecks deletion generation
    # before any inference result may be returned to the admitted request.
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
                purpose=_VISION_PURPOSE,
                system_instruction=_SYSTEM_INSTRUCTION,
                input_text=(
                    "Classify only safe, directly visible scene/object/activity "
                    "candidates using the allowed kind/code vocabulary."
                ),
                image_bytes=image,
                content_type=snapshot.content_type,
                detail="high",
                max_output_tokens=512,
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
        raise VisionError("VISION_MEDIA_CHANGED_DURING_INFERENCE", 409)

    # GuardedSession.commit() is the final account/data-deletion generation gate.
    # This remains a read-only commit; Vision creates no trusted or durable personal fact.
    db.commit()
    return result
