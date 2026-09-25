from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import IntEnum
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.family_models import (
    FamilyAccessAuditEvent,
    FamilyAuditAction,
    FamilyAuditAuthorityType,
    FamilyAuditResourceType,
    FamilyAuditResult,
    FamilyEmergencyLocationShare,
    FamilyMembership,
)
from app.models import LocationPoint, PrivacyState
from app.services.family_sensitive_read_service import (
    CURRENT_LOCATION_MAX_AGE,
    FamilyCurrentLocationView,
)
from app.services.privacy_service import ensure_utc, lock_location_derivation_state


class EmergencyShareDuration(IntEnum):
    MINUTES_30 = 30
    MINUTES_60 = 60
    MINUTES_180 = 180


SUPPORTED_EMERGENCY_SHARE_DURATIONS = frozenset(
    item.value for item in EmergencyShareDuration
)
EMERGENCY_SHARE_LIST_LIMIT = 50


def _reference_now(now: datetime | None) -> datetime:
    return ensure_utc(now or datetime.now(UTC))


class FamilyEmergencyShareError(RuntimeError):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class FamilyEmergencyShareView:
    share_id: UUID
    resource_owner_user_id: UUID
    grantee_user_id: UUID
    expires_at: datetime
    created_at: datetime
    direction: str


def _lock_membership_pair(
    db: Session,
    *,
    first_user_id: UUID,
    second_user_id: UUID,
) -> dict[UUID, UUID]:
    rows = db.execute(
        select(FamilyMembership.user_id, FamilyMembership.family_id)
        .where(FamilyMembership.user_id.in_((first_user_id, second_user_id)))
        .order_by(FamilyMembership.user_id.asc())
        .with_for_update()
    ).all()
    return {row.user_id: row.family_id for row in rows}


def _normalize_duration(duration_minutes: int) -> int:
    if duration_minutes not in SUPPORTED_EMERGENCY_SHARE_DURATIONS:
        raise FamilyEmergencyShareError(
            "EMERGENCY_SHARE_DURATION_UNSUPPORTED",
            422,
        )
    return duration_minutes


def create_emergency_location_share(
    db: Session,
    *,
    resource_owner_user_id: UUID,
    grantee_user_id: UUID,
    duration_minutes: int,
    now: datetime | None = None,
) -> FamilyEmergencyShareView:
    if resource_owner_user_id == grantee_user_id:
        raise FamilyEmergencyShareError("EMERGENCY_SHARE_TARGET_INVALID", 409)

    duration = _normalize_duration(duration_minutes)
    reference = ensure_utc(now or datetime.now(UTC))

    locked = _lock_membership_pair(
        db,
        first_user_id=resource_owner_user_id,
        second_user_id=grantee_user_id,
    )
    owner_family = locked.get(resource_owner_user_id)
    grantee_family = locked.get(grantee_user_id)
    if (
        owner_family is None
        or grantee_family is None
        or owner_family != grantee_family
    ):
        db.rollback()
        raise FamilyEmergencyShareError("EMERGENCY_SHARE_TARGET_INVALID", 404)

    previous = tuple(
        db.scalars(
            select(FamilyEmergencyLocationShare)
            .where(
                FamilyEmergencyLocationShare.family_id == owner_family,
                FamilyEmergencyLocationShare.resource_owner_user_id
                == resource_owner_user_id,
                FamilyEmergencyLocationShare.grantee_user_id == grantee_user_id,
                FamilyEmergencyLocationShare.revoked_at.is_(None),
                FamilyEmergencyLocationShare.expires_at > reference,
            )
            .order_by(
                FamilyEmergencyLocationShare.created_at.asc(),
                FamilyEmergencyLocationShare.id.asc(),
            )
            .with_for_update()
        )
    )
    for item in previous:
        item.revoked_at = reference

    share = FamilyEmergencyLocationShare(
        family_id=owner_family,
        resource_owner_user_id=resource_owner_user_id,
        grantee_user_id=grantee_user_id,
        created_at=reference,
        expires_at=reference + timedelta(minutes=duration),
    )
    db.add(share)
    db.commit()
    return FamilyEmergencyShareView(
        share_id=share.id,
        resource_owner_user_id=share.resource_owner_user_id,
        grantee_user_id=share.grantee_user_id,
        expires_at=ensure_utc(share.expires_at),
        created_at=ensure_utc(share.created_at),
        direction="OUTGOING",
    )


