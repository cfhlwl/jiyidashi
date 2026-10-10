from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.auth_models import AuthSession, WechatExchangeState, WechatLoginExchange
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import User
from app.services.wechat_auth_provider import (
    DisabledWechatAuthProvider,
    FakeWechatAuthProvider,
    VerifiedWechatResult,
    WechatOAuthProvider,
    WechatOAuthProviderConfig,
    WechatProviderError,
    get_wechat_provider,
)
from app.services.wechat_login_service import WechatLoginError, exchange_wechat_credential


def _config(**overrides) -> WechatOAuthProviderConfig:
    values = {
        "app_id": "wx-test-app",
        "app_secret": "server-only-app-secret",
        "subject_scope": "wx-test-group",
        "fingerprint_secret": "test-fingerprint-secret",
        "api_base_url": "https://api.weixin.qq.com",
        "timeout_seconds": 5.0,
        "max_response_bytes": 65536,
        "live_enabled": True,
    }
    values.update(overrides)
    return WechatOAuthProviderConfig(**values)


def _transport(payload=None, *, status_code=200, error: Exception | None = None, calls=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        if error is not None:
            raise error
        return httpx.Response(status_code, json=payload, request=request)

    return httpx.MockTransport(handler)


def _exchange(provider: WechatOAuthProvider, credential: str = "native-code-123"):
    return provider.exchange_credential(credential=credential, request_id=uuid4())


def test_oauth_exchange_returns_scoped_verified_identifiers_and_never_tokens():
    calls: list[httpx.Request] = []
    provider = WechatOAuthProvider(
        _config(),
        transport=_transport(
            {
                "access_token": "provider-access-token",
                "expires_in": 7200,
                "refresh_token": "provider-refresh-token",
                "openid": "openid-123",
                "scope": "snsapi_userinfo",
                "unionid": "unionid-123",
            },
            calls=calls,
        ),
    )

    result = _exchange(provider)

    assert result == VerifiedWechatResult(
        app_id="wx-test-app",
        scope="wx-test-group",
        openid="openid-123",
        unionid="unionid-123",
        verified_at=result.verified_at,
    )
    assert result.canonical_subjects() == (
        "unionid:wx-test-group:unionid-123",
        "openid:wx-test-app:openid-123",
    )
    assert len(calls) == 1
    assert calls[0].url.scheme == "https"
    assert calls[0].url.host == "api.weixin.qq.com"
    assert calls[0].url.path == "/sns/oauth2/access_token"
    assert calls[0].url.params["appid"] == "wx-test-app"
    assert calls[0].url.params["secret"] == "server-only-app-secret"
    assert calls[0].url.params["code"] == "native-code-123"
    assert "provider-access-token" not in repr(result)
    assert "provider-refresh-token" not in repr(result)


def test_oauth_exchange_accepts_official_openid_only_response():
    provider = WechatOAuthProvider(
        _config(),
        transport=_transport(
            {
                "access_token": "provider-access-token",
                "expires_in": 7200,
                "refresh_token": "provider-refresh-token",
                "openid": "openid-only",
                "scope": "snsapi_base",
            }
        ),
    )

    result = _exchange(provider)

    assert result.unionid is None
    assert result.canonical_subjects() == ("openid:wx-test-app:openid-only",)


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        ({"errcode": 40029, "errmsg": "invalid code"}, "INVALID"),
        ({"errcode": 40163, "errmsg": "code been used"}, "REPLAYED"),
        ({"errcode": 45011, "errmsg": "too frequent"}, "RATE_LIMITED"),
        ({"access_token": "token", "openid": "openid", "appid": "wrong-app"}, "PROVIDER_ERROR"),
        ({"access_token": "token"}, "PROVIDER_ERROR"),
        ({"access_token": "token", "openid": "bad openid"}, "PROVIDER_ERROR"),
        ({"access_token": "token", "openid": "openid", "expires_in": "7200"}, "PROVIDER_ERROR"),
    ],
)
def test_oauth_exchange_rejects_provider_errors_and_malformed_schema(payload, expected_code):
    provider = WechatOAuthProvider(_config(), transport=_transport(payload))

    with pytest.raises(WechatProviderError) as raised:
        _exchange(provider)

    assert raised.value.code == expected_code
    assert "server-only-app-secret" not in str(raised.value)
    assert "native-code-123" not in str(raised.value)


