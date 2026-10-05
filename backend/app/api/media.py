from __future__ import annotations

import hashlib
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.analytics_models import ProductActivity
from app.core.db import get_db
from app.deps import get_current_user_id
from app.ocr_models import OCRRequest, OCRResult
from app.schemas import (
    MediaCompleteResponse,
    MediaDownloadResponse,
    MediaRead,
    MediaUploadCreate,
    MediaUploadResponse,
    PhotoMemoryCreate,
    PhotoMemoryResponse,
    SignedTransfer,
    VoiceMemoryCreate,
    VoiceMemoryResponse,
)
from app.services.ai_gateway import AIGateway, get_ai_gateway
from app.services.analytics_service import record_active_day_safe
from app.services.api_abuse import enforce_authenticated_api_rate
from app.services.asr import ASRProvider, get_asr_provider
from app.services.auth_rate_limit import ApiRouteClass
from app.services.entitlement_service import EntitlementError
from app.services.media_service import (
    MediaError,
    cleanup_media_staging,
    complete_media_upload,
    create_photo_memory,
    create_voice_memory,
    sign_media_download,
    start_media_upload,
)
from app.services.object_storage import ObjectStorage, PresignedTransfer, get_object_storage
from app.services.ocr_service import OCRError, extract_ocr
from app.services.vision_service import VisionError, observe_vision
from app.vision_models import VisionRequest, VisionResult

