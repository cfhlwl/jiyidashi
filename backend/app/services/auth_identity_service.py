from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.account_deletion_models import AccountDeletionOperation
from app.auth_models import AuthIdentity, AuthProvider
from app.core.observability import emit_operational_event
from app.models import User
from app.services.auth_session_service import (
    PublicAuthError,
    PublicSessionTokens,
    create_public_session_in_transaction,
)
from app.services.entitlement_service import create_registration_default_entitlement

_PHONE_E164_RE = re.compile(r"\+[1-9][0-9]{7,14}\Z")
_WECHAT_COMPONENT_RE = re.compile(r"[A-Za-z0-9._~-]+\Z")


class AuthIdentityError(RuntimeError):
    def __init__(self, code: str, status_code: int = 409):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class AuthIdentityResolution:
    identity: AuthIdentity
    user_id: UUID


@dataclass(frozen=True)
class AuthIdentityCreation:
    identity: AuthIdentity
    user_id: UUID
    created: bool


@dataclass(frozen=True)
class AuthenticatedSession:
    tokens: PublicSessionTokens
    account_deletion_in_progress: bool


def canonicalize_email_subject(value: str) -> str:
    subject = value.strip().casefold()
    if not subject or any(ord(char) < 32 for char in subject):
        raise AuthIdentityError("AUTH_IDENTITY_SUBJECT_INVALID", 422)
    return subject


def canonicalize_phone_subject(value: str) -> str:
    # V1 deliberately accepts only an already canonical E.164 value. Without a
    # trusted region context, guessing a country code would create a new authority.
    if value != value.strip() or _PHONE_E164_RE.fullmatch(value) is None:
        raise AuthIdentityError("AUTH_PHONE_SUBJECT_NOT_CANONICAL", 422)
    return value


def canonicalize_wechat_subject(value: str) -> str:
    if value != value.strip() or len(value) > 255 or any(
        ord(char) < 32 or char.isspace() for char in value
    ):
        raise AuthIdentityError("AUTH_WECHAT_SUBJECT_INVALID", 422)

    parts = value.split(":")
    if len(parts) != 3 or parts[0] not in {"unionid", "openid"}:
        raise AuthIdentityError("AUTH_WECHAT_SUBJECT_INVALID", 422)
    if not _WECHAT_COMPONENT_RE.fullmatch(parts[1]) or not _WECHAT_COMPONENT_RE.fullmatch(
        parts[2]
    ):
        raise AuthIdentityError("AUTH_WECHAT_SUBJECT_INVALID", 422)
    return value


def canonicalize_subject(provider: AuthProvider, value: str) -> str:
    if provider is AuthProvider.EMAIL_PASSWORD:
        return canonicalize_email_subject(value)
    if provider is AuthProvider.PHONE:
        return canonicalize_phone_subject(value)
    if provider is AuthProvider.WECHAT:
        return canonicalize_wechat_subject(value)
    raise AuthIdentityError("AUTH_PROVIDER_UNSUPPORTED", 422)


def _canonical_projection(provider: AuthProvider, subject: str) -> dict[str, str]:
    if provider is AuthProvider.EMAIL_PASSWORD:
        return {"email": subject}
    if provider is AuthProvider.PHONE:
        return {"phone": subject}
    return {}


def _check_user_available(user: User) -> None:
    if user.auth_disabled_at is not None:
        raise AuthIdentityError("AUTH_ACCOUNT_UNAVAILABLE", 401)


def _validate_identity_material(
    provider: AuthProvider,
    *,
    secret_hash: str | None,
    verified_at: datetime | None,
    require_verified: bool = False,
) -> None:
    """Keep provider-specific identity invariants at the authority boundary."""

    if require_verified and verified_at is None:
        raise AuthIdentityError("AUTH_IDENTITY_NOT_VERIFIED", 422)
    if provider is AuthProvider.EMAIL_PASSWORD:
        if not secret_hash:
            raise AuthIdentityError("AUTH_IDENTITY_SECRET_REQUIRED", 422)
        return
    if verified_at is None:
        raise AuthIdentityError("AUTH_IDENTITY_NOT_VERIFIED", 422)
    if secret_hash is not None:
        raise AuthIdentityError("AUTH_IDENTITY_SECRET_NOT_ALLOWED", 422)