@pytest.mark.parametrize(
    ("status_code", "expected_code", "ambiguous"),
    [
        (401, "PROVIDER_ERROR", False),
        (429, "RATE_LIMITED", False),
        (500, "TIMEOUT", True),
        (503, "TIMEOUT", True),
        (302, "PROVIDER_ERROR", False),
    ],
)
def test_oauth_exchange_normalizes_http_failures_without_retry(
    status_code, expected_code, ambiguous
):
    calls: list[httpx.Request] = []
    provider = WechatOAuthProvider(
        _config(),
        transport=_transport(
            {"errmsg": "secret=server-only-app-secret"},
            status_code=status_code,
            calls=calls,
        ),
    )

    with pytest.raises(WechatProviderError) as raised:
        _exchange(provider)

    assert raised.value.code == expected_code
    assert raised.value.ambiguous is ambiguous
    assert len(calls) == 1


def test_oauth_exchange_treats_malformed_5xx_body_as_ambiguous():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"not-json", request=request)

    provider = WechatOAuthProvider(_config(), transport=httpx.MockTransport(handler))

    with pytest.raises(WechatProviderError) as raised:
        _exchange(provider)

    assert raised.value.code == "TIMEOUT"
    assert raised.value.ambiguous is True


def test_oauth_exchange_does_not_follow_redirects_to_another_host():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            302,
            headers={"location": "https://evil.example/collect"},
            request=request,
        )

    provider = WechatOAuthProvider(_config(), transport=httpx.MockTransport(handler))
    with pytest.raises(WechatProviderError, match="PROVIDER_ERROR"):
        _exchange(provider)
    assert len(calls) == 1


def test_oauth_exchange_fails_closed_on_oversized_response():
    provider = WechatOAuthProvider(
        _config(max_response_bytes=1024),
        transport=_transport({"access_token": "token", "openid": "x" * 4096}),
    )

    with pytest.raises(WechatProviderError, match="PROVIDER_ERROR"):
        _exchange(provider)


def test_oauth_exchange_maps_network_timeout_to_ambiguous_without_leaking_inputs():
    provider = WechatOAuthProvider(
        _config(),
        transport=_transport(
            error=httpx.ReadTimeout(
                "secret=server-only-app-secret code=native-code-123",
                request=httpx.Request("GET", "https://api.weixin.qq.com"),
            )
        ),
    )

    with pytest.raises(WechatProviderError) as raised:
        _exchange(provider)

    assert raised.value.code == "TIMEOUT"
    assert raised.value.ambiguous is True
    assert str(raised.value) == "TIMEOUT"


def test_oauth_exchange_redacts_httpx_info_logs(caplog):
    caplog.set_level(logging.INFO, logger="httpx")
    provider = WechatOAuthProvider(
        _config(),
        transport=_transport(
            {
                "access_token": "provider-access-token",
                "openid": "openid-log-safe",
            }
        ),
    )

    _exchange(provider)

    assert any(record.name == "httpx" for record in caplog.records)
    assert "server-only-app-secret" not in caplog.text
    assert "native-code-123" not in caplog.text
    assert "<redacted>" in caplog.text


