from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.core.config import Settings, get_settings
from app.services.auth_identity_service import AuthIdentityError, canonicalize_wechat_subject


class WechatProviderError(RuntimeError):
    """Provider-neutral failure; raw SDK/API errors never cross this boundary."""

    def __init__(self, code: str, *, ambiguous: bool = False):
        super().__init__(code)
        self.code = code
        self.ambiguous = ambiguous


@dataclass(frozen=True)
class VerifiedWechatResult:
    """Verified provider identifiers returned by a trusted server adapter."""

    app_id: str
    scope: str
    openid: str | None
    unionid: str | None
    verified_at: datetime
    provider_request_id: str | None = None

    def validate_against_settings(self, settings: Settings) -> None:
        """Bind trusted provider output to JiYi's server-side app contract."""
        configured_app_id = settings.auth_wechat_app_id.strip()
        configured_scope = settings.auth_wechat_subject_scope.strip()
        if not configured_app_id or not configured_scope:
            raise WechatProviderError("UNAVAILABLE")
        if self.app_id != configured_app_id or self.scope != configured_scope:
            raise WechatProviderError("PROVIDER_ERROR")
        try:
            self.canonical_subjects()
        except WechatProviderError:
            raise

    def canonical_subjects(self) -> tuple[str, ...]:
        if not self.app_id.strip() or not self.scope.strip():
            raise WechatProviderError("PROVIDER_ERROR")
        subjects: list[str] = []
        if self.unionid:
            subjects.append(f"unionid:{self.scope}:{self.unionid}")
        if self.openid:
            subjects.append(f"openid:{self.app_id}:{self.openid}")
        if not subjects:
            raise WechatProviderError("PROVIDER_ERROR")
        try:
            canonical = tuple(canonicalize_wechat_subject(subject) for subject in subjects)
        except AuthIdentityError as exc:
            raise WechatProviderError("PROVIDER_ERROR") from exc
        if self.verified_at.tzinfo is None or self.verified_at.utcoffset() is None:
            raise WechatProviderError("PROVIDER_ERROR")
        return canonical


class WechatAuthProvider(Protocol):
    available: bool

    def exchange_credential(
        self,
        *,
        credential: str,
        request_id: UUID,
    ) -> VerifiedWechatResult:
        """Verify an opaque native credential without touching JiYi state."""


class DisabledWechatAuthProvider:
    available = False

    def exchange_credential(
        self,
        *,
        credential: str,
        request_id: UUID,
    ) -> VerifiedWechatResult:
        raise WechatProviderError("UNAVAILABLE")


class FakeWechatAuthProvider:
    """Test-only adapter. It is never exposed as a production capability."""

    available = True

    def __init__(self, result: VerifiedWechatResult | None = None):
        self.result = result or VerifiedWechatResult(
            app_id="test-app",
            scope="test-scope",
            openid="test-openid",
            unionid="test-unionid",
            verified_at=datetime.now(UTC),
            provider_request_id="fake-wechat-request",
        )
        self.calls = 0

    def exchange_credential(
        self,
        *,
        credential: str,
        request_id: UUID,
    ) -> VerifiedWechatResult:
        self.calls += 1
        if not credential.strip():
            raise WechatProviderError("INVALID")
        return self.result


def get_wechat_provider(settings: Settings | None = None) -> WechatAuthProvider:
    current = settings or get_settings()
    provider_name = current.auth_wechat_provider.strip().lower()
    if not current.is_production and provider_name == "fake":
        return FakeWechatAuthProvider()
    # AUTH-04 Phase A intentionally has no live OpenSDK/API adapter. Keeping the
    # factory disabled makes missing registration/configuration fail closed.
    return DisabledWechatAuthProvider()
