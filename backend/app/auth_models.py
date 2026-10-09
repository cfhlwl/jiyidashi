from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models import utcnow


class AuthProvider(StrEnum):
    EMAIL_PASSWORD = "EMAIL_PASSWORD"
    PHONE = "PHONE"
    WECHAT = "WECHAT"


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
        Index(
            "uq_auth_identities_user_email_password",
            "user_id",
            unique=True,
            sqlite_where=text("provider = 'EMAIL_PASSWORD'"),
            postgresql_where=text("provider = 'EMAIL_PASSWORD'"),
        ),
        Index(
            "uq_auth_identities_user_phone",
            "user_id",
            unique=True,
            sqlite_where=text("provider = 'PHONE'"),
            postgresql_where=text("provider = 'PHONE'"),
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


class WechatExchangeState(StrEnum):
    RESERVED = "RESERVED"
    COMPLETED = "COMPLETED"
    PROVIDER_REJECTED = "PROVIDER_REJECTED"
    PROVIDER_UNKNOWN = "PROVIDER_UNKNOWN"


class WechatExchangeRecoveryState(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class WechatLoginExchange(Base):
    """Durable receipt for one provider credential exchange.

    The transient WeChat code/access token is never stored. The keyed
    fingerprint only fences replay; completed receipts are terminal.
    """

    __tablename__ = "auth_wechat_login_exchanges"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_wechat_login_request_id"),
        UniqueConstraint("credential_fingerprint", name="uq_wechat_login_credential_fingerprint"),
        Index("ix_wechat_login_state_expires", "state", "expires_at"),
        Index("ix_wechat_login_lease", "state", "lease_expires_at"),
        CheckConstraint(
            "state IN ('RESERVED', 'COMPLETED', 'PROVIDER_REJECTED', 'PROVIDER_UNKNOWN')",
            name="ck_wechat_login_exchange_state",
        ),
        CheckConstraint(
            "recovery_state IN ('OPEN', 'CLOSED')",
            name="ck_wechat_login_recovery_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    request_id: Mapped[UUID] = mapped_column(nullable=False)
    credential_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint_key_version: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[WechatExchangeState] = mapped_column(
        String(32), nullable=False, default=WechatExchangeState.RESERVED
    )
    recovery_state: Mapped[WechatExchangeRecoveryState] = mapped_column(
        String(16), nullable=False, default=WechatExchangeRecoveryState.CLOSED
    )
    device_id: Mapped[str] = mapped_column(String(120), nullable=False)
    client_platform: Mapped[str | None] = mapped_column(String(32), nullable=True)
    device_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    replacement_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recovery_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recovery_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


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


class PhoneOneTapExchangeState(StrEnum):
    RESERVED = "RESERVED"
    COMPLETED = "COMPLETED"
    PROVIDER_REJECTED = "PROVIDER_REJECTED"
    PROVIDER_UNKNOWN = "PROVIDER_UNKNOWN"


class PhoneOneTapRecoveryState(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class AuthSmsOtpChallengeState(StrEnum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"
    LOCKED = "LOCKED"
    PROVIDER_ERROR = "PROVIDER_ERROR"


class AuthSmsOtpChallenge(Base):
    """Durable SMS OTP challenge authority without storing the raw OTP."""

    __tablename__ = "auth_sms_otp_challenges"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_auth_sms_otp_request_id"),
        UniqueConstraint("active_key", name="uq_auth_sms_otp_active_key"),
        Index("ix_auth_sms_otp_state_expires", "state", "expires_at"),
        Index("ix_auth_sms_otp_phone_created", "phone_subject", "created_at"),
        CheckConstraint(
            "state IN ('PENDING', 'VERIFIED', 'EXPIRED', 'LOCKED', 'PROVIDER_ERROR')",
            name="ck_auth_sms_otp_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    request_id: Mapped[UUID] = mapped_column(nullable=False)
    active_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    phone_subject: Mapped[str] = mapped_column(String(32), nullable=False)
    code_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    code_key_version: Mapped[str] = mapped_column(String(16), nullable=False)
    device_id: Mapped[str] = mapped_column(String(120), nullable=False)
    client_platform: Mapped[str | None] = mapped_column(String(32), nullable=True)
    device_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    state: Mapped[AuthSmsOtpChallengeState] = mapped_column(
        String(32),
        nullable=False,
        default=AuthSmsOtpChallengeState.PENDING,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cooldown_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PhoneOneTapExchange(Base):
    """Durable authority for one provider-token exchange attempt.

    The provider login token itself is never stored. ``token_fingerprint`` is a
    deployment-keyed digest used only for replay/conflict decisions. Session and
    user references are nullable so exchange history cannot block account/session
    deletion.
    """

    __tablename__ = "auth_phone_one_tap_exchanges"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_phone_one_tap_request_id"),
        UniqueConstraint("token_fingerprint", name="uq_phone_one_tap_token_fingerprint"),
        Index("ix_phone_one_tap_state_expires", "state", "expires_at"),
        Index("ix_phone_one_tap_lease", "state", "lease_expires_at"),
        Index("ix_phone_one_tap_created", "created_at"),
        CheckConstraint(
            "state IN ('RESERVED', 'COMPLETED', 'PROVIDER_REJECTED', 'PROVIDER_UNKNOWN')",
            name="ck_phone_one_tap_exchange_state",
        ),
        CheckConstraint(
            "recovery_state IN ('OPEN', 'CLOSED')",
            name="ck_phone_one_tap_recovery_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    request_id: Mapped[UUID] = mapped_column(nullable=False)
    token_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint_key_version: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[PhoneOneTapExchangeState] = mapped_column(
        String(32),
        nullable=False,
        default=PhoneOneTapExchangeState.RESERVED,
    )
    recovery_state: Mapped[PhoneOneTapRecoveryState] = mapped_column(
        String(16),
        nullable=False,
        default=PhoneOneTapRecoveryState.CLOSED,
    )
    device_id: Mapped[str] = mapped_column(String(120), nullable=False)
    client_platform: Mapped[str | None] = mapped_column(String(32), nullable=True)
    device_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    replacement_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recovery_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recovery_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