def resolve_auth_identity(
    db: Session,
    *,
    provider: AuthProvider,
    subject: str,
) -> AuthIdentityResolution | None:
    """Resolve only through the canonical provider/subject authority.

    User.email and User.phone are intentionally not fallback lookup paths.
    """

    canonical_subject = canonicalize_subject(provider, subject)
    identity = db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == provider,
            AuthIdentity.subject == canonical_subject,
        )
    )
    if identity is None:
        return None

    user = db.get(User, identity.user_id)
    if user is None:
        raise AuthIdentityError("AUTH_IDENTITY_NOT_FOUND", 401)
    if user.auth_disabled_at is not None:
        raise AuthIdentityError("AUTH_ACCOUNT_UNAVAILABLE", 401)
    if (
        provider in {AuthProvider.PHONE, AuthProvider.WECHAT}
        and identity.verified_at is None
    ):
        raise AuthIdentityError("AUTH_IDENTITY_NOT_VERIFIED", 401)
    return AuthIdentityResolution(identity=identity, user_id=user.id)


def _user_provider_identity(
    db: Session,
    *,
    user_id: UUID,
    provider: AuthProvider,
) -> AuthIdentity | None:
    if provider not in {AuthProvider.EMAIL_PASSWORD, AuthProvider.PHONE}:
        return None
    return db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.user_id == user_id,
            AuthIdentity.provider == provider,
        )
    )


def _apply_projection(user: User, *, provider: AuthProvider, subject: str) -> None:
    for field, value in _canonical_projection(provider, subject).items():
        setattr(user, field, value)


def create_user_for_verified_identity(
    db: Session,
    *,
    provider: AuthProvider,
    subject: str,
    secret_hash: str | None = None,
    verified_at: datetime | None = None,
    nickname: str = "新用户",
    timezone: str = "Asia/Shanghai",
    locale: str = "zh-CN",
    entitlement_creator=create_registration_default_entitlement,
) -> AuthIdentityCreation:
    """Atomically create User, identity, projections, and initial entitlement.

    The caller owns the surrounding request. A nested transaction makes a unique-key
    race roll back the provisional User and entitlement together, then retries by
    resolving the winner's identity without changing its User.id.
    """

    _validate_identity_material(
        provider,
        secret_hash=secret_hash,
        verified_at=verified_at,
    )
    canonical_subject = canonicalize_subject(provider, subject)
    existing = db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == provider,
            AuthIdentity.subject == canonical_subject,
        )
    )
    if existing is not None:
        resolution = resolve_auth_identity(
            db,
            provider=provider,
            subject=canonical_subject,
        )
        if resolution is None:  # pragma: no cover - same transaction cannot lose row
            raise AuthIdentityError("AUTH_IDENTITY_NOT_FOUND", 409)
        return AuthIdentityCreation(
            identity=resolution.identity,
            user_id=resolution.user_id,
            created=False,
        )

    try:
        with db.begin_nested():
            user = User(nickname=nickname, timezone=timezone, locale=locale)
            _apply_projection(user, provider=provider, subject=canonical_subject)
            db.add(user)
            db.flush()

            identity = AuthIdentity(
                user_id=user.id,
                provider=provider,
                subject=canonical_subject,
                secret_hash=secret_hash,
                verified_at=verified_at,
            )
            db.add(identity)
            entitlement_creator(db, user_id=user.id)
            db.flush()
    except IntegrityError as exc:
        winner = resolve_auth_identity(
            db,
            provider=provider,
            subject=canonical_subject,
        )
        if winner is None:
            raise AuthIdentityError("AUTH_IDENTITY_CONFLICT", 409) from exc
        return AuthIdentityCreation(
            identity=winner.identity,
            user_id=winner.user_id,
            created=False,
        )

    return AuthIdentityCreation(identity=identity, user_id=user.id, created=True)


def _lock_user_for_identity_link(db: Session, user_id: UUID) -> User:
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise AuthIdentityError("AUTH_ACCOUNT_UNAVAILABLE", 401)
    _check_user_available(user)
    deletion_active = db.scalar(
        select(AccountDeletionOperation.id)
        .where(AccountDeletionOperation.user_id == user_id)
        .limit(1)
    )
    if deletion_active is not None:
        raise AuthIdentityError("ACCOUNT_DELETION_IN_PROGRESS", 423)
    return user