def list_active_emergency_location_shares(
    db: Session,
    *,
    user_id: UUID,
    now: datetime | None = None,
) -> tuple[FamilyEmergencyShareView, ...]:
    reference = ensure_utc(now or datetime.now(UTC))
    membership = db.scalar(
        select(FamilyMembership).where(FamilyMembership.user_id == user_id)
    )
    if membership is None:
        raise FamilyEmergencyShareError("FAMILY_NOT_FOUND", 404)

    rows = tuple(
        db.scalars(
            select(FamilyEmergencyLocationShare)
            .where(
                FamilyEmergencyLocationShare.family_id == membership.family_id,
                FamilyEmergencyLocationShare.revoked_at.is_(None),
                FamilyEmergencyLocationShare.expires_at > reference,
                or_(
                    FamilyEmergencyLocationShare.resource_owner_user_id == user_id,
                    FamilyEmergencyLocationShare.grantee_user_id == user_id,
                ),
            )
            .order_by(
                FamilyEmergencyLocationShare.created_at.desc(),
                FamilyEmergencyLocationShare.id.desc(),
            )
            .limit(EMERGENCY_SHARE_LIST_LIMIT)
        )
    )
    return tuple(
        FamilyEmergencyShareView(
            share_id=item.id,
            resource_owner_user_id=item.resource_owner_user_id,
            grantee_user_id=item.grantee_user_id,
            expires_at=ensure_utc(item.expires_at),
            created_at=ensure_utc(item.created_at),
            direction=(
                "OUTGOING"
                if item.resource_owner_user_id == user_id
                else "INCOMING"
            ),
        )
        for item in rows
    )


def revoke_emergency_location_share(
    db: Session,
    *,
    actor_user_id: UUID,
    share_id: UUID,
    now: datetime | None = None,
) -> None:
    reference = ensure_utc(now or datetime.now(UTC))
    probe = db.scalar(
        select(FamilyEmergencyLocationShare).where(
            FamilyEmergencyLocationShare.id == share_id
        )
    )
    if probe is None or probe.resource_owner_user_id != actor_user_id:
        db.rollback()
        raise FamilyEmergencyShareError("EMERGENCY_SHARE_NOT_AVAILABLE", 404)

    locked = _lock_membership_pair(
        db,
        first_user_id=probe.resource_owner_user_id,
        second_user_id=probe.grantee_user_id,
    )
    if (
        locked.get(probe.resource_owner_user_id) != probe.family_id
        or locked.get(probe.grantee_user_id) != probe.family_id
    ):
        db.rollback()
        raise FamilyEmergencyShareError("EMERGENCY_SHARE_NOT_AVAILABLE", 404)

    share = db.scalar(
        select(FamilyEmergencyLocationShare)
        .where(
            FamilyEmergencyLocationShare.id == share_id,
            FamilyEmergencyLocationShare.resource_owner_user_id == actor_user_id,
        )
        .with_for_update()
    )
    if share is None:
        db.rollback()
        raise FamilyEmergencyShareError("EMERGENCY_SHARE_NOT_AVAILABLE", 404)

    if share.revoked_at is None:
        share.revoked_at = reference
    db.commit()


def _record_emergency_audit(
    db: Session,
    *,
    family_id: UUID,
    actor_user_id: UUID,
    resource_owner_user_id: UUID,
    result: FamilyAuditResult,
) -> None:
    db.add(
        FamilyAccessAuditEvent(
            family_id=family_id,
            actor_user_id=actor_user_id,
            resource_owner_user_id=resource_owner_user_id,
            authority_type=FamilyAuditAuthorityType.EMERGENCY_SHARE.value,
            permission_code=None,
            resource_type=FamilyAuditResourceType.CURRENT_LOCATION.value,
            action=FamilyAuditAction.READ_EMERGENCY_LOCATION.value,
            result=result.value,
        )
    )


def _unavailable(
    authority: Session,
    *,
    family_id: UUID,
    actor_user_id: UUID,
    resource_owner_user_id: UUID,
) -> None:
    _record_emergency_audit(
        authority,
        family_id=family_id,
        actor_user_id=actor_user_id,
        resource_owner_user_id=resource_owner_user_id,
        result=FamilyAuditResult.UNAVAILABLE,
    )
    authority.commit()
    raise FamilyEmergencyShareError("CURRENT_LOCATION_UNAVAILABLE", 404)


