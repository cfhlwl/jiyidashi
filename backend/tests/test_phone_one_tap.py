from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from app.account_deletion_models import AccountDeletionOperation
from app.auth_models import (
    AuthIdentity,
    AuthProvider,
    AuthRateLimitBucket,
    AuthSession,
    PhoneOneTapExchange,
    PhoneOneTapExchangeState,
    PhoneOneTapRecoveryState,
)
from app.core.db import GuardedSession, SessionLocal
from app.entitlement_models import UserEntitlement
from app.models import Device, User
from app.services import phone_one_tap_service
from app.services.auth_identity_service import (
    create_user_for_verified_identity,
    issue_authenticated_session,
)
from app.services.phone_one_tap_provider import (
    PhoneOneTapProviderError,
    VerifiedPhoneResult,
    normalize_aliyun_mainland_mobile,
)
from app.services.phone_one_tap_service import (
    PhoneOneTapError,
    exchange_phone_one_tap,
    purge_expired_phone_one_tap_exchanges,
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
                select(PhoneOneTapExchange).where(PhoneOneTapExchange.request_id == request_id)
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
    monkeypatch.setattr(settings, "auth_phone_one_tap_ip_limit", 1000)
    monkeypatch.setattr(settings, "auth_phone_one_tap_device_limit", 1000)
    monkeypatch.setattr(settings, "auth_phone_one_tap_request_limit", 1000)
    monkeypatch.setattr(settings, "auth_phone_one_tap_token_limit", 1000)
    with SessionLocal() as db:
        db.execute(
            delete(AuthRateLimitBucket).where(AuthRateLimitBucket.scope.like("phone_one_tap_%"))
        )
        db.commit()
    return settings


def _payload(token: str, request_id=None) -> dict[str, object]:
    return {
        "login_token": token,
        "request_id": str(request_id or uuid4()),
        "device_id": "physical-test-device",
        "client_platform": "android",
        "device_name": "AUTH-02B test",
    }


def _seed_phone_user(phone: str, *, disabled: bool = False) -> User:
    with SessionLocal() as db:
        created = create_user_for_verified_identity(
            db,
            provider=AuthProvider.PHONE,
            subject=phone,
            verified_at=datetime.now(UTC),
        )
        user = db.get(User, created.user_id)
        assert user is not None
        if disabled:
            user.auth_disabled_at = datetime.now(UTC)
        db.commit()
        return user


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("13900001234", "+8613900001234"),
        ("+8613900001234", None),
        ("139****1234", None),
        (" 13900001234", None),
        ("1390000123a", None),
        ("1390000123", None),
        ("8613900001234", None),
    ],
)
def test_aliyun_national_mobile_normalization(raw, expected):
    if expected is None:
        with pytest.raises(PhoneOneTapProviderError):
            normalize_aliyun_mainland_mobile(raw)
    else:
        assert normalize_aliyun_mainland_mobile(raw) == expected


