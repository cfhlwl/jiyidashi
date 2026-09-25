from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.family_models import (
    FamilyAccessAuditEvent,
    FamilyAuditAction,
    FamilyAuditAuthorityType,
    FamilyAuditResourceType,
    FamilyAuditResult,
    FamilyMembership,
    FamilyPermissionCode,
    FamilyPermissionGrant,
)
from app.media_models import MediaAsset, MediaKind, MediaStatus
from app.models import LocationPoint, Memory, PrivacyState
from app.schemas import TodayFootprintResponse
from app.services.object_storage import ObjectStorage, ObjectStorageError, PresignedTransfer
from app.services.privacy_service import ensure_utc, lock_location_derivation_state
from app.services.today_footprint_service import get_today_footprint

CURRENT_LOCATION_MAX_AGE = timedelta(minutes=15)
FAMILY_PHOTO_LIST_LIMIT = 50


class FamilySensitiveReadError(RuntimeError):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class FamilyCurrentLocationView:
    resource_owner_user_id: UUID
    latitude: float
    longitude: float
    accuracy: float | None
    recorded_at: datetime
    fresh_until: datetime


@dataclass(frozen=True)
class FamilyMemoryView:
    memory_id: UUID
    memory_type: str
    title: str | None
    content: str
    occurred_at: datetime
    source_type: str
    is_confirmed: bool
    edit_revision: int
    created_at: datetime


@dataclass(frozen=True)
class FamilyPhotoView:
    media_id: UUID
    content_type: str
    size_bytes: int
    created_at: datetime
    completed_at: datetime | None


def _record_family_access(
    db: Session,
    *,
    family_id: UUID,
    actor_user_id: UUID,
    resource_owner_user_id: UUID,
    permission_code: FamilyPermissionCode,
    resource_type: FamilyAuditResourceType,
    action: FamilyAuditAction,
    result: FamilyAuditResult,
) -> None:
    # Audit rows intentionally contain only access metadata. Never add payload,
    # object keys, signed URLs, raw provider errors, coordinates or Memory text here.
    db.add(
        FamilyAccessAuditEvent(
            family_id=family_id,
            actor_user_id=actor_user_id,
            resource_owner_user_id=resource_owner_user_id,
            authority_type=FamilyAuditAuthorityType.EXACT_GRANT.value,
            permission_code=permission_code.value,
            resource_type=resource_type.value,
            action=action.value,
            result=result.value,
        )
    )


def _require_exact_family_grant(
    db: Session,
    *,
    resource_owner_user_id: UUID,
    grantee_user_id: UUID,
    permission_code: FamilyPermissionCode,
    resource_type: FamilyAuditResourceType,
    action: FamilyAuditAction,
) -> UUID:
    if resource_owner_user_id == grantee_user_id:
        raise FamilySensitiveReadError("FAMILY_SELF_READ_NOT_APPLICABLE", 409)

    rows = db.execute(
        select(
            FamilyMembership.user_id,
            FamilyMembership.family_id,
        )
        .where(
            FamilyMembership.user_id.in_(
                (resource_owner_user_id, grantee_user_id)
            )
        )
        .order_by(FamilyMembership.user_id.asc())
        .with_for_update()
    ).all()
    memberships = {row.user_id: row.family_id for row in rows}

    owner_family_id = memberships.get(resource_owner_user_id)
    grantee_family_id = memberships.get(grantee_user_id)
    if (
        owner_family_id is None
        or grantee_family_id is None
        or owner_family_id != grantee_family_id
    ):
        # Cross-family/non-member attempts deliberately do not persist an audit row:
        # there is no authoritative shared Family scope to attach it to.
        raise FamilySensitiveReadError("FAMILY_READ_NOT_AUTHORIZED", 403)

    grant_id = db.scalar(
        select(FamilyPermissionGrant.id)
        .where(
            FamilyPermissionGrant.family_id == owner_family_id,
            FamilyPermissionGrant.resource_owner_user_id
            == resource_owner_user_id,
            FamilyPermissionGrant.grantee_user_id == grantee_user_id,
            FamilyPermissionGrant.permission_code == permission_code.value,
        )
        .with_for_update()
        .limit(1)
    )
    if grant_id is None:
        _record_family_access(
            db,
            family_id=owner_family_id,
            actor_user_id=grantee_user_id,
            resource_owner_user_id=resource_owner_user_id,
            permission_code=permission_code,
            resource_type=resource_type,
            action=action,
            result=FamilyAuditResult.DENIED,
        )
        # DENIED must survive the exception. The membership pair is still locked here,
        # so the result corresponds to the same serialized authority state.
        db.commit()
        raise FamilySensitiveReadError("FAMILY_READ_NOT_AUTHORIZED", 403)

    return owner_family_id


