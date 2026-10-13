from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.services.wechat_miniprogram_provider import (
    WechatMiniProgramOfficialProvider,
    WechatMiniProgramProviderConfig,
    WechatMiniProgramProviderError,
)


def _config(**overrides) -> WechatMiniProgramProviderConfig:
    values = {
        "app_id": "wx-mini-test",
        "app_secret": "server-only-secret",
        "api_base_url": "https://api.weixin.qq.com",
        "timeout_seconds": 5.0,
        "max_response_bytes": 65536,
        "live_enabled": True,
    }
    values.update(overrides)
    return WechatMiniProgramProviderConfig(**values)


def test_code2session_uses_official_https_contract_and_discards_session_key():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "openid": "openid-1",
                "session_key": "provider-session-key",
                "unionid": "union-1",
            },
            request=request,
        )

    result = WechatMiniProgramOfficialProvider(
        _config(), transport=httpx.MockTransport(handler)
    ).exchange_code(code="wx-login-code", request_id=__import__("uuid").uuid4())
    query = parse_qs(urlparse(str(calls[0].url)).query)
    assert calls[0].url.scheme == "https"
    assert calls[0].url.host == "api.weixin.qq.com"
    assert query["appid"] == ["wx-mini-test"]
    assert query["secret"] == ["server-only-secret"]
    assert query["js_code"] == ["wx-login-code"]
    assert query["grant_type"] == ["authorization_code"]
    assert result.openid == "openid-1"
    assert result.unionid == "union-1"
    assert not hasattr(result, "session_key")


@pytest.mark.parametrize(
    "payload",
    [
        {"errcode": 40029, "errmsg": "invalid code"},
        {"openid": "openid-only"},
        {"openid": "openid", "session_key": ""},
        ["not-an-object"],
    ],
)
def test_code2session_rejects_provider_errors_and_incomplete_schema(payload):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    provider = WechatMiniProgramOfficialProvider(
        _config(), transport=httpx.MockTransport(handler)
    )
    with pytest.raises(WechatMiniProgramProviderError):
        provider.exchange_code(code="code", request_id=__import__("uuid").uuid4())


@pytest.mark.parametrize(
    "base_url",
    [
        "http://api.weixin.qq.com",
        "https://evil.example",
        "https://api.weixin.qq.com:8443",
        "https://api.weixin.qq.com/sns/jscode2session?secret=bad",
    ],
)
def test_code2session_rejects_non_official_endpoint(base_url):
    provider = WechatMiniProgramOfficialProvider(
        _config(api_base_url=base_url)
    )
    assert provider.available is False
    with pytest.raises(WechatMiniProgramProviderError, match="UNAVAILABLE"):
        provider.exchange_code(code="code", request_id=__import__("uuid").uuid4())
