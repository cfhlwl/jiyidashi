from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select

from app.auth_models import (
    AuthIdentity,
    AuthProvider,
    AuthSession,
    AuthSmsOtpChallenge,
    AuthSmsOtpChallengeState,
)
from app.core.db import SessionLocal
from app.services.sms_otp_provider import FakeSmsOtpProvider


def _settings(monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "auth_sms_otp_provider", "fake")
    monkeypatch.setattr(settings, "auth_sms_otp_code_secret", "test-sms-otp-secret")
    monkeypatch.setattr(settings, "auth_sms_otp_ip_limit", 1000)
    monkeypatch.setattr(settings, "auth_sms_otp_device_limit", 1000)
    monkeypatch.setattr(settings, "auth_sms_otp_phone_limit", 1000)
    monkeypatch.setattr(settings, "auth_sms_otp_verify_ip_limit", 1000)
    monkeypatch.setattr(settings, "auth_sms_otp_verify_request_limit", 1000)
    return settings


def _provider() -> FakeSmsOtpProvider:
    from app.services.sms_otp_provider import _fake_provider

    _fake_provider.sent.clear()
    return _fake_provider


@pytest.mark.asyncio
async def test_sms_otp_new_phone_uses_canonical_identity_and_session(client, monkeypatch):
    settings = _settings(monkeypatch)
    provider = _provider()
    request = await client.post(
        "/v1/auth/phone/sms/request",
        json={"phone": "+8613800000001", "device_id": "sms-test-device"},
    )
    assert request.status_code == 200
    request_id = request.json()["request_id"]
    code = provider.sent[next(iter(provider.sent))]
    verified = await client.post(
        "/v1/auth/phone/sms/verify",
        json={
            "request_id": request_id,
            "code": code,
            "device_id": "sms-test-device",
        },
    )
    assert verified.status_code == 200
    user_id = verified.json()["user_id"]
    with SessionLocal() as db:
        identity = db.scalar(
            select(AuthIdentity).where(
                AuthIdentity.provider == AuthProvider.PHONE,
                AuthIdentity.subject == "+8613800000001",
            )
        )
        assert identity is not None and str(identity.user_id) == user_id
        row = db.scalar(
            select(AuthSmsOtpChallenge).where(AuthSmsOtpChallenge.request_id == UUID(request_id))
        )
        assert row is not None
        assert row.state == AuthSmsOtpChallengeState.VERIFIED
        assert code not in row.code_digest
    assert settings.auth_sms_otp_provider == "fake"


@pytest.mark.asyncio
async def test_sms_otp_server_cooldown_blocks_double_request(client, monkeypatch):
    _settings(monkeypatch)
    _provider()
    payload = {"phone": "+8613800000002", "device_id": "sms-test-device"}
    first = await client.post("/v1/auth/phone/sms/request", json=payload)
    second = await client.post("/v1/auth/phone/sms/request", json=payload)
    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"] == "AUTH_SMS_OTP_COOLDOWN"


@pytest.mark.asyncio
async def test_sms_otp_challenge_device_binding_preserves_original_authority(
    client, monkeypatch
):
    _settings(monkeypatch)
    provider = _provider()
    requested = await client.post(
        "/v1/auth/phone/sms/request",
        json={"phone": "+8613800000005", "device_id": "DEVICE-A"},
    )
    assert requested.status_code == 200
    request_id = requested.json()["request_id"]
    code = provider.sent[next(iter(provider.sent))]

    mismatch = await client.post(
        "/v1/auth/phone/sms/verify",
        json={"request_id": request_id, "code": code, "device_id": "DEVICE-B"},
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"] == "AUTH_SMS_OTP_CHALLENGE_MISMATCH"
    assert "access_token" not in mismatch.json()
    assert "refresh_token" not in mismatch.json()

    with SessionLocal() as db:
        row = db.scalar(
            select(AuthSmsOtpChallenge).where(AuthSmsOtpChallenge.request_id == UUID(request_id))
        )
        assert row is not None
        assert row.state == AuthSmsOtpChallengeState.PENDING
        assert row.session_id is None
        assert row.resolved_user_id is None

    retry = await client.post(
        "/v1/auth/phone/sms/verify",
        json={"request_id": request_id, "code": code, "device_id": "DEVICE-A"},
    )
    assert retry.status_code == 200
    session_id = UUID(retry.json()["session_id"])
    with SessionLocal() as db:
        session = db.get(AuthSession, session_id)
        assert session is not None
        assert session.device_id == "DEVICE-A"


@pytest.mark.asyncio
async def test_sms_otp_invalid_and_expired_are_consumer_safe(client, monkeypatch):
    settings = _settings(monkeypatch)
    provider = _provider()
    response = await client.post(
        "/v1/auth/phone/sms/request",
        json={"phone": "+8613800000003", "device_id": "sms-test-device"},
    )
    request_id = response.json()["request_id"]
    invalid = await client.post(
        "/v1/auth/phone/sms/verify",
        json={"request_id": request_id, "code": "000000", "device_id": "sms-test-device"},
    )
    assert invalid.status_code == 401
    assert invalid.json()["detail"] == "AUTH_SMS_OTP_INVALID"
    with SessionLocal() as db:
        row = db.scalar(
            select(AuthSmsOtpChallenge).where(AuthSmsOtpChallenge.request_id == UUID(request_id))
        )
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    expired = await client.post(
        "/v1/auth/phone/sms/verify",
        json={
            "request_id": request_id,
            "code": provider.sent[next(iter(provider.sent))],
            "device_id": "sms-test-device",
        },
    )
    assert expired.status_code == 410
    assert expired.json()["detail"] == "AUTH_SMS_OTP_EXPIRED"
    assert settings.auth_sms_otp_code_secret == "test-sms-otp-secret"


@pytest.mark.asyncio
async def test_sms_otp_disabled_provider_fails_closed(client, monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "auth_sms_otp_provider", "disabled")
    monkeypatch.setattr(settings, "auth_sms_otp_code_secret", "test-sms-otp-secret")
    response = await client.post(
        "/v1/auth/phone/sms/request",
        json={"phone": "+8613800000004", "device_id": "sms-test-device"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "AUTH_SMS_OTP_UNAVAILABLE"
