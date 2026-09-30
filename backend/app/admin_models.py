from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models import utcnow


class AdminRole(StrEnum):
    SUPER_ADMIN = "SUPER_ADMIN"
    OPERATOR = "OPERATOR"
    SUPPORT_READONLY = "SUPPORT_READONLY"


class AdminAccount(Base):
    """Independent privileged identity. It is never a product User/AuthIdentity."""

    __tablename__ = "admin_accounts"
    __table_args__ = (
        UniqueConstraint("email", name="uq_admin_accounts_email"),
        CheckConstraint(
            "role IN ('SUPER_ADMIN','OPERATOR','SUPPORT_READONLY')",
            name="ck_admin_accounts_role",
        ),
        CheckConstraint("revision >= 0", name="ck_admin_accounts_revision"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AdminSession(Base):
    """Revocable opaque browser session. Raw session/CSRF tokens are never persisted."""

    __tablename__ = "admin_sessions"
    __table_args__ = (
        UniqueConstraint("token_digest", name="uq_admin_sessions_token_digest"),
        Index("ix_admin_sessions_admin_expires", "admin_id", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    admin_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    csrf_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    admin_revision_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AdminAuditEvent(Base):
    """Append-only bounded privileged-operation audit event."""

    __tablename__ = "admin_audit_events"
    __table_args__ = (
        Index("ix_admin_audit_created_id", "created_at", "id"),
        Index("ix_admin_audit_actor_created", "admin_actor_id", "created_at"),
        Index("ix_admin_audit_action_created", "action", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    admin_actor_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admin_accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    admin_role_snapshot: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(96), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(255))
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    request_ref: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EntitlementQuotaPolicy(Base):
    """Canonical DB-backed runtime quota catalog for commercial plans."""

    __tablename__ = "entitlement_quota_policies"
    __table_args__ = (
        CheckConstraint(
            "plan_code IN ('FREE','PERSONAL','FAMILY','PREMIUM')",
            name="ck_entitlement_quota_policy_plan",
        ),
        CheckConstraint("revision >= 0", name="ck_entitlement_quota_policy_revision"),
        CheckConstraint("storage_bytes >= 0", name="ck_entitlement_quota_storage"),
        CheckConstraint(
            "ai_provider_requests >= 0",
            name="ck_entitlement_quota_ai_requests",
        ),
        CheckConstraint("ai_input_tokens >= 0", name="ck_entitlement_quota_input"),
        CheckConstraint("ai_output_tokens >= 0", name="ck_entitlement_quota_output"),
    )

    plan_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ai_provider_requests: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ai_input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ai_output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_by_admin_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admin_accounts.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