def get_emergency_shared_location(
    db: Session,
    *,
    share_id: UUID,
    grantee_user_id: UUID,
    now: datetime | None = None,
) -> FamilyCurrentLocationView:
    with Session(bind=db.get_bind(), autoflush=False, expire_on_commit=False) as authority:
        try:
            probe = authority.scalar(
                select(FamilyEmergencyLocationShare).where(
                    FamilyEmergencyLocationShare.id == share_id
                )
            )
            if probe is None or probe.grantee_user_id != grantee_user_id:
                raise FamilyEmergencyShareError(
                    "EMERGENCY_SHARE_NOT_AVAILABLE",
                    404,
                )

            locked = _lock_membership_pair(
                authority,
                first_user_id=probe.resource_owner_user_id,
                second_user_id=grantee_user_id,
            )
            if (
                locked.get(probe.resource_owner_user_id) != probe.family_id
                or locked.get(grantee_user_id) != probe.family_id
            ):
                raise FamilyEmergencyShareError(
                    "EMERGENCY_SHARE_NOT_AVAILABLE",
                    404,
                )

            share = authority.scalar(
                select(FamilyEmergencyLocationShare)
                .where(
                    FamilyEmergencyLocationShare.id == share_id,
                    FamilyEmergencyLocationShare.family_id == probe.family_id,
                    FamilyEmergencyLocationShare.resource_owner_user_id
                    == probe.resource_owner_user_id,
                    FamilyEmergencyLocationShare.grantee_user_id == grantee_user_id,
                )
                .with_for_update()
            )
            lock_reference = _reference_now(now)
            if (
                share is None
                or share.revoked_at is not None
                or ensure_utc(share.expires_at) <= lock_reference
            ):
                raise FamilyEmergencyShareError(
                    "EMERGENCY_SHARE_NOT_AVAILABLE",
                    404,
                )

            lock_location_derivation_state(
                authority,
                share.resource_owner_user_id,
            )
            location_reference = _reference_now(now)
            if ensure_utc(share.expires_at) <= location_reference:
                raise FamilyEmergencyShareError(
                    "EMERGENCY_SHARE_NOT_AVAILABLE",
                    404,
                )

            paused_until = authority.scalar(
                select(PrivacyState.recording_paused_until).where(
                    PrivacyState.user_id == share.resource_owner_user_id
                )
            )
            if (
                paused_until is not None
                and ensure_utc(paused_until) > location_reference
            ):
                _unavailable(
                    authority,
                    family_id=share.family_id,
                    actor_user_id=grantee_user_id,
                    resource_owner_user_id=share.resource_owner_user_id,
                )

            row = authority.execute(
                select(
                    LocationPoint.latitude,
                    LocationPoint.longitude,
                    LocationPoint.accuracy,
                    LocationPoint.recorded_at,
                )
                .where(LocationPoint.user_id == share.resource_owner_user_id)
                .order_by(
                    LocationPoint.recorded_at.desc(),
                    LocationPoint.id.desc(),
                )
                .limit(1)
            ).one_or_none()
            if row is None:
                _unavailable(
                    authority,
                    family_id=share.family_id,
                    actor_user_id=grantee_user_id,
                    resource_owner_user_id=share.resource_owner_user_id,
                )

            recorded_at = ensure_utc(row.recorded_at)
            settings = get_settings()
            if (
                recorded_at
                > location_reference + timedelta(
                    seconds=settings.location_future_skew_seconds
                )
                or recorded_at < location_reference - CURRENT_LOCATION_MAX_AGE
            ):
                _unavailable(
                    authority,
                    family_id=share.family_id,
                    actor_user_id=grantee_user_id,
                    resource_owner_user_id=share.resource_owner_user_id,
                )

            final_reference = _reference_now(now)
            if ensure_utc(share.expires_at) <= final_reference:
                raise FamilyEmergencyShareError(
                    "EMERGENCY_SHARE_NOT_AVAILABLE",
                    404,
                )

            result = FamilyCurrentLocationView(
                resource_owner_user_id=share.resource_owner_user_id,
                latitude=row.latitude,
                longitude=row.longitude,
                accuracy=row.accuracy,
                recorded_at=recorded_at,
                fresh_until=recorded_at + CURRENT_LOCATION_MAX_AGE,
            )
            _record_emergency_audit(
                authority,
                family_id=share.family_id,
                actor_user_id=grantee_user_id,
                resource_owner_user_id=share.resource_owner_user_id,
                result=FamilyAuditResult.ALLOWED,
            )
            authority.commit()
            return result
        except FamilyEmergencyShareError:
            if authority.in_transaction():
                authority.rollback()
            raise
        except BaseException:
            authority.rollback()
            raise
