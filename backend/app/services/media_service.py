from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.media_models import (
    MediaASRClaim,
    MediaAsset,
    MediaEvidenceLink,
    MediaKind,
    MediaStatus,
)
from app.models import Memory, MemorySource, MemoryType, SourceType
from app.schemas import MediaUploadCreate, PhotoMemoryCreate, VoiceMemoryCreate
from app.services.asr import ASRProvider, ASRProviderError
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
ALLOWED_AUDIO_CONTENT_TYPES = {"audio/mpeg", "audio/mp4"}
IMAGE_SIGNATURE_PREFIX_BYTES = 64
AUDIO_SIGNATURE_PREFIX_BYTES = 1024
MP4_AUDIO_BRANDS = {b"M4A ", b"isom", b"iso2", b"mp41", b"mp42"}
ASR_CLAIM_LEASE = timedelta(minutes=10)
HEIC_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"hevm", b"hevs"}
HEIF_BRANDS = HEIC_BRANDS | {b"mif1", b"msf1"}
MEDIA_MEMORY_REQUEST_HASH_KEY = "media_memory_request_sha256"

ASR_ERROR_STATUS = {
    "ASR_PROVIDER_UNAVAILABLE": 503,
    "ASR_TIMEOUT": 504,
    "ASR_PROVIDER_FAILED": 502,
    "ASR_PROVIDER_INVALID_RESPONSE": 502,
    "ASR_CONFIDENCE_MISSING": 502,
    "ASR_EMPTY_RESULT": 422,
}


# [人工注释][S1-004][S1-005][S1-006] 媒体服务统一持有用户归属、服务端 object key 与 READY 门禁。
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


# [人工注释][S1-PR18-FIX-001][S1-007] 外部对象下载/ASR 只消费普通值 snapshot，
# 不把已参与数据库事务的 ORM 实例跨越网络 I/O 保存或继续访问。
@dataclass(frozen=True)
class VoiceMediaSnapshot:
    media_id: UUID
    object_key: str
    content_type: str
    size_bytes: int
    original_filename: str | None
    claim_token: UUID


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


def _validate_audio_signature(content_type: str, prefix: bytes) -> None:
    # MIME 不能直接升级 READY：MP3 检查 ID3/frame sync，M4A 检查 ISO-BMFF ftyp 品牌。
    # 这里只证明容器格式与声明一致；是否真的可转写仍由服务端 ASR fail-closed 决定。
    is_valid = False
    if content_type == "audio/mpeg":
        is_valid = prefix.startswith(b"ID3") or (
            len(prefix) >= 2 and prefix[0] == 0xFF and (prefix[1] & 0xE0) == 0xE0
        )
    elif content_type == "audio/mp4":
        is_valid = bool(_iso_bmff_brands(prefix) & MP4_AUDIO_BRANDS)
    if not is_valid:
        raise MediaError("MEDIA_AUDIO_INVALID", 409)


def _validate_media_object(
    storage: ObjectStorage,
    asset: MediaAsset,
    object_key: str,
) -> None:
    max_bytes = (
        IMAGE_SIGNATURE_PREFIX_BYTES
        if asset.kind == MediaKind.IMAGE
        else AUDIO_SIGNATURE_PREFIX_BYTES
    )
    try:
        prefix = storage.read_prefix(object_key, max_bytes)
    except ObjectNotFound as exc:
        raise MediaError("MEDIA_OBJECT_NOT_FOUND", 409) from exc
    except ObjectStorageError as exc:
        raise MediaError("MEDIA_STORAGE_UNAVAILABLE", 503) from exc

    if asset.kind == MediaKind.IMAGE:
        _validate_image_signature(asset.content_type, prefix)
        return
    if asset.kind == MediaKind.AUDIO:
        _validate_audio_signature(asset.content_type, prefix)
        return
    raise MediaError("MEDIA_KIND_UNSUPPORTED", 422)


