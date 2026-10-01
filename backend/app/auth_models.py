from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models import utcnow


class AuthProvider(StrEnum):
    EMAIL_PASSWORD = "EMAIL_PASSWORD"


class AuthIdentity(Base):
    """Login identity separated from the long-lived user profile.

    [人工注释][S1-001] 身份提供方与 User 分离，后续接 Apple / 微信 / 手机号时不改用户主表。
    """

    __tablename__ = "auth_identities"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "subject",
            name="uq_auth_identities_provider_subject",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[AuthProvider] = mapped_column(
        Enum(AuthProvider, native_enum=False),
        nullable=False,
    )
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    secret_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthOneTimePurpose(StrEnum):
    EMAIL_VERIFY = "EMAIL_VERIFY"
    PASSWORD_RESET = "PASSWORD_RESET"


class AuthSession(Base):
    """Durable public-auth session authority.

    Raw refresh tokens are never persisted. The current refresh token is represented
    only by a server-keyed digest; consumed refresh digests move to receipts so replay
    can revoke the affected token family.
    """

    __tablename__ = "auth_sessions"
    __table_args__ = (
        UniqueConstraint("refresh_digest", name="uq_auth_sessions_refresh_digest"),
        Index("ix_auth_sessions_user_expires", "user_id", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[str] = mapped_column(String(120))
    refresh_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    rotation_revision: Mapped[int] = mapped_column(Integer, default=0)
    client_platform: Mapped[str | None] = mapped_column(String(32), nullable=True)
    device_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoke_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AuthRefreshTokenReceipt(Base):
    """Consumed refresh digest retained only for replay detection."""

    __tablename__ = "auth_refresh_token_receipts"
    __table_args__ = (
        Index("ix_auth_refresh_receipts_session", "session_id", "consumed_at"),
    )

    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="CASCADE")
    )
    rotation_revision: Mapped[int] = mapped_column(Integer)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuthOneTimeToken(Base):
    """Hashed single-use verification/reset token."""

    __tablename__ = "auth_one_time_tokens"
    __table_args__ = (
        UniqueConstraint("digest", name="uq_auth_one_time_tokens_digest"),
        Index("ix_auth_one_time_user_purpose", "user_id", "purpose", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[AuthOneTimePurpose] = mapped_column(
        Enum(AuthOneTimePurpose, native_enum=False)
    )
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AuthRateLimitBucket(Base):
    """Persistent anonymous-auth abuse guard shared by all app workers."""

    __tablename__ = "auth_rate_limit_buckets"

    # [人工注释][S1-FIX-003] 只保存 HMAC bucket key，不落原始 IP / 邮箱；
    # 数据库门禁在 Argon2 前生效。
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope: Mapped[str] = mapped_column(String(40), index=True)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    blocked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
