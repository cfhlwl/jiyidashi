from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.core.config import Settings, get_settings


class SmsOtpProviderError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SmsOtpDelivery:
    provider_request_id: str | None = None


class SmsOtpProvider(Protocol):
    available: bool

    def deliver_code(self, *, phone_subject: str, code: str, request_id: UUID) -> SmsOtpDelivery:
        ...


class DisabledSmsOtpProvider:
    available = False

    def deliver_code(self, *, phone_subject: str, code: str, request_id: UUID) -> SmsOtpDelivery:
        raise SmsOtpProviderError("UNAVAILABLE")


class FakeSmsOtpProvider:
    """Test-only delivery seam; codes remain in process memory and are never logged."""

    available = True

    def __init__(self) -> None:
        self.sent: dict[UUID, str] = {}

    def deliver_code(self, *, phone_subject: str, code: str, request_id: UUID) -> SmsOtpDelivery:
        self.sent[request_id] = code
        return SmsOtpDelivery(provider_request_id=f"fake-{request_id}")


_fake_provider = FakeSmsOtpProvider()


def get_sms_otp_provider(settings: Settings | None = None) -> SmsOtpProvider:
    current = settings or get_settings()
    if current.app_env.lower() == "production":
        return DisabledSmsOtpProvider()
    if current.auth_sms_otp_provider.strip().lower() == "fake":
        return _fake_provider
    return DisabledSmsOtpProvider()