def test_oauth_exchange_sanitizes_timeout_trace_and_exception_chain(caplog):
    caplog.set_level(logging.DEBUG, logger="httpx")
    provider = WechatOAuthProvider(
        _config(),
        transport=_transport(
            error=httpx.ReadTimeout(
                "https://api.weixin.qq.com/sns/oauth2/access_token"
                "?secret=server-only-app-secret&code=native-code-123",
                request=httpx.Request("GET", "https://api.weixin.qq.com"),
            )
        ),
    )

    with pytest.raises(WechatProviderError) as raised:
        _exchange(provider)

    assert raised.value.code == "TIMEOUT"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert "server-only-app-secret" not in caplog.text
    assert "native-code-123" not in caplog.text


def test_oauth_exchange_redacts_exception_stack_and_structured_url_extra(caplog):
    raw_secret = "server-only-app-secret"
    raw_code = "native-code-123"
    raw_url = (
        "https://api.weixin.qq.com/sns/oauth2/access_token"
        f"?secret={raw_secret}&code={raw_code}"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        logger = logging.getLogger("httpx")
        try:
            raise RuntimeError(raw_url)
        except RuntimeError:
            logger.exception(
                "provider trace",
                extra={"url": raw_url, "nested": {"code": raw_code}},
                stack_info=True,
            )
        return httpx.Response(
            200,
            json={"access_token": "provider-access-token", "openid": "openid-trace"},
            request=request,
        )

    caplog.set_level(logging.DEBUG, logger="httpx")
    _exchange(WechatOAuthProvider(_config(), transport=httpx.MockTransport(handler)))

    assert raw_secret not in caplog.text
    assert raw_code not in caplog.text
    assert "<redacted>" in caplog.text
    assert all(raw_secret not in repr(record.__dict__) for record in caplog.records)
    assert all(raw_code not in repr(record.__dict__) for record in caplog.records)


def test_oauth_exchange_redacts_concurrent_requests_with_distinct_credentials(caplog):
    raw_values = (
        ("secret-one", "code-one"),
        ("secret-two", "code-two"),
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        secret = request.url.params["secret"]
        code = request.url.params["code"]
        logging.getLogger("httpx").info(
            "provider request %s",
            request.url,
            extra={
                "request_url": str(request.url),
                "credentials": {"secret": secret, "code": code},
            },
        )
        return httpx.Response(
            200,
            json={"access_token": "provider-access-token", "openid": code},
            request=request,
        )

    def run(values: tuple[str, str]) -> VerifiedWechatResult:
        secret, code = values
        provider = WechatOAuthProvider(
            _config(app_secret=secret), transport=httpx.MockTransport(handler)
        )
        return _exchange(provider, credential=code)

    caplog.set_level(logging.DEBUG, logger="httpx")
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, raw_values))

    assert len(results) == 2
    for secret, code in raw_values:
        assert secret not in caplog.text
        assert code not in caplog.text


