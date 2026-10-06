from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.core.config import get_settings
from app.notification_models import PushPlatform, PushProvider


@dataclass(frozen=True, repr=False)
class NotificationProviderRequest:
    """Ephemeral provider request.

    raw_token intentionally has no repr and must never enter logs/persistence.
    """

    delivery_id: UUID
    device_id: UUID
    platform: str
    provider: str
    raw_token: str
    title: str
    body: str
    payload: dict


@dataclass(frozen=True)
class NotificationProviderResult:
    accepted: bool
    retryable: bool
    error_code: str | None = None
    invalid_token: bool = False
    retry_after_seconds: int | None = None

    @classmethod
    def accepted_result(cls) -> "NotificationProviderResult":
        return cls(accepted=True, retryable=False)

    @classmethod
    def retryable_failure(
        cls,
        code: str,
        *,
        retry_after_seconds: int | None = None,
    ) -> "NotificationProviderResult":
        return cls(
            accepted=False,
            retryable=True,
            error_code=_safe_error_code(code),
            retry_after_seconds=retry_after_seconds,
        )

    @classmethod
    def terminal_failure(
        cls,
        code: str,
        *,
        invalid_token: bool = False,
    ) -> "NotificationProviderResult":
        return cls(
            accepted=False,
            retryable=False,
            error_code=_safe_error_code(code),
            invalid_token=invalid_token,
        )


class NotificationProviderAdapter(Protocol):
    def deliver(
        self,
        request: NotificationProviderRequest,
    ) -> NotificationProviderResult: ...


class _AcceptingTestAdapter:
    def deliver(
        self,
        request: NotificationProviderRequest,
    ) -> NotificationProviderResult:
        del request
        return NotificationProviderResult.accepted_result()


class _UnconfiguredAdapter:
    def deliver(
        self,
        request: NotificationProviderRequest,
    ) -> NotificationProviderResult:
        del request
        return NotificationProviderResult.terminal_failure(
            "NOTIFICATION_PROVIDER_UNCONFIGURED"
        )


_TEST_OVERRIDES: dict[tuple[str, str], NotificationProviderAdapter] = {}


def _safe_error_code(value: str | None) -> str:
    normalized = (value or "NOTIFICATION_PROVIDER_FAILURE").strip().upper()
    safe = "".join(
        char if char.isalnum() or char == "_" else "_"
        for char in normalized
    )
    return (safe or "NOTIFICATION_PROVIDER_FAILURE")[:80]


def set_notification_provider_for_testing(
    *,
    platform: PushPlatform | str,
    provider: PushProvider | str,
    adapter: NotificationProviderAdapter | None,
) -> None:
    key = (
        platform.value if isinstance(platform, PushPlatform) else str(platform),
        provider.value if isinstance(provider, PushProvider) else str(provider),
    )
    if adapter is None:
        _TEST_OVERRIDES.pop(key, None)
    else:
        _TEST_OVERRIDES[key] = adapter


def provider_matches_platform(*, platform: str, provider: str) -> bool:
    allowed = {
        PushPlatform.IOS.value: {
            PushProvider.APNS.value,
            PushProvider.TEST.value,
        },
        PushPlatform.ANDROID.value: {
            PushProvider.FCM.value,
            PushProvider.HMS.value,
            PushProvider.TEST.value,
        },
    }
    return provider in allowed.get(platform, set())


def resolve_notification_provider(
    *,
    platform: str,
    provider: str,
) -> NotificationProviderAdapter:
    if not provider_matches_platform(platform=platform, provider=provider):
        return _UnconfiguredAdapter()

    settings = get_settings()
    if not settings.is_production:
        override = _TEST_OVERRIDES.get((platform, provider))
        if override is not None:
            return override
        if provider == PushProvider.TEST.value:
            return _AcceptingTestAdapter()

    # NOTIFY-001A deliberately ships no live APNs/Android network adapter.
    # Production therefore fails closed instead of fabricating provider acceptance.
    return _UnconfiguredAdapter()
