"""Real PostgreSQL AUTH-005 identity link/unlink authority gate."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from threading import Barrier, Event, Thread
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select

from app.auth_models import (
    AuthIdentity,
    AuthIdentityOperation,
    AuthIdentityOperationState,
    AuthProvider,
    AuthSession,
)
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.entitlement_models import UserEntitlement
from app.models import User
from app.services.auth_identity_link_provider import (
    FakeAuthIdentityLinkProvider,
    VerifiedIdentityProof,
)
from app.services.auth_identity_operation_service import link_identity, unlink_identity
from app.services.auth_identity_service import (
    AuthIdentityError,
    create_user_for_verified_identity,
    link_verified_identity,
)
from app.services.auth_session_service import create_public_session

DATABASE_URL = os.environ["DATABASE_URL"]
if not DATABASE_URL.startswith("postgresql"):
    raise SystemExit("AUTH-005 integration requires PostgreSQL")

_THREAD_TIMEOUT = 30


def _seed_user(label: str):
    with SessionLocal() as db:
        created = create_user_for_verified_identity(
            db,
            provider=AuthProvider.EMAIL_PASSWORD,
            subject=f"auth005-{label}-{uuid4().hex}@example.com",
            secret_hash="integration-only",
            verified_at=datetime.now(UTC),
        )
        db.commit()
        pair = create_public_session(
            db,
            user_id=created.user_id,
            device_id=f"auth005-{label}-{uuid4().hex}",
        )
        return created.user_id, pair.session_id


def _cleanup(user_ids: list[UUID]) -> None:
    with SessionLocal() as db:
        db.execute(
            delete(AuthIdentityOperation).where(
                AuthIdentityOperation.user_id.in_(user_ids)
            )
        )
        db.execute(delete(AuthSession).where(AuthSession.user_id.in_(user_ids)))
        db.execute(delete(AuthIdentity).where(AuthIdentity.user_id.in_(user_ids)))
        db.execute(delete(UserEntitlement).where(UserEntitlement.user_id.in_(user_ids)))
        db.execute(delete(User).where(User.id.in_(user_ids)))
        db.commit()


class _BarrierProvider(FakeAuthIdentityLinkProvider):
    def __init__(self, barrier: Barrier, proof: VerifiedIdentityProof) -> None:
        super().__init__(
            link_results={"opaque-link-token": proof},
            reauth_results={"opaque-reauth": proof.reauthenticated_at},
        )
        self.barrier = barrier

    def verify_link_credentials(self, **kwargs):
        self.barrier.wait(timeout=_THREAD_TIMEOUT)
        return super().verify_link_credentials(**kwargs)


class _DelayedProvider(FakeAuthIdentityLinkProvider):
    def __init__(self, started: Event, release: Event, proof: VerifiedIdentityProof) -> None:
        super().__init__(
            link_results={"opaque-link-token": proof},
            reauth_results={"opaque-reauth": proof.reauthenticated_at},
        )
        self.started = started
        self.release = release

    def verify_link_credentials(self, **kwargs):
        self.started.set()
        assert self.release.wait(timeout=_THREAD_TIMEOUT)
        return super().verify_link_credentials(**kwargs)


class _BarrierReauthProvider(FakeAuthIdentityLinkProvider):
    def __init__(self, barrier: Barrier, verified_at: datetime) -> None:
        super().__init__(reauth_results={"reauth": verified_at})
        self.barrier = barrier

    def verify_reauthentication(self, **kwargs):
        self.barrier.wait(timeout=_THREAD_TIMEOUT)
        return super().verify_reauthentication(**kwargs)


def _prove_cross_owner_unique_identity_race() -> None:
    users = [_seed_user("a"), _seed_user("b")]
    user_ids = [users[0][0], users[1][0]]
    shared_subject = f"unionid:auth005:{uuid4().hex[:20]}"
    barrier = Barrier(2)
    outcomes: list[tuple[str, str | None]] = []
    errors: list[BaseException] = []

    def link(index: int) -> None:
        user_id, session_id = users[index]
        proof = VerifiedIdentityProof(
            provider=AuthProvider.WECHAT,
            subject=shared_subject,
            verified_at=datetime.now(UTC),
            reauthenticated_at=datetime.now(UTC),
            user_id=user_id,
            session_id=session_id,
            provider_request_id=f"mock-provider-{index}",
        )
        provider = _BarrierProvider(barrier, proof)
        with SessionLocal() as db:
            try:
                result = link_identity(
                    db,
                    user_id=user_id,
                    session_id=session_id,
                    request_id=uuid4(),
                    credential="opaque-link-token",
                    reauth_credential="opaque-reauth",
                    provider=provider,
                )
                outcomes.append(("success", str(result.identity.id)))
            except AuthIdentityError as exc:
                outcomes.append(("rejected", exc.code))
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

    threads = [
        Thread(target=link, args=(0,), name="auth005-link-a"),
        Thread(target=link, args=(1,), name="auth005-link-b"),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=_THREAD_TIMEOUT)
        assert not thread.is_alive(), f"thread did not finish: {thread.name}"

    assert errors == [], [repr(error) for error in errors]
    assert sorted(outcome[0] for outcome in outcomes) == ["rejected", "success"]
    assert "AUTH_IDENTITY_CONFLICT" in [outcome[1] for outcome in outcomes]

    with SessionLocal() as db:
        identities = list(
            db.scalars(
                select(AuthIdentity).where(
                    AuthIdentity.provider == AuthProvider.WECHAT,
                    AuthIdentity.subject == shared_subject,
                )
            )
        )
        assert len(identities) == 1
        assert {row.user_id for row in identities}.issubset(set(user_ids))
        operations = list(
            db.scalars(
                select(AuthIdentityOperation).where(
                    AuthIdentityOperation.user_id.in_(user_ids)
                )
            )
        )
        assert {row.state for row in operations} == {
            AuthIdentityOperationState.REJECTED,
            AuthIdentityOperationState.COMPLETED,
        }
        assert db.scalar(select(func.count(User.id)).where(User.id.in_(user_ids))) == 2
        assert db.scalar(
            select(func.count(UserEntitlement.user_id)).where(
                UserEntitlement.user_id.in_(user_ids)
            )
        ) == 2
    _cleanup(user_ids)


def _prove_late_provider_result_cannot_complete_unknown_operation() -> None:
    user_id, session_id = _seed_user("late-provider")
    settings = get_settings()
    # A negative test-only timeout makes the recovery worker deterministic
    # without sleeping; production settings remain positive.
    settings.auth_identity_operation_reservation_timeout_seconds = -1
    subject = f"unionid:auth005-late:{uuid4().hex[:20]}"
    now = datetime.now(UTC)
    proof = VerifiedIdentityProof(
        provider=AuthProvider.WECHAT,
        subject=subject,
        verified_at=now,
        reauthenticated_at=now,
        user_id=user_id,
        session_id=session_id,
        provider_request_id="late-provider",
    )
    started = Event()
    release = Event()
    provider = _DelayedProvider(started, release, proof)
    request_id = uuid4()
    outcomes: list[str] = []
    errors: list[BaseException] = []

    def original_worker() -> None:
        with SessionLocal() as db:
            try:
                result = link_identity(
                    db,
                    user_id=user_id,
                    session_id=session_id,
                    request_id=request_id,
                    credential="opaque-link-token",
                    reauth_credential="opaque-reauth",
                    provider=provider,
                    settings=settings,
                )
                outcomes.append(f"original:success:{result.operation.value}")
            except AuthIdentityError as exc:
                outcomes.append(f"original:{exc.code}")
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

    def timeout_worker() -> None:
        assert started.wait(timeout=_THREAD_TIMEOUT)
        with SessionLocal() as db:
            try:
                result = link_identity(
                    db,
                    user_id=user_id,
                    session_id=session_id,
                    request_id=request_id,
                    credential="opaque-link-token",
                    reauth_credential="opaque-reauth",
                    provider=provider,
                    settings=settings,
                )
                outcomes.append(f"timeout:success:{result.operation.value}")
            except AuthIdentityError as exc:
                outcomes.append(f"timeout:{exc.code}")
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

    first = Thread(target=original_worker, name="auth005-late-provider")
    second = Thread(target=timeout_worker, name="auth005-timeout-recovery")
    first.start()
    assert started.wait(timeout=_THREAD_TIMEOUT)
    second.start()
    second.join(timeout=_THREAD_TIMEOUT)
    assert not second.is_alive(), "timeout worker did not finish"
    with SessionLocal() as db:
        state_before_release = db.scalar(
            select(AuthIdentityOperation.state).where(
                AuthIdentityOperation.request_id == request_id
            )
        )
    assert state_before_release == AuthIdentityOperationState.REJECTED, state_before_release
    release.set()
    first.join(timeout=_THREAD_TIMEOUT)
    assert not first.is_alive(), "original worker did not finish"
    assert provider.link_calls == 1
    assert errors == [], [repr(error) for error in errors]
    assert sorted(outcomes) == [
        "original:AUTH_IDENTITY_OPERATION_UNKNOWN",
        "timeout:AUTH_IDENTITY_OPERATION_UNKNOWN",
    ], outcomes

    with SessionLocal() as db:
        operation = db.scalar(
            select(AuthIdentityOperation).where(
                AuthIdentityOperation.request_id == request_id
            )
        )
        assert operation is not None
        assert operation.state == AuthIdentityOperationState.REJECTED
        assert operation.error_code == "AUTH_IDENTITY_OPERATION_UNKNOWN"
        assert db.scalar(
            select(AuthIdentity).where(
                AuthIdentity.user_id == user_id,
                AuthIdentity.provider == AuthProvider.WECHAT,
                AuthIdentity.subject == subject,
            )
        ) is None
    _cleanup([user_id])


def _seed_identity_set(label: str) -> tuple[UUID, UUID, UUID, UUID]:
    with SessionLocal() as db:
        created = create_user_for_verified_identity(
            db,
            provider=AuthProvider.EMAIL_PASSWORD,
            subject=f"auth005-{label}-{uuid4().hex}@example.com",
            secret_hash="integration-only",
            verified_at=datetime.now(UTC),
        )
        db.commit()
        phone = link_verified_identity(
            db,
            user_id=created.user_id,
            provider=AuthProvider.PHONE,
            subject=f"+8613812{uuid4().int % 10**8:08d}",
            verified_at=datetime.now(UTC),
        )
        wechat = link_verified_identity(
            db,
            user_id=created.user_id,
            provider=AuthProvider.WECHAT,
            subject=f"unionid:auth005-{label}:{uuid4().hex[:20]}",
            verified_at=datetime.now(UTC),
        )
        db.commit()
        pair = create_public_session(
            db,
            user_id=created.user_id,
            device_id=f"auth005-{label}-{uuid4().hex}",
        )
        return created.user_id, pair.session_id, phone.identity.id, wechat.identity.id


def _prove_unlink_projection_audit_and_concurrent_delete() -> None:
    user_id, session_id, phone_id, wechat_id = _seed_identity_set("unlink-audit")
    now = datetime.now(UTC)
    provider = FakeAuthIdentityLinkProvider(reauth_results={"reauth": now})
    with SessionLocal() as db:
        removed = unlink_identity(
            db,
            user_id=user_id,
            session_id=session_id,
            request_id=uuid4(),
            identity_id=phone_id,
            reauth_credential="reauth",
            provider=provider,
        )
        assert removed.identity is not None
        assert db.get(User, user_id).phone is None
        unlink_operation = db.scalar(
            select(AuthIdentityOperation).where(
                AuthIdentityOperation.identity_id.is_(None),
                AuthIdentityOperation.operation_type == "UNLINK",
                AuthIdentityOperation.user_id == user_id,
            )
        )
        assert unlink_operation is not None

        link_provider = FakeAuthIdentityLinkProvider(
            link_results={
                "opaque-link-token": VerifiedIdentityProof(
                    provider=AuthProvider.WECHAT,
                    subject=f"unionid:auth005-audit:{uuid4().hex[:20]}",
                    verified_at=now,
                    reauthenticated_at=now,
                    user_id=user_id,
                    session_id=session_id,
                    provider_request_id="audit-link-provider",
                )
            },
            reauth_results={"opaque-reauth": now},
        )
        linked = link_identity(
            db,
            user_id=user_id,
            session_id=session_id,
            request_id=uuid4(),
            credential="opaque-link-token",
            reauth_credential="opaque-reauth",
            provider=link_provider,
        )
        assert linked.identity is not None
        link_operation = db.scalar(
            select(AuthIdentityOperation).where(
                AuthIdentityOperation.identity_id == linked.identity.id,
                AuthIdentityOperation.user_id == user_id,
            )
        )
        assert link_operation is not None
        link_operation_id = link_operation.id
        unlink_operation_id = unlink_operation.id
        db.execute(delete(User).where(User.id == user_id))
        db.commit()
        db.expire_all()
        audit_rows = list(
            db.scalars(
                select(AuthIdentityOperation).where(
                    AuthIdentityOperation.id.in_([link_operation_id, unlink_operation_id])
                )
            )
        )
        assert len(audit_rows) == 2
        assert all(
            row.user_id is None and row.session_id is None and row.identity_id is None
            for row in audit_rows
        ), [(row.user_id, row.session_id, row.identity_id) for row in audit_rows]

    concurrent_user, concurrent_session, _, concurrent_wechat = _seed_identity_set(
        "concurrent-unlink"
    )
    barrier = Barrier(2)
    outcomes: list[str] = []
    errors: list[BaseException] = []

    def unlink_worker() -> None:
        with SessionLocal() as db:
            try:
                result = unlink_identity(
                    db,
                    user_id=concurrent_user,
                    session_id=concurrent_session,
                    request_id=uuid4(),
                    identity_id=concurrent_wechat,
                    reauth_credential="reauth",
                    provider=_BarrierReauthProvider(barrier, datetime.now(UTC)),
                )
                outcomes.append(result.operation.value)
            except AuthIdentityError as exc:
                outcomes.append(exc.code)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

    threads = [
        Thread(target=unlink_worker, name="auth005-unlink-a"),
        Thread(target=unlink_worker, name="auth005-unlink-b"),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=_THREAD_TIMEOUT)
        assert not thread.is_alive(), f"thread did not finish: {thread.name}"
    assert errors == [], [repr(error) for error in errors]
    assert outcomes.count("UNLINK") == 1
    assert outcomes.count("AUTH_IDENTITY_NOT_FOUND") == 1
    with SessionLocal() as db:
        assert db.scalar(select(AuthIdentity).where(AuthIdentity.id == concurrent_wechat)) is None
        assert db.scalar(
            select(func.count(AuthIdentity.id)).where(
                AuthIdentity.user_id == concurrent_user
            )
        ) == 2
        operation_states = set(
            db.scalars(
                select(AuthIdentityOperation.state).where(
                    AuthIdentityOperation.user_id == concurrent_user
                )
            )
        )
        assert operation_states == {
            AuthIdentityOperationState.COMPLETED,
            AuthIdentityOperationState.REJECTED,
        }
    _cleanup([concurrent_user])


def main() -> None:
    _prove_cross_owner_unique_identity_race()
    _prove_late_provider_result_cannot_complete_unknown_operation()
    _prove_unlink_projection_audit_and_concurrent_delete()
    print("PostgreSQL AUTH-005 identity link/unlink authority PASS")


if __name__ == "__main__":
    main()