def get_family_photos(
    db: Session,
    *,
    resource_owner_user_id: UUID,
    grantee_user_id: UUID,
) -> tuple[FamilyPhotoView, ...]:
    with Session(bind=db.get_bind(), autoflush=False, expire_on_commit=False) as authority:
        try:
            family_id = _require_exact_family_grant(
                authority,
                resource_owner_user_id=resource_owner_user_id,
                grantee_user_id=grantee_user_id,
                permission_code=FamilyPermissionCode.VIEW_PHOTOS,
                resource_type=FamilyAuditResourceType.PHOTO,
                action=FamilyAuditAction.LIST_PHOTOS,
            )
            rows = authority.execute(
                select(
                    MediaAsset.id.label("media_id"),
                    MediaAsset.content_type,
                    MediaAsset.size_bytes,
                    MediaAsset.created_at,
                    MediaAsset.completed_at,
                )
                .where(
                    MediaAsset.user_id == resource_owner_user_id,
                    MediaAsset.kind == MediaKind.IMAGE,
                    MediaAsset.status == MediaStatus.READY,
                )
                .order_by(MediaAsset.created_at.desc(), MediaAsset.id.desc())
                .limit(FAMILY_PHOTO_LIST_LIMIT)
            ).all()
            result = tuple(
                FamilyPhotoView(
                    media_id=row.media_id,
                    content_type=row.content_type,
                    size_bytes=row.size_bytes,
                    created_at=row.created_at,
                    completed_at=row.completed_at,
                )
                for row in rows
            )
            _record_family_access(
                authority,
                family_id=family_id,
                actor_user_id=grantee_user_id,
                resource_owner_user_id=resource_owner_user_id,
                permission_code=FamilyPermissionCode.VIEW_PHOTOS,
                resource_type=FamilyAuditResourceType.PHOTO,
                action=FamilyAuditAction.LIST_PHOTOS,
                result=FamilyAuditResult.ALLOWED,
            )
            authority.commit()
            return result
        except FamilySensitiveReadError:
            if authority.in_transaction():
                authority.rollback()
            raise
        except BaseException:
            authority.rollback()
            raise


def sign_family_photo_download(
    db: Session,
    *,
    resource_owner_user_id: UUID,
    grantee_user_id: UUID,
    media_id: UUID,
    storage: ObjectStorage,
) -> PresignedTransfer:
    with Session(bind=db.get_bind(), autoflush=False, expire_on_commit=False) as authority:
        try:
            family_id = _require_exact_family_grant(
                authority,
                resource_owner_user_id=resource_owner_user_id,
                grantee_user_id=grantee_user_id,
                permission_code=FamilyPermissionCode.VIEW_PHOTOS,
                resource_type=FamilyAuditResourceType.PHOTO,
                action=FamilyAuditAction.DOWNLOAD_PHOTO,
            )
            row = authority.execute(
                select(MediaAsset.id.label("media_id"), MediaAsset.object_key).where(
                    MediaAsset.id == media_id,
                    MediaAsset.user_id == resource_owner_user_id,
                    MediaAsset.kind == MediaKind.IMAGE,
                    MediaAsset.status == MediaStatus.READY,
                )
            ).one_or_none()
            if row is None:
                _record_family_access(
                    authority,
                    family_id=family_id,
                    actor_user_id=grantee_user_id,
                    resource_owner_user_id=resource_owner_user_id,
                    permission_code=FamilyPermissionCode.VIEW_PHOTOS,
                    resource_type=FamilyAuditResourceType.PHOTO,
                    action=FamilyAuditAction.DOWNLOAD_PHOTO,
                    result=FamilyAuditResult.UNAVAILABLE,
                )
                authority.commit()
                raise FamilySensitiveReadError("FAMILY_PHOTO_UNAVAILABLE", 404)

            try:
                transfer = storage.sign_download(row.object_key)
            except ObjectStorageError as exc:
                _record_family_access(
                    authority,
                    family_id=family_id,
                    actor_user_id=grantee_user_id,
                    resource_owner_user_id=resource_owner_user_id,
                    permission_code=FamilyPermissionCode.VIEW_PHOTOS,
                    resource_type=FamilyAuditResourceType.PHOTO,
                    action=FamilyAuditAction.DOWNLOAD_PHOTO,
                    result=FamilyAuditResult.UNAVAILABLE,
                )
                authority.commit()
                raise FamilySensitiveReadError("FAMILY_PHOTO_STORAGE_UNAVAILABLE", 503) from exc

            if (
                transfer.method.upper() != "GET"
                or ensure_utc(transfer.expires_at) <= datetime.now(UTC)
            ):
                _record_family_access(
                    authority,
                    family_id=family_id,
                    actor_user_id=grantee_user_id,
                    resource_owner_user_id=resource_owner_user_id,
                    permission_code=FamilyPermissionCode.VIEW_PHOTOS,
                    resource_type=FamilyAuditResourceType.PHOTO,
                    action=FamilyAuditAction.DOWNLOAD_PHOTO,
                    result=FamilyAuditResult.UNAVAILABLE,
                )
                authority.commit()
                raise FamilySensitiveReadError("FAMILY_PHOTO_STORAGE_UNAVAILABLE", 503)

            _record_family_access(
                authority,
                family_id=family_id,
                actor_user_id=grantee_user_id,
                resource_owner_user_id=resource_owner_user_id,
                permission_code=FamilyPermissionCode.VIEW_PHOTOS,
                resource_type=FamilyAuditResourceType.PHOTO,
                action=FamilyAuditAction.DOWNLOAD_PHOTO,
                result=FamilyAuditResult.ALLOWED,
            )
            authority.commit()
            return transfer
        except FamilySensitiveReadError:
            if authority.in_transaction():
                authority.rollback()
            raise
        except BaseException:
            authority.rollback()
            raise


