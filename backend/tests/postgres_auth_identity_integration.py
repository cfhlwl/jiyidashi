"""PostgreSQL proof for AUTH-01 identity/session/deletion lock ordering."""

from __future__ import annotations

import os
from threading import Event, Thread
from uuid import uuid4

from sqlalchemy import delete, select

from app.account_deletion_models import AccountDeletionOperation
from app.auth_models import AuthIdentity, AuthProvider, AuthSession
from app.core.db import SessionLocal
from app.models import User
from app.services import auth_identity_service
from app.services.account_deletion_service import _begin_or_load_account_deletion
from app.services.auth_identity_service import (
    issue_authenticated_session,
    link_verified_identity,
)

DATABASE_URL = os.environ["DATABASE_URL"]


def _seed_user() -> User:
    with SessionLocal() as db:
        user = User(nickname="AUTH-01 PostgreSQL")
        db.add(user)
        db.flush()
        db.add(
            AuthIdentity(
                user_id=user.id,
                provider=AuthProvider.EMAIL_PASSWORD,
                subject=f"auth-01-{user.id}@example.com",
                verified_at=user.created_at,
            )
        )
        db.commit()
        db.refresh(user)
        return user


def _cleanup(user_id) -> None:
    with SessionLocal() as db:
        db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
        db.execute(
            delete(AccountDeletionOperation).where(
                AccountDeletionOperation.user_id == user_id
            )
        )
        db.execute(delete(AuthIdentity).where(AuthIdentity.user_id == user_id))
        db.execute(delete(User).where(User.id == user_id))
        db.commit()


def _prove_delete_vs_shared_session_issuance() -> None:
    user = _seed_user()
    issuance_entered = Event()
    release_issuance = Event()
    deletion_finished = Event()
    errors: list[BaseException] = []
    issued = []
    real_create = auth_identity_service.create_public_session

    def blocked_create(*args, **kwargs):
        issuance_entered.set()
        if not release_issuance.wait(timeout=15):
            raise AssertionError("session issuance was not released")
        return real_create(*args, **kwargs)

    auth_identity_service.create_public_session = blocked_create

    def issue() -> None:
        with SessionLocal() as db:
            try:
                issued.append(
                    issue_authenticated_session(
                        db,
                        user_id=user.id,
                        device_id="auth-01-race",
                    )
                )
            except BaseException as exc:  # noqa: BLE001 - thread reports proof failures
                errors.append(exc)

    def start_delete() -> None:
        with SessionLocal() as db:
            try:
                _begin_or_load_account_deletion(
                    db,
                    user_id=user.id,
                    request_id=uuid4(),
                )
            except BaseException as exc:  # noqa: BLE001 - thread reports proof failures
                errors.append(exc)
            finally:
                deletion_finished.set()

    issue_thread = Thread(target=issue, name="auth-01-issuance")
    delete_thread = Thread(target=start_delete, name="auth-01-deletion")
    issue_thread.start()
    assert issuance_entered.wait(timeout=15)
    delete_thread.start()
    assert not deletion_finished.wait(timeout=0.25)
    release_issuance.set()
    issue_thread.join(timeout=30)
    delete_thread.join(timeout=30)
    auth_identity_service.create_public_session = real_create

    assert not issue_thread.is_alive()
    assert not delete_thread.is_alive()
    assert errors == []
    assert len(issued) == 1
    assert issued[0].account_deletion_in_progress is False

    with SessionLocal() as db:
        session = db.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
        assert session is not None
        assert session.revoked_at is not None
        assert db.scalar(
            select(AccountDeletionOperation.id).where(
                AccountDeletionOperation.user_id == user.id
            )
        ) is not None
    _cleanup(user.id)


def _prove_delete_vs_identity_link() -> None:
    user = _seed_user()
    with SessionLocal() as deleting:
        assert _begin_or_load_account_deletion(
            deleting,
            user_id=user.id,
            request_id=uuid4(),
        ) is not None

    with SessionLocal() as linking:
        try:
            link_verified_identity(
                linking,
                user_id=user.id,
                provider=AuthProvider.PHONE,
                subject="+8613812345678",
                verified_at=user.created_at,
            )
            raise AssertionError("identity link passed during account deletion")
        except auth_identity_service.AuthIdentityError as exc:
            assert exc.code == "ACCOUNT_DELETION_IN_PROGRESS"

    _cleanup(user.id)


def main() -> None:
    assert DATABASE_URL.startswith("postgresql")
    _prove_delete_vs_shared_session_issuance()
    _prove_delete_vs_identity_link()
    print("PostgreSQL AUTH-01 identity/session/deletion concurrency PASS")


if __name__ == "__main__":
    main()