@pytest.mark.asyncio
async def test_production_default_provider_is_fail_closed(client, monkeypatch):
    settings = _settings(monkeypatch)
    monkeypatch.setattr(settings, "auth_phone_one_tap_fingerprint_secret", "")
    response = await client.post(
        "/v1/auth/phone/one-tap", json=_payload("production-disabled-token")
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "AUTH_PHONE_ONE_TAP_UNAVAILABLE"


@pytest.mark.asyncio
async def test_existing_phone_identity_is_resolved_without_new_user(client, monkeypatch):
    _settings(monkeypatch)
    existing = _seed_phone_user("+8613900001240")
    provider = FakePhoneOneTapProvider(
        {
            "existing-token": VerifiedPhoneResult(
                canonical_phone_subject=existing.phone,
                verified_at=datetime.now(UTC),
            )
        }
    )
    monkeypatch.setattr(phone_one_tap_service, "get_phone_one_tap_provider", lambda: provider)
    response = await client.post("/v1/auth/phone/one-tap", json=_payload("existing-token"))
    assert response.status_code == 200
    assert response.json()["user_id"] == str(existing.id)


@pytest.mark.asyncio
async def test_legacy_user_phone_projection_is_not_login_authority(client, monkeypatch):
    _settings(monkeypatch)
    with SessionLocal() as db:
        legacy = User(nickname="legacy-phone-projection", phone="+8613900001241")
        db.add(legacy)
        db.commit()
        legacy_id = legacy.id
    provider = FakePhoneOneTapProvider(
        {
            "projection-token": VerifiedPhoneResult(
                canonical_phone_subject="+8613900001241",
                verified_at=datetime.now(UTC),
            )
        }
    )
    monkeypatch.setattr(phone_one_tap_service, "get_phone_one_tap_provider", lambda: provider)
    response = await client.post("/v1/auth/phone/one-tap", json=_payload("projection-token"))
    assert response.status_code == 409
    assert response.json()["detail"] == "AUTH_IDENTITY_CONFLICT"
    with SessionLocal() as db:
        assert db.scalar(select(AuthSession).where(AuthSession.user_id == legacy_id)) is None


@pytest.mark.asyncio
async def test_auth_disabled_phone_terminalizes_provider_token(client, monkeypatch):
    _settings(monkeypatch)
    disabled = _seed_phone_user("+8613900001242", disabled=True)
    provider = FakePhoneOneTapProvider(
        {
            "disabled-token": VerifiedPhoneResult(
                canonical_phone_subject=disabled.phone,
                verified_at=datetime.now(UTC),
            )
        }
    )
    monkeypatch.setattr(phone_one_tap_service, "get_phone_one_tap_provider", lambda: provider)
    request_id = uuid4()
    response = await client.post(
        "/v1/auth/phone/one-tap", json=_payload("disabled-token", request_id)
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "AUTH_ACCOUNT_UNAVAILABLE"
    retry = await client.post("/v1/auth/phone/one-tap", json=_payload("disabled-token", request_id))
    assert retry.status_code == 401
    assert retry.json()["detail"] == "AUTH_ACCOUNT_UNAVAILABLE"
    assert provider.calls == ["disabled-token"]


@pytest.mark.asyncio
async def test_active_account_deletion_returns_continuation_session(client, monkeypatch):
    _settings(monkeypatch)
    deleting = _seed_phone_user("+8613900001243")
    with SessionLocal() as db:
        db.add(
            AccountDeletionOperation(
                user_id=deleting.id,
                request_id=uuid4(),
                data_deletion_request_id=uuid4(),
            )
        )
        db.commit()
    provider = FakePhoneOneTapProvider(
        {
            "deletion-token": VerifiedPhoneResult(
                canonical_phone_subject=deleting.phone,
                verified_at=datetime.now(UTC),
            )
        }
    )
    monkeypatch.setattr(phone_one_tap_service, "get_phone_one_tap_provider", lambda: provider)
    response = await client.post("/v1/auth/phone/one-tap", json=_payload("deletion-token"))
    assert response.status_code == 200
    assert response.json()["account_deletion_in_progress"] is True


@pytest.mark.asyncio
async def test_phone_one_tap_creates_phone_identity_and_recovers_response_loss(client, monkeypatch):
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
            select(PhoneOneTapExchange).where(PhoneOneTapExchange.request_id == request_id)
        )
        assert identity is not None
        assert exchange is not None
        assert exchange.state == PhoneOneTapExchangeState.COMPLETED
        assert exchange.recovery_state == PhoneOneTapRecoveryState.OPEN
        assert str(exchange.session_id) == first["session_id"]

    retry = await client.post("/v1/auth/phone/one-tap", json=_payload("token-a", request_id))
    assert retry.status_code == 200
    assert retry.json()["session_id"] != first["session_id"]
    assert provider.calls == ["token-a"]

    replay = await client.post("/v1/auth/phone/one-tap", json=_payload("token-a", request_id))
    assert replay.status_code == 409
    assert replay.json()["detail"] == "AUTH_PHONE_ONE_TAP_TOKEN_REPLAYED"

    with SessionLocal() as db:
        sessions = list(
            db.scalars(select(AuthSession).where(AuthSession.user_id == identity.user_id))
        )
        assert len(sessions) == 2
        assert sum(session.revoked_at is not None for session in sessions) == 1
        exchange = db.scalar(
            select(PhoneOneTapExchange).where(PhoneOneTapExchange.request_id == request_id)
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

    different_request = await client.post("/v1/auth/phone/one-tap", json=_payload("token-c"))
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

    response = await client.post("/v1/auth/phone/one-tap", json=_payload("expired", request_id))
    assert response.status_code == 401
    assert response.json()["detail"] == "AUTH_PHONE_ONE_TAP_TOKEN_EXPIRED"

    retry = await client.post("/v1/auth/phone/one-tap", json=_payload("expired", request_id))
    assert retry.status_code == 401
    assert retry.json()["detail"] == "AUTH_PHONE_ONE_TAP_TOKEN_EXPIRED"
    assert provider.calls == ["expired"]


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["phone", "mobile", "masked_phone"])
async def test_phone_fields_are_not_accepted_auth_authority(client, monkeypatch, field):
    _settings(monkeypatch)
    payload = _payload("token-a")
    payload[field] = "+8613900001234"
    response = await client.post("/v1/auth/phone/one-tap", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_phone_one_tap_purge_is_bounded_and_preserves_account_authority(client, monkeypatch):
    _settings(monkeypatch)
    provider = FakePhoneOneTapProvider(
        {
            "purge-token": VerifiedPhoneResult(
                canonical_phone_subject="+8613900001236",
                verified_at=datetime.now(UTC),
            )
        }
    )
    monkeypatch.setattr(phone_one_tap_service, "get_phone_one_tap_provider", lambda: provider)
    request_id = uuid4()
    response = await client.post("/v1/auth/phone/one-tap", json=_payload("purge-token", request_id))
    assert response.status_code == 200

    with SessionLocal() as db:
        row = db.scalar(
            select(PhoneOneTapExchange).where(PhoneOneTapExchange.request_id == request_id)
        )
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

        assert purge_expired_phone_one_tap_exchanges(db, batch_size=1) == 1
        assert (
            db.scalar(
                select(AuthIdentity).where(
                    AuthIdentity.user_id == row.resolved_user_id,
                    AuthIdentity.provider == AuthProvider.PHONE,
                )
            )
            is not None
        )
        assert db.get(AuthSession, UUID(response.json()["session_id"])) is not None
        assert (
            db.scalar(
                select(PhoneOneTapExchange).where(PhoneOneTapExchange.request_id == request_id)
            )
            is None
        )


@pytest.mark.asyncio
async def test_completed_recovery_deadline_expired_is_replayed_without_replacement(
    client, monkeypatch
):
    _settings(monkeypatch)
    request_id = uuid4()
    provider = FakePhoneOneTapProvider(
        {
            "deadline-token": VerifiedPhoneResult(
                canonical_phone_subject="+8613900001244", verified_at=datetime.now(UTC)
            )
        }
    )
    monkeypatch.setattr(phone_one_tap_service, "get_phone_one_tap_provider", lambda: provider)
    first = await client.post("/v1/auth/phone/one-tap", json=_payload("deadline-token", request_id))
    assert first.status_code == 200
    with SessionLocal() as db:
        row = db.scalar(
            select(PhoneOneTapExchange).where(PhoneOneTapExchange.request_id == request_id)
        )
        assert row is not None
        row.recovery_deadline = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    retry = await client.post("/v1/auth/phone/one-tap", json=_payload("deadline-token", request_id))
    assert retry.status_code == 409
    assert retry.json()["detail"] == "AUTH_PHONE_ONE_TAP_TOKEN_REPLAYED"
    assert provider.calls == ["deadline-token"]
    with SessionLocal() as db:
        row = db.scalar(
            select(PhoneOneTapExchange).where(PhoneOneTapExchange.request_id == request_id)
        )
        assert row is not None and row.replacement_session_id is None and row.recovery_count == 0


@pytest.mark.asyncio
async def test_completed_recovery_rotated_session_is_replayed_without_replacement(
    client, monkeypatch
):
    _settings(monkeypatch)
    request_id = uuid4()
    provider = FakePhoneOneTapProvider(
        {
            "rotated-token": VerifiedPhoneResult(
                canonical_phone_subject="+8613900001245", verified_at=datetime.now(UTC)
            )
        }
    )
    monkeypatch.setattr(phone_one_tap_service, "get_phone_one_tap_provider", lambda: provider)
    first = await client.post("/v1/auth/phone/one-tap", json=_payload("rotated-token", request_id))
    assert first.status_code == 200
    with SessionLocal() as db:
        session = db.get(AuthSession, UUID(first.json()["session_id"]))
        assert session is not None
        session.rotation_revision = 1
        db.commit()
    retry = await client.post("/v1/auth/phone/one-tap", json=_payload("rotated-token", request_id))
    assert retry.status_code == 409
    assert retry.json()["detail"] == "AUTH_PHONE_ONE_TAP_TOKEN_REPLAYED"
    assert provider.calls == ["rotated-token"]
    with SessionLocal() as db:
        row = db.scalar(
            select(PhoneOneTapExchange).where(PhoneOneTapExchange.request_id == request_id)
        )
        assert row is not None and row.replacement_session_id is None and row.recovery_count == 0


@pytest.mark.asyncio
async def test_raw_phone_token_never_persists_or_leaks_to_logs_or_error_body(
    client, monkeypatch, caplog
):
    _settings(monkeypatch)
    caplog.set_level("INFO")
    raw_token = "SUPER-SECRET-PHONE-TOKEN-raw-leak-regression"
    request_id = uuid4()
    provider = FakePhoneOneTapProvider({raw_token: PhoneOneTapProviderError("TOKEN_INVALID")})
    monkeypatch.setattr(phone_one_tap_service, "get_phone_one_tap_provider", lambda: provider)
    response = await client.post("/v1/auth/phone/one-tap", json=_payload(raw_token, request_id))
    assert response.status_code == 401
    assert raw_token not in response.text and raw_token not in caplog.text
    with SessionLocal() as db:
        row = db.scalar(
            select(PhoneOneTapExchange).where(PhoneOneTapExchange.request_id == request_id)
        )
        assert row is not None and raw_token not in repr(row.__dict__)


@pytest.mark.asyncio
async def test_phone_one_tap_rate_limit_returns_retry_after(client, monkeypatch):
    settings = _settings(monkeypatch)
    monkeypatch.setattr(settings, "auth_phone_one_tap_ip_limit", 1)
    provider = FakePhoneOneTapProvider(
        {
            "rate-token-a": VerifiedPhoneResult(
                canonical_phone_subject="+8613900001246", verified_at=datetime.now(UTC)
            ),
            "rate-token-b": VerifiedPhoneResult(
                canonical_phone_subject="+8613900001247", verified_at=datetime.now(UTC)
            ),
        }
    )
    monkeypatch.setattr(phone_one_tap_service, "get_phone_one_tap_provider", lambda: provider)
    first = await client.post("/v1/auth/phone/one-tap", json=_payload("rate-token-a"))
    assert first.status_code == 200
    second = await client.post("/v1/auth/phone/one-tap", json=_payload("rate-token-b"))
    assert second.status_code == 429
    assert second.json()["detail"] == "AUTH_RATE_LIMITED"
    assert int(second.headers["Retry-After"]) >= 1
    assert provider.calls == ["rate-token-a"]


def test_phone_one_tap_finalization_rolls_back_all_account_authority(monkeypatch):
    settings = _settings(monkeypatch)
    monkeypatch.setattr(settings, "auth_rate_limit_enabled", False)
    raw_token = "SUPER-SECRET-PHONE-TOKEN-finalization-failure"
    request_id = uuid4()
    provider = FakePhoneOneTapProvider(
        {
            raw_token: VerifiedPhoneResult(
                canonical_phone_subject="+8613900001248", verified_at=datetime.now(UTC)
            )
        }
    )
    real_flush = GuardedSession.flush

    def fail_finalization_flush(session, *args, **kwargs):
        if provider.calls:
            raise RuntimeError("injected finalization failure")
        return real_flush(session, *args, **kwargs)

    monkeypatch.setattr(GuardedSession, "flush", fail_finalization_flush)
    with SessionLocal() as db:
        with pytest.raises(RuntimeError, match="injected finalization failure"):
            exchange_phone_one_tap(
                db,
                login_token=raw_token,
                request_id=request_id,
                device_id="finalization-failure-device",
                client_platform="test",
                device_name="test",
                client_ip="198.51.100.250",
                provider=provider,
                settings=settings,
            )
    monkeypatch.setattr(GuardedSession, "flush", real_flush)
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.phone == "+8613900001248")) is None
        assert (
            db.scalar(
                select(AuthIdentity).where(
                    AuthIdentity.provider == AuthProvider.PHONE,
                    AuthIdentity.subject == "+8613900001248",
                )
            )
            is None
        )
        assert (
            db.scalar(select(UserEntitlement).join(User).where(User.phone == "+8613900001248"))
            is None
        )
        assert (
            db.scalar(
                select(AuthSession).where(AuthSession.device_id == "finalization-failure-device")
            )
            is None
        )
        row = db.scalar(
            select(PhoneOneTapExchange).where(PhoneOneTapExchange.request_id == request_id)
        )
        assert row is not None and row.state == PhoneOneTapExchangeState.RESERVED
    retry_provider = FakePhoneOneTapProvider(
        {
            raw_token: VerifiedPhoneResult(
                canonical_phone_subject="+8613900001248", verified_at=datetime.now(UTC)
            )
        }
    )
    with SessionLocal() as db:
        with pytest.raises(PhoneOneTapError) as exc_info:
            exchange_phone_one_tap(
                db,
                login_token=raw_token,
                request_id=request_id,
                device_id="finalization-failure-device",
                client_platform="test",
                device_name="test",
                client_ip="198.51.100.250",
                provider=retry_provider,
                settings=settings,
            )
        assert exc_info.value.code == "AUTH_PHONE_ONE_TAP_TIMEOUT"
    assert retry_provider.calls == []


