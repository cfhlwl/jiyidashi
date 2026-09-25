from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models import utcnow


class FamilyRole(StrEnum):
    OWNER = "OWNER"
    MEMBER = "MEMBER"


class FamilyPermissionCode(StrEnum):
    VIEW_CURRENT_LOCATION = "VIEW_CURRENT_LOCATION"
    VIEW_FOOTPRINT = "VIEW_FOOTPRINT"
    VIEW_MEMORY = "VIEW_MEMORY"
    VIEW_PHOTOS = "VIEW_PHOTOS"


class FamilyAuditResourceType(StrEnum):
    CURRENT_LOCATION = "CURRENT_LOCATION"
    TODAY_FOOTPRINT = "TODAY_FOOTPRINT"
    MEMORY = "MEMORY"
    PHOTO = "PHOTO"


class FamilyAuditAction(StrEnum):
    READ_CURRENT_LOCATION = "READ_CURRENT_LOCATION"
    READ_TODAY_FOOTPRINT = "READ_TODAY_FOOTPRINT"
    READ_MEMORY = "READ_MEMORY"
    LIST_PHOTOS = "LIST_PHOTOS"
    DOWNLOAD_PHOTO = "DOWNLOAD_PHOTO"


class FamilyAuditResult(StrEnum):
    ALLOWED = "ALLOWED"
    DENIED = "DENIED"
    UNAVAILABLE = "UNAVAILABLE"


SUPPORTED_FAMILY_PERMISSION_CODES = frozenset(item.value for item in FamilyPermissionCode)


class Family(Base):
    __tablename__ = "families"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FamilyMembership(Base):
    __tablename__ = "family_memberships"
    __table_args__ = (
        UniqueConstraint(
            "family_id",
            "user_id",
            name="uq_family_memberships_family_user",
        ),
        # V1 has exactly one active membership row per user. Removal deletes the row.
        UniqueConstraint(
            "user_id",
            name="uq_family_memberships_one_family_per_user",
        ),
        CheckConstraint(
            "role IN ('OWNER', 'MEMBER')",
            name="ck_family_memberships_role",
        ),
        # Application lifecycle guarantees at least one OWNER after create; this DB index
        # guarantees there can never be two owners for the same Family.
        Index(
            "uq_family_memberships_one_owner",
            "family_id",
            unique=True,
            postgresql_where=text("role = 'OWNER'"),
            sqlite_where=text("role = 'OWNER'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE")
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FamilyInvite(Base):
    __tablename__ = "family_invites"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_family_invites_token_hash"),
        CheckConstraint(
            "NOT (accepted_at IS NOT NULL AND revoked_at IS NOT NULL)",
            name="ck_family_invites_not_accepted_and_revoked",
        ),
        CheckConstraint(
            "((accepted_at IS NULL AND accepted_by_user_id IS NULL) "
            "OR (accepted_at IS NOT NULL AND accepted_by_user_id IS NOT NULL))",
            name="ck_family_invites_accept_pair",
        ),
        Index(
            "ix_family_invites_family_created",
            "family_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE")
    )
    inviter_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    token_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    accepted_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FamilyPermissionGrant(Base):
    __tablename__ = "family_permission_grants"
    __table_args__ = (
        UniqueConstraint(
            "family_id",
            "resource_owner_user_id",
            "grantee_user_id",
            "permission_code",
            name="uq_family_permission_grants_semantic_key",
        ),
        CheckConstraint(
            "resource_owner_user_id <> grantee_user_id",
            name="ck_family_permission_grants_distinct_users",
        ),
        CheckConstraint(
            "permission_code IN "
            "('VIEW_CURRENT_LOCATION', 'VIEW_FOOTPRINT', 'VIEW_MEMORY', 'VIEW_PHOTOS')",
            name="ck_family_permission_grants_code",
        ),
        # These composite FKs make same-Family active membership a DB-level invariant.
        # Deleting either membership cascades every grant that depended on it.
        ForeignKeyConstraint(
            ["family_id", "resource_owner_user_id"],
            ["family_memberships.family_id", "family_memberships.user_id"],
            name="fk_family_grants_resource_owner_membership",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["family_id", "grantee_user_id"],
            ["family_memberships.family_id", "family_memberships.user_id"],
            name="fk_family_grants_grantee_membership",
            ondelete="CASCADE",
        ),
        Index(
            "ix_family_permission_grants_grantee_code",
            "grantee_user_id",
            "permission_code",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column()
    resource_owner_user_id: Mapped[UUID] = mapped_column()
    grantee_user_id: Mapped[UUID] = mapped_column()
    permission_code: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)



class FamilyAccessAuditEvent(Base):
    __tablename__ = "family_access_audit_events"
    __table_args__ = (
        CheckConstraint(
            "permission_code IN "
            "('VIEW_CURRENT_LOCATION', 'VIEW_FOOTPRINT', 'VIEW_MEMORY', 'VIEW_PHOTOS')",
            name="ck_family_access_audit_permission_code",
        ),
        CheckConstraint(
            "resource_type IN ('CURRENT_LOCATION', 'TODAY_FOOTPRINT', 'MEMORY', 'PHOTO')",
            name="ck_family_access_audit_resource_type",
        ),
        CheckConstraint(
            "action IN "
            "('READ_CURRENT_LOCATION', 'READ_TODAY_FOOTPRINT', 'READ_MEMORY', "
            "'LIST_PHOTOS', 'DOWNLOAD_PHOTO')",
            name="ck_family_access_audit_action",
        ),
        CheckConstraint(
            "result IN ('ALLOWED', 'DENIED', 'UNAVAILABLE')",
            name="ck_family_access_audit_result",
        ),
        CheckConstraint(
            "actor_user_id <> resource_owner_user_id",
            name="ck_family_access_audit_distinct_users",
        ),
        Index(
            "ix_family_access_audit_family_created",
            "family_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(
        ForeignKey("families.id", ondelete="CASCADE")
    )
    actor_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    resource_owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    permission_code: Mapped[str] = mapped_column(String(40))
    resource_type: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(40))
    result: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
