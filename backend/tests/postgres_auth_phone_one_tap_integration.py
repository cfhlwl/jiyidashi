"""Real PostgreSQL AUTH-02B phone one-tap authority gate."""

from __future__ import annotations

import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select

from app.abuse_models import ConcurrencyGuard, WorkPermit
from app.auth_models import (
    AuthIdentity,
    AuthProvider,
    AuthSession,
    PhoneOneTapExchange,
    PhoneOneTapExchangeState,
)
from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.models import Device, User
from app.notification_schemas import DevicePushRegistrationRequest
from app.services.auth_session_service import create_public_session
from app.services.concurrency_guard import (
    ConcurrencyRejected,
    claim_phone_one_tap_permit,
    release_permit,
)
from app.services.notification_service import (
    fence_other_owner_push_bindings_for_client_uuid,
    register_device_push,
)
from app.services.phone_one_tap_provider import VerifiedPhoneResult
from app.services.phone_one_tap_service import (
    PhoneOneTapError,
    _fingerprint,
    exchange_phone_one_tap,
)

DATABASE_URL = os.environ["DATABASE_URL"]
settings = get_settings()
settings.auth_phone_one_tap_fingerprint_secret = "auth-02b-postgres-test-key"
settings.auth_phone_one_tap_global_concurrency = 8
settings.auth_phone_one_tap_permit_lease_seconds = 30


class FakeProvider:
    available = True

    def __init__(self, outcomes: dict[str, VerifiedPhoneResult]):
        self.outcomes = outcomes
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def exchange_login_token(self, *, login_token: str, request_id: UUID):
        with self._lock:
            self.calls.append(login_token)
        with SessionLocal() as db:
            assert db.in_transaction() is False
        return self.outcomes[login_token]


def _require_real_postgresql() -> None:
    if not DATABASE_URL.startswith("postgresql"):
        raise RuntimeError("AUTH-02B race gate requires PostgreSQL DATABASE_URL")
    if engine.dialect.name != "postgresql":
        raise RuntimeError(f"expected PostgreSQL engine, got {engine.dialect.name}")
    with SessionLocal() as db:
        if db.get_bind().dialect.name != "postgresql":
            raise RuntimeError("SessionLocal is not bound to PostgreSQL")


def _exchange(
    *,
    provider: FakeProvider,
    token: str,
    request_id: UUID,
    device_id: str,
):
    with SessionLocal() as db:
        try:
            result = exchange_phone_one_tap(
                db,
                login_token=token,
                request_id=request_id,
                device_id=device_id,
                client_platform="postgres-integration",
                device_name="AUTH-02B PostgreSQL",
                client_ip=f"198.51.100.{uuid4().int % 200 + 1}",
                provider=provider,
                settings=settings,
            )
            return ("ok", result)
        except PhoneOneTapError as exc:
            return (exc.code, None)


def _cleanup(
    *,
    request_ids: set[UUID],
    user_ids: set[UUID],
    client_uuids: set[str],
) -> None:
    with SessionLocal() as db:
        if request_ids:
            db.execute(
                delete(PhoneOneTapExchange).where(
                    PhoneOneTapExchange.request_id.in_(request_ids)
                )
            )
        if client_uuids:
            db.execute(delete(Device).where(Device.client_uuid.in_(client_uuids)))
        if user_ids:
            db.execute(delete(AuthSession).where(AuthSession.user_id.in_(user_ids)))
            db.execute(delete(AuthIdentity).where(AuthIdentity.user_id.in_(user_ids)))
            db.execute(delete(User).where(User.id.in_(user_ids)))
        db.execute(delete(WorkPermit).where(WorkPermit.service_class == "PHONE_ONE_TAP"))
        db.execute(
            delete(ConcurrencyGuard).where(
                ConcurrencyGuard.scope_key == "global:PHONE_ONE_TAP"
            )
        )
        db.commit()