def test_oauth_exchange_enforces_total_timeout_for_slow_response_headers():
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        started.set()
        try:
            await asyncio.to_thread(release.wait, 5)
            return httpx.Response(
                200,
                json={"access_token": "token", "openid": "openid-slow-header"},
                request=request,
            )
        finally:
            finished.set()

    provider = WechatOAuthProvider(
        _config(timeout_seconds=0.1),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(WechatProviderError) as raised:
        _exchange(provider)

    assert started.is_set()
    assert calls == 1
    assert raised.value.code == "TIMEOUT"
    assert raised.value.ambiguous is True
    release.set()
    assert finished.wait(timeout=1)


class _BlockingBody(httpx.AsyncByteStream):
    def __init__(self, started: threading.Event, release: threading.Event) -> None:
        self._started = started
        self._release = release

    async def __aiter__(self):
        self._started.set()
        await asyncio.to_thread(self._release.wait, 5)
        yield b'{"access_token":"token","openid":"openid-slow-body"}'


def test_oauth_exchange_enforces_total_timeout_for_slow_stream_body():
    started = threading.Event()
    release = threading.Event()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, stream=_BlockingBody(started, release), request=request)

    provider = WechatOAuthProvider(
        _config(timeout_seconds=0.1),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(WechatProviderError) as raised:
        _exchange(provider)

    assert started.is_set()
    assert calls == 1
    assert raised.value.code == "TIMEOUT"
    assert raised.value.ambiguous is True
    release.set()


class _TricklingBody(httpx.AsyncByteStream):
    def __init__(self, started: threading.Event, cancelled: threading.Event) -> None:
        self._started = started
        self._cancelled = cancelled

    async def __aiter__(self):
        self._started.set()
        try:
            while True:
                yield b"x"
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            self._cancelled.set()
            raise


def test_oauth_exchange_timeout_cancels_continuous_trickle_body():
    started = threading.Event()
    cancelled = threading.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=_TricklingBody(started, cancelled),
            request=request,
        )

    provider = WechatOAuthProvider(
        _config(timeout_seconds=0.05),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(WechatProviderError) as raised:
        _exchange(provider)

    assert started.is_set()
    assert cancelled.wait(timeout=1)
    assert raised.value.code == "TIMEOUT"
    assert raised.value.ambiguous is True


def test_repeated_provider_timeouts_leave_no_exchange_workers_or_open_tasks():
    started = threading.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.sleep(30)
        return httpx.Response(
            200,
            json={"access_token": "token", "openid": "openid-trickle"},
            request=request,
        )

    provider = WechatOAuthProvider(
        _config(timeout_seconds=0.05),
        transport=httpx.MockTransport(handler),
    )
    before = {thread.name for thread in threading.enumerate()}

    for _ in range(5):
        with pytest.raises(WechatProviderError) as raised:
            _exchange(provider)
        assert raised.value.code == "TIMEOUT"
        assert raised.value.ambiguous is True

    after = {thread.name for thread in threading.enumerate()}
    assert started.is_set()
    assert "wechat-oauth-exchange" not in after
    assert after - before == set()


@pytest.mark.parametrize(
    "base_url",
    [
        "",
        "http://api.weixin.qq.com",
        "https://evil.example",
        "https://api.weixin.qq.com/sns",
        "https://user:password@api.weixin.qq.com",
        "https://api.weixin.qq.com?forward=evil",
        "https://api.weixin.qq.com:8443",
    ],
)
def test_oauth_config_rejects_unapproved_endpoint(base_url):
    provider = WechatOAuthProvider(_config(api_base_url=base_url))

    assert provider.available is False
    with pytest.raises(WechatProviderError, match="UNAVAILABLE"):
        _exchange(provider)


def test_factory_requires_live_gate_and_complete_server_configuration(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "auth_wechat_provider", "wechat")
    monkeypatch.setattr(settings, "auth_wechat_live_enabled", False)
    monkeypatch.setattr(settings, "auth_wechat_app_id", "wx-test-app")
    monkeypatch.setattr(settings, "auth_wechat_app_secret", "server-only-app-secret")
    monkeypatch.setattr(settings, "auth_wechat_subject_scope", "wx-test-group")
    monkeypatch.setattr(settings, "auth_wechat_fingerprint_secret", "test-fingerprint-secret")
    monkeypatch.setattr(settings, "auth_wechat_api_base_url", "https://api.weixin.qq.com")

    assert isinstance(get_wechat_provider(settings), DisabledWechatAuthProvider)

    monkeypatch.setattr(settings, "auth_wechat_live_enabled", True)
    provider = get_wechat_provider(settings)
    assert isinstance(provider, WechatOAuthProvider)
    assert provider.available is True

    monkeypatch.setattr(settings, "auth_wechat_app_secret", "")
    assert isinstance(get_wechat_provider(settings), DisabledWechatAuthProvider)

    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "auth_wechat_provider", "fake")
    assert isinstance(get_wechat_provider(settings), FakeWechatAuthProvider)


