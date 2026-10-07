from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.auth_models import (
    AuthIdentity,
    AuthProvider,
    AuthSession,
    PhoneOneTapExchange,
    PhoneOneTapExchangeState,
    PhoneOneTapRecoveryState,
)
from app.core.db import SessionLocal
from app.services import phone_one_tap_service
from app.services.phone_one_tap_provider import (
    PhoneOneTapProviderError,
    VerifiedPhoneResult,
)


class FakePhoneOneTapProvider:
    available = True

    def __init__(self, outcomes: dict[str, object]):
        self.outcomes = outcomes
        self.calls: list[str] = []
        self.observed_exchange_state: list[PhoneOneTapExchangeState | None] = []

    def exchange_login_token(self, *, login_token, request_id):
        self.calls.append(login_token)
        with SessionLocal() as db:
            row = db.scalar(
                select(PhoneOneTapExchange).where(
                    PhoneOneTapExchange.request_id == request_id
                )
            )
            self.observed_exchange_state.append(row.state if row else None)
        outcome = self.outcomes[login_token]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _settings(monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "auth_phone_one_tap_fingerprint_secret", "test-phone-key")
    monkeypatch.setattr(settings, "auth_phone_one_tap_exchange_reservation_seconds", 60)
    monkeypatch.setattr(settings, "auth_phone_one_tap_recovery_deadline_seconds", 60)
    return settings


def _payload(token: str, request_id=None) -> dict[str, object]:
    return {
        "login_token": token,
        "request_id": str(request_id or uuid4()),
        "device_id": "physical-test-device",
        "client_platform": "android",
        "device_name": "AUTH-02B test",
    }


@pytest.mark.asyncio
async def test_phone_one_tap_creates_phone_identity_and_recovers_response_loss(
    client, monkeypatch
):
    _settings(monkeypatch)
    request_id = uuid4()
    provider = FakePhoneOneTapProvider(
        {
            "token-a": VerifiedPhoneResult(
                canonical_phone_subject="+8613900001234",
                verified_at=datetime.now(UTC),
                provider_request_id="fake-request-a",
            )
        }
    )
    monkeypatch.setattr(phone_one_tap_service, "get_phone_one_tap_provider", lambda: provider)

    response = await client.post("/v1/auth/phone/one-tap", json=_payload("token-a", request_id))
    assert response.status_code == 200
    first = response.json()
    assert first["account_deletion_in_progress"] is False
    assert provider.calls == ["token-a"]
    assert provider.observed_exchange_state == [PhoneOneTapExchangeState.RESERVED]

    with SessionLocal() as db:
        identity = db.scalar(
            select(AuthIdentity).where(
                AuthIdentity.provider == AuthProvider.PHONE,
                AuthIdentity.subject == "+8613900001234",
            )
        )
        exchange = db.scalar(
            select(PhoneOneTapExchange).where(
                PhoneOneTapExchange.request_id == request_id
            )
        )
        assert identity is not None
        assert exchange is not None
        assert exchange.state == PhoneOneTapExchangeState.COMPLETED
        assert exchange.recovery_state == PhoneOneTapRecoveryState.OPEN
        assert str(exchange.session_id) == first["session_id"]

    retry = await client.post(
        "/v1/auth/phone/one-tap", json=_payload("token-a", request_id)
    )
    assert retry.status_code == 200
    assert retry.json()["session_id"] != first["session_id"]
    assert provider.calls == ["token-a"]

    replay = await client.post(
        "/v1/auth/phone/one-tap", json=_payload("token-a", request_id)
    )
    assert replay.status_code == 409
    assert replay.json()["detail"] == "AUTH_PHONE_ONE_TAP_TOKEN_REPLAYED"

    with SessionLocal() as db:
        sessions = list(
            db.scalars(
                select(AuthSession).where(AuthSession.user_id == identity.user_id)
            )
        )
        assert len(sessions) == 2
        assert sum(session.revoked_at is not None for session in sessions) == 1
        exchange = db.scalar(
            select(PhoneOneTapExchange).where(
                PhoneOneTapExchange.request_id == request_id
            )
        )
        assert exchange.recovery_count == 1
        assert exchange.recovery_state == PhoneOneTapRecoveryState.CLOSED


@pytest.mark.asyncio
async def test_phone_one_tap_replay_and_conflict_fail_closed(client, monkeypatch):
    _settings(monkeypatch)
    provider = FakePhoneOneTapProvider(
        {
            "token-c": VerifiedPhoneResult(
                canonical_phone_subject="+8613900001235",
                verified_at=datetime.now(UTC),
            )
        }
    )
    monkeypatch.setattr(phone_one_tap_service, "get_phone_one_tap_provider", lambda: provider)

    request_id = uuid4()
    assert (
        await client.post("/v1/auth/phone/one-tap", json=_payload("token-c", request_id))
    ).status_code == 200

    different_request = await client.post(
        "/v1/auth/phone/one-tap", json=_payload("token-c")
    )
    assert different_request.status_code == 409
    assert different_request.json()["detail"] == "AUTH_PHONE_ONE_TAP_TOKEN_REPLAYED"

    different_token = await client.post(
        "/v1/auth/phone/one-tap", json=_payload("token-d", request_id)
    )
    assert different_token.status_code == 409
    assert different_token.json()["detail"] == "AUTH_PHONE_ONE_TAP_CONFLICT"
    assert provider.calls == ["token-c"]


@pytest.mark.asyncio
async def test_phone_one_tap_provider_rejection_is_durable(client, monkeypatch):
    _settings(monkeypatch)
    provider = FakePhoneOneTapProvider(
        {
            "expired": PhoneOneTapProviderError("TOKEN_EXPIRED"),
        }
    )
    monkeypatch.setattr(phone_one_tap_service, "get_phone_one_tap_provider", lambda: provider)
    request_id = uuid4()

    response = await client.post(
        "/v1/auth/phone/one-tap", json=_payload("expired", request_id)
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "AUTH_PHONE_ONE_TAP_TOKEN_EXPIRED"

    retry = await client.post(
        "/v1/auth/phone/one-tap", json=_payload("expired", request_id)
    )
    assert retry.status_code == 401
    assert retry.json()["detail"] == "AUTH_PHONE_ONE_TAP_TOKEN_EXPIRED"
    assert provider.calls == ["expired"]


@pytest.mark.asyncio
async def test_phone_field_is_not_an_accepted_auth_authority(client, monkeypatch):
    _settings(monkeypatch)
    payload = _payload("token-a")
    payload["phone"] = "+8613900001234"
    response = await client.post("/v1/auth/phone/one-tap", json=payload)
    assert response.status_code == 422
