from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import re
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import quote, quote_plus, urlparse
from uuid import UUID

import httpx

from app.core.config import Settings, get_settings
from app.services.auth_identity_service import AuthIdentityError, canonicalize_wechat_subject

_OFFICIAL_WECHAT_API_HOST = "api.weixin.qq.com"
_ACCESS_TOKEN_PATH = "/sns/oauth2/access_token"
_WECHAT_ERRCODE_MAP = {
    40029: "INVALID",
    40163: "REPLAYED",
    45011: "RATE_LIMITED",
}


_PROVIDER_LOG_SECRETS: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar(
    "wechat_provider_log_secrets", default=()
)
_SENSITIVE_QUERY_VALUE = re.compile(
    r"(?i)([?&](?:secret|code|access_token|refresh_token)=)([^&#\s'\"]+)"
)
_SENSITIVE_JSON_VALUE = re.compile(
    r'(?i)((?:"|\b)(?:secret|code|access_token|refresh_token)(?:"|\b)\s*[:=]\s*["\'])([^"\']+)'
)


def _redact_text(value: str, secrets: tuple[str, ...]) -> str:
    for secret in secrets:
        value = value.replace(secret, "<redacted>")
    value = _SENSITIVE_QUERY_VALUE.sub(r"\1<redacted>", value)
    return _SENSITIVE_JSON_VALUE.sub(r"\1<redacted>", value)