def _prove_reservation_race(request_ids: set[UUID], user_ids: set[UUID]) -> None:
    request_id = uuid4()
    request_ids.add(request_id)
    provider = FakeProvider(
        {
            "race-token": VerifiedPhoneResult(
                canonical_phone_subject="+8613900001201",
                verified_at=datetime.now(UTC),
            )
        }
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: _exchange(
                    provider=provider,
                    token="race-token",
                    request_id=request_id,
                    device_id=f"pg-race-{uuid4()}",
                ),
                range(2),
            )
        )
    assert sorted(result[0] for result in results) == [
        "AUTH_PHONE_ONE_TAP_TIMEOUT",
        "ok",
    ]
    assert provider.calls == ["race-token"]
    with SessionLocal() as db:
        row = db.scalar(
            select(PhoneOneTapExchange).where(
                PhoneOneTapExchange.request_id == request_id
            )
        )
        assert row is not None and row.state == PhoneOneTapExchangeState.COMPLETED
        user_ids.add(row.resolved_user_id)


def _prove_replay_conflict_and_identity_race(
    request_ids: set[UUID], user_ids: set[UUID]
) -> None:
    provider = FakeProvider(
        {
            "identity-a": VerifiedPhoneResult(
                canonical_phone_subject="+8613900001202",
                verified_at=datetime.now(UTC),
            ),
            "identity-b": VerifiedPhoneResult(
                canonical_phone_subject="+8613900001202",
                verified_at=datetime.now(UTC),
            ),
            "race-a": VerifiedPhoneResult(
                canonical_phone_subject="+8613900001205",
                verified_at=datetime.now(UTC),
            ),
            "race-b": VerifiedPhoneResult(
                canonical_phone_subject="+8613900001205",
                verified_at=datetime.now(UTC),
            ),
        }
    )
    first_request = uuid4()
    request_ids.add(first_request)
    first = _exchange(
        provider=provider,
        token="identity-a",
        request_id=first_request,
        device_id=f"pg-identity-a-{uuid4()}",
    )
    assert first[0] == "ok", first
    replay = _exchange(
        provider=provider,
        token="identity-a",
        request_id=uuid4(),
        device_id=f"pg-replay-{uuid4()}",
    )
    assert replay[0] == "AUTH_PHONE_ONE_TAP_TOKEN_REPLAYED", replay
    conflict = _exchange(
        provider=provider,
        token="identity-b",
        request_id=first_request,
        device_id=f"pg-conflict-{uuid4()}",
    )
    assert conflict[0] == "AUTH_PHONE_ONE_TAP_CONFLICT", conflict

    race_requests = {uuid4(), uuid4()}
    request_ids.update(race_requests)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda item: _exchange(
                    provider=provider,
                    token=item[0],
                    request_id=item[1],
                    device_id=f"pg-phone-race-{uuid4()}",
                ),
                zip(("race-a", "race-b"), race_requests, strict=True),
            )
        )
    assert all(result[0] == "ok" for result in results), results
    with SessionLocal() as db:
        identity_count = db.scalar(
            select(func.count(AuthIdentity.id)).where(
                AuthIdentity.provider == AuthProvider.PHONE,
                AuthIdentity.subject == "+8613900001205",
            )
        )
        identity = db.scalar(
            select(AuthIdentity).where(
                AuthIdentity.provider == AuthProvider.PHONE,
                AuthIdentity.subject == "+8613900001205",
            )
        )
        assert identity_count == 1
        assert identity is not None
        user_ids.add(identity.user_id)
        owner = db.get(User, identity.user_id)
        assert owner is not None and owner.phone == "+8613900001205"


def _prove_recovery_race(request_ids: set[UUID], user_ids: set[UUID]) -> None:
    provider = FakeProvider(
        {
            "recovery-token": VerifiedPhoneResult(
                canonical_phone_subject="+8613900001203",
                verified_at=datetime.now(UTC),
            )
        }
    )
    request_id = uuid4()
    request_ids.add(request_id)
    first = _exchange(
        provider=provider,
        token="recovery-token",
        request_id=request_id,
        device_id=f"pg-recovery-{uuid4()}",
    )
    assert first[0] == "ok", first
    user_ids.add(first[1].tokens.user_id)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: _exchange(
                    provider=provider,
                    token="recovery-token",
                    request_id=request_id,
                    device_id="ignored-after-completion",
                ),
                range(2),
            )
        )
    assert sorted(result[0] for result in results) == [
        "AUTH_PHONE_ONE_TAP_TOKEN_REPLAYED",
        "ok",
    ]
    with SessionLocal() as db:
        row = db.scalar(
            select(PhoneOneTapExchange).where(
                PhoneOneTapExchange.request_id == request_id
            )
        )
        assert row is not None and row.recovery_count == 1
        assert row.replacement_session_id is not None
        assert len(provider.calls) == 1


