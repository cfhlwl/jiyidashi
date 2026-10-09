from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse
from uuid import UUID

from app.core.config import Settings
from app.services.sms_otp_provider import SmsOtpDelivery, SmsOtpProviderError

_MAINLAND_PHONE = re.compile(r"^\+86(1[3-9]\d{9})$")
_OTP = re.compile(r"^\d{6}$")
_OFFICIAL_ENDPOINT_HOST = "dysmsapi.aliyuncs.com"
_RATE_LIMIT_CODES = {
    "isv.businesslimitcontrol",
    "isv.quotanumberlimit",
    "isv.quotaexceed",
    "throttling",
    "flowlimit",
}


@dataclass(frozen=True)
class AliyunSmsProviderConfig:
    endpoint: str
    region: str
    sign_name: str
    template_code: str
    credential_source: str
    access_key_id: str
    access_key_secret: str
    timeout_seconds: float

    @classmethod
    def from_settings(cls, settings: Settings) -> AliyunSmsProviderConfig:
        return cls(
            endpoint=settings.auth_sms_otp_aliyun_endpoint.strip(),
            region=settings.auth_sms_otp_aliyun_region.strip(),
            sign_name=settings.auth_sms_otp_aliyun_sign_name.strip(),
            template_code=settings.auth_sms_otp_aliyun_template_code.strip(),
            credential_source=settings.auth_sms_otp_aliyun_credential_source.strip().lower(),
            access_key_id=settings.auth_sms_otp_aliyun_access_key_id.strip(),
            access_key_secret=settings.auth_sms_otp_aliyun_access_key_secret.strip(),
            timeout_seconds=settings.auth_sms_otp_aliyun_timeout_seconds,
        )

    @property
    def complete(self) -> bool:
        return (
            self.normalized_endpoint is not None
            and bool(self.region)
            and bool(self.sign_name)
            and bool(self.template_code)
            and self.credential_source == "environment"
            and bool(self.access_key_id)
            and bool(self.access_key_secret)
        )

    @property
    def normalized_endpoint(self) -> str | None:
        value = self.endpoint.strip()
        if not value:
            return None
        candidate = urlparse(value if "://" in value else f"//{value}")
        if "://" in value and candidate.scheme.lower() != "https":
            return None
        try:
            port = candidate.port
        except ValueError:
            return None
        if (
            candidate.hostname != _OFFICIAL_ENDPOINT_HOST
            or candidate.username
            or candidate.password
            or port is not None
            or candidate.path not in ("", "/")
            or candidate.query
            or candidate.fragment
        ):
            return None
        return _OFFICIAL_ENDPOINT_HOST


@dataclass(frozen=True)
class AliyunSmsResponse:
    code: str | None
    request_id: str | None
    status_code: int | None = None


class AliyunSmsTransport(Protocol):
    def send_sms(
        self,
        *,
        phone_number: str,
        sign_name: str,
        template_code: str,
        template_param: str,
        request_id: UUID,
    ) -> AliyunSmsResponse: ...


class _OfficialAliyunSmsTransport:
    """Thin adapter around the pinned official Alibaba Cloud Python SDK."""

    def __init__(self, config: AliyunSmsProviderConfig) -> None:
        from alibabacloud_dysmsapi20170525.client import Client
        from alibabacloud_tea_openapi import models as open_api_models

        sdk_config = open_api_models.Config(
            access_key_id=config.access_key_id,
            access_key_secret=config.access_key_secret,
        )
        sdk_config.endpoint = config.normalized_endpoint
        sdk_config.protocol = "https"
        sdk_config.region_id = config.region
        self.sdk_config = sdk_config
        self._client = Client(sdk_config)
        self._config = config

    def send_sms(
        self,
        *,
        phone_number: str,
        sign_name: str,
        template_code: str,
        template_param: str,
        request_id: UUID,
    ) -> AliyunSmsResponse:
        from alibabacloud_dysmsapi20170525 import models as sms_models
        from alibabacloud_tea_util import models as util_models

        request = sms_models.SendSmsRequest(
            phone_numbers=phone_number,
            sign_name=sign_name,
            template_code=template_code,
            template_param=template_param,
        )
        timeout_ms = int(self._config.timeout_seconds * 1000)
        runtime = util_models.RuntimeOptions(
            autoretry=False,
            max_attempts=1,
            connect_timeout=timeout_ms,
            read_timeout=timeout_ms,
        )
        response = self._client.send_sms_with_options(request, runtime)
        body = getattr(response, "body", None)
        return AliyunSmsResponse(
            code=getattr(body, "code", None),
            request_id=getattr(body, "request_id", None),
            status_code=getattr(response, "status_code", None),
        )


class AliyunSmsOtpProvider:
    """Server-side Alibaba Cloud SendSms implementation.

    The transport is injectable so tests never contact Alibaba Cloud. This
    adapter makes exactly one provider call per challenge and never retries an
    ambiguous send result.
    """

    def __init__(
        self,
        config: AliyunSmsProviderConfig,
        transport: AliyunSmsTransport | None = None,
    ) -> None:
        self.config = config
        self._transport = transport
        if self._transport is None and config.complete:
            try:
                self._transport = _OfficialAliyunSmsTransport(config)
            except (ImportError, ModuleNotFoundError):
                self._transport = None

    @classmethod
    def from_settings(cls, settings: Settings) -> AliyunSmsOtpProvider:
        return cls(AliyunSmsProviderConfig.from_settings(settings))

    @property
    def available(self) -> bool:
        return self.config.complete and self._transport is not None

    def deliver_code(self, *, phone_subject: str, code: str, request_id: UUID) -> SmsOtpDelivery:
        if not self.available:
            raise SmsOtpProviderError("UNAVAILABLE")
        if not _OTP.fullmatch(code):
            raise SmsOtpProviderError("PROVIDER_ERROR")
        phone_match = _MAINLAND_PHONE.fullmatch(phone_subject)
        if phone_match is None:
            raise SmsOtpProviderError("PROVIDER_ERROR")

        # The approved template receives only the server-generated OTP. No
        # caller-controlled template variables are accepted.
        template_param = json.dumps({"code": code}, separators=(",", ":"))
        try:
            result = self._transport.send_sms(
                phone_number=phone_match.group(1),
                sign_name=self.config.sign_name,
                template_code=self.config.template_code,
                template_param=template_param,
                request_id=request_id,
            )
        except TimeoutError as exc:
            raise SmsOtpProviderError("TIMEOUT") from exc
        except Exception as exc:
            raise SmsOtpProviderError(_exception_code(exc)) from exc

        provider_code = (result.code or "").strip()
        if provider_code.upper() == "OK" and result.request_id:
            return SmsOtpDelivery(provider_request_id=result.request_id)
        if _is_rate_limited(provider_code, result.status_code):
            raise SmsOtpProviderError("RATE_LIMITED")
        raise SmsOtpProviderError("PROVIDER_ERROR")


def _is_rate_limited(code: str, status_code: int | None) -> bool:
    if status_code == 429:
        return True
    normalized = code.strip().lower()
    return normalized in _RATE_LIMIT_CODES or "throttl" in normalized or "limit" in normalized


def _exception_code(exc: Exception) -> str:
    status_code = getattr(exc, "status_code", None) or getattr(exc, "statusCode", None)
    if status_code == 429:
        return "RATE_LIMITED"
    if isinstance(status_code, int) and status_code >= 500:
        return "PROVIDER_ERROR"
    name = type(exc).__name__.lower()
    if "timeout" in name or "timedout" in name:
        return "TIMEOUT"
    return "PROVIDER_ERROR"