def _validate_upload_policy(payload: MediaUploadCreate, content_type: str) -> None:
    settings = get_settings()
    if payload.kind == MediaKind.IMAGE:
        if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
            raise MediaError("MEDIA_CONTENT_TYPE_UNSUPPORTED", 422)
        if payload.size_bytes > settings.media_max_image_bytes:
            raise MediaError("MEDIA_TOO_LARGE", 413)
        return
    if payload.kind == MediaKind.AUDIO:
        if content_type not in ALLOWED_AUDIO_CONTENT_TYPES:
            raise MediaError("MEDIA_CONTENT_TYPE_UNSUPPORTED", 422)
        if payload.size_bytes > settings.media_max_audio_bytes:
            raise MediaError("MEDIA_TOO_LARGE", 413)
        return
    raise MediaError("MEDIA_KIND_UNSUPPORTED", 422)


def start_media_upload(
    db: Session,
    user_id: UUID,
    payload: MediaUploadCreate,
    storage: ObjectStorage,
) -> MediaUploadResult:
    # [人工注释][S1-004][S1-006] 图片/语音共用 user-scoped client_upload_id 幂等协议；
    # 相同幂等键但元数据变化必须 409，防止另一份文件偷换进既有 Evidence 身份。
    content_type = _normalize_content_type(payload.content_type)
    _validate_upload_policy(payload, content_type)

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
    # [人工注释][S1-004][S1-005][S1-006] READY 只能来自服务端校验。客户端 PUT 只写 staging；
    # 图片/语音都要在 staging 与 final 各验一次真实文件头，再提交 READY。
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
    _validate_media_object(storage, asset, asset.upload_object_key)

    try:
        storage.promote_object(asset.upload_object_key, asset.object_key)
        final = storage.stat_object(asset.object_key)
    except ObjectNotFound as exc:
        raise MediaError("MEDIA_PROMOTION_FAILED", 503) from exc
    except ObjectStorageError as exc:
        raise MediaError("MEDIA_STORAGE_UNAVAILABLE", 503) from exc
    _validate_stored_object(asset, final)
    # [人工注释][S1-004][S1-005] final 再验一次文件头，封住 staging 校验后、
    # COPY 前旧 PUT 改写的竞态。
    _validate_media_object(storage, asset, asset.object_key)

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
    # [人工注释][S1-006] 每次下载签名前按 media_id + user_id 查库，再对 final key 签名。
    # 对其他用户统一 404，图片/语音都不能仅凭 object key 或猜测 UUID 跨用户读取。
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


def _existing_media_memory(
    db: Session,
    user_id: UUID,
    media_id: UUID,
) -> Memory | None:
    link = db.scalar(select(MediaEvidenceLink).where(MediaEvidenceLink.media_id == media_id))
    if link is None:
        return None
    memory_id = db.scalar(
        select(MemorySource.memory_id).where(MemorySource.id == link.memory_source_id)
    )
    if memory_id is None:
        raise MediaError("MEDIA_EVIDENCE_INVALID", 409)
    memory = get_memory_for_user(db, user_id, memory_id)
    if memory is None:
        # [人工注释][S1-007] 软删除后的语音 Memory 不得通过再次 ASR“复活”；
        # 既有 MediaEvidenceLink 是永久幂等水位，删除语义优先。
        raise MediaError("MEDIA_MEMORY_DELETED", 409)
    return memory