def _privacy_pause_active(
    db: Session,
    *,
    user_id: UUID,
    now: datetime,
) -> bool:
    paused_until = db.scalar(
        select(PrivacyState.recording_paused_until).where(
            PrivacyState.user_id == user_id
        )
    )
    return paused_until is not None and ensure_utc(paused_until) > now


def get_family_current_location(
    db: Session,
    *,
    resource_owner_user_id: UUID,
    grantee_user_id: UUID,
    now: datetime | None = None,
) -> FamilyCurrentLocationView:
    reference = ensure_utc(now or datetime.now(UTC))

    with Session(bind=db.get_bind(), autoflush=False, expire_on_commit=False) as authority:
        try:
            family_id = _require_exact_family_grant(
                authority,
                resource_owner_user_id=resource_owner_user_id,
                grantee_user_id=grantee_user_id,
                permission_code=FamilyPermissionCode.VIEW_CURRENT_LOCATION,
                resource_type=FamilyAuditResourceType.CURRENT_LOCATION,
                action=FamilyAuditAction.READ_CURRENT_LOCATION,
            )
            lock_location_derivation_state(authority, resource_owner_user_id)

            if _privacy_pause_active(
                authority,
                user_id=resource_owner_user_id,
                now=reference,
            ):
                _record_family_access(
                    authority,
                    family_id=family_id,
                    actor_user_id=grantee_user_id,
                    resource_owner_user_id=resource_owner_user_id,
                    permission_code=FamilyPermissionCode.VIEW_CURRENT_LOCATION,
                    resource_type=FamilyAuditResourceType.CURRENT_LOCATION,
                    action=FamilyAuditAction.READ_CURRENT_LOCATION,
                    result=FamilyAuditResult.UNAVAILABLE,
                )
                authority.commit()
                raise FamilySensitiveReadError("CURRENT_LOCATION_UNAVAILABLE", 404)

            row = authority.execute(
                select(
                    LocationPoint.latitude,
                    LocationPoint.longitude,
                    LocationPoint.accuracy,
                    LocationPoint.recorded_at,
                )
                .where(LocationPoint.user_id == resource_owner_user_id)
                .order_by(
                    LocationPoint.recorded_at.desc(),
                    LocationPoint.id.desc(),
                )
                .limit(1)
            ).one_or_none()
            if row is None:
                _record_family_access(
                    authority,
                    family_id=family_id,
                    actor_user_id=grantee_user_id,
                    resource_owner_user_id=resource_owner_user_id,
                    permission_code=FamilyPermissionCode.VIEW_CURRENT_LOCATION,
                    resource_type=FamilyAuditResourceType.CURRENT_LOCATION,
                    action=FamilyAuditAction.READ_CURRENT_LOCATION,
                    result=FamilyAuditResult.UNAVAILABLE,
                )
                authority.commit()
                raise FamilySensitiveReadError("CURRENT_LOCATION_UNAVAILABLE", 404)

            recorded_at = ensure_utc(row.recorded_at)
            settings = get_settings()
            if (
                recorded_at
                > reference + timedelta(seconds=settings.location_future_skew_seconds)
                or recorded_at < reference - CURRENT_LOCATION_MAX_AGE
            ):
                _record_family_access(
                    authority,
                    family_id=family_id,
                    actor_user_id=grantee_user_id,
                    resource_owner_user_id=resource_owner_user_id,
                    permission_code=FamilyPermissionCode.VIEW_CURRENT_LOCATION,
                    resource_type=FamilyAuditResourceType.CURRENT_LOCATION,
                    action=FamilyAuditAction.READ_CURRENT_LOCATION,
                    result=FamilyAuditResult.UNAVAILABLE,
                )
                authority.commit()
                raise FamilySensitiveReadError("CURRENT_LOCATION_UNAVAILABLE", 404)

            result = FamilyCurrentLocationView(
                resource_owner_user_id=resource_owner_user_id,
                latitude=row.latitude,
                longitude=row.longitude,
                accuracy=row.accuracy,
                recorded_at=recorded_at,
                fresh_until=recorded_at + CURRENT_LOCATION_MAX_AGE,
            )
            _record_family_access(
                authority,
                family_id=family_id,
                actor_user_id=grantee_user_id,
                resource_owner_user_id=resource_owner_user_id,
                permission_code=FamilyPermissionCode.VIEW_CURRENT_LOCATION,
                resource_type=FamilyAuditResourceType.CURRENT_LOCATION,
                action=FamilyAuditAction.READ_CURRENT_LOCATION,
                result=FamilyAuditResult.ALLOWED,
            )
            authority.commit()
            return result
        except FamilySensitiveReadError:
            if authority.in_transaction():
                authority.rollback()
            raise
        except BaseException:
            authority.rollback()
            raise


