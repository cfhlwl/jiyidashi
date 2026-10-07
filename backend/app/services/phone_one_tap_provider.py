from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.services.auth_identity_service import (
    AuthIdentityError,
    canonicalize_phone_subject,
)


class PhoneOneTapProviderError(RuntimeError):
    """Provider-neutral, sanitized provider outcome."""

    def __init__(self, code: str, *, ambiguous: bool = False):
        super().__init__(code)
        self.code = code
        self.ambiguous = ambiguous


@dataclass(frozen=True)
class VerifiedPhoneResult:
    canonical_phone_subject: str
    verified_at: datetime
    provider_request_id: str | None = None

    def __post_init__(self) -> None:
        try:
            canonicalize_phone_subject(self.canonical_phone_subject)
        except AuthIdentityError as exc:
            raise PhoneOneTapProviderError("PROVIDER_ERROR") from exc
        if self.verified_at.tzinfo is None or self.verified_at.utcoffset() is None:
            raise PhoneOneTapProviderError("PROVIDER_ERROR")


class PhoneOneTapProvider(Protocol):
    available: bool

    def exchange_login_token(
        self,
        *,
        login_token: str,
        request_id: UUID,
    ) -> VerifiedPhoneResult:
        """Exchange a provider token without touching JiYi identity/session state."""


class DisabledPhoneOneTapProvider:
    """Production-safe default until the real provider is separately activated."""

    available = False

    def exchange_login_token(
        self,
        *,
        login_token: str,
        request_id: UUID,
    ) -> VerifiedPhoneResult:
        raise PhoneOneTapProviderError("UNAVAILABLE")


def get_phone_one_tap_provider() -> PhoneOneTapProvider:
    # AUTH-02B deliberately has no Alibaba SDK, credential, scheme, or network
    # adapter. A future AUTH-02E activation must replace this factory explicitly.
    return DisabledPhoneOneTapProvider()


def normalize_aliyun_mainland_mobile(value: str) -> str:
    """Normalize only the documented mainland-national-number seam.

    This pure helper does not call Aliyun. It rejects masked values, arbitrary
    country-code guesses, and all non-11-digit national inputs.
    """

    if not isinstance(value, str) or len(value) != 11 or not value.isascii():
        raise PhoneOneTapProviderError("PROVIDER_ERROR")
    if not value.isdigit() or value[0] != "1" or value[1] not in "3-9":
        raise PhoneOneTapProviderError("PROVIDER_ERROR")
    try:
        return canonicalize_phone_subject(f"+86{value}")
    except AuthIdentityError as exc:
        raise PhoneOneTapProviderError("PROVIDER_ERROR") from exc


def utc_now() -> datetime:
    return datetime.now(UTC)