def _canonical_request_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _media_memory_request_hash(
    *,
    kind: str,
    title: str | None,
    content: str | None,
    occurred_at: datetime | None,
) -> str:
    # 只保存不可逆请求指纹，不在 metadata 中复制用户正文。
    # null occurred_at 也参与指纹，因此“首次让服务端定时”与后续显式改时间不会静默等价。
    payload = {
        "kind": kind,
        "title": title,
        "content": content,
        "occurred_at": _canonical_request_time(occurred_at),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _assert_photo_memory_replay_matches(
    memory: Memory,
    payload: PhotoMemoryCreate,
) -> None:
    expected_hash = _media_memory_request_hash(
        kind="PHOTO",
        title=payload.title,
        content=payload.content.strip(),
        occurred_at=payload.occurred_at,
    )
    stored_hash = (memory.metadata_json or {}).get(MEDIA_MEMORY_REQUEST_HASH_KEY)
    if isinstance(stored_hash, str):
        if stored_hash != expected_hash:
            raise MediaError("MEDIA_MEMORY_IDEMPOTENCY_CONFLICT", 409)
        return

    # 兼容 H 线之前已经存在的媒体 Memory：旧记录没有请求指纹。
    # 能可靠比较的字段必须一致；旧请求未显式传 occurred_at 时无法反推出 null，只接受现有时间。
    if memory.title != payload.title or memory.content != payload.content.strip():
        raise MediaError("MEDIA_MEMORY_IDEMPOTENCY_CONFLICT", 409)
    if (
        payload.occurred_at is not None
        and _canonical_request_time(memory.occurred_at)
        != _canonical_request_time(payload.occurred_at)
    ):
        raise MediaError("MEDIA_MEMORY_IDEMPOTENCY_CONFLICT", 409)


def _assert_voice_memory_replay_matches(
    memory: Memory,
    payload: VoiceMemoryCreate,
) -> None:
    expected_hash = _media_memory_request_hash(
        kind="VOICE",
        title=payload.title,
        content=None,
        occurred_at=payload.occurred_at,
    )
    stored_hash = (memory.metadata_json or {}).get(MEDIA_MEMORY_REQUEST_HASH_KEY)
    if isinstance(stored_hash, str):
        if stored_hash != expected_hash:
            raise MediaError("MEDIA_MEMORY_IDEMPOTENCY_CONFLICT", 409)
        return

    if memory.title != payload.title:
        raise MediaError("MEDIA_MEMORY_IDEMPOTENCY_CONFLICT", 409)
    if (
        payload.occurred_at is not None
        and _canonical_request_time(memory.occurred_at)
        != _canonical_request_time(payload.occurred_at)
    ):
        raise MediaError("MEDIA_MEMORY_IDEMPOTENCY_CONFLICT", 409)


def _link_memory_source(
    db: Session,
    *,
    asset: MediaAsset,
    memory: Memory,
    source_type: SourceType,
) -> None:
    source = db.scalar(
        select(MemorySource).where(
            MemorySource.memory_id == memory.id,
            MemorySource.source_type == source_type,
            MemorySource.source_id == str(asset.id),
        )
    )
    if source is None:
        raise MediaError("MEDIA_EVIDENCE_INVALID", 500)
    db.add(MediaEvidenceLink(media_id=asset.id, memory_source_id=source.id))
    db.flush()


def create_photo_memory(
    db: Session,
    user_id: UUID,
    media_id: UUID,
    payload: PhotoMemoryCreate,
) -> tuple[MediaAsset, Memory]:
    # [人工注释][S1-005] 图片 Memory 必须锁定当前用户已 READY 的 IMAGE；同一 media 只允许
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
    if asset.kind != MediaKind.IMAGE:
        raise MediaError("MEDIA_KIND_MISMATCH", 409)

    existing_memory = _existing_media_memory(db, user_id, asset.id)
    if existing_memory is not None:
        _assert_photo_memory_replay_matches(existing_memory, payload)
        return asset, existing_memory

    request_hash = _media_memory_request_hash(
        kind="PHOTO",
        title=payload.title,
        content=payload.content.strip(),
        occurred_at=payload.occurred_at,
    )
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
                MEDIA_MEMORY_REQUEST_HASH_KEY: request_hash,
            },
            source_id=str(asset.id),
            evidence_text=payload.content,
        ),
    )
    db.flush()
    _link_memory_source(
        db,
        asset=asset,
        memory=memory,
        source_type=SourceType.USER_PHOTO,
    )
    return asset, memory


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _release_voice_asr_claim(db: Session, media_id: UUID, claim_token: UUID) -> None:
    # [人工注释][S1-PR18-FIX-002][S1-007] 旧请求只能释放自己的 token；若租约已过期并
    # 被新请求接管，token mismatch 会保留新 claim，避免旧失败回调误删新单飞所有权。
    if db.in_transaction():
        db.rollback()
    claim = db.scalar(
        select(MediaASRClaim)
        .where(
            MediaASRClaim.media_id == media_id,
            MediaASRClaim.claim_token == claim_token,
        )
        .with_for_update()
    )
    if claim is None:
        db.rollback()
        return
    db.delete(claim)
    db.commit()