def get_family_memories(
    db: Session,
    *,
    resource_owner_user_id: UUID,
    grantee_user_id: UUID,
    limit: int = 50,
) -> list[FamilyMemoryView]:
    if limit < 1 or limit > 50:
        raise ValueError("family memory limit must be between 1 and 50")

    with Session(bind=db.get_bind(), autoflush=False, expire_on_commit=False) as authority:
        try:
            family_id = _require_exact_family_grant(
                authority,
                resource_owner_user_id=resource_owner_user_id,
                grantee_user_id=grantee_user_id,
                permission_code=FamilyPermissionCode.VIEW_MEMORY,
                resource_type=FamilyAuditResourceType.MEMORY,
                action=FamilyAuditAction.READ_MEMORY,
            )
            rows = authority.execute(
                select(
                    Memory.id,
                    Memory.memory_type,
                    Memory.title,
                    Memory.content,
                    Memory.occurred_at,
                    Memory.source_type,
                    Memory.is_confirmed,
                    Memory.edit_revision,
                    Memory.created_at,
                )
                .where(
                    Memory.user_id == resource_owner_user_id,
                    Memory.is_deleted.is_(False),
                )
                .order_by(Memory.occurred_at.desc(), Memory.id.desc())
                .with_for_update()
                .limit(limit)
            ).all()

            result = [
                FamilyMemoryView(
                    memory_id=row.id,
                    memory_type=row.memory_type.value,
                    title=row.title,
                    content=row.content,
                    occurred_at=ensure_utc(row.occurred_at),
                    source_type=row.source_type.value,
                    is_confirmed=row.is_confirmed,
                    edit_revision=row.edit_revision,
                    created_at=ensure_utc(row.created_at),
                )
                for row in rows
            ]
            _record_family_access(
                authority,
                family_id=family_id,
                actor_user_id=grantee_user_id,
                resource_owner_user_id=resource_owner_user_id,
                permission_code=FamilyPermissionCode.VIEW_MEMORY,
                resource_type=FamilyAuditResourceType.MEMORY,
                action=FamilyAuditAction.READ_MEMORY,
                result=FamilyAuditResult.ALLOWED,
            )
            authority.commit()
            return result
        except FamilySensitiveReadError:
            if authority.in_transaction():
                authority.rollback()
            raise
        except BaseException:
            authority.rollback()
            raise


def get_family_today_footprint(
    db: Session,
    *,
    resource_owner_user_id: UUID,
    grantee_user_id: UUID,
) -> TodayFootprintResponse:
    with Session(bind=db.get_bind(), autoflush=False, expire_on_commit=False) as authority:
        try:
            family_id = _require_exact_family_grant(
                authority,
                resource_owner_user_id=resource_owner_user_id,
                grantee_user_id=grantee_user_id,
                permission_code=FamilyPermissionCode.VIEW_FOOTPRINT,
                resource_type=FamilyAuditResourceType.TODAY_FOOTPRINT,
                action=FamilyAuditAction.READ_TODAY_FOOTPRINT,
            )
            with authority.no_autoflush:
                result = get_today_footprint(
                    authority,
                    user_id=resource_owner_user_id,
                )
            _record_family_access(
                authority,
                family_id=family_id,
                actor_user_id=grantee_user_id,
                resource_owner_user_id=resource_owner_user_id,
                permission_code=FamilyPermissionCode.VIEW_FOOTPRINT,
                resource_type=FamilyAuditResourceType.TODAY_FOOTPRINT,
                action=FamilyAuditAction.READ_TODAY_FOOTPRINT,
                result=FamilyAuditResult.ALLOWED,
            )
            authority.commit()
            return result
        except FamilySensitiveReadError:
            if authority.in_transaction():
                authority.rollback()
            raise
        except BaseException:
            authority.rollback()
            raise
