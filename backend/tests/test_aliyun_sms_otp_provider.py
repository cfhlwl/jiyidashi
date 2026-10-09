from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

import pytest

from app.core.config import get_settings
from app.services.aliyun_sms_otp_provider import (
    AliyunSmsOtpProvider,
    AliyunSmsProviderConfig,
    AliyunSmsResponse,
    _OfficialAliyunSmsTransport,
)
from app.services.sms_otp_provider import SmsOtpProviderError, get_sms_otp_provider


@dataclass
class FakeAliyunTransport:
    response: AliyunSmsResponse | None = None
    error: Exception | None = None
    calls: list[dict[str, object]] = field(default_factory=list)

    def send_sms(self, **kwargs) -> AliyunSmsResponse:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def _config(**overrides) -> AliyunSmsProviderConfig:
    values = {
        "endpoint": "dysmsapi.aliyuncs.com",
        "region": "cn-hangzhou",
        "sign_name": "JiYi",
        "template_code": "SMS_TEST",
        "credential_source": "environment",
        "access_key_id": "test-access-key-id",
        "access_key_secret": "test-access-key-secret",
        "timeout_seconds": 5.0,
    }
    values.update(overrides)
    return AliyunSmsProviderConfig(**values)


def test_aliyun_provider_missing_config_is_unavailable():
    provider = AliyunSmsOtpProvider(_config(access_key_secret=""))
    assert provider.available is False
    with pytest.raises(SmsOtpProviderError, match="UNAVAILABLE"):
        provider.deliver_code(phone_subject="+8613812345678", code="123456", request_id=uuid4())


@pytest.mark.parametrize(
    "endpoint",
    [
        "",
        "http://dysmsapi.aliyuncs.com",
        "https://invalid.example.com",
        "https://user:secret@dysmsapi.aliyuncs.com",
        "https://dysmsapi.aliyuncs.com/path",
        "https://dysmsapi.aliyuncs.com?query=1",
        "https://dysmsapi.aliyuncs.com#fragment",
        "dysmsapi.aliyuncs.com:not-a-port",
    ],
)
def test_aliyun_endpoint_contract_fails_closed(endpoint):
    assert AliyunSmsOtpProvider(_config(endpoint=endpoint)).available is False


def test_official_transport_construction_sets_host_https_and_region():
    transport = _OfficialAliyunSmsTransport(_config())

    assert transport.sdk_config.endpoint == "dysmsapi.aliyuncs.com"
    assert transport.sdk_config.protocol == "https"
    assert transport.sdk_config.region_id == "cn-hangzhou"


def test_production_fake_provider_is_fail_closed(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "auth_sms_otp_provider", "fake")
    assert get_sms_otp_provider(settings).available is False


def test_aliyun_success_maps_request_id_and_only_otp_template_variable():
    transport = FakeAliyunTransport(response=AliyunSmsResponse("OK", "provider-request-1", 200))
    provider = AliyunSmsOtpProvider(_config(), transport)

    result = provider.deliver_code(
        phone_subject="+8613812345678", code="123456", request_id=uuid4()
    )

    assert result.provider_request_id == "provider-request-1"
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["phone_number"] == "13812345678"
    assert call["sign_name"] == "JiYi"
    assert call["template_code"] == "SMS_TEST"
    assert call["template_param"] == '{"code":"123456"}'


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            AliyunSmsResponse("isv.BUSINESS_LIMIT_CONTROL", "provider-request-2", 200),
            "RATE_LIMITED",
        ),
        (AliyunSmsResponse("", "provider-request-3", 429), "RATE_LIMITED"),
        (AliyunSmsResponse("InternalError", "provider-request-4", 500), "PROVIDER_ERROR"),
        (AliyunSmsResponse(None, None, 200), "PROVIDER_ERROR"),
        (
            AliyunSmsResponse("isv.MOBILE_NUMBER_ILLEGAL", "provider-request-5", 200),
            "PROVIDER_ERROR",
        ),
    ],
)
def test_aliyun_response_errors_are_normalized_without_retry(response, expected):
    transport = FakeAliyunTransport(response=response)
    provider = AliyunSmsOtpProvider(_config(), transport)

    with pytest.raises(SmsOtpProviderError) as raised:
        provider.deliver_code(phone_subject="+8613812345678", code="123456", request_id=uuid4())

    assert raised.value.code == expected
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    ("error", "expected"),
    [(TimeoutError(), "TIMEOUT"), (RuntimeError("provider transport failure"), "PROVIDER_ERROR")],
)
def test_aliyun_transport_errors_are_single_attempt(error, expected):
    transport = FakeAliyunTransport(error=error)
    provider = AliyunSmsOtpProvider(_config(), transport)

    with pytest.raises(SmsOtpProviderError) as raised:
        provider.deliver_code(phone_subject="+8613812345678", code="123456", request_id=uuid4())

    assert raised.value.code == expected
    assert len(transport.calls) == 1


def test_aliyun_rejects_non_mainland_or_non_otp_inputs_without_provider_call():
    transport = FakeAliyunTransport(response=AliyunSmsResponse("OK", "provider-request-6", 200))
    provider = AliyunSmsOtpProvider(_config(), transport)

    with pytest.raises(SmsOtpProviderError, match="PROVIDER_ERROR"):
        provider.deliver_code(phone_subject="+14155550100", code="123456", request_id=uuid4())
    with pytest.raises(SmsOtpProviderError, match="PROVIDER_ERROR"):
        provider.deliver_code(phone_subject="+8613812345678", code="12345", request_id=uuid4())
    assert transport.calls == []