def _read_and_transcribe_voice(
    db: Session,
    snapshot: VoiceMediaSnapshot,
    storage: ObjectStorage,
    asr: ASRProvider,
):
    # [人工注释][S1-PR18-FIX-001][S1-007] claim 已 commit 后才能进入此函数；
    # 对象下载与付费 provider 调用期间必须没有活跃 SQLAlchemy transaction/连接占用。
    if db.in_transaction():
        _release_voice_asr_claim(db, snapshot.media_id, snapshot.claim_token)
        raise MediaError("ASR_TRANSACTION_BOUNDARY_INVALID", 500)

    settings = get_settings()
    try:
        audio = storage.read_object(snapshot.object_key, settings.media_max_audio_bytes)
    except ObjectNotFound as exc:
        _release_voice_asr_claim(db, snapshot.media_id, snapshot.claim_token)
        raise MediaError("MEDIA_OBJECT_NOT_FOUND", 409) from exc
    except ObjectStorageError as exc:
        _release_voice_asr_claim(db, snapshot.media_id, snapshot.claim_token)
        raise MediaError("MEDIA_STORAGE_UNAVAILABLE", 503) from exc
    if len(audio) != snapshot.size_bytes:
        _release_voice_asr_claim(db, snapshot.media_id, snapshot.claim_token)
        raise MediaError("MEDIA_OBJECT_SIZE_MISMATCH", 409)

    try:
        result = asr.transcribe(
            audio,
            content_type=snapshot.content_type,
            filename=snapshot.original_filename,
        )
    except ASRProviderError as exc:
        _release_voice_asr_claim(db, snapshot.media_id, snapshot.claim_token)
        raise MediaError(exc.code, ASR_ERROR_STATUS.get(exc.code, 502)) from exc

    transcript = result.text.strip()
    if not transcript:
        _release_voice_asr_claim(db, snapshot.media_id, snapshot.claim_token)
        raise MediaError("ASR_EMPTY_RESULT", 422)
    if result.confidence < settings.asr_min_confidence:
        _release_voice_asr_claim(db, snapshot.media_id, snapshot.claim_token)
        raise MediaError("ASR_LOW_CONFIDENCE", 422)
    return result, transcript