def _redact_extra(value: object, secrets: tuple[str, ...]) -> object:
    if isinstance(value, str):
        return _redact_text(value, secrets)
    if isinstance(value, dict):
        return {
            _redact_extra(key, secrets) if not isinstance(key, str) else key: _redact_extra(
                item, secrets
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_extra(item, secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_extra(item, secrets) for item in value)
    if value is None or isinstance(value, (bool, int, float, complex)):
        return value
    if isinstance(value, httpx.URL):
        return _redact_text(str(value), secrets)
    if isinstance(value, httpx.Request):
        return _redact_text(str(value.url), secrets)
    if isinstance(value, httpx.Response):
        request = value.request
        return _redact_text(str(request.url) if request is not None else str(value), secrets)
    if isinstance(value, BaseException):
        return _redact_text(str(value), secrets)
    try:
        # Structured telemetry objects must not survive as typed values: a
        # later formatter may call repr/str outside this filter's control.
        return _redact_text(str(value), secrets)
    except Exception:
        return "<redacted>"


class _SensitiveProviderLogFilter(logging.Filter):
    """Keep HTTPX observability while redacting provider credentials at output."""

    def filter(self, record: logging.LogRecord) -> bool:
        secrets = tuple(
            variant
            for value in _PROVIDER_LOG_SECRETS.get()
            if value
            for variant in (value, quote(value, safe=""), quote_plus(value))
        )
        try:
            message = record.getMessage()
        except Exception:
            record.msg = "provider HTTP log redacted"
            record.args = ()
            return True
        record.msg = _redact_text(message, secrets)
        record.args = ()
        if record.exc_info:
            try:
                record.exc_text = _redact_text(
                    "".join(traceback.format_exception(*record.exc_info)), secrets
                )
            except Exception:
                record.exc_text = "provider HTTP exception redacted"
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = _redact_text(record.exc_text, secrets)
        if record.stack_info:
            record.stack_info = _redact_text(record.stack_info, secrets)
        for key, value in tuple(record.__dict__.items()):
            if key in {"msg", "args", "exc_info", "exc_text", "stack_info"}:
                continue
            record.__dict__[key] = _redact_extra(value, secrets)
        return True


@contextmanager
def _redacted_provider_logging(*, credential: str, app_secret: str):
    token = _PROVIDER_LOG_SECRETS.set((credential, app_secret))
    try:
        yield
    finally:
        _PROVIDER_LOG_SECRETS.reset(token)


_PROVIDER_LOG_FILTER = _SensitiveProviderLogFilter()
for _logger_name in (
    "httpx",
    "httpcore",
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.proxy",
    "httpcore._async.connection",
    "httpcore._async.http11",
):
    logging.getLogger(_logger_name).addFilter(_PROVIDER_LOG_FILTER)


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


@dataclass(frozen=True)
class WechatOAuthProviderConfig:
    """Server-only configuration for the official mobile OAuth exchange."""

    app_id: str
    app_secret: str = field(repr=False)
    subject_scope: str = ""
    fingerprint_secret: str = field(default="", repr=False)
    api_base_url: str = ""
    timeout_seconds: float = 5.0
    max_response_bytes: int = 65536
    live_enabled: bool = False

    @classmethod
    def from_settings(cls, settings: Settings) -> WechatOAuthProviderConfig:
        return cls(
            app_id=settings.auth_wechat_app_id.strip(),
            app_secret=settings.auth_wechat_app_secret.strip(),
            subject_scope=settings.auth_wechat_subject_scope.strip(),
            fingerprint_secret=settings.auth_wechat_fingerprint_secret.strip(),
            api_base_url=settings.auth_wechat_api_base_url.strip(),
            timeout_seconds=settings.auth_wechat_timeout_seconds,
            max_response_bytes=settings.auth_wechat_max_response_bytes,
            live_enabled=settings.auth_wechat_live_enabled,
        )

    @property
    def normalized_api_base_url(self) -> str | None:
        value = self.api_base_url.strip()
        parsed = urlparse(value)
        try:
            port = parsed.port
        except ValueError:
            return None
        if (
            parsed.scheme.lower() != "https"
            or parsed.hostname != _OFFICIAL_WECHAT_API_HOST
            or port not in (None, 443)
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            return None
        return f"https://{_OFFICIAL_WECHAT_API_HOST}"

    @property
    def complete(self) -> bool:
        return bool(
            self.live_enabled
            and self.app_id
            and self.app_secret
            and self.subject_scope
            and self.fingerprint_secret
            and self.normalized_api_base_url
            and self.timeout_seconds > 0
            and self.max_response_bytes > 0
        )


class WechatAuthProvider(Protocol):
    available: bool

    def exchange_credential(
        self,
        *,
        credential: str,
        request_id: UUID,
    ) -> VerifiedWechatResult:
        """Exchange an opaque native credential without touching JiYi state."""


class WechatOAuthProvider:
    """Exchange a native mobile-login code through WeChat's server OAuth API.

    Production uses one bounded HTTP request with redirects disabled; tests use
    httpx.MockTransport. Raw code, AppSecret, access tokens, and provider bodies
    never leave this adapter as an exception or structured result.
    """

    def __init__(
        self,
        config: WechatOAuthProviderConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self._transport = transport

    @classmethod
    def from_settings(cls, settings: Settings) -> WechatOAuthProvider:
        return cls(WechatOAuthProviderConfig.from_settings(settings))

    @property
    def available(self) -> bool:
        return self.config.complete

    def exchange_credential(
        self,
        *,
        credential: str,
        request_id: UUID,
    ) -> VerifiedWechatResult:
        del request_id
        if not self.available:
            raise WechatProviderError("UNAVAILABLE")
        if not credential.strip():
            raise WechatProviderError("INVALID")

        sanitized_error: WechatProviderError | None = None
        try:
            status_code, body = self._request(credential)
        except WechatProviderError:
            raise
        except httpx.TimeoutException:
            sanitized_error = WechatProviderError("TIMEOUT", ambiguous=True)
        except httpx.RequestError:
            sanitized_error = WechatProviderError("PROVIDER_ERROR", ambiguous=True)
        except Exception:  # pragma: no cover - defensive provider boundary
            sanitized_error = WechatProviderError("PROVIDER_ERROR", ambiguous=True)
        if sanitized_error is not None:
            raise sanitized_error

        if status_code == 429:
            raise WechatProviderError("RATE_LIMITED")
        if status_code >= 500:
            raise WechatProviderError("TIMEOUT", ambiguous=True)
        if status_code != 200:
            raise WechatProviderError("PROVIDER_ERROR")
        payload = self._decode_json(body)
        return self._verified_result(payload)

    def _request(self, credential: str) -> tuple[int, bytes]:
        base_url = self.config.normalized_api_base_url
        if base_url is None:
            raise WechatProviderError("UNAVAILABLE")
        return asyncio.run(self._request_async(base_url, credential))

    async def _request_async(self, base_url: str, credential: str) -> tuple[int, bytes]:
        timeout = httpx.Timeout(self.config.timeout_seconds)
        try:
            # Cover client construction, request I/O, response streaming, and
            # cooperative transport cleanup with one cancellation scope.
            async with asyncio.timeout(self.config.timeout_seconds):
                async with httpx.AsyncClient(
                    base_url=base_url,
                    follow_redirects=False,
                    timeout=timeout,
                    transport=self._transport,
                    trust_env=False,
                ) as client:
                    return await self._request_once(client, credential)
        except TimeoutError:
            raise WechatProviderError("TIMEOUT", ambiguous=True) from None

    async def _request_once(self, client: httpx.AsyncClient, credential: str) -> tuple[int, bytes]:
        with _redacted_provider_logging(
            credential=credential,
            app_secret=self.config.app_secret,
        ):
            async with client.stream(
                "GET",
                _ACCESS_TOKEN_PATH,
                params={
                    "appid": self.config.app_id,
                    "secret": self.config.app_secret,
                    "code": credential,
                    "grant_type": "authorization_code",
                },
            ) as response:
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > self.config.max_response_bytes:
                        raise WechatProviderError("PROVIDER_ERROR")
                    chunks.append(chunk)
                return response.status_code, b"".join(chunks)

    @staticmethod
    def _decode_json(body: bytes) -> dict[str, object]:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WechatProviderError("PROVIDER_ERROR") from exc
        if not isinstance(payload, dict):
            raise WechatProviderError("PROVIDER_ERROR")
        return payload

    def _verified_result(self, payload: dict[str, object]) -> VerifiedWechatResult:
        errcode = payload.get("errcode")
        if errcode is not None:
            if isinstance(errcode, bool) or not isinstance(errcode, int):
                raise WechatProviderError("PROVIDER_ERROR")
            if errcode != 0:
                raise WechatProviderError(_WECHAT_ERRCODE_MAP.get(errcode, "PROVIDER_ERROR"))

        response_app_id = payload.get("appid")
        if response_app_id is not None and (
            not isinstance(response_app_id, str) or response_app_id != self.config.app_id
        ):
            raise WechatProviderError("PROVIDER_ERROR")

        access_token = payload.get("access_token")
        openid = payload.get("openid")
        if (
            not isinstance(access_token, str)
            or not access_token.strip()
            or not isinstance(openid, str)
            or not openid.strip()
        ):
            raise WechatProviderError("PROVIDER_ERROR")

        for field_name in ("refresh_token", "scope"):
            value = payload.get(field_name)
            if value is not None and not isinstance(value, str):
                raise WechatProviderError("PROVIDER_ERROR")
        unionid = payload.get("unionid")
        if unionid is not None and (not isinstance(unionid, str) or not unionid.strip()):
            raise WechatProviderError("PROVIDER_ERROR")
        expires_in = payload.get("expires_in")
        if expires_in is not None and (
            isinstance(expires_in, bool) or not isinstance(expires_in, int) or expires_in <= 0
        ):
            raise WechatProviderError("PROVIDER_ERROR")

        result = VerifiedWechatResult(
            app_id=self.config.app_id,
            scope=self.config.subject_scope,
            openid=openid,
            unionid=unionid,
            verified_at=datetime.now(UTC),
        )
        try:
            result.canonical_subjects()
        except WechatProviderError as exc:
            raise WechatProviderError("PROVIDER_ERROR") from exc
        return result


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
    if provider_name == "wechat" and current.auth_wechat_live_enabled:
        provider = WechatOAuthProvider.from_settings(current)
        if provider.available:
            return provider
    return DisabledWechatAuthProvider()