def _link_verified_identities_without_commit(
    db: Session,
    *,
    user_id: UUID,
    provider: AuthProvider,
    canonical_subjects: list[str],
    verified_at: datetime | None,
    secret_hash: str | None,
    require_verified: bool = True,
) -> list[AuthIdentity]:
    """Link identities while leaving transaction ownership with the caller."""

    _validate_identity_material(
        provider,
        secret_hash=secret_hash,
        verified_at=verified_at,
        require_verified=require_verified,
    )
    user = _lock_user_for_identity_link(db, user_id)

    # Query in canonical stable order so a multi-alias link has one lock order.
    existing_by_subject: dict[str, AuthIdentity] = {}
    for canonical_subject in sorted(set(canonical_subjects)):
        identity = db.scalar(
            select(AuthIdentity)
            .where(
                AuthIdentity.provider == provider,
                AuthIdentity.subject == canonical_subject,
            )
            .with_for_update()
        )
        if identity is not None:
            existing_by_subject[canonical_subject] = identity

    for identity in existing_by_subject.values():
        if identity.user_id != user_id:
            raise AuthIdentityError("AUTH_IDENTITY_CONFLICT", 409)
        if identity.verified_at is None:
            raise AuthIdentityError("AUTH_IDENTITY_NOT_VERIFIED", 409)

    if provider in {AuthProvider.EMAIL_PASSWORD, AuthProvider.PHONE}:
        current_provider_identity = _user_provider_identity(
            db,
            user_id=user_id,
            provider=provider,
        )
        missing_subjects = [
            subject
            for subject in canonical_subjects
            if subject not in existing_by_subject
        ]
        if current_provider_identity is not None and missing_subjects:
            raise AuthIdentityError("AUTH_IDENTITY_CONFLICT", 409)

    identities: list[AuthIdentity] = []
    for canonical_subject in canonical_subjects:
        identity = existing_by_subject.get(canonical_subject)
        if identity is None:
            identity = AuthIdentity(
                user_id=user_id,
                provider=provider,
                subject=canonical_subject,
                secret_hash=secret_hash,
                verified_at=verified_at,
            )
            db.add(identity)
        identities.append(identity)

    if canonical_subjects:
        _apply_projection(user, provider=provider, subject=canonical_subjects[0])
    return identities


def link_verified_identity(
    db: Session,
    *,
    user_id: UUID,
    provider: AuthProvider,
    subject: str,
    verified_at: datetime | None = None,
    secret_hash: str | None = None,
) -> AuthIdentityResolution:
    """Link an already verified identity without exposing a provider endpoint."""

    canonical_subject = canonicalize_subject(provider, subject)
    try:
        identity = _link_verified_identities_without_commit(
            db,
            user_id=user_id,
            provider=provider,
            canonical_subjects=[canonical_subject],
            verified_at=verified_at,
            secret_hash=secret_hash,
            require_verified=True,
        )[0]
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        winner = db.scalar(
            select(AuthIdentity).where(
                AuthIdentity.provider == provider,
                AuthIdentity.subject == canonical_subject,
            )
        )
        if winner is not None and winner.user_id == user_id:
            if winner.verified_at is None:
                raise AuthIdentityError("AUTH_IDENTITY_NOT_VERIFIED", 409) from exc
            if provider is AuthProvider.EMAIL_PASSWORD and not winner.secret_hash:
                raise AuthIdentityError("AUTH_IDENTITY_CONFLICT", 409) from exc
            if provider in {AuthProvider.PHONE, AuthProvider.WECHAT} and winner.secret_hash:
                raise AuthIdentityError("AUTH_IDENTITY_CONFLICT", 409) from exc
            return AuthIdentityResolution(identity=winner, user_id=user_id)
        raise AuthIdentityError("AUTH_IDENTITY_CONFLICT", 409) from exc
    return AuthIdentityResolution(identity=identity, user_id=user_id)


def link_verified_wechat_aliases(
    db: Session,
    *,
    user_id: UUID,
    aliases: list[str] | tuple[str, ...],
    verified_at: datetime | None,
) -> tuple[AuthIdentity, ...]:
    """Atomically bind all verified WeChat aliases or none of them."""

    canonical_aliases = [
        canonicalize_subject(AuthProvider.WECHAT, alias) for alias in aliases
    ]
    if not canonical_aliases:
        raise AuthIdentityError("AUTH_WECHAT_ALIAS_REQUIRED", 422)
    if len(set(canonical_aliases)) != len(canonical_aliases):
        raise AuthIdentityError("AUTH_WECHAT_ALIAS_DUPLICATE", 422)
    try:
        identities = _link_verified_identities_without_commit(
            db,
            user_id=user_id,
            provider=AuthProvider.WECHAT,
            canonical_subjects=canonical_aliases,
            verified_at=verified_at,
            secret_hash=None,
            require_verified=True,
        )
        db.commit()
    except AuthIdentityError:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        reconciled = [
            db.scalar(
                select(AuthIdentity).where(
                    AuthIdentity.provider == AuthProvider.WECHAT,
                    AuthIdentity.subject == canonical_subject,
                )
            )
            for canonical_subject in sorted(canonical_aliases)
        ]
        if any(identity is not None and identity.user_id != user_id for identity in reconciled):
            raise AuthIdentityError("AUTH_IDENTITY_CONFLICT", 409) from exc
        if any(identity is None for identity in reconciled):
            raise AuthIdentityError("AUTH_IDENTITY_CONFLICT", 409) from exc
        if any(identity.verified_at is None for identity in reconciled):
            raise AuthIdentityError("AUTH_IDENTITY_NOT_VERIFIED", 409) from exc
        if any(identity.secret_hash is not None for identity in reconciled):
            raise AuthIdentityError("AUTH_IDENTITY_CONFLICT", 409) from exc
        return tuple(reconciled)
    return tuple(identities)


