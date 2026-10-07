from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

import httpx
import jwt

from app.core.config import Settings, get_settings
from app.notification_models import PushPlatform, PushProvider

_MAX_PROVIDER_RETRY_SECONDS = 900
_MAX_KEY_BYTES = 64 * 1024
_FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_FCM_AUDIENCE = "https://oauth2.googleapis.com/token"


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
    def accepted_result(cls) -> NotificationProviderResult:
        return cls(accepted=True, retryable=False)

    @classmethod
    def retryable_failure(
        cls,
        code: str,
        *,
        retry_after_seconds: int | None = None,
    ) -> NotificationProviderResult:
        return cls(
            accepted=False,
            retryable=True,
            error_code=_safe_error_code(code),
            retry_after_seconds=_bounded_retry(retry_after_seconds),
        )

    @classmethod
    def terminal_failure(
        cls,
        code: str,
        *,
        invalid_token: bool = False,
    ) -> NotificationProviderResult:
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


def _safe_error_code(value: str | None) -> str:
    normalized = (value or "NOTIFICATION_PROVIDER_FAILURE").strip().upper()
    safe = "".join(
        char if char.isalnum() or char == "_" else "_"
        for char in normalized
    )
    return (safe or "NOTIFICATION_PROVIDER_FAILURE")[:80]


def _bounded_retry(value: int | None) -> int | None:
    if value is None:
        return None
    return min(max(int(value), 1), _MAX_PROVIDER_RETRY_SECONDS)


def _retry_after(response: httpx.Response) -> int | None:
    raw = response.headers.get("retry-after", "").strip()
    if not raw:
        return None
    try:
        return _bounded_retry(int(raw))
    except ValueError:
        try:
            target = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
        if target.tzinfo is None:
            target = target.replace(tzinfo=UTC)
        seconds = int((target.astimezone(UTC) - datetime.now(UTC)).total_seconds())
        return _bounded_retry(max(seconds, 1))


def _http_timeout(settings: Settings) -> httpx.Timeout:
    return httpx.Timeout(
        connect=settings.push_provider_connect_timeout_seconds,
        read=settings.push_provider_read_timeout_seconds,
        write=settings.push_provider_write_timeout_seconds,
        pool=settings.push_provider_pool_timeout_seconds,
    )


def _load_private_key(*, inline: str, file_path: str) -> str:
    inline = inline.strip()
    file_path = file_path.strip()
    if bool(inline) == bool(file_path):
        raise ValueError("exactly one private-key source must be configured")
    if inline:
        key = inline.replace("\\n", "\n")
    else:
        path = Path(file_path)
        size = path.stat().st_size
        if size <= 0 or size > _MAX_KEY_BYTES:
            raise ValueError("private-key file size is invalid")
        key = path.read_text(encoding="utf-8")
    if "PRIVATE KEY" not in key or "PLACEHOLDER" in key.upper() or "CHANGE_ME" in key.upper():
        raise ValueError("private-key material is invalid")
    return key


def _canonical_payload(payload: dict) -> dict[str, str | int]:
    version = payload.get("version")
    destination = payload.get("destination")
    resource_id = payload.get("resource_id")
    canonical: dict[str, str | int] = {
        "version": int(version) if isinstance(version, int) else 1,
        "destination": str(destination or "HOME"),
    }
    if resource_id is not None:
        canonical["resource_id"] = str(resource_id)
    return canonical


class APNsNotificationProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._settings = settings
        self._client = client or httpx.Client(http2=True, timeout=_http_timeout(settings))
        self._owns_client = client is None
        self._clock = clock
        self._jwt_lock = threading.Lock()
        self._cached_jwt: str | None = None
        self._cached_jwt_at = 0.0
        self._private_key = _load_private_key(
            inline=settings.apns_private_key,
            file_path=settings.apns_private_key_file,
        )

    @property
    def endpoint(self) -> str:
        if self._settings.apns_environment == "production":
            return "https://api.push.apple.com"
        return "https://api.sandbox.push.apple.com"

    def _provider_jwt(self) -> str:
        now = self._clock()
        refresh_after = self._settings.apns_jwt_refresh_minutes * 60
        with self._jwt_lock:
            if self._cached_jwt and now - self._cached_jwt_at < refresh_after:
                return self._cached_jwt
            token = jwt.encode(
                {"iss": self._settings.apns_team_id, "iat": int(now)},
                self._private_key,
                algorithm="ES256",
                headers={"kid": self._settings.apns_key_id},
            )
            self._cached_jwt = token
            self._cached_jwt_at = now
            return token

    def deliver(self, request: NotificationProviderRequest) -> NotificationProviderResult:
        payload = {
            "aps": {
                "alert": {"title": request.title, "body": request.body},
                "sound": "default",
            },
            **_canonical_payload(request.payload),
        }
        try:
            response = self._client.post(
                f"{self.endpoint}/3/device/{request.raw_token}",
                headers={
                    "authorization": f"bearer {self._provider_jwt()}",
                    "apns-topic": self._settings.apns_topic,
                    "apns-push-type": "alert",
                    "apns-priority": "10",
                },
                json=payload,
            )
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
            return NotificationProviderResult.retryable_failure("APNS_NETWORK_FAILURE")
        except Exception:
            return NotificationProviderResult.terminal_failure("APNS_PROVIDER_FAILURE")

        if response.status_code == 200:
            return NotificationProviderResult.accepted_result()

        reason = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                reason = str(body.get("reason") or "")
        except (ValueError, TypeError):
            pass
        normalized = _safe_error_code(reason or f"HTTP_{response.status_code}")

        if response.status_code == 429 or response.status_code >= 500:
            return NotificationProviderResult.retryable_failure(
                f"APNS_{normalized}",
                retry_after_seconds=_retry_after(response),
            )
        if reason in {"BadDeviceToken", "DeviceTokenNotForTopic", "Unregistered"}:
            return NotificationProviderResult.terminal_failure(
                f"APNS_{normalized}",
                invalid_token=True,
            )
        return NotificationProviderResult.terminal_failure(f"APNS_{normalized}")

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


class _OAuthTokenCache:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.token: str | None = None
        self.expires_at = 0.0

    def current(self, now: float) -> str | None:
        if self.token and self.expires_at - now > 60:
            return self.token
        return None

    def store(self, *, token: str, expires_in: int, now: float) -> str:
        self.token = token
        self.expires_at = now + max(60, int(expires_in))
        return token

    def clear(self) -> None:
        self.token = None
        self.expires_at = 0.0


class FCMNotificationProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._settings = settings
        self._client = client or httpx.Client(http2=True, timeout=_http_timeout(settings))
        self._owns_client = client is None
        self._clock = clock
        self._token_cache = _OAuthTokenCache()
        self._private_key = _load_private_key(
            inline=settings.fcm_private_key,
            file_path=settings.fcm_private_key_file,
        )

    def _access_token(self) -> str:
        now = self._clock()
        with self._token_cache.lock:
            cached = self._token_cache.current(now)
            if cached:
                return cached
            assertion = jwt.encode(
                {
                    "iss": self._settings.fcm_client_email,
                    "scope": _FCM_SCOPE,
                    "aud": _FCM_AUDIENCE,
                    "iat": int(now),
                    "exp": int(now) + 3600,
                },
                self._private_key,
                algorithm="RS256",
            )
            response = self._client.post(
                self._settings.fcm_token_uri,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
            )
            response.raise_for_status()
            body = response.json()
            token = body.get("access_token") if isinstance(body, dict) else None
            expires_in = body.get("expires_in", 3600) if isinstance(body, dict) else 3600
            if not isinstance(token, str) or not token:
                raise ValueError("FCM OAuth response missing access token")
            return self._token_cache.store(
                token=token,
                expires_in=int(expires_in),
                now=now,
            )

    def deliver(self, request: NotificationProviderRequest) -> NotificationProviderResult:
        canonical = _canonical_payload(request.payload)
        data = {key: str(value) for key, value in canonical.items()}
        data["title"] = request.title[:160]
        data["body"] = request.body[:1000]
        try:
            access_token = self._access_token()
            response = self._client.post(
                (
                    "https://fcm.googleapis.com/v1/projects/"
                    f"{self._settings.fcm_project_id}/messages:send"
                ),
                headers={"authorization": f"Bearer {access_token}"},
                json={
                    "message": {
                        "token": request.raw_token,
                        "data": data,
                        "android": {"priority": "high", "ttl": "86400s"},
                    }
                },
            )
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
            return NotificationProviderResult.retryable_failure("FCM_NETWORK_FAILURE")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429 or exc.response.status_code >= 500:
                return NotificationProviderResult.retryable_failure(
                    "FCM_OAUTH_TRANSIENT"
                )
            return NotificationProviderResult.terminal_failure("FCM_OAUTH_REJECTED")
        except Exception:
            return NotificationProviderResult.terminal_failure("FCM_PROVIDER_FAILURE")

        if response.status_code == 200:
            return NotificationProviderResult.accepted_result()

        status = ""
        error_code = ""
        try:
            body = response.json()
            error = body.get("error") if isinstance(body, dict) else None
            if isinstance(error, dict):
                status = str(error.get("status") or "")
                for detail in error.get("details") or []:
                    if isinstance(detail, dict):
                        candidate = detail.get("errorCode")
                        if isinstance(candidate, str):
                            error_code = candidate
                            break
        except (ValueError, TypeError):
            pass

        canonical_error = _safe_error_code(error_code or status or f"HTTP_{response.status_code}")
        if response.status_code == 401:
            self._token_cache.clear()
            return NotificationProviderResult.retryable_failure(
                "FCM_AUTH_REFRESH_REQUIRED"
            )
        if (
            response.status_code == 429
            or response.status_code >= 500
            or status in {"UNAVAILABLE", "INTERNAL", "RESOURCE_EXHAUSTED"}
            or error_code in {"QUOTA_EXCEEDED", "UNAVAILABLE", "INTERNAL"}
        ):
            return NotificationProviderResult.retryable_failure(
                f"FCM_{canonical_error}",
                retry_after_seconds=_retry_after(response),
            )
        if error_code == "UNREGISTERED":
            return NotificationProviderResult.terminal_failure(
                "FCM_UNREGISTERED",
                invalid_token=True,
            )
        return NotificationProviderResult.terminal_failure(f"FCM_{canonical_error}")

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


class HMSNotificationProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._settings = settings
        self._client = client or httpx.Client(http2=True, timeout=_http_timeout(settings))
        self._owns_client = client is None
        self._clock = clock
        self._token_cache = _OAuthTokenCache()

    def _access_token(self) -> str:
        now = self._clock()
        with self._token_cache.lock:
            cached = self._token_cache.current(now)
            if cached:
                return cached
            response = self._client.post(
                self._settings.hms_oauth_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._settings.hms_client_id,
                    "client_secret": self._settings.hms_client_secret,
                },
            )
            response.raise_for_status()
            body = response.json()
            token = body.get("access_token") if isinstance(body, dict) else None
            expires_in = body.get("expires_in", 3600) if isinstance(body, dict) else 3600
            if not isinstance(token, str) or not token:
                raise ValueError("HMS OAuth response missing access token")
            return self._token_cache.store(
                token=token,
                expires_in=int(expires_in),
                now=now,
            )

    def deliver(self, request: NotificationProviderRequest) -> NotificationProviderResult:
        canonical = _canonical_payload(request.payload)
        client_data = {
            **canonical,
            "title": request.title[:160],
            "body": request.body[:1000],
        }
        try:
            access_token = self._access_token()
            response = self._client.post(
                (
                    f"{self._settings.hms_push_base_url.rstrip('/')}/v1/"
                    f"{self._settings.hms_app_id}/messages:send"
                ),
                headers={"authorization": f"Bearer {access_token}"},
                json={
                    "validate_only": False,
                    "message": {
                        "data": json.dumps(client_data, separators=(",", ":")),
                        "android": {"urgency": "HIGH", "ttl": "86400s"},
                        "token": [request.raw_token],
                    },
                },
            )
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
            return NotificationProviderResult.retryable_failure("HMS_NETWORK_FAILURE")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429 or exc.response.status_code >= 500:
                return NotificationProviderResult.retryable_failure(
                    "HMS_OAUTH_TRANSIENT"
                )
            return NotificationProviderResult.terminal_failure("HMS_OAUTH_REJECTED")
        except Exception:
            return NotificationProviderResult.terminal_failure("HMS_PROVIDER_FAILURE")

        code = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                code = str(body.get("code") or "")
        except (ValueError, TypeError):
            pass

        if response.status_code == 200 and code == "80000000":
            return NotificationProviderResult.accepted_result()
        if response.status_code == 401:
            self._token_cache.clear()
            return NotificationProviderResult.retryable_failure(
                "HMS_AUTH_REFRESH_REQUIRED"
            )
        if response.status_code in {429, 500, 502, 503, 504} or code in {
            "80000001",
            "81000001",
        }:
            return NotificationProviderResult.retryable_failure(
                f"HMS_{_safe_error_code(code or f'HTTP_{response.status_code}')}",
                retry_after_seconds=_retry_after(response),
            )
        if code in {"80300007", "80300028"}:
            return NotificationProviderResult.terminal_failure(
                f"HMS_{code}",
                invalid_token=True,
            )
        return NotificationProviderResult.terminal_failure(
            f"HMS_{_safe_error_code(code or f'HTTP_{response.status_code}')}"
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


_TEST_OVERRIDES: dict[tuple[str, str], NotificationProviderAdapter] = {}
_LIVE_ADAPTERS: dict[str, NotificationProviderAdapter] = {}
_LIVE_ADAPTER_LOCK = threading.Lock()


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


def provider_registration_allowed(
    *,
    platform: str,
    provider: str,
    settings: Settings | None = None,
) -> bool:
    settings = settings or get_settings()
    if not provider_matches_platform(platform=platform, provider=provider):
        return False
    if not settings.is_production:
        return True
    if provider == PushProvider.TEST.value:
        return False
    if not settings.push_app_identity_reviewed:
        return False
    if provider == PushProvider.APNS.value:
        return (
            settings.apns_enabled
            and settings.apns_environment == "production"
            and settings.apns_topic.strip() == settings.push_ios_bundle_id.strip()
        )
    if provider == PushProvider.FCM.value:
        return settings.fcm_enabled and bool(settings.push_android_application_id.strip())
    if provider == PushProvider.HMS.value:
        return settings.hms_enabled and bool(settings.push_android_application_id.strip())
    return False


def _live_adapter(provider: str, settings: Settings) -> NotificationProviderAdapter:
    with _LIVE_ADAPTER_LOCK:
        cached = _LIVE_ADAPTERS.get(provider)
        if cached is not None:
            return cached
        try:
            if provider == PushProvider.APNS.value and settings.apns_enabled:
                adapter: NotificationProviderAdapter = APNsNotificationProvider(settings)
            elif provider == PushProvider.FCM.value and settings.fcm_enabled:
                adapter = FCMNotificationProvider(settings)
            elif provider == PushProvider.HMS.value and settings.hms_enabled:
                adapter = HMSNotificationProvider(settings)
            else:
                adapter = _UnconfiguredAdapter()
        except Exception:
            adapter = _UnconfiguredAdapter()
        _LIVE_ADAPTERS[provider] = adapter
        return adapter


def reset_live_notification_providers_for_testing() -> None:
    with _LIVE_ADAPTER_LOCK:
        for adapter in _LIVE_ADAPTERS.values():
            close = getattr(adapter, "close", None)
            if callable(close):
                close()
        _LIVE_ADAPTERS.clear()


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

    if not provider_registration_allowed(
        platform=platform,
        provider=provider,
        settings=settings,
    ):
        return _UnconfiguredAdapter()
    return _live_adapter(provider, settings)