router = APIRouter(prefix="/media", tags=["media"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]
Storage = Annotated[ObjectStorage, Depends(get_object_storage)]
ASR = Annotated[ASRProvider, Depends(get_asr_provider)]
AI = Annotated[AIGateway, Depends(get_ai_gateway)]


def _raise_http(exc: MediaError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail=exc.code,
        headers=_retry_headers(exc.retry_after),
    ) from exc


def _retry_headers(retry_after: int | None) -> dict[str, str] | None:
    if retry_after is None:
        return None
    return {"Retry-After": str(max(1, int(retry_after)))}


def _raise_ocr_http(exc: OCRError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail=exc.code,
        headers=_retry_headers(exc.retry_after),
    ) from exc


def _raise_vision_http(exc: VisionError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail=exc.code,
        headers=_retry_headers(exc.retry_after),
    ) from exc


def _signed_transfer(value: PresignedTransfer) -> SignedTransfer:
    return SignedTransfer(
        method=value.method,
        url=value.url,
        headers=value.headers,
        expires_at=value.expires_at,
    )


def _media_read(asset) -> MediaRead:
    return MediaRead.model_validate(asset)


def _media_cache_version(asset) -> str:
    # Local presentation cache needs a stable content identity that is independent
    # from short-lived signed URLs. Keep storage implementation details server-only:
    # hash them into an opaque version together with canonical READY metadata.
    if asset.storage_etag is None or asset.completed_at is None:
        raise MediaError("MEDIA_NOT_READY", 409)
    payload = (
        f"{asset.id}:{asset.storage_etag}:{asset.size_bytes}:"
        f"{asset.completed_at.isoformat()}"
    ).encode()
    return hashlib.sha256(payload).hexdigest()


@router.post(
    "/uploads",
    response_model=MediaUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_upload(
    payload: MediaUploadCreate,
    request: Request,
    user_id: CurrentUser,
    db: DbSession,
    storage: Storage,
) -> MediaUploadResponse:
    enforce_authenticated_api_rate(
        db,
        user_id=user_id,
        request=request,
        route_class=ApiRouteClass.MEDIA_TRANSFER,
    )
    # [人工注释][S1-004][S1-006] 图片/语音创建上传都只返回短时 PUT 与 opaque media_id；
    # staging/final object key 永不进入公开 payload。
    try:
        result = start_media_upload(db, user_id, payload, storage)
    except EntitlementError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    except MediaError as exc:
        _raise_http(exc)
    db.commit()
    record_active_day_safe(
        db,
        user_id=user_id,
        activity=ProductActivity.MEDIA_UPLOAD_RESERVED,
    )
    db.refresh(result.asset)
    media = _media_read(result.asset)
    return MediaUploadResponse(
        **media.model_dump(),
        upload=_signed_transfer(result.upload) if result.upload is not None else None,
    )


@router.post("/{media_id}/complete", response_model=MediaCompleteResponse)
def complete_upload(
    media_id: UUID,
    request: Request,
    user_id: CurrentUser,
    db: DbSession,
    storage: Storage,
) -> MediaCompleteResponse:
    enforce_authenticated_api_rate(
        db,
        user_id=user_id,
        request=request,
        route_class=ApiRouteClass.MEDIA_TRANSFER,
    )
    # [人工注释][S1-004][S1-006] complete 不接受 object key/size/type 参数；
    # READY 必须先 commit 成功，staging 才允许 best-effort 清理，图片/语音规则一致。
    try:
        asset = complete_media_upload(db, user_id, media_id, storage)
    except MediaError as exc:
        _raise_http(exc)
    db.commit()
    record_active_day_safe(
        db,
        user_id=user_id,
        activity=ProductActivity.MEDIA_UPLOAD_COMPLETED,
    )
    cleanup_media_staging(storage, asset)
    db.refresh(asset)
    media = _media_read(asset)
    return MediaCompleteResponse(
        **media.model_dump(),
        cache_version=_media_cache_version(asset),
    )


@router.post("/{media_id}/download", response_model=MediaDownloadResponse)
def create_download(
    media_id: UUID,
    request: Request,
    user_id: CurrentUser,
    db: DbSession,
    storage: Storage,
) -> MediaDownloadResponse:
    enforce_authenticated_api_rate(
        db,
        user_id=user_id,
        request=request,
        route_class=ApiRouteClass.MEDIA_TRANSFER,
    )
    # [人工注释][S1-006] 每次读取都重新签发短时 GET，数据库和 API 均不保存永久公开 URL。
    try:
        asset, transfer = sign_media_download(db, user_id, media_id, storage)
    except MediaError as exc:
        _raise_http(exc)
    return MediaDownloadResponse(
        media_id=asset.id,
        cache_version=_media_cache_version(asset),
        download=_signed_transfer(transfer),
    )


@router.post("/{media_id}/ocr", response_model=OCRResult)
async def extract_text_from_image(
    media_id: UUID,
    request: Request,
    user_id: CurrentUser,
    db: DbSession,
    storage: Storage,
    gateway: AI,
) -> OCRResult:
    enforce_authenticated_api_rate(
        db,
        user_id=user_id,
        request=request,
        route_class=ApiRouteClass.EXPENSIVE_AI,
    )
    # [人工注释][S3-006] OCR 只能由用户对一个明确 media_id 主动触发。
    # API 不接受 object URL/key/provider/key；结果仅作为 inference 返回，不写 Memory/Store。
    try:
        return await extract_ocr(
            db,
            user_id=user_id,
            request=OCRRequest(media_id=media_id),
            storage=storage,
            gateway=gateway,
        )
    except OCRError as exc:
        _raise_ocr_http(exc)


@router.post("/{media_id}/vision", response_model=VisionResult)
async def observe_image(
    media_id: UUID,
    request: Request,
    user_id: CurrentUser,
    db: DbSession,
    storage: Storage,
    gateway: AI,
) -> VisionResult:
    enforce_authenticated_api_rate(
        db,
        user_id=user_id,
        request=request,
        route_class=ApiRouteClass.EXPENSIVE_AI,
    )
    # Vision is an explicit read-only inference action over one owner-scoped Media row.
    # The request cannot choose storage/provider/trust fields, and no result enters Store.
    try:
        return await observe_vision(
            db,
            user_id=user_id,
            request=VisionRequest(media_id=media_id),
            storage=storage,
            gateway=gateway,
        )
    except VisionError as exc:
        _raise_vision_http(exc)


@router.post(
    "/{media_id}/memory",
    response_model=PhotoMemoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_memory_from_photo(
    media_id: UUID,
    payload: PhotoMemoryCreate,
    user_id: CurrentUser,
    db: DbSession,
) -> PhotoMemoryResponse:
    # [人工注释][S1-005] 这里只把已验证原始图片和用户主动文字接成 PHOTO Memory。
    # 不读取图片语义、不做 OCR/Vision，也不允许客户端提交 confidence/confirmed。
    try:
        asset, memory = create_photo_memory(db, user_id, media_id, payload)
    except MediaError as exc:
        _raise_http(exc)
    db.commit()
    db.refresh(asset)
    db.refresh(memory)
    return PhotoMemoryResponse(media=_media_read(asset), memory=memory)


@router.post(
    "/{media_id}/voice-memory",
    response_model=VoiceMemoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_memory_from_voice(
    media_id: UUID,
    payload: VoiceMemoryCreate,
    request: Request,
    user_id: CurrentUser,
    db: DbSession,
    storage: Storage,
    asr: ASR,
) -> VoiceMemoryResponse:
    enforce_authenticated_api_rate(
        db,
        user_id=user_id,
        request=request,
        route_class=ApiRouteClass.EXPENSIVE_AI,
    )
    # [人工注释][S1-004][S1-007] 客户端只提交 media_id + 可选标题/发生时间。
    # transcript/confidence/provider 成功状态全部由服务端从 READY 原始音频派生。
    try:
        asset, memory = create_voice_memory(
            db,
            user_id,
            media_id,
            payload,
            storage,
            asr,
        )
    except MediaError as exc:
        _raise_http(exc)
    db.commit()
    db.refresh(asset)
    db.refresh(memory)
    return VoiceMemoryResponse(media=_media_read(asset), memory=memory)
