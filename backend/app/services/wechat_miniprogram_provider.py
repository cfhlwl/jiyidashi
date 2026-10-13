from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlparse
from uuid import UUID

import httpx

from app.core.config import Settings, get_settings
from app.services.wechat_auth_provider import _redacted_provider_logging

_OFFICIAL_HOST = "api.weixin.qq.com"
_CODE2SESSION_PATH = "/sns/jscode2session"
_ERROR_CODES = {
    40013: "CONFIG_ERROR",
    40029: "INVALID",
    45011: "RATE_LIMITED",
    40226: "PROVIDER_REJECTED",
}


class WechatMiniProgramProviderError(RuntimeError):
    def __init__(self, code: str, *, ambiguous: bool = False):
        super().__init__(code)
        self.code = code
        self.ambiguous = ambiguous


@dataclass(frozen=True)
class VerifiedWechatMiniProgramResult:
    app_id: str
    openid: str
    unionid: str | None
    verified_at: datetime
    provider_request_id: str | None = None


@dataclass(frozen=True)
class WechatMiniProgramProviderConfig:
    app_id: str
    app_secret: str = field(repr=False)
    api_base_url: str = ""
    timeout_seconds: float = 5.0
    max_response_bytes: int = 65536
    live_enabled: bool = False

    @classmethod
    def from_settings(cls, settings: Settings) -> WechatMiniProgramProviderConfig:
        return cls(
            app_id=settings.auth_wechat_miniprogram_app_id.strip(),
            app_secret=settings.auth_wechat_miniprogram_app_secret.strip(),
            api_base_url=settings.auth_wechat_miniprogram_api_base_url.strip(),
            timeout_seconds=settings.auth_wechat_miniprogram_timeout_seconds,
            max_response_bytes=settings.auth_wechat_miniprogram_max_response_bytes,
            live_enabled=settings.auth_wechat_miniprogram_live_enabled,
        )

    @property
    def normalized_api_base_url(self) -> str | None:
        parsed = urlparse(self.api_base_url)
        try:
            port = parsed.port
        except ValueError:
            return None
        if (
            parsed.scheme.lower() != "https"
            or parsed.hostname != _OFFICIAL_HOST
            or port not in (None, 443)
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            return None
        return f"https://{_OFFICIAL_HOST}"

    @property
    def complete(self) -> bool:
        return bool(
            self.live_enabled
            and self.app_id
            and self.app_secret
            and self.normalized_api_base_url
            and self.timeout_seconds > 0
            and self.max_response_bytes > 0
        )


class WechatMiniProgramProvider(Protocol):
    available: bool

    def exchange_code(
        self, *, code: str, request_id: UUID
    ) -> VerifiedWechatMiniProgramResult: ...


class WechatMiniProgramOfficialProvider:
    def __init__(
        self,
        config: WechatMiniProgramProviderConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self._transport = transport

    @classmethod
    def from_settings(cls, settings: Settings) -> WechatMiniProgramProvider:
        return cls(WechatMiniProgramProviderConfig.from_settings(settings))

    @property
    def available(self) -> bool:
        return self.config.complete

    def exchange_code(
        self, *, code: str, request_id: UUID
    ) -> VerifiedWechatMiniProgramResult:
        del request_id
        if not self.available:
            raise WechatMiniProgramProviderError("UNAVAILABLE")
        if not code.strip():
            raise WechatMiniProgramProviderError("INVALID")
        try:
            status_code, body = asyncio.run(self._request_async(code))
        except WechatMiniProgramProviderError:
            raise
        except httpx.TimeoutException:
            raise WechatMiniProgramProviderError("TIMEOUT", ambiguous=True) from None
        except httpx.RequestError:
            raise WechatMiniProgramProviderError("PROVIDER_ERROR", ambiguous=True) from None
        except Exception:
            raise WechatMiniProgramProviderError("PROVIDER_ERROR", ambiguous=True) from None
        if status_code == 429:
            raise WechatMiniProgramProviderError("RATE_LIMITED")
        if status_code >= 500:
            raise WechatMiniProgramProviderError("TIMEOUT", ambiguous=True)
        if status_code != 200:
            raise WechatMiniProgramProviderError("PROVIDER_ERROR")
        return self._decode_and_validate(body)

    async def _request_async(self, code: str) -> tuple[int, bytes]:
        base_url = self.config.normalized_api_base_url
        if base_url is None:
            raise WechatMiniProgramProviderError("UNAVAILABLE")
        timeout = httpx.Timeout(self.config.timeout_seconds)
        try:
            async with asyncio.timeout(self.config.timeout_seconds):
                async with httpx.AsyncClient(
                    base_url=base_url,
                    follow_redirects=False,
                    timeout=timeout,
                    transport=self._transport,
                    trust_env=False,
                ) as client:
                    with _redacted_provider_logging(
                        credential=code,
                        app_secret=self.config.app_secret,
                    ):
                        async with client.stream(
                            "GET",
                            _CODE2SESSION_PATH,
                            params={
                                "appid": self.config.app_id,
                                "secret": self.config.app_secret,
                                "js_code": code,
                                "grant_type": "authorization_code",
                            },
                        ) as response:
                            chunks: list[bytes] = []
                            total = 0
                            async for chunk in response.aiter_bytes():
                                total += len(chunk)
                                if total > self.config.max_response_bytes:
                                    raise WechatMiniProgramProviderError("PROVIDER_ERROR")
                                chunks.append(chunk)
                            return response.status_code, b"".join(chunks)
        except TimeoutError:
            raise WechatMiniProgramProviderError("TIMEOUT", ambiguous=True) from None

    def _decode_and_validate(self, body: bytes) -> VerifiedWechatMiniProgramResult:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WechatMiniProgramProviderError("PROVIDER_ERROR") from exc
        if not isinstance(payload, dict):
            raise WechatMiniProgramProviderError("PROVIDER_ERROR")
        errcode = payload.get("errcode")
        if errcode is not None:
            if isinstance(errcode, bool) or not isinstance(errcode, int):
                raise WechatMiniProgramProviderError("PROVIDER_ERROR")
            if errcode != 0:
                raise WechatMiniProgramProviderError(_ERROR_CODES.get(errcode, "PROVIDER_ERROR"))
        openid = payload.get("openid")
        session_key = payload.get("session_key")
        unionid = payload.get("unionid")
        if not isinstance(openid, str) or not openid.strip():
            raise WechatMiniProgramProviderError("PROVIDER_ERROR")
        if not isinstance(session_key, str) or not session_key.strip():
            raise WechatMiniProgramProviderError("PROVIDER_ERROR")
        if unionid is not None and (not isinstance(unionid, str) or not unionid.strip()):
            raise WechatMiniProgramProviderError("PROVIDER_ERROR")
        return VerifiedWechatMiniProgramResult(
            app_id=self.config.app_id,
            openid=openid.strip(),
            unionid=unionid.strip() if isinstance(unionid, str) else None,
            verified_at=datetime.now(UTC),
        )


class DisabledWechatMiniProgramProvider:
    available = False

    def exchange_code(self, *, code: str, request_id: UUID) -> VerifiedWechatMiniProgramResult:
        raise WechatMiniProgramProviderError("UNAVAILABLE")


class FakeWechatMiniProgramProvider:
    available = True

    def __init__(self, result: VerifiedWechatMiniProgramResult | None = None):
        self.result = result or VerifiedWechatMiniProgramResult(
            app_id="test-mini-app",
            openid="test-mini-openid",
            unionid=None,
            verified_at=datetime.now(UTC),
        )
        self.calls = 0

    def exchange_code(self, *, code: str, request_id: UUID) -> VerifiedWechatMiniProgramResult:
        self.calls += 1
        if not code.strip():
            raise WechatMiniProgramProviderError("INVALID")
        return self.result


def get_wechat_miniprogram_provider(
    settings: Settings | None = None,
) -> WechatMiniProgramProvider:
    current = settings or get_settings()
    provider_name = current.auth_wechat_miniprogram_provider.strip().lower()
    if not current.is_production and provider_name == "fake":
        return FakeWechatMiniProgramProvider()
    if provider_name == "wechat_miniprogram" and current.auth_wechat_miniprogram_live_enabled:
        provider = WechatMiniProgramOfficialProvider.from_settings(current)
        if provider.available:
            return provider
    return DisabledWechatMiniProgramProvider()
