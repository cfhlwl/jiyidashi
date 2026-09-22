from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Connection, delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.family_models import (
    SUPPORTED_FAMILY_PERMISSION_CODES,
    Family,
    FamilyInvite,
    FamilyMembership,
    FamilyPermissionCode,
    FamilyPermissionGrant,
    FamilyRole,
)
from app.models import User

INVITE_TTL = timedelta(hours=24)


class FamilyServiceError(RuntimeError):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class FamilyMemberView:
    user_id: UUID
    role: str
    created_at: datetime


@dataclass(frozen=True)
class FamilyView:
    family_id: UUID
    current_user_role: str
    members: tuple[FamilyMemberView, ...]


@dataclass(frozen=True)
class FamilyInviteSecret:
    invite_id: UUID
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class FamilyPermissionView:
    grantee_user_id: UUID
    permission_codes: tuple[str, ...]


def _engine_bind(db: Session):
    bind = db.get_bind()
    return bind.engine if isinstance(bind, Connection) else bind


def _read_session(db: Session) -> Session:
    # Family authorization must observe committed server-owned state only.
    return Session(bind=_engine_bind(db), autoflush=False, expire_on_commit=False)


def _membership_for_user(
    db: Session,
    user_id: UUID,
    *,
    for_update: bool = False,
) -> FamilyMembership | None:
    statement = select(FamilyMembership).where(FamilyMembership.user_id == user_id)
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def _require_membership(
    db: Session,
    user_id: UUID,
    *,
    for_update: bool = False,
) -> FamilyMembership:
    membership = _membership_for_user(db, user_id, for_update=for_update)
    if membership is None:
        raise FamilyServiceError("FAMILY_NOT_FOUND", 404)
    return membership


def _require_owner(db: Session, user_id: UUID) -> FamilyMembership:
    membership = _require_membership(db, user_id, for_update=True)
    if membership.role != FamilyRole.OWNER.value:
        raise FamilyServiceError("FAMILY_OWNER_REQUIRED", 403)
    return membership


def _lock_memberships_canonical(
    db: Session,
    *user_ids: UUID,
) -> dict[UUID, FamilyMembership]:
    """Lock an authorization pair in one stable database order.

    Every mutation that needs two membership rows must use this helper rather than
    locking "actor then target". PostgreSQL applies FOR UPDATE after the ORDER BY,
    so callers with the same pair acquire the rows in the same user_id order even
    when their semantic directions are reversed.
    """

    unique_user_ids = tuple(set(user_ids))
    if not unique_user_ids:
        return {}
    rows = tuple(
        db.scalars(
            select(FamilyMembership)
            .where(FamilyMembership.user_id.in_(unique_user_ids))
            .order_by(FamilyMembership.user_id.asc())
            .with_for_update()
        )
    )
    return {row.user_id: row for row in rows}