@pytest.mark.asyncio
async def test_phone_one_tap_endpoint_fences_old_owner_push_binding(client, monkeypatch):
    _settings(monkeypatch)
    owner_a = _seed_phone_user("+8613900001249")
    owner_b = _seed_phone_user("+8613900001250")
    client_uuid = f"endpoint-phone-fence-{uuid4()}"
    with SessionLocal() as db:
        issued = issue_authenticated_session(
            db,
            user_id=owner_a.id,
            device_id=client_uuid,
            client_platform="android",
            device_name="owner-a",
        )
    push = await client.put(
        "/v1/notifications/device",
        headers={"Authorization": f"Bearer {issued.tokens.access_token}"},
        json={
            "client_uuid": client_uuid,
            "platform": "ANDROID",
            "provider": "TEST",
            "push_token": "endpoint-push-token-123456",
        },
    )
    assert push.status_code == 200, push.text
    provider = FakePhoneOneTapProvider(
        {
            "endpoint-owner-b-token": VerifiedPhoneResult(
                canonical_phone_subject=owner_b.phone, verified_at=datetime.now(UTC)
            )
        }
    )
    monkeypatch.setattr(phone_one_tap_service, "get_phone_one_tap_provider", lambda: provider)
    payload = _payload("endpoint-owner-b-token")
    payload["device_id"] = client_uuid
    response = await client.post("/v1/auth/phone/one-tap", json=payload)
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        old_session = db.get(AuthSession, issued.tokens.session_id)
        old_device = db.scalar(
            select(Device).where(Device.user_id == owner_a.id, Device.client_uuid == client_uuid)
        )
        assert old_session is not None and old_session.revoked_at is not None
        assert old_session.revoke_reason == "INSTALLATION_SUPERSEDED"
        assert old_device is not None and old_device.push_enabled is False
