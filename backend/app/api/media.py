from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.ocr_models import OCRRequest, OCRResult
from app.schemas import (
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
from app.services.asr import ASRProvider, get_asr_provider
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

router = APIRouter(prefix="/media", tags=["media"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]
Storage = Annotated[ObjectStorage, Depends(get_object_storage)]
ASR = Annotated[ASRProvider, Depends(get_asr_provider)]
AI = Annotated[AIGateway, Depends(get_ai_gateway)]


def _raise_http(exc: MediaError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


def _raise_ocr_http(exc: OCRError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


def _signed_transfer(value: PresignedTransfer) -> SignedTransfer:
    return SignedTransfer(
        method=value.method,
        url=value.url,
        headers=value.headers,
        expires_at=value.expires_at,
    )


def _media_read(asset) -> MediaRead:
    return MediaRead.model_validate(asset)


@router.post(
    "/uploads",
    response_model=MediaUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_upload(
    payload: MediaUploadCreate,
    user_id: CurrentUser,
    db: DbSession,
    storage: Storage,
) -> MediaUploadResponse:
    # [人工注释][S1-004][S1-006] 图片/语音创建上传都只返回短时 PUT 与 opaque media_id；
    # staging/final object key 永不进入公开 payload。
    try:
        result = start_media_upload(db, user_id, payload, storage)
    except MediaError as exc:
        _raise_http(exc)
    db.commit()
    db.refresh(result.asset)
    media = _media_read(result.asset)
    return MediaUploadResponse(
        **media.model_dump(),
        upload=_signed_transfer(result.upload) if result.upload is not None else None,
    )


@router.post("/{media_id}/complete", response_model=MediaRead)
def complete_upload(
    media_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
    storage: Storage,
) -> MediaRead:
    # [人工注释][S1-004][S1-006] complete 不接受 object key/size/type 参数；
    # READY 必须先 commit 成功，staging 才允许 best-effort 清理，图片/语音规则一致。
    try:
        asset = complete_media_upload(db, user_id, media_id, storage)
    except MediaError as exc:
        _raise_http(exc)
    db.commit()
    cleanup_media_staging(storage, asset)
    db.refresh(asset)
    return _media_read(asset)


@router.post("/{media_id}/download", response_model=MediaDownloadResponse)
def create_download(
    media_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
    storage: Storage,
) -> MediaDownloadResponse:
    # [人工注释][S1-006] 每次读取都重新签发短时 GET，数据库和 API 均不保存永久公开 URL。
    try:
        asset, transfer = sign_media_download(db, user_id, media_id, storage)
    except MediaError as exc:
        _raise_http(exc)
    return MediaDownloadResponse(
        media_id=asset.id,
        download=_signed_transfer(transfer),
    )


@router.post("/{media_id}/ocr", response_model=OCRResult)
async def extract_text_from_image(
    media_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
    storage: Storage,
    gateway: AI,
) -> OCRResult:
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
    user_id: CurrentUser,
    db: DbSession,
    storage: Storage,
    asr: ASR,
) -> VoiceMemoryResponse:
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