def test_real_adapter_uses_existing_receipt_to_block_code_replay(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_rate_limit_enabled", False)
    monkeypatch.setattr(settings, "auth_wechat_fingerprint_secret", "test-b1-fingerprint-secret")
    monkeypatch.setattr(settings, "auth_wechat_app_id", "wx-b1-app")
    monkeypatch.setattr(settings, "auth_wechat_subject_scope", "wx-b1-group")
    suffix = uuid4().hex
    calls: list[httpx.Request] = []
    provider = WechatOAuthProvider(
        _config(
            app_id="wx-b1-app",
            subject_scope="wx-b1-group",
        ),
        transport=_transport(
            {
                "access_token": "provider-access-token",
                "expires_in": 7200,
                "refresh_token": "provider-refresh-token",
                "openid": f"openid-{suffix}",
                "unionid": f"unionid-{suffix}",
            },
            calls=calls,
        ),
    )
    request_id = uuid4()
    credential = f"native-code-{suffix}"

    with SessionLocal() as db:
        first = exchange_wechat_credential(
            db,
            credential=credential,
            request_id=request_id,
            device_id=f"b1-device-{suffix}",
            client_platform="test",
            device_name="B1",
            client_ip="127.0.0.1",
            provider=provider,
            settings=settings,
        )
        with pytest.raises(WechatLoginError, match="AUTH_WECHAT_CREDENTIAL_REPLAYED"):
            exchange_wechat_credential(
                db,
                credential=credential,
                request_id=request_id,
                device_id=f"b1-device-{suffix}",
                client_platform="test",
                device_name="B1",
                client_ip="127.0.0.1",
                provider=provider,
                settings=settings,
            )

    assert first.tokens.user_id is not None
    assert len(calls) == 1


def test_slow_provider_timeout_terminalizes_receipt_without_session_or_retry(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_rate_limit_enabled", False)
    monkeypatch.setattr(settings, "auth_wechat_fingerprint_secret", "test-timeout-fingerprint")
    monkeypatch.setattr(settings, "auth_wechat_app_id", "wx-timeout-app")
    monkeypatch.setattr(settings, "auth_wechat_subject_scope", "wx-timeout-group")
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        started.set()
        try:
            await asyncio.to_thread(release.wait, 5)
            return httpx.Response(
                200,
                json={"access_token": "token", "openid": "openid-timeout"},
                request=request,
            )
        finally:
            finished.set()

    provider = WechatOAuthProvider(
        _config(
            app_id="wx-timeout-app",
            subject_scope="wx-timeout-group",
            timeout_seconds=0.1,
        ),
        transport=httpx.MockTransport(handler),
    )
    request_id = uuid4()
    credential = "native-code-timeout"

    with SessionLocal() as db:
        before_sessions = set(db.scalars(select(AuthSession.id)))
        before_users = set(db.scalars(select(User.id)))
        with pytest.raises(WechatLoginError, match="AUTH_WECHAT_TIMEOUT"):
            exchange_wechat_credential(
                db,
                credential=credential,
                request_id=request_id,
                device_id="timeout-device",
                client_platform="test",
                device_name="timeout",
                client_ip="127.0.0.1",
                provider=provider,
                settings=settings,
            )

        receipt = db.scalar(
            select(WechatLoginExchange).where(WechatLoginExchange.request_id == request_id)
        )
        assert receipt is not None
        assert receipt.state == WechatExchangeState.PROVIDER_UNKNOWN
        assert receipt.error_code == "AUTH_WECHAT_TIMEOUT"
        assert receipt.resolved_user_id is None
        assert receipt.session_id is None
        assert set(db.scalars(select(AuthSession.id))) == before_sessions
        assert set(db.scalars(select(User.id))) == before_users

        release.set()
        assert finished.wait(timeout=1)

        with pytest.raises(WechatLoginError, match="AUTH_WECHAT_TIMEOUT"):
            exchange_wechat_credential(
                db,
                credential=credential,
                request_id=request_id,
                device_id="timeout-device",
                client_platform="test",
                device_name="timeout",
                client_ip="127.0.0.1",
                provider=provider,
                settings=settings,
            )

    assert started.is_set()
    assert calls == 1
