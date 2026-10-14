"""Real PostgreSQL AUTH-005 identity link/unlink authority gate."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from threading import Barrier, Thread
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select

from app.auth_models import (
    AuthIdentity,
    AuthIdentityOperation,
    AuthIdentityOperationState,
    AuthProvider,
    AuthSession,
)
from app.core.db import SessionLocal
from app.entitlement_models import UserEntitlement
from app.models import User
from app.services.auth_identity_link_provider import (
    FakeAuthIdentityLinkProvider,
    VerifiedIdentityProof,
)
from app.services.auth_identity_operation_service import link_identity
from app.services.auth_identity_service import AuthIdentityError, create_user_for_verified_identity
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


def main() -> None:
    _prove_cross_owner_unique_identity_race()
    print("PostgreSQL AUTH-005 identity link/unlink authority PASS")


if __name__ == "__main__":
    main()
