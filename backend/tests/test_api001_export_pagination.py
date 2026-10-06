from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.core.db import SessionLocal
from app.models import ObjectItem


async def _new_user(client, nickname: str) -> tuple[dict[str, str], UUID]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, UUID(body["user_id"])


@pytest.mark.asyncio
async def test_objects_default_page_is_bounded_and_stable(client):
    headers, user_id = await _new_user(client, "api001-objects")
    with SessionLocal() as db:
        for index in range(55):
            name = f"item-{index:03d}"
            db.add(ObjectItem(user_id=user_id, name=name, normalized_name=name))
        db.commit()

    first = await client.get("/v1/objects", headers=headers)
    assert first.status_code == 200
    body = first.json()
    assert len(body["items"]) == 50
    assert body["next_cursor"]
    assert [item["name"] for item in body["items"]] == [
        f"item-{index:03d}" for index in range(50)
    ]

    second = await client.get(
        "/v1/objects",
        headers=headers,
        params={"cursor": body["next_cursor"]},
    )
    assert second.status_code == 200
    assert [item["name"] for item in second.json()["items"]] == [
        f"item-{index:03d}" for index in range(50, 55)
    ]
    assert second.json()["next_cursor"] is None


@pytest.mark.asyncio
async def test_objects_limit_max_and_cursor_tamper_fail_closed(client):
    headers, _ = await _new_user(client, "api001-cursor")
    assert (
        await client.get("/v1/objects", headers=headers, params={"limit": 101})
    ).status_code == 422

    first = await client.get("/v1/objects", headers=headers, params={"limit": 1})
    assert first.status_code == 200
    # Empty accounts have no cursor, so create one object and retry.
    assert (
        await client.post("/v1/objects", headers=headers, json={"name": "alpha"})
    ).status_code == 201
    assert (
        await client.post("/v1/objects", headers=headers, json={"name": "beta"})
    ).status_code == 201
    first = await client.get("/v1/objects", headers=headers, params={"limit": 1})
    cursor = first.json()["next_cursor"]
    assert cursor
    forged = cursor[:-1] + ("A" if cursor[-1] != "A" else "B")
    response = await client.get(
        "/v1/objects",
        headers=headers,
        params={"cursor": forged},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "OBJECT_CURSOR_INVALID"


@pytest.mark.asyncio
async def test_object_cursor_is_owner_bound(client):
    headers_a, _ = await _new_user(client, "api001-owner-a")
    headers_b, _ = await _new_user(client, "api001-owner-b")
    for name in ("a", "b"):
        assert (
            await client.post("/v1/objects", headers=headers_a, json={"name": name})
        ).status_code == 201
    first = await client.get("/v1/objects", headers=headers_a, params={"limit": 1})
    cursor = first.json()["next_cursor"]
    response = await client.get(
        "/v1/objects",
        headers=headers_b,
        params={"cursor": cursor},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "OBJECT_CURSOR_INVALID"