def create_family(db: Session, *, user_id: UUID) -> FamilyView:
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        db.rollback()
        raise FamilyServiceError("USER_NOT_FOUND", 404)
    if _membership_for_user(db, user_id) is not None:
        db.rollback()
        raise FamilyServiceError("FAMILY_ALREADY_JOINED", 409)

    family = Family(created_by_user_id=user_id)
    db.add(family)
    db.flush()
    db.add(
        FamilyMembership(
            family_id=family.id,
            user_id=user_id,
            role=FamilyRole.OWNER.value,
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _membership_for_user(db, user_id) is not None:
            raise FamilyServiceError("FAMILY_ALREADY_JOINED", 409) from exc
        raise FamilyServiceError("FAMILY_CREATE_CONFLICT", 409) from exc
    return get_family(db, user_id=user_id)


def get_family(db: Session, *, user_id: UUID) -> FamilyView:
    with _read_session(db) as read:
        membership = _require_membership(read, user_id)
        rows = tuple(
            read.scalars(
                select(FamilyMembership)
                .where(FamilyMembership.family_id == membership.family_id)
                .order_by(FamilyMembership.created_at.asc(), FamilyMembership.user_id.asc())
            )
        )
        return FamilyView(
            family_id=membership.family_id,
            current_user_role=membership.role,
            members=tuple(
                FamilyMemberView(
                    user_id=item.user_id,
                    role=item.role,
                    created_at=item.created_at,
                )
                for item in rows
            ),
        )


def _hash_invite_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_invite(
    db: Session,
    *,
    user_id: UUID,
    now: datetime | None = None,
) -> FamilyInviteSecret:
    membership = _require_owner(db, user_id)
    created_at = now or datetime.now(UTC)
    token = secrets.token_urlsafe(32)
    invite = FamilyInvite(
        family_id=membership.family_id,
        inviter_user_id=user_id,
        token_hash=_hash_invite_token(token),
        expires_at=created_at + INVITE_TTL,
        created_at=created_at,
    )
    db.add(invite)
    db.commit()
    return FamilyInviteSecret(
        invite_id=invite.id,
        token=token,
        expires_at=invite.expires_at,
    )


def revoke_invite(
    db: Session,
    *,
    user_id: UUID,
    invite_id: UUID,
    now: datetime | None = None,
) -> None:
    membership = _require_owner(db, user_id)
    invite = db.scalar(
        select(FamilyInvite)
        .where(
            FamilyInvite.id == invite_id,
            FamilyInvite.family_id == membership.family_id,
        )
        .with_for_update()
    )
    if invite is None:
        db.rollback()
        raise FamilyServiceError("FAMILY_INVITE_NOT_FOUND", 404)
    if invite.accepted_at is not None:
        db.rollback()
        raise FamilyServiceError("FAMILY_INVITE_NOT_ACTIVE", 409)
    if invite.revoked_at is None:
        invite.revoked_at = now or datetime.now(UTC)
    db.commit()


def accept_invite(
    db: Session,
    *,
    user_id: UUID,
    token: str,
    now: datetime | None = None,
) -> FamilyView:
    if not isinstance(token, str) or not token or len(token) > 512:
        raise FamilyServiceError("FAMILY_INVITE_INVALID", 400)
    current_time = now or datetime.now(UTC)

    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        db.rollback()
        raise FamilyServiceError("USER_NOT_FOUND", 404)

    invite = db.scalar(
        select(FamilyInvite)
        .where(FamilyInvite.token_hash == _hash_invite_token(token))
        .with_for_update()
    )
    if invite is None:
        db.rollback()
        raise FamilyServiceError("FAMILY_INVITE_INVALID", 404)
    if invite.revoked_at is not None or invite.accepted_at is not None:
        db.rollback()
        raise FamilyServiceError("FAMILY_INVITE_NOT_ACTIVE", 409)
    expires_at = invite.expires_at
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= current_time:
        db.rollback()
        raise FamilyServiceError("FAMILY_INVITE_EXPIRED", 410)

    if _membership_for_user(db, user_id) is not None:
        db.rollback()
        raise FamilyServiceError("FAMILY_ALREADY_JOINED", 409)

    db.add(
        FamilyMembership(
            family_id=invite.family_id,
            user_id=user_id,
            role=FamilyRole.MEMBER.value,
        )
    )
    invite.accepted_at = current_time
    invite.accepted_by_user_id = user_id
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _membership_for_user(db, user_id) is not None:
            raise FamilyServiceError("FAMILY_ALREADY_JOINED", 409) from exc
        raise FamilyServiceError("FAMILY_INVITE_NOT_ACTIVE", 409) from exc
    return get_family(db, user_id=user_id)


def _delete_grants_for_member(
    db: Session,
    *,
    family_id: UUID,
    user_id: UUID,
) -> None:
    db.execute(
        delete(FamilyPermissionGrant).where(
            FamilyPermissionGrant.family_id == family_id,
            or_(
                FamilyPermissionGrant.resource_owner_user_id == user_id,
                FamilyPermissionGrant.grantee_user_id == user_id,
            ),
        )
    )


def remove_member(
    db: Session,
    *,
    actor_user_id: UUID,
    target_user_id: UUID,
) -> None:
    locked = _lock_memberships_canonical(
        db,
        actor_user_id,
        target_user_id,
    )
    actor = locked.get(actor_user_id)
    if actor is None:
        db.rollback()
        raise FamilyServiceError("FAMILY_NOT_FOUND", 404)

    target = locked.get(target_user_id)
    if target is None or target.family_id != actor.family_id:
        db.rollback()
        raise FamilyServiceError("FAMILY_MEMBER_NOT_FOUND", 404)

    if actor_user_id == target_user_id:
        if actor.role == FamilyRole.OWNER.value:
            db.rollback()
            raise FamilyServiceError("FAMILY_OWNER_CANNOT_LEAVE", 409)
        _delete_grants_for_member(
            db,
            family_id=actor.family_id,
            user_id=target_user_id,
        )
        db.delete(target)
        db.commit()
        return

    if actor.role != FamilyRole.OWNER.value:
        db.rollback()
        raise FamilyServiceError("FAMILY_OWNER_REQUIRED", 403)
    if target.role == FamilyRole.OWNER.value:
        db.rollback()
        raise FamilyServiceError("FAMILY_OWNER_CANNOT_BE_REMOVED", 409)

    _delete_grants_for_member(
        db,
        family_id=actor.family_id,
        user_id=target_user_id,
    )
    db.delete(target)
    db.commit()


def _normalize_codes(
    permission_codes: set[str] | frozenset[str] | tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    normalized = tuple(sorted(set(permission_codes)))
    if any(code not in SUPPORTED_FAMILY_PERMISSION_CODES for code in normalized):
        raise FamilyServiceError("FAMILY_PERMISSION_UNSUPPORTED", 422)
    return normalized


def replace_permissions(
    db: Session,
    *,
    resource_owner_user_id: UUID,
    grantee_user_id: UUID,
    permission_codes: set[str] | frozenset[str] | tuple[str, ...] | list[str],
) -> FamilyPermissionView:
    codes = _normalize_codes(permission_codes)
    if resource_owner_user_id == grantee_user_id:
        db.rollback()
        raise FamilyServiceError("FAMILY_PERMISSION_SELF_GRANT_FORBIDDEN", 409)

    locked = _lock_memberships_canonical(
        db,
        resource_owner_user_id,
        grantee_user_id,
    )
    owner_membership = locked.get(resource_owner_user_id)
    if owner_membership is None:
        db.rollback()
        raise FamilyServiceError("FAMILY_NOT_FOUND", 404)

    grantee = locked.get(grantee_user_id)
    if grantee is None or grantee.family_id != owner_membership.family_id:
        db.rollback()
        raise FamilyServiceError("FAMILY_MEMBER_NOT_FOUND", 404)

    db.execute(
        delete(FamilyPermissionGrant).where(
            FamilyPermissionGrant.family_id == owner_membership.family_id,
            FamilyPermissionGrant.resource_owner_user_id == resource_owner_user_id,
            FamilyPermissionGrant.grantee_user_id == grantee_user_id,
        )
    )
    for code in codes:
        db.add(
            FamilyPermissionGrant(
                family_id=owner_membership.family_id,
                resource_owner_user_id=resource_owner_user_id,
                grantee_user_id=grantee_user_id,
                permission_code=code,
            )
        )
    db.commit()
    return FamilyPermissionView(
        grantee_user_id=grantee_user_id,
        permission_codes=codes,
    )


def list_permissions(
    db: Session,
    *,
    resource_owner_user_id: UUID,
) -> tuple[FamilyPermissionView, ...]:
    with _read_session(db) as read:
        membership = _require_membership(read, resource_owner_user_id)
        rows = read.execute(
            select(
                FamilyPermissionGrant.grantee_user_id,
                FamilyPermissionGrant.permission_code,
            )
            .where(
                FamilyPermissionGrant.family_id == membership.family_id,
                FamilyPermissionGrant.resource_owner_user_id == resource_owner_user_id,
            )
            .order_by(
                FamilyPermissionGrant.grantee_user_id.asc(),
                FamilyPermissionGrant.permission_code.asc(),
            )
        ).all()

    grouped: dict[UUID, list[str]] = {}
    for grantee_id, code in rows:
        grouped.setdefault(grantee_id, []).append(code)
    return tuple(
        FamilyPermissionView(
            grantee_user_id=grantee_id,
            permission_codes=tuple(codes),
        )
        for grantee_id, codes in grouped.items()
    )


def has_family_permission(
    db: Session,
    *,
    resource_owner_user_id: UUID,
    grantee_user_id: UUID,
    permission_code: str | FamilyPermissionCode,
) -> bool:
    code = (
        permission_code.value
        if isinstance(permission_code, FamilyPermissionCode)
        else permission_code
    )
    if code not in SUPPORTED_FAMILY_PERMISSION_CODES:
        return False
    if resource_owner_user_id == grantee_user_id:
        return False

    owner_membership = aliased(FamilyMembership)
    grantee_membership = aliased(FamilyMembership)
    with _read_session(db) as read:
        grant_id = read.scalar(
            select(FamilyPermissionGrant.id)
            .join(
                owner_membership,
                (owner_membership.family_id == FamilyPermissionGrant.family_id)
                & (
                    owner_membership.user_id
                    == FamilyPermissionGrant.resource_owner_user_id
                ),
            )
            .join(
                grantee_membership,
                (grantee_membership.family_id == FamilyPermissionGrant.family_id)
                & (grantee_membership.user_id == FamilyPermissionGrant.grantee_user_id),
            )
            .where(
                FamilyPermissionGrant.resource_owner_user_id
                == resource_owner_user_id,
                FamilyPermissionGrant.grantee_user_id == grantee_user_id,
                FamilyPermissionGrant.permission_code == code,
            )
            .limit(1)
        )
        return grant_id is not None
