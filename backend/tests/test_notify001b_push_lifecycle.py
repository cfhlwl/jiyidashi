from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Device


async def test_auth_logout_fences_session_device_push_binding(client):
    auth = await client.post(
        "/v1/auth/dev-token",
        json={"nickname": "notify-001b-logout"},
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
    auth = await client.post(
        "/v1/auth/dev-token",
        json={"nickname": "notify-001b-logout-all"},
    )
    assert auth.status_code == 200, auth.text
    body = auth.json()
    user_id = UUID(body["user_id"])
    headers = {"Authorization": f"Bearer {body['access_token']}"}

    for suffix in ("a", "b"):
        response = await client.put(
            "/v1/notifications/device",
            headers=headers,
            json={
                "client_uuid": f"logout-all-{suffix}",
                "platform": "ANDROID",
                "provider": "TEST",
                "push_token": f"notify-001b-logout-all-token-{suffix}-123456",
            },
        )
        assert response.status_code == 200, response.text

    logged_out = await client.post("/v1/auth/logout-all", headers=headers)
    assert logged_out.status_code == 202, logged_out.text

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
        json={"user_id": str(owner_a), "nickname": "notify-owner-a"},
    )
    assert auth_a.status_code == 200, auth_a.text
    headers_a = {"Authorization": f"Bearer {auth_a.json()['access_token']}"}

    registered = await client.put(
        "/v1/notifications/device",
        headers=headers_a,
        json={
            "client_uuid": "dev-token",
            "platform": "ANDROID",
            "provider": "TEST",
            "push_token": "notify-owner-a-provider-token-123456",
        },
    )
    assert registered.status_code == 200, registered.text
    device_id = UUID(registered.json()["id"])

    auth_b = await client.post(
        "/v1/auth/dev-token",
        json={"user_id": str(owner_b), "nickname": "notify-owner-b"},
    )
    assert auth_b.status_code == 200, auth_b.text
    assert UUID(auth_b.json()["user_id"]) == owner_b

    with SessionLocal() as db:
        prior = db.get(Device, device_id)
        assert prior is not None
        assert prior.user_id == owner_a
        assert prior.client_uuid == "dev-token"
        assert prior.push_enabled is False
        assert prior.push_token is None
        assert prior.push_token_digest is None
        assert prior.push_invalidated_at is not None