def unlink_identity(
    db: Session,
    *,
    user_id: UUID,
    identity_id: UUID,
) -> None:
    """Foundation-only unlink with last-login-method and projection guards."""

    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise AuthIdentityError("AUTH_ACCOUNT_UNAVAILABLE", 401)
    _check_user_available(user)
    deletion_active = db.scalar(
        select(AccountDeletionOperation.id)
        .where(AccountDeletionOperation.user_id == user_id)
        .limit(1)
    )
    if deletion_active is not None:
        raise AuthIdentityError("ACCOUNT_DELETION_IN_PROGRESS", 423)

    identity = db.scalar(
        select(AuthIdentity)
        .where(AuthIdentity.id == identity_id, AuthIdentity.user_id == user_id)
        .with_for_update()
    )
    if identity is None:
        raise AuthIdentityError("AUTH_IDENTITY_NOT_FOUND", 404)

    identity_count = int(
        db.scalar(
            select(func.count(AuthIdentity.id)).where(
                AuthIdentity.user_id == user_id
            )
        )
        or 0
    )
    if identity_count <= 1:
        raise AuthIdentityError("AUTH_LAST_IDENTITY_REQUIRED", 409)

    provider = identity.provider
    db.delete(identity)
    if provider in {AuthProvider.EMAIL_PASSWORD, AuthProvider.PHONE}:
        replacement = db.scalar(
            select(AuthIdentity)
            .where(
                AuthIdentity.user_id == user_id,
                AuthIdentity.provider == provider,
                AuthIdentity.id != identity_id,
            )
            .order_by(AuthIdentity.created_at, AuthIdentity.id)
        )
        if provider is AuthProvider.EMAIL_PASSWORD:
            user.email = replacement.subject if replacement is not None else None
        else:
            user.phone = replacement.subject if replacement is not None else None
    db.commit()


def issue_authenticated_session_in_transaction(
    db: Session,
    *,
    user_id: UUID,
    device_id: str,
    client_platform: str | None = None,
    device_name: str | None = None,
) -> AuthenticatedSession:
    """Shared provider-neutral session issuance authority."""

    user = db.scalar(
        select(User).where(User.id == user_id).with_for_update(read=True, key_share=True)
    )
    if user is None:
        raise PublicAuthError("AUTH_ACCOUNT_UNAVAILABLE")
    if user.auth_disabled_at is not None:
        raise PublicAuthError("AUTH_ACCOUNT_UNAVAILABLE")

    account_deletion_in_progress = (
        db.scalar(
            select(AccountDeletionOperation.id)
            .where(AccountDeletionOperation.user_id == user_id)
            .limit(1)
        )
        is not None
    )
    pair = create_public_session_in_transaction(
        db,
        user_id=user_id,
        device_id=device_id,
        client_platform=client_platform,
        device_name=device_name,
    )
    return AuthenticatedSession(
        tokens=pair,
        account_deletion_in_progress=account_deletion_in_progress,
    )


def issue_authenticated_session(
    db: Session,
    *,
    user_id: UUID,
    device_id: str,
    client_platform: str | None = None,
    device_name: str | None = None,
) -> AuthenticatedSession:
    issued = issue_authenticated_session_in_transaction(
        db,
        user_id=user_id,
        device_id=device_id,
        client_platform=client_platform,
        device_name=device_name,
    )
    db.commit()
    emit_operational_event(
        event="auth.session.created",
        correlation_id=str(issued.tokens.session_id),
        operation="PUBLIC_AUTH_SESSION",
        operation_status="CREATED",
    )
    return issued
