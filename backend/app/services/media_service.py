from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.media_models import MediaAsset, MediaEvidenceLink, MediaKind, MediaStatus
from app.models import Memory, MemorySource, MemoryType, SourceType
from app.schemas import MediaUploadCreate, PhotoMemoryCreate
from app.services.memory_service import TrustedMemoryWrite, create_trusted_memory, get_memory_for_user
from app.services.object_storage import (
    ObjectNotFound,
    ObjectStorage,
    ObjectStorageError,
    PresignedTransfer,
)

ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}


# [人工注释][S1-005][S1-006] 媒体服务统一持有“用户归属 + 服务端 object_key + READY 门禁”；
# 客户端只能携带 media_id，不能提交任意 object_key 绕过所有权检查。
class MediaError(RuntimeError):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class MediaUploadResult:
    asset: MediaAsset
    upload: PresignedTransfer | None


def _normalize_filename(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().replace("\\", "/").rsplit("/", 1)[-1].strip()
    return normalized[:255] or None


def _normalize_content_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()


def _get_asset_for_user(db: Session, user_id: UUID, media_id: UUID) -> MediaAsset | None:
    return db.scalar(
        select(MediaAsset).where(
            MediaAsset.id == media_id,
            MediaAsset.user_id == user_id,
        )
    )


def _same_upload(asset: MediaAsset, payload: MediaUploadCreate) -> bool:
    return (
        asset.kind == payload.kind
        and asset.content_type == _normalize_content_type(payload.content_type)
        and asset.size_bytes == payload.size_bytes
        and asset.original_filename == _normalize_filename(payload.original_filename)
    )


def _object_key(user_id: UUID, media_id: UUID) -> str:
    settings = get_settings()
    prefix = settings.storage_object_prefix.strip("/") or "media"
    return f"{prefix}/{user_id}/{media_id.hex}"


def _sign_upload(storage: ObjectStorage, asset: MediaAsset) -> PresignedTransfer:
    try:
        return storage.sign_upload(asset.object_key, asset.content_type)
    except ObjectStorageError as exc:
        raise MediaError("MEDIA_STORAGE_UNAVAILABLE", 503) from exc


def start_media_upload(
    db: Session,
    user_id: UUID,
    payload: MediaUploadCreate,
    storage: ObjectStorage,
) -> MediaUploadResult:
    # [人工注释][S1-006] client_upload_id 是用户域内幂等键；重复同请求复用同一 media_id/object_key，
    # 相同幂等键但元数据变化必须 409，防止客户端把另一份文件偷换进既有 Evidence 身份。
    content_type = _normalize_content_type(payload.content_type)
    if payload.kind != MediaKind.IMAGE:
        raise MediaError("MEDIA_KIND_UNSUPPORTED", 422)
    if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise MediaError("MEDIA_CONTENT_TYPE_UNSUPPORTED", 422)
    if payload.size_bytes > get_settings().media_max_image_bytes:
        raise MediaError("MEDIA_TOO_LARGE", 413)

    existing = db.scalar(
        select(MediaAsset).where(
            MediaAsset.user_id == user_id,
            MediaAsset.client_upload_id == payload.client_upload_id,
        )
    )
    if existing is not None:
        if not _same_upload(existing, payload):
            raise MediaError("MEDIA_UPLOAD_ID_CONFLICT", 409)
        if existing.status == MediaStatus.READY:
            return MediaUploadResult(asset=existing, upload=None)
        return MediaUploadResult(asset=existing, upload=_sign_upload(storage, existing))

    media_id = uuid4()
    asset = MediaAsset(
        id=media_id,
        user_id=user_id,
        client_upload_id=payload.client_upload_id,
        kind=payload.kind,
        status=MediaStatus.PENDING,
        object_key=_object_key(user_id, media_id),
        content_type=content_type,
        size_bytes=payload.size_bytes,
        original_filename=_normalize_filename(payload.original_filename),
    )
    db.add(asset)
    try:
        db.flush()
    except IntegrityError:
        # [人工注释][S1-006] 并发首次提交由数据库唯一约束裁决；回滚后只允许读取当前用户相同幂等键。
        db.rollback()
        existing = db.scalar(
            select(MediaAsset).where(
                MediaAsset.user_id == user_id,
                MediaAsset.client_upload_id == payload.client_upload_id,
            )
        )
        if existing is None or not _same_upload(existing, payload):
            raise MediaError("MEDIA_UPLOAD_ID_CONFLICT", 409) from None
        if existing.status == MediaStatus.READY:
            return MediaUploadResult(asset=existing, upload=None)
        return MediaUploadResult(asset=existing, upload=_sign_upload(storage, existing))

    return MediaUploadResult(asset=asset, upload=_sign_upload(storage, asset))


def complete_media_upload(
    db: Session,
    user_id: UUID,
    media_id: UUID,
    storage: ObjectStorage,
) -> MediaAsset:
    # [人工注释][S1-005][S1-006] READY 只能来自服务端对私有桶 HEAD 的验证；
    # 客户端“上传成功”声明不具有可信等级，尺寸/类型不一致的对象不得成为 Evidence。
    asset = db.scalar(
        select(MediaAsset)
        .where(MediaAsset.id == media_id, MediaAsset.user_id == user_id)
        .with_for_update()
    )
    if asset is None:
        raise MediaError("MEDIA_NOT_FOUND", 404)
    if asset.status == MediaStatus.READY:
        return asset

    try:
        stored = storage.stat_object(asset.object_key)
    except ObjectNotFound as exc:
        raise MediaError("MEDIA_OBJECT_NOT_FOUND", 409) from exc
    except ObjectStorageError as exc:
        raise MediaError("MEDIA_STORAGE_UNAVAILABLE", 503) from exc

    if stored.size_bytes != asset.size_bytes:
        raise MediaError("MEDIA_OBJECT_SIZE_MISMATCH", 409)
    if _normalize_content_type(stored.content_type) != asset.content_type:
        raise MediaError("MEDIA_OBJECT_TYPE_MISMATCH", 409)

    asset.status = MediaStatus.READY
    asset.storage_etag = stored.etag
    asset.completed_at = datetime.now(UTC)
    db.flush()
    return asset


def sign_media_download(
    db: Session,
    user_id: UUID,
    media_id: UUID,
    storage: ObjectStorage,
) -> tuple[MediaAsset, PresignedTransfer]:
    # [人工注释][S1-006] 下载签名先按 media_id + 当前 user_id 查库，再用服务端保存的 object_key 签名；
    # 对其他用户统一 404，禁止仅凭 object key 或猜测 UUID 跨用户读取。
    asset = _get_asset_for_user(db, user_id, media_id)
    if asset is None:
        raise MediaError("MEDIA_NOT_FOUND", 404)
    if asset.status != MediaStatus.READY:
        raise MediaError("MEDIA_NOT_READY", 409)
    try:
        transfer = storage.sign_download(asset.object_key)
    except ObjectStorageError as exc:
        raise MediaError("MEDIA_STORAGE_UNAVAILABLE", 503) from exc
    return asset, transfer


def create_photo_memory(
    db: Session,
    user_id: UUID,
    media_id: UUID,
    payload: PhotoMemoryCreate,
) -> tuple[MediaAsset, Memory]:
    # [人工注释][S1-005] 图片 Memory 必须锁定当前用户已 READY 的媒体；同一 media 只允许一个 Evidence 关联，
    # 重复提交直接返回既有 Memory，不重复制造事实，也不执行任何 OCR/Vision 推断。
    asset = db.scalar(
        select(MediaAsset)
        .where(MediaAsset.id == media_id, MediaAsset.user_id == user_id)
        .with_for_update()
    )
    if asset is None:
        raise MediaError("MEDIA_NOT_FOUND", 404)
    if asset.status != MediaStatus.READY:
        raise MediaError("MEDIA_NOT_READY", 409)

    existing_link = db.scalar(
        select(MediaEvidenceLink).where(MediaEvidenceLink.media_id == asset.id)
    )
    if existing_link is not None:
        memory_id = db.scalar(
            select(MemorySource.memory_id).where(
                MemorySource.id == existing_link.memory_source_id
            )
        )
        if memory_id is None:
            raise MediaError("MEDIA_EVIDENCE_INVALID", 409)
        existing_memory = get_memory_for_user(db, user_id, memory_id)
        if existing_memory is None:
            raise MediaError("MEDIA_MEMORY_DELETED", 409)
        return asset, existing_memory

    memory = create_trusted_memory(
        db,
        user_id,
        TrustedMemoryWrite(
            memory_type=MemoryType.PHOTO,
            title=payload.title,
            content=payload.content,
            occurred_at=payload.occurred_at or datetime.now(UTC),
            source_type=SourceType.USER_PHOTO,
            confidence=1.0,
            is_confirmed=True,
            metadata={
                "media_id": str(asset.id),
                "media_kind": asset.kind.value,
            },
            source_id=str(asset.id),
            evidence_text=payload.content,
        ),
    )
    db.flush()
    source = db.scalar(
        select(MemorySource).where(
            MemorySource.memory_id == memory.id,
            MemorySource.source_type == SourceType.USER_PHOTO,
            MemorySource.source_id == str(asset.id),
        )
    )
    if source is None:
        raise MediaError("MEDIA_EVIDENCE_INVALID", 500)
    db.add(MediaEvidenceLink(media_id=asset.id, memory_source_id=source.id))
    db.flush()
    return asset, memory
