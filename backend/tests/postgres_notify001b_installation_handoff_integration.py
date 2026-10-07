"""Real PostgreSQL NOTIFY-001B installation handoff authority gate."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

from sqlalchemy import delete, select

from app.auth_models import AuthSession
from app.core.db import SessionLocal, engine
from app.models import Device, User
from app.notification_schemas import DevicePushRegistrationRequest
from app.services.auth_session_service import (
    create_public_session,
    lock_installation_authority_in_transaction,
)
from app.services.notification_service import (
    NotificationDeviceError,
    fence_other_owner_push_bindings_for_client_uuid,
    register_device_push,
)

DATABASE_URL = os.environ["DATABASE_URL"]


def _require_real_postgresql() -> None:
    if not DATABASE_URL.startswith("postgresql"):
        raise RuntimeError(
            "NOTIFY-001B race gate requires an external PostgreSQL DATABASE_URL"
        )
    if engine.dialect.name != "postgresql":
        raise RuntimeError(
            f"NOTIFY-001B race gate engine is {engine.dialect.name}, expected postgresql"
        )
    with SessionLocal() as db:
        dialect = db.get_bind().dialect.name
        if dialect != "postgresql":
            raise RuntimeError(
                f"NOTIFY-001B race gate SessionLocal is {dialect}, expected postgresql"
            )


def _prove_installation_handoff_blocks_stale_push_resurrection() -> None:
    owner_a = uuid4()
    owner_b = uuid4()
    client_uuid = f"notify-pg-race-{uuid4()}"

    with SessionLocal() as db:
        db.add(User(id=owner_a, nickname="notify-pg-race-owner-a"))
        db.add(User(id=owner_b, nickname="notify-pg-race-owner-b"))
        db.commit()
        session_a = create_public_session(
            db,
            user_id=owner_a,
            device_id=client_uuid,
            client_platform="integration",
            device_name="race-a",
        )

    payload = DevicePushRegistrationRequest(
        client_uuid=client_uuid,
        platform="ANDROID",
        provider="TEST",
        push_token=f"notify-pg-race-token-{uuid4()}",
    )
    started = Event()

    def stale_register() -> str:
        started.set()
        with SessionLocal() as db:
            try:
                register_device_push(
                    db,
                    user_id=owner_a,
                    payload=payload,
                    session_id=session_a.session_id,
                )
            except NotificationDeviceError as exc:
                return exc.code
            return "REGISTERED"

    try:
        with SessionLocal() as db_b:
            lock_installation_authority_in_transaction(db_b, client_uuid)
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(stale_register)
                if not started.wait(timeout=5):
                    raise AssertionError("stale registration worker did not start")
                session_b = create_public_session(
                    db_b,
                    user_id=owner_b,
                    device_id=client_uuid,
                    client_platform="integration",
                    device_name="race-b",
                )
                fence_other_owner_push_bindings_for_client_uuid(
                    db_b,
                    user_id=owner_b,
                    client_uuid=client_uuid,
                )
                result = future.result(timeout=10)
                assert result == "PUSH_SESSION_INVALID", result

        with SessionLocal() as db:
            old_session = db.get(AuthSession, session_a.session_id)
            new_session = db.get(AuthSession, session_b.session_id)
            assert old_session is not None
            assert old_session.revoked_at is not None
            assert old_session.revoke_reason == "INSTALLATION_SUPERSEDED"
            assert new_session is not None
            assert new_session.revoked_at is None

            stale_device = db.scalar(
                select(Device).where(
                    Device.user_id == owner_a,
                    Device.client_uuid == client_uuid,
                )
            )
            assert stale_device is None or stale_device.push_enabled is False
    finally:
        with SessionLocal() as db:
            db.execute(delete(Device).where(Device.client_uuid == client_uuid))
            db.execute(
                delete(AuthSession).where(
                    AuthSession.user_id.in_((owner_a, owner_b))
                )
            )
            db.execute(delete(User).where(User.id.in_((owner_a, owner_b))))
            db.commit()


def main() -> None:
    _require_real_postgresql()
    _prove_installation_handoff_blocks_stale_push_resurrection()
    print("PostgreSQL NOTIFY-001B installation handoff race PASS")


if __name__ == "__main__":
    main()
