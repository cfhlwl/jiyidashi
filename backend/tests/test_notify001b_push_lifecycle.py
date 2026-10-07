from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.auth_models import AuthSession
from app.core.db import SessionLocal
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


async def test_auth_logout_fences_session_device_push_binding(client):
    auth = await client.post(
        "/v1/auth/dev-token",
        json={"nickname": "notify-001b-logout", "device_id": "dev-token"},
    )
    assert auth.status_code == 200, auth.text
    body = auth.json()
    user_id = UUID(body["user_id"])
    headers = {"Authorization": f"Bearer {body['access_token']}"}

    registered = await client.put(
        "/v1/notifications/device",
        headers=headers,
        json={
            "client_uuid": "dev-token",
            "platform": "IOS",
            "provider": "TEST",
            "push_token": "notify-001b-logout-token-123456",
            "app_version": "1.0.0",
            "os_version": "test",
        },
    )
    assert registered.status_code == 200, registered.text
    device_id = UUID(registered.json()["id"])

    logged_out = await client.post("/v1/auth/logout", headers=headers)
    assert logged_out.status_code == 200, logged_out.text

    with SessionLocal() as db:
        row = db.get(Device, device_id)
        assert row is not None
        assert row.user_id == user_id
        assert row.client_uuid == "dev-token"
        assert row.push_enabled is False
        assert row.push_token is None
        assert row.push_token_digest is None
        assert row.push_invalidated_at is not None


async def test_logout_all_fences_all_active_push_bindings_for_owner(client):
    auth_a = await client.post(
        "/v1/auth/dev-token",
        json={
            "nickname": "notify-001b-logout-all",
            "device_id": "logout-all-a",
        },
    )
    assert auth_a.status_code == 200, auth_a.text
    body_a = auth_a.json()
    user_id = UUID(body_a["user_id"])
    headers_a = {"Authorization": f"Bearer {body_a['access_token']}"}

    registered_a = await client.put(
        "/v1/notifications/device",
        headers=headers_a,
        json={
            "client_uuid": "logout-all-a",
            "platform": "ANDROID",
            "provider": "TEST",
            "push_token": "notify-001b-logout-all-token-a-123456",
        },
    )
    assert registered_a.status_code == 200, registered_a.text

    auth_b = await client.post(
        "/v1/auth/dev-token",
        json={
            "user_id": str(user_id),
            "nickname": "notify-001b-logout-all",
            "device_id": "logout-all-b",
        },
    )
    assert auth_b.status_code == 200, auth_b.text
    headers_b = {"Authorization": f"Bearer {auth_b.json()['access_token']}"}

    registered_b = await client.put(
        "/v1/notifications/device",
        headers=headers_b,
        json={
            "client_uuid": "logout-all-b",
            "platform": "ANDROID",
            "provider": "TEST",
            "push_token": "notify-001b-logout-all-token-b-123456",
        },
    )
    assert registered_b.status_code == 200, registered_b.text

    logged_out = await client.post("/v1/auth/logout-all", headers=headers_b)
    assert logged_out.status_code == 200, logged_out.text

    with SessionLocal() as db:
        devices = list(
            db.scalars(
                select(Device).where(
                    Device.user_id == user_id,
                    Device.client_uuid.in_(("logout-all-a", "logout-all-b")),
                )
            )
        )
        assert len(devices) == 2
        assert all(not row.push_enabled for row in devices)
        assert all(row.push_token is None for row in devices)
        assert all(row.push_token_digest is None for row in devices)


