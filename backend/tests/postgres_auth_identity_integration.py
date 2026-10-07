"""PostgreSQL proof for AUTH-01 identity/session/deletion lock ordering."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from threading import Barrier, Event, Thread
from uuid import uuid4

from sqlalchemy import delete, func, select

from app.account_deletion_models import AccountDeletionOperation
from app.auth_models import AuthIdentity, AuthProvider, AuthSession
from app.core.db import SessionLocal
from app.entitlement_models import UserEntitlement
from app.models import User
from app.services import auth_identity_service
from app.services.account_deletion_service import _begin_or_load_account_deletion
from app.services.auth_identity_service import (
    create_user_for_verified_identity,
    issue_authenticated_session,
    link_verified_identity,
)

DATABASE_URL = os.environ["DATABASE_URL"]
_THREAD_TIMEOUT = 30


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
                secret_hash="integration-only",
                verified_at=datetime.now(UTC),
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


def _join_or_fail(*threads: Thread) -> None:
    for thread in threads:
        thread.join(timeout=_THREAD_TIMEOUT)
        assert not thread.is_alive(), f"thread did not finish: {thread.name}"


def _prove_issuance_first_then_delete() -> None:
    """A: issuance holds KEY SHARE; deletion waits, then revokes issued session."""

    user = _seed_user()
    issuance_entered = Event()
    release_issuance = Event()
    deletion_finished = Event()
    errors: list[BaseException] = []
    issued = []
    real_create = auth_identity_service.create_public_session

    def blocked_create(*args, **kwargs):
        issuance_entered.set()
        assert release_issuance.wait(timeout=_THREAD_TIMEOUT)
        return real_create(*args, **kwargs)

    auth_identity_service.create_public_session = blocked_create
    try:
        def issue() -> None:
            with SessionLocal() as db:
                try:
                    issued.append(
                        issue_authenticated_session(
                            db,
                            user_id=user.id,
                            device_id="auth-01-issuance-first",
                        )
                    )
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

        def start_delete() -> None:
            with SessionLocal() as db:
                try:
                    assert _begin_or_load_account_deletion(
                        db,
                        user_id=user.id,
                        request_id=uuid4(),
                    ) is not None
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)
                finally:
                    deletion_finished.set()

        issue_thread = Thread(target=issue, name="auth-01-issuance-first")
        delete_thread = Thread(target=start_delete, name="auth-01-delete-after-issuance")
        issue_thread.start()
        assert issuance_entered.wait(timeout=_THREAD_TIMEOUT)
        delete_thread.start()
        assert not deletion_finished.wait(timeout=0.25)
        release_issuance.set()
        _join_or_fail(issue_thread, delete_thread)
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
    finally:
        auth_identity_service.create_public_session = real_create
        _cleanup(user.id)


def _prove_link_first_then_delete() -> None:
    """B: identity link holds User authority; deletion waits for its commit."""

    user = _seed_user()
    link_entered = Event()
    release_link = Event()
    deletion_finished = Event()
    errors: list[BaseException] = []
    real_projection = auth_identity_service._apply_projection

    def blocked_projection(*args, **kwargs):
        link_entered.set()
        assert release_link.wait(timeout=_THREAD_TIMEOUT)
        return real_projection(*args, **kwargs)

    auth_identity_service._apply_projection = blocked_projection
    try:
        def link() -> None:
            with SessionLocal() as db:
                try:
                    link_verified_identity(
                        db,
                        user_id=user.id,
                        provider=AuthProvider.PHONE,
                        subject="+8613812345678",
                        verified_at=datetime.now(UTC),
                    )
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

        def start_delete() -> None:
            with SessionLocal() as db:
                try:
                    assert _begin_or_load_account_deletion(
                        db,
                        user_id=user.id,
                        request_id=uuid4(),
                    ) is not None
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)
                finally:
                    deletion_finished.set()

        link_thread = Thread(target=link, name="auth-01-link-first")
        delete_thread = Thread(target=start_delete, name="auth-01-delete-after-link")
        link_thread.start()
        assert link_entered.wait(timeout=_THREAD_TIMEOUT)
        delete_thread.start()
        assert not deletion_finished.wait(timeout=0.25)
        release_link.set()
        _join_or_fail(link_thread, delete_thread)
        assert errors == []

        with SessionLocal() as db:
            assert db.scalar(
                select(AuthIdentity.id).where(
                    AuthIdentity.user_id == user.id,
                    AuthIdentity.provider == AuthProvider.PHONE,
                    AuthIdentity.subject == "+8613812345678",
                )
            ) is not None
            assert db.scalar(
                select(AccountDeletionOperation.id).where(
                    AccountDeletionOperation.user_id == user.id
                )
            ) is not None
    finally:
        auth_identity_service._apply_projection = real_projection
        _cleanup(user.id)


def _prove_delete_first_blocks_link() -> None:
    """C: a committed deletion gate rejects linking without mutation."""

    user = _seed_user()
    try:
        with SessionLocal() as deleting:
            assert _begin_or_load_account_deletion(
                deleting,
                user_id=user.id,
                request_id=uuid4(),
            ) is not None

        with SessionLocal() as linking:
            before = linking.scalar(
                select(func.count(AuthIdentity.id)).where(
                    AuthIdentity.user_id == user.id
                )
            )
            try:
                link_verified_identity(
                    linking,
                    user_id=user.id,
                    provider=AuthProvider.PHONE,
                    subject="+8613912345678",
                    verified_at=datetime.now(UTC),
                )
                raise AssertionError("identity link passed after deletion gate commit")
            except auth_identity_service.AuthIdentityError as exc:
                assert exc.code == "ACCOUNT_DELETION_IN_PROGRESS"
            finally:
                linking.rollback()
            after = linking.scalar(
                select(func.count(AuthIdentity.id)).where(
                    AuthIdentity.user_id == user.id
                )
            )
            assert after == before
            assert linking.scalar(
                select(User.phone).where(User.id == user.id)
            ) is None
    finally:
        _cleanup(user.id)


def _prove_concurrent_phone_first_creation() -> None:
    """D: two PostgreSQL sessions converge on one phone identity and User."""

    subject = "+8613812345679"
    barrier = Barrier(2)
    results = []
    errors: list[BaseException] = []
    verified_at = datetime.now(UTC)

    def create() -> None:
        with SessionLocal() as db:
            try:
                barrier.wait(timeout=_THREAD_TIMEOUT)
                result = create_user_for_verified_identity(
                    db,
                    provider=AuthProvider.PHONE,
                    subject=subject,
                    verified_at=verified_at,
                )
                db.commit()
                results.append(result)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
                db.rollback()

    first = Thread(target=create, name="auth-01-phone-first")
    second = Thread(target=create, name="auth-01-phone-second")
    first.start()
    second.start()
    _join_or_fail(first, second)
    assert errors == []
    assert len(results) == 2
    assert len({result.user_id for result in results}) == 1

    with SessionLocal() as db:
        users = list(db.scalars(select(User).where(User.phone == subject)))
        identities = list(
            db.scalars(
                select(AuthIdentity).where(
                    AuthIdentity.provider == AuthProvider.PHONE,
                    AuthIdentity.subject == subject,
                )
            )
        )
        assert len(users) == 1
        assert len(identities) == 1
        assert identities[0].user_id == users[0].id
        assert db.scalar(
            select(func.count(UserEntitlement.user_id)).where(
                UserEntitlement.user_id == users[0].id
            )
        ) == 1
        user_id = users[0].id
    _cleanup(user_id)


def main() -> None:
    assert DATABASE_URL.startswith("postgresql")
    _prove_issuance_first_then_delete()
    _prove_link_first_then_delete()
    _prove_delete_first_blocks_link()
    _prove_concurrent_phone_first_creation()
    print("PostgreSQL AUTH-01 identity/session/deletion concurrency PASS")


if __name__ == "__main__":
    main()
