from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.auth_models import AuthProvider
from app.core.config import Settings, get_settings
from app.services.auth_identity_service import AuthIdentityError, canonicalize_subject


class AuthIdentityLinkProviderError(RuntimeError):
    """Provider-neutral, client-safe verification outcome."""

    def __init__(self, code: str, status_code: int = 503):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class VerifiedIdentityProof:
    """Server-produced proof; none of these identity fields come from the API body."""

    provider: AuthProvider
    subject: str
    verified_at: datetime
    reauthenticated_at: datetime
    user_id: UUID
    session_id: UUID
    secret_hash: str | None = None
    provider_request_id: str | None = None

    def __post_init__(self) -> None:
        try:
            canonical = canonicalize_subject(self.provider, self.subject)
        except AuthIdentityError as exc:
            raise AuthIdentityLinkProviderError("AUTH_PROVIDER_TOKEN_INVALID", 401) from exc
        if canonical != self.subject:
            raise AuthIdentityLinkProviderError("AUTH_PROVIDER_TOKEN_INVALID", 401)
        for value in (self.verified_at, self.reauthenticated_at):
            if value.tzinfo is None or value.utcoffset() is None:
                raise AuthIdentityLinkProviderError("AUTH_PROVIDER_ERROR")


class AuthIdentityLinkProvider(Protocol):
    available: bool

    def verify_link_credentials(
        self,
        *,
        credential: str,
        reauth_credential: str,
        user_id: UUID,
        session_id: UUID,
        request_id: UUID,
    ) -> VerifiedIdentityProof:
        """Verify opaque provider and step-up credentials without DB mutation."""

    def verify_reauthentication(
        self,
        *,
        reauth_credential: str,
        user_id: UUID,
        session_id: UUID,
        request_id: UUID,
    ) -> datetime:
        """Return the server-observed recent reauthentication time."""


class DisabledAuthIdentityLinkProvider:
    available = False

    def verify_link_credentials(self, **_: object) -> VerifiedIdentityProof:
        raise AuthIdentityLinkProviderError("AUTH_PROVIDER_UNAVAILABLE", 503)

    def verify_reauthentication(self, **_: object) -> datetime:
        raise AuthIdentityLinkProviderError("AUTH_PROVIDER_UNAVAILABLE", 503)


class FakeAuthIdentityLinkProvider:
    """Explicit test/development seam; never selected in production."""

    available = True

    def __init__(
        self,
        *,
        link_results: dict[str, VerifiedIdentityProof] | None = None,
        reauth_results: dict[str, datetime] | None = None,
    ) -> None:
        self.link_results = link_results or {}
        self.reauth_results = reauth_results or {}
        self.link_calls = 0
        self.reauth_calls = 0

    def verify_link_credentials(
        self,
        *,
        credential: str,
        reauth_credential: str,
        user_id: UUID,
        session_id: UUID,
        request_id: UUID,
    ) -> VerifiedIdentityProof:
        self.link_calls += 1
        result = self.link_results.get(credential)
        if result is None or reauth_credential not in self.reauth_results:
            raise AuthIdentityLinkProviderError("AUTH_PROVIDER_TOKEN_INVALID", 401)
        if result.user_id != user_id or result.session_id != session_id:
            raise AuthIdentityLinkProviderError("AUTH_PROVIDER_SCOPE_MISMATCH", 403)
        return result

    def verify_reauthentication(
        self,
        *,
        reauth_credential: str,
        user_id: UUID,
        session_id: UUID,
        request_id: UUID,
    ) -> datetime:
        self.reauth_calls += 1
        verified = self.reauth_results.get(reauth_credential)
        if verified is None:
            raise AuthIdentityLinkProviderError("AUTH_REAUTH_REQUIRED", 403)
        return verified


def get_auth_identity_link_provider(
    settings: Settings | None = None,
) -> AuthIdentityLinkProvider:
    current = settings or get_settings()
    if not current.is_production and current.auth_identity_link_provider.strip().lower() == "fake":
        return FakeAuthIdentityLinkProvider()
    return DisabledAuthIdentityLinkProvider()


def ensure_recent_reauthentication(
    verified_at: datetime,
    *,
    now: datetime | None = None,
    max_age_seconds: int,
) -> None:
    current = now or datetime.now(UTC)
    observed = verified_at if verified_at.tzinfo else verified_at.replace(tzinfo=UTC)
    age = (current - observed.astimezone(UTC)).total_seconds()
    if age < 0 or age > max_age_seconds:
        raise AuthIdentityLinkProviderError("AUTH_REAUTH_REQUIRED", 403)
