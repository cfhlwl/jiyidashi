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
from app.services.memory_service import (
    TrustedMemoryWrite,
    create_trusted_memory,
    get_memory_for_user,
)
from app.services.object_storage import (
    ObjectNotFound,
    ObjectStorage,
    ObjectStorageError,
    PresignedTransfer,
    StoredObject,
)

ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}
IMAGE_SIGNATURE_PREFIX_BYTES = 64
HEIC_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"hevm", b"hevs"}
HEIF_BRANDS = HEIC_BRANDS | {b"mif1", b"msf1"}


# [人工注释][S1-005][S1-006] 媒体服务统一持有用户归属、服务端 object key 与 READY 门禁。
# 客户端只能携带 media_id，不能提交任意 object key 绕过所有权检查。
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


def _object_keys(user_id: UUID, media_id: UUID) -> tuple[str, str]:
    settings = get_settings()
    prefix = settings.storage_object_prefix.strip("/") or "media"
    upload_key = f"{prefix}/_staging/{user_id}/{media_id.hex}/{uuid4().hex}"
    final_key = f"{prefix}/{user_id}/{media_id.hex}"
    return upload_key, final_key


def _sign_upload(storage: ObjectStorage, asset: MediaAsset) -> PresignedTransfer:
    try:
        return storage.sign_upload(asset.upload_object_key, asset.content_type)
    except ObjectStorageError as exc:
        raise MediaError("MEDIA_STORAGE_UNAVAILABLE", 503) from exc


def _validate_stored_object(asset: MediaAsset, stored: StoredObject) -> None:
    if stored.size_bytes != asset.size_bytes:
        raise MediaError("MEDIA_OBJECT_SIZE_MISMATCH", 409)
    if _normalize_content_type(stored.content_type) != asset.content_type:
        raise MediaError("MEDIA_OBJECT_TYPE_MISMATCH", 409)


def _iso_bmff_brands(prefix: bytes) -> set[bytes]:
    if len(prefix) < 16 or prefix[4:8] != b"ftyp":
        return set()
    box_size = int.from_bytes(prefix[:4], "big")
    if box_size < 16:
        return set()
    available_end = min(len(prefix), box_size)
    brands = {prefix[8:12]}
    for index in range(16, available_end - 3, 4):
        brands.add(prefix[index : index + 4])
    return brands


def _validate_image_signature(content_type: str, prefix: bytes) -> None:
    # [人工注释][S1-005] MIME 元数据来自客户端上传请求，不能单独证明对象真的是图片。
    # READY 前必须验证最小文件签名；这里只识别容器/文件头，不做 OCR、Vision 或语义分析。
    is_valid = False
    if content_type == "image/jpeg":
        is_valid = len(prefix) >= 3 and prefix[:3] == b"\xff\xd8\xff"
    elif content_type == "image/png":
        is_valid = prefix.startswith(b"\x89PNG\r\n\x1a\n")
    elif content_type == "image/webp":
        is_valid = len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP"
    elif content_type == "image/heic":
        is_valid = bool(_iso_bmff_brands(prefix) & HEIC_BRANDS)
    elif content_type == "image/heif":
        is_valid = bool(_iso_bmff_brands(prefix) & HEIF_BRANDS)

    if not is_valid:
        raise MediaError("MEDIA_IMAGE_INVALID", 409)


def _validate_image_object(storage: ObjectStorage, asset: MediaAsset, object_key: str) -> None:
    try:
        prefix = storage.read_prefix(object_key, IMAGE_SIGNATURE_PREFIX_BYTES)
    except ObjectNotFound as exc:
        raise MediaError("MEDIA_OBJECT_NOT_FOUND", 409) from exc
    except ObjectStorageError as exc:
        raise MediaError("MEDIA_STORAGE_UNAVAILABLE", 503) from exc
    _validate_image_signature(asset.content_type, prefix)


def start_media_upload(
    db: Session,
    user_id: UUID,
    payload: MediaUploadCreate,
    storage: ObjectStorage,
) -> MediaUploadResult:
    # [人工注释][S1-006] client_upload_id 是用户域内幂等键。相同请求复用媒体身份；
    # 相同幂等键但元数据变化必须 409，防止另一份文件偷换进既有 Evidence 身份。
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
    upload_key, final_key = _object_keys(user_id, media_id)
    asset = MediaAsset(
        id=media_id,
        user_id=user_id,
        client_upload_id=payload.client_upload_id,
        kind=payload.kind,
        status=MediaStatus.PENDING,
        upload_object_key=upload_key,
        object_key=final_key,
        content_type=content_type,
        size_bytes=payload.size_bytes,
        original_filename=_normalize_filename(payload.original_filename),
    )
    db.add(asset)
    try:
        db.flush()
    except IntegrityError:
        # [人工注释][S1-006] 并发首次提交由数据库唯一约束裁决；回滚后只读取
        # 当前用户相同幂等键，绝不跨用户复用媒体对象。
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
    # [人工注释][S1-005][S1-006] READY 只能来自服务端校验。客户端 PUT 只写 staging；
    # 服务端校验后晋升到 final，Evidence/下载只读取 final，旧 PUT 签名无法覆盖已确认原图。
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
        staged = storage.stat_object(asset.upload_object_key)
    except ObjectNotFound as exc:
        raise MediaError("MEDIA_OBJECT_NOT_FOUND", 409) from exc
    except ObjectStorageError as exc:
        raise MediaError("MEDIA_STORAGE_UNAVAILABLE", 503) from exc
    _validate_stored_object(asset, staged)
    _validate_image_object(storage, asset, asset.upload_object_key)

    try:
        storage.promote_object(asset.upload_object_key, asset.object_key)
        final = storage.stat_object(asset.object_key)
    except ObjectNotFound as exc:
        raise MediaError("MEDIA_PROMOTION_FAILED", 503) from exc
    except ObjectStorageError as exc:
        raise MediaError("MEDIA_STORAGE_UNAVAILABLE", 503) from exc
    _validate_stored_object(asset, final)
    # [人工注释][S1-005] final 再验一次签名，封住“校验 staging 后、COPY 前旧 PUT 改写”的竞态。
    _validate_image_object(storage, asset, asset.object_key)

    asset.status = MediaStatus.READY
    asset.storage_etag = final.etag
    asset.completed_at = datetime.now(UTC)
    db.flush()
    return asset


def cleanup_media_staging(storage: ObjectStorage, asset: MediaAsset) -> None:
    # [人工注释][S1-006] staging 只能在 READY 数据库事务 commit 成功后 best-effort 清理。
    # commit 失败时保留 staging，使 PENDING 任务可以重试；清理失败只留下私有垃圾对象。
    try:
        storage.delete_object(asset.upload_object_key)
    except ObjectStorageError:
        pass


def sign_media_download(
    db: Session,
    user_id: UUID,
    media_id: UUID,
    storage: ObjectStorage,
) -> tuple[MediaAsset, PresignedTransfer]:
    # [人工注释][S1-006] 下载签名前按 media_id + user_id 查库，再对 final key 签名。
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
    # [人工注释][S1-005] 图片 Memory 必须锁定当前用户已 READY 的媒体；同一 media 只允许
    # 一个 Evidence 关联。重复提交返回既有 Memory，不制造第二条事实，也不做 OCR/Vision。
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