def _prove_recovery_vs_normal_login(
    request_ids: set[UUID], user_ids: set[UUID]
) -> None:
    device_id = f"pg-recovery-installation-{uuid4()}"
    provider = FakeProvider({
        "recovery-installation-token": VerifiedPhoneResult(
            canonical_phone_subject="+861390001206", verified_at=datetime.now(UTC)
        )
    })
    request_id = uuid4()
    request_ids.add(request_id)
    first = _exchange(
        provider=provider,
        token="recovery-installation-token",
        request_id=request_id,
        device_id=device_id,
    )
    assert first[0] == "ok", first
    user_ids.add(first[1].tokens.user_id)
    normal_user_id = uuid4()
    user_ids.add(normal_user_id)
    with SessionLocal() as db:
        db.add(User(id=normal_user_id, nickname="normal-login-race"))
        db.commit()

    barrier = threading.Barrier(2)
    results: list[tuple[str, str, str | None]] = []

    def recover() -> None:
        with SessionLocal() as db:
            try:
                barrier.wait(timeout=5)
                recovered = exchange_phone_one_tap(
                    db,
                    login_token="recovery-installation-token",
                    request_id=request_id,
                    device_id="ignored-after-completion",
                    client_platform="postgres-integration",
                    device_name="AUTH-02B recovery race",
                    client_ip="198.51.100.241",
                    provider=provider,
                    settings=settings,
                )
                results.append(("recovery", "ok", str(recovered.tokens.session_id)))
            except PhoneOneTapError as exc:
                results.append(("recovery", exc.code, None))
            except Exception as exc:  # pragma: no cover - failure evidence
                results.append(("recovery", "EXCEPTION", repr(exc)))

    def normal_login() -> None:
        with SessionLocal() as db:
            try:
                barrier.wait(timeout=5)
                issued = create_public_session(
                    db,
                    user_id=normal_user_id,
                    device_id=device_id,
                    client_platform="postgres-integration",
                    device_name="AUTH-02B normal race",
                )
                results.append(("normal", "ok", str(issued.session_id)))
            except Exception as exc:  # pragma: no cover - failure evidence
                results.append(("normal", "EXCEPTION", repr(exc)))

    threads = [threading.Thread(target=recover), threading.Thread(target=normal_login)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive(), "recovery/normal installation race deadlocked"
    assert sorted((role, status) for role, status, _ in results) in (
        [("normal", "ok"), ("recovery", "AUTH_PHONE_ONE_TAP_TOKEN_REPLAYED")],
        [("normal", "ok"), ("recovery", "ok")],
    ), results
    with SessionLocal() as db:
        active = list(db.scalars(select(AuthSession).where(
            AuthSession.device_id == device_id,
            AuthSession.revoked_at.is_(None),
        )))
        assert len(active) == 1
        row = db.scalar(select(PhoneOneTapExchange).where(
            PhoneOneTapExchange.request_id == request_id
        ))
        assert row is not None and row.state == PhoneOneTapExchangeState.COMPLETED
        assert row.recovery_count <= 1


def _prove_stale_reserved(request_ids: set[UUID]) -> None:
    token = "stale-token"
    request_id = uuid4()
    request_ids.add(request_id)
    now = datetime.now(UTC)
    with SessionLocal() as db:
        db.add(
            PhoneOneTapExchange(
                request_id=request_id,
                token_fingerprint=_fingerprint(token, settings),
                fingerprint_key_version=settings.auth_phone_one_tap_fingerprint_key_version,
                state=PhoneOneTapExchangeState.RESERVED,
                device_id=f"pg-stale-{uuid4()}",
                lease_expires_at=now - timedelta(seconds=1),
                expires_at=now + timedelta(hours=1),
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
    provider = FakeProvider(
        {
            token: VerifiedPhoneResult(
                canonical_phone_subject="+8613900001204",
                verified_at=now,
            )
        }
    )
    result = _exchange(
        provider=provider,
        token=token,
        request_id=request_id,
        device_id=f"pg-stale-{uuid4()}",
    )
    assert result[0] == "AUTH_PHONE_ONE_TAP_TIMEOUT", result
    assert provider.calls == []
    with SessionLocal() as db:
        row = db.scalar(
            select(PhoneOneTapExchange).where(
                PhoneOneTapExchange.request_id == request_id
            )
        )
        assert row is not None and row.state == PhoneOneTapExchangeState.PROVIDER_UNKNOWN


def _prove_permit_race() -> None:
    with SessionLocal() as db:
        db.execute(delete(WorkPermit).where(WorkPermit.service_class == "PHONE_ONE_TAP"))
        db.execute(
            delete(ConcurrencyGuard).where(
                ConcurrencyGuard.scope_key == "global:PHONE_ONE_TAP"
            )
        )
        db.commit()
    original_limit = settings.auth_phone_one_tap_global_concurrency
    settings.auth_phone_one_tap_global_concurrency = 1
    try:
        def claim():
            try:
                permit = claim_phone_one_tap_permit(engine, settings=settings)
                return (True, permit)
            except ConcurrencyRejected:
                return (False, None)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: claim(), range(2)))
        assert sorted(result[0] for result in results) == [False, True]
        winner = next(result[1] for result in results if result[0])
        release_permit(engine, permit=winner, settings=settings)
    finally:
        settings.auth_phone_one_tap_global_concurrency = original_limit


def _prove_installation_and_push_fence(
    request_ids: set[UUID], user_ids: set[UUID], client_uuids: set[str]
) -> None:
    owner_a, owner_b = uuid4(), uuid4()
    client_uuid = f"pg-phone-installation-{uuid4()}"
    user_ids.update({owner_a, owner_b})
    client_uuids.add(client_uuid)
    with SessionLocal() as db:
        db.add(User(id=owner_a, nickname="phone-owner-a"))
        db.add(User(id=owner_b, nickname="phone-owner-b"))
        db.commit()
        session_a = create_public_session(
            db,
            user_id=owner_a,
            device_id=client_uuid,
            client_platform="integration",
            device_name="phone-a",
        )
        register_device_push(
            db,
            user_id=owner_a,
            payload=DevicePushRegistrationRequest(
                client_uuid=client_uuid,
                platform="ANDROID",
                provider="TEST",
                push_token=f"phone-push-{uuid4()}",
            ),
            session_id=session_a.session_id,
        )
    provider = FakeProvider(
        {
            "owner-b-token": VerifiedPhoneResult(
                canonical_phone_subject=f"+86139{uuid4().int % 100000000:08d}",
                verified_at=datetime.now(UTC),
            )
        }
    )
    request_id = uuid4()
    request_ids.add(request_id)
    result = _exchange(
        provider=provider,
        token="owner-b-token",
        request_id=request_id,
        device_id=client_uuid,
    )
    assert result[0] == "ok", result
    owner_b = result[1].tokens.user_id
    user_ids.add(owner_b)
    with SessionLocal() as db:
        fence_other_owner_push_bindings_for_client_uuid(
            db,
            user_id=owner_b,
            client_uuid=client_uuid,
        )
        old_session = db.get(AuthSession, session_a.session_id)
        old_device = db.scalar(
            select(Device).where(
                Device.user_id == owner_a,
                Device.client_uuid == client_uuid,
            )
        )
        assert old_session is not None
        assert old_session.revoked_at is not None
        assert old_session.revoke_reason == "INSTALLATION_SUPERSEDED"
        assert old_device is not None and old_device.push_enabled is False


def _migration_roundtrip() -> None:
    root = Path(__file__).resolve().parents[1]
    for command in (
        ["alembic", "downgrade", "0037_auth_identity_foundation"],
        ["alembic", "upgrade", "head"],
        ["alembic", "check"],
    ):
        subprocess.run(command, cwd=root, check=True)


def main() -> None:
    _require_real_postgresql()
    request_ids: set[UUID] = set()
    user_ids: set[UUID] = set()
    client_uuids: set[str] = set()
    try:
        _prove_reservation_race(request_ids, user_ids)
        _prove_replay_conflict_and_identity_race(request_ids, user_ids)
        _prove_recovery_race(request_ids, user_ids)
        _prove_recovery_vs_normal_login(request_ids, user_ids)
        _prove_stale_reserved(request_ids)
        _prove_permit_race()
        _prove_installation_and_push_fence(request_ids, user_ids, client_uuids)
        _migration_roundtrip()
    finally:
        _cleanup(
            request_ids=request_ids,
            user_ids=user_ids,
            client_uuids=client_uuids,
        )
    print("PostgreSQL AUTH-02B phone one-tap authority PASS")


if __name__ == "__main__":
    main()
