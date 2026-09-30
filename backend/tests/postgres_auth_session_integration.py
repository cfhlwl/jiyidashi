"""Real PostgreSQL AUTH-001 refresh/session authority gate."""

from __future__ import annotations

import os
from threading import Barrier, Lock, Thread
from uuid import uuid4

from sqlalchemy import delete, select, text

from app.auth_models import AuthRefreshTokenReceipt, AuthSession
from app.core.db import SessionLocal, engine
from app.core.security import decode_access_token_claims
from app.models import User
from app.services.auth_session_service import (
    PublicAuthError,
    authenticate_access_session,
    create_public_session,
    refresh_public_session,
)

DATABASE_URL = os.environ["DATABASE_URL"]


def _seed_session():
    with SessionLocal() as db:
        user = User(nickname="AUTH-001 PostgreSQL")
        db.add(user)
        db.commit()
        db.refresh(user)
        pair = create_public_session(
            db,
            user_id=user.id,
            device_id="pg-auth-race",
            client_platform="integration",
        )
        return user.id, pair


def _prove_no_plaintext_secret_columns() -> None:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name IN (
                    'auth_sessions',
                    'auth_refresh_token_receipts',
                    'auth_one_time_tokens'
                  )
                ORDER BY table_name, ordinal_position
                """
            )
        ).all()
    columns = {(table, column) for table, column in rows}
    assert ("auth_sessions", "refresh_digest") in columns
    assert ("auth_refresh_token_receipts", "digest") in columns
    assert ("auth_one_time_tokens", "digest") in columns
    forbidden = {
        "refresh_token",
        "refresh_secret",
        "verification_token",
        "reset_token",
        "password",
    }
    assert not {column for _, column in columns}.intersection(forbidden)


def _prove_concurrent_refresh_exactly_one() -> None:
    user_id, initial = _seed_session()
    barrier = Barrier(2)
    lock = Lock()
    successes = []
    errors: list[str] = []
    unexpected: list[BaseException] = []

    def worker() -> None:
        db = SessionLocal()
        try:
            barrier.wait(timeout=15)
            rotated = refresh_public_session(
                db,
                refresh_token=initial.refresh_token,
            )
            with lock:
                successes.append(rotated)
        except PublicAuthError as exc:
            db.rollback()
            with lock:
                errors.append(exc.code)
        except BaseException as exc:  # noqa: BLE001
            db.rollback()
            with lock:
                unexpected.append(exc)
        finally:
            db.close()

    first = Thread(target=worker, name="auth-refresh-a")
    second = Thread(target=worker, name="auth-refresh-b")
    first.start()
    second.start()
    first.join(timeout=30)
    second.join(timeout=30)

    assert not first.is_alive()
    assert not second.is_alive()
    assert unexpected == []
    assert len(successes) == 1
    assert errors == ["REFRESH_TOKEN_REUSED"]

    rotated = successes[0]
    assert rotated.session_id == initial.session_id
    assert rotated.refresh_token != initial.refresh_token

    with SessionLocal() as db:
        session = db.get(AuthSession, initial.session_id)
        assert session is not None
        assert session.rotation_revision == 1
        assert session.revoked_at is not None
        assert session.revoke_reason == "REFRESH_REPLAY"

        receipts = list(
            db.scalars(
                select(AuthRefreshTokenReceipt).where(
                    AuthRefreshTokenReceipt.session_id == initial.session_id
                )
            )
        )
        assert len(receipts) == 1
        assert receipts[0].rotation_revision == 0

        claims = decode_access_token_claims(rotated.access_token)
        try:
            authenticate_access_session(db, claims)
            raise AssertionError("successor access JWT survived refresh replay")
        except PublicAuthError as exc:
            assert exc.code == "AUTH_SESSION_INVALID"

        db.execute(
            delete(AuthRefreshTokenReceipt).where(
                AuthRefreshTokenReceipt.session_id == initial.session_id
            )
        )
        db.execute(delete(AuthSession).where(AuthSession.id == initial.session_id))
        db.execute(delete(User).where(User.id == user_id))
        db.commit()


def main() -> None:
    assert DATABASE_URL.startswith("postgresql")
    _prove_no_plaintext_secret_columns()
    _prove_concurrent_refresh_exactly_one()
    print("PostgreSQL AUTH-001 refresh/session authority PASS")


if __name__ == "__main__":
    main()