def create_voice_memory(
    db: Session,
    user_id: UUID,
    media_id: UUID,
    payload: VoiceMemoryCreate,
    storage: ObjectStorage,
    asr: ASRProvider,
) -> tuple[MediaAsset, Memory]:
    settings = get_settings()

    # [人工注释][S1-PR18-FIX-001][S1-PR18-FIX-002][S1-007] Phase 1 是短事务：
    # 锁 READY audio、检查 Evidence、原子 claim，然后立即 commit 释放连接；不在事务里等网络 I/O。
    asset = db.scalar(
        select(MediaAsset)
        .where(MediaAsset.id == media_id, MediaAsset.user_id == user_id)
        .with_for_update()
    )
    if asset is None:
        raise MediaError("MEDIA_NOT_FOUND", 404)
    if asset.status != MediaStatus.READY:
        raise MediaError("MEDIA_NOT_READY", 409)
    if asset.kind != MediaKind.AUDIO:
        raise MediaError("MEDIA_KIND_MISMATCH", 409)

    existing_memory = _existing_media_memory(db, user_id, asset.id)
    if existing_memory is not None:
        _assert_voice_memory_replay_matches(existing_memory, payload)
        return asset, existing_memory
    if asset.size_bytes > settings.media_max_audio_bytes:
        raise MediaError("MEDIA_TOO_LARGE", 413)

    now = datetime.now(UTC)
    claim = db.get(MediaASRClaim, asset.id)
    if claim is not None and _as_utc(claim.lease_expires_at) > now:
        db.rollback()
        raise MediaError("ASR_IN_PROGRESS", 409)

    claim_token = uuid4()
    lease_expires_at = now + ASR_CLAIM_LEASE
    if claim is None:
        claim = MediaASRClaim(
            media_id=asset.id,
            claim_token=claim_token,
            lease_expires_at=lease_expires_at,
        )
        db.add(claim)
    else:
        claim.claim_token = claim_token
        claim.lease_expires_at = lease_expires_at
        claim.updated_at = now

    snapshot = VoiceMediaSnapshot(
        media_id=asset.id,
        object_key=asset.object_key,
        content_type=asset.content_type,
        size_bytes=asset.size_bytes,
        original_filename=asset.original_filename,
        claim_token=claim_token,
    )
    db.flush()
    db.commit()

    result, transcript = _read_and_transcribe_voice(db, snapshot, storage, asr)

    # [人工注释][S1-PR18-FIX-001][S1-PR18-FIX-002][S1-007] Phase 3 重新开启短事务；
    # finalize 前重新校验 owner/READY/AUDIO/Evidence 与 claim token，不能信任 Phase 1 的 ORM 状态。
    try:
        locked_asset = db.scalar(
            select(MediaAsset)
            .where(MediaAsset.id == media_id, MediaAsset.user_id == user_id)
            .with_for_update()
        )
        if locked_asset is None:
            raise MediaError("MEDIA_NOT_FOUND", 404)
        if locked_asset.status != MediaStatus.READY:
            raise MediaError("MEDIA_NOT_READY", 409)
        if locked_asset.kind != MediaKind.AUDIO:
            raise MediaError("MEDIA_KIND_MISMATCH", 409)

        locked_claim = db.scalar(
            select(MediaASRClaim)
            .where(MediaASRClaim.media_id == media_id)
            .with_for_update()
        )
        if locked_claim is None or locked_claim.claim_token != claim_token:
            raise MediaError("ASR_CLAIM_LOST", 409)

        existing_memory = _existing_media_memory(db, user_id, locked_asset.id)
        if existing_memory is not None:
            _assert_voice_memory_replay_matches(existing_memory, payload)
            db.delete(locked_claim)
            db.commit()
            return locked_asset, existing_memory

        request_hash = _media_memory_request_hash(
            kind="VOICE",
            title=payload.title,
            content=None,
            occurred_at=payload.occurred_at,
        )
        memory = create_trusted_memory(
            db,
            user_id,
            TrustedMemoryWrite(
                memory_type=MemoryType.VOICE,
                title=payload.title,
                content=transcript,
                occurred_at=payload.occurred_at or datetime.now(UTC),
                source_type=SourceType.USER_VOICE,
                confidence=result.confidence,
                is_confirmed=True,
                metadata={
                    "media_id": str(locked_asset.id),
                    "media_kind": locked_asset.kind.value,
                    "capture_mode": "MANUAL",
                    "asr_provider": result.provider,
                    "asr_model": result.model,
                    "asr_confidence": result.confidence,
                    MEDIA_MEMORY_REQUEST_HASH_KEY: request_hash,
                },
                source_id=str(locked_asset.id),
                evidence_text=transcript,
            ),
        )
        db.flush()
        _link_memory_source(
            db,
            asset=locked_asset,
            memory=memory,
            source_type=SourceType.USER_VOICE,
        )
        db.delete(locked_claim)
        db.commit()
        return locked_asset, memory
    except Exception:
        db.rollback()
        _release_voice_asr_claim(db, media_id, claim_token)
        raise