async def test_account_switch_fences_prior_owner_on_same_installation(client):
    owner_a = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    owner_b = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")

    auth_a = await client.post(
        "/v1/auth/dev-token",
        json={
            "user_id": str(owner_a),
            "nickname": "notify-owner-a",
            "device_id": "notify-switch-installation",
        },
    )
    assert auth_a.status_code == 200, auth_a.text
    headers_a = {"Authorization": f"Bearer {auth_a.json()['access_token']}"}

    registered = await client.put(
        "/v1/notifications/device",
        headers=headers_a,
        json={
            "client_uuid": "notify-switch-installation",
            "platform": "ANDROID",
            "provider": "TEST",
            "push_token": "notify-owner-a-provider-token-123456",
        },
    )
    assert registered.status_code == 200, registered.text
    device_id = UUID(registered.json()["id"])

    auth_b = await client.post(
        "/v1/auth/dev-token",
        json={
            "user_id": str(owner_b),
            "nickname": "notify-owner-b",
            "device_id": "notify-switch-installation",
        },
    )
    assert auth_b.status_code == 200, auth_b.text
    assert UUID(auth_b.json()["user_id"]) == owner_b

    stale_resurrection = await client.put(
        "/v1/notifications/device",
        headers=headers_a,
        json={
            "client_uuid": "notify-switch-installation",
            "platform": "ANDROID",
            "provider": "TEST",
            "push_token": "notify-owner-a-resurrection-token-123456",
        },
    )
    assert stale_resurrection.status_code == 401, stale_resurrection.text

    with SessionLocal() as db:
        prior = db.get(Device, device_id)
        assert prior is not None
        assert prior.user_id == owner_a
        assert prior.client_uuid == "notify-switch-installation"
        assert prior.push_enabled is False
        assert prior.push_token is None
        assert prior.push_token_digest is None
        assert prior.push_invalidated_at is not None


async def test_revoked_session_cannot_commit_late_push_registration(client):
    auth = await client.post(
        "/v1/auth/dev-token",
        json={"nickname": "notify-late-register", "device_id": "notify-late-register"},
    )
    assert auth.status_code == 200, auth.text
    body = auth.json()
    user_id = UUID(body["user_id"])
    session_id = UUID(body["session_id"])
    headers = {"Authorization": f"Bearer {body['access_token']}"}

    logged_out = await client.post("/v1/auth/logout", headers=headers)
    assert logged_out.status_code == 200, logged_out.text

    payload = DevicePushRegistrationRequest(
        client_uuid="notify-late-register",
        platform="ANDROID",
        provider="TEST",
        push_token="notify-late-register-token-123456",
    )
    with SessionLocal() as db:
        with pytest.raises(NotificationDeviceError) as exc_info:
            register_device_push(
                db,
                user_id=user_id,
                payload=payload,
                session_id=session_id,
            )
        assert exc_info.value.code == "PUSH_SESSION_INVALID"
        assert exc_info.value.status_code == 401

        row = db.scalar(
            select(Device).where(
                Device.user_id == user_id,
                Device.client_uuid == "notify-late-register",
            )
        )
        assert row is None or row.push_enabled is False



def test_postgresql_account_switch_race_cannot_resurrect_old_push_session():
    with SessionLocal() as probe:
        if probe.get_bind().dialect.name != "postgresql":
            pytest.skip("requires PostgreSQL advisory-lock semantics")

    owner_a = uuid4()
    owner_b = uuid4()
    client_uuid = f"notify-race-{uuid4()}"
    with SessionLocal() as db:
        db.add(User(id=owner_a, nickname="notify-race-owner-a"))
        db.add(User(id=owner_b, nickname="notify-race-owner-b"))
        db.commit()
        session_a = create_public_session(
            db,
            user_id=owner_a,
            device_id=client_uuid,
            client_platform="test",
            device_name="race-a",
        )

    payload = DevicePushRegistrationRequest(
        client_uuid=client_uuid,
        platform="ANDROID",
        provider="TEST",
        push_token=f"notify-race-token-{uuid4()}",
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
                assert started.wait(timeout=5)
                session_b = create_public_session(
                    db_b,
                    user_id=owner_b,
                    device_id=client_uuid,
                    client_platform="test",
                    device_name="race-b",
                )
                fence_other_owner_push_bindings_for_client_uuid(
                    db_b,
                    user_id=owner_b,
                    client_uuid=client_uuid,
                )
                assert future.result(timeout=10) == "PUSH_SESSION_INVALID"

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
            for user_id in (owner_a, owner_b):
                user = db.get(User, user_id)
                if user is not None:
                    db.delete(user)
            db.commit()
