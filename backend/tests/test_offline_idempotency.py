from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.idempotency_models import ClientMutation
from app.models import Memory, MemorySource, ObjectLocation


async def _headers(client: AsyncClient, email: str) -> dict[str, str]:
    response = await client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "correct-horse-battery-staple",
            "nickname": "离线同步用户",
            "timezone": "Asia/Shanghai",
            "locale": "zh-CN",
        },
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_response_loss_retry_returns_same_memory_without_duplicate_evidence(
    client: AsyncClient,
):
    headers = await _headers(client, "offline-memory@example.com")
    key = "11111111-1111-4111-8111-111111111111"
    request_headers = {**headers, "Idempotency-Key": key}
    payload = {
        "memory_type": "NOTE",
        "title": "离线记录",
        "content": "服务端已经提交但第一次响应被客户端丢失",
        "capture_source": "USER_TEXT",
    }

    # 第一次响应内容故意不作为客户端状态依据；
    # 随后用同 key 重放，模拟 server commit 成功但 response-loss 的 unknown-commit。
    first = await client.post("/v1/memories", headers=request_headers, json=payload)
    assert first.status_code == 201
    retried = await client.post("/v1/memories", headers=request_headers, json=payload)
    assert retried.status_code == 201
    assert retried.json()["id"] == first.json()["id"]

    memory_id = UUID(first.json()["id"])
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Memory.id)).where(Memory.id == memory_id)) == 1
        assert (
            db.scalar(
                select(func.count(MemorySource.id)).where(
                    MemorySource.memory_id == memory_id
                )
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count(ClientMutation.id)).where(
                    ClientMutation.client_uuid == UUID(key)
                )
            )
            == 1
        )


async def test_same_memory_key_with_different_payload_fails_closed(client: AsyncClient):
    headers = await _headers(client, "offline-conflict@example.com")
    key = "22222222-2222-4222-8222-222222222222"
    request_headers = {**headers, "Idempotency-Key": key}

    first = await client.post(
        "/v1/memories",
        headers=request_headers,
        json={
            "memory_type": "NOTE",
            "content": "原始内容",
            "capture_source": "USER_TEXT",
        },
    )
    assert first.status_code == 201

    conflict = await client.post(
        "/v1/memories",
        headers=request_headers,
        json={
            "memory_type": "NOTE",
            "content": "被错误复用 key 的另一份内容",
            "capture_source": "USER_TEXT",
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST"


async def test_idempotency_key_is_isolated_by_authenticated_user(client: AsyncClient):
    headers_a = await _headers(client, "offline-user-a@example.com")
    headers_b = await _headers(client, "offline-user-b@example.com")
    key = "33333333-3333-4333-8333-333333333333"
    payload = {
        "memory_type": "NOTE",
        "content": "同一个客户端 UUID 在不同账号中必须隔离",
        "capture_source": "USER_TEXT",
    }

    a = await client.post(
        "/v1/memories",
        headers={**headers_a, "Idempotency-Key": key},
        json=payload,
    )
    b = await client.post(
        "/v1/memories",
        headers={**headers_b, "Idempotency-Key": key},
        json=payload,
    )
    assert a.status_code == 201
    assert b.status_code == 201
    assert a.json()["id"] != b.json()["id"]


async def test_object_location_response_loss_retry_reuses_location_and_memory(
    client: AsyncClient,
):
    headers = await _headers(client, "offline-object@example.com")
    created_object = await client.post(
        "/v1/objects",
        headers=headers,
        json={"name": "备用钥匙"},
    )
    assert created_object.status_code == 201
    object_id = created_object.json()["id"]
    key = "44444444-4444-4444-8444-444444444444"
    request_headers = {**headers, "Idempotency-Key": key}
    payload = {
        "location_text": "玄关右侧抽屉",
        "capture_source": "USER_TEXT",
        "recorded_at": "2026-09-17T21:00:00+08:00",
    }

    first = await client.post(
        f"/v1/objects/{object_id}/locations",
        headers=request_headers,
        json=payload,
    )
    assert first.status_code == 201
    retried = await client.post(
        f"/v1/objects/{object_id}/locations",
        headers=request_headers,
        json=payload,
    )
    assert retried.status_code == 201
    assert retried.json()["id"] == first.json()["id"]
    assert retried.json()["memory_id"] == first.json()["memory_id"]

    location_id = UUID(first.json()["id"])
    memory_id = UUID(first.json()["memory_id"])
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count(ObjectLocation.id)).where(
                    ObjectLocation.id == location_id
                )
            )
            == 1
        )
        assert db.scalar(select(func.count(Memory.id)).where(Memory.id == memory_id)) == 1
        assert (
            db.scalar(
                select(func.count(MemorySource.id)).where(
                    MemorySource.memory_id == memory_id
                )
            )
            == 1
        )


async def test_object_location_key_cannot_be_reused_for_another_payload(
    client: AsyncClient,
):
    headers = await _headers(client, "offline-object-conflict@example.com")
    created_object = await client.post(
        "/v1/objects",
        headers=headers,
        json={"name": "银行卡"},
    )
    object_id = created_object.json()["id"]
    key = "55555555-5555-4555-8555-555555555555"
    request_headers = {**headers, "Idempotency-Key": key}

    first = await client.post(
        f"/v1/objects/{object_id}/locations",
        headers=request_headers,
        json={"location_text": "书桌抽屉", "capture_source": "USER_TEXT"},
    )
    assert first.status_code == 201
    conflict = await client.post(
        f"/v1/objects/{object_id}/locations",
        headers=request_headers,
        json={"location_text": "卧室柜子", "capture_source": "USER_TEXT"},
    )
    assert conflict.status_code == 409


async def test_deleted_object_location_memory_makes_idempotent_replay_resource_gone(
    client: AsyncClient,
):
    headers = await _headers(client, "offline-object-delete@example.com")
    created_object = await client.post(
        "/v1/objects",
        headers=headers,
        json={"name": "护照"},
    )
    assert created_object.status_code == 201
    object_id = created_object.json()["id"]
    key = "66666666-6666-4666-8666-666666666666"
    request_headers = {**headers, "Idempotency-Key": key}
    payload = {
        "location_text": "旧抽屉",
        "capture_source": "USER_TEXT",
        "recorded_at": "2026-09-17T02:00:00Z",
    }

    created = await client.post(
        f"/v1/objects/{object_id}/locations",
        headers=request_headers,
        json=payload,
    )
    assert created.status_code == 201
    memory_id = created.json()["memory_id"]

    deleted = await client.delete(f"/v1/memories/{memory_id}", headers=headers)
    assert deleted.status_code == 204

    replayed = await client.post(
        f"/v1/objects/{object_id}/locations",
        headers=request_headers,
        json=payload,
    )
    assert replayed.status_code == 409
    assert replayed.json()["detail"] == "IDEMPOTENT_RESOURCE_GONE"
    assert "旧抽屉" not in replayed.text


async def test_delayed_location_before_unknown_watermark_stays_stale(
    client: AsyncClient,
):
    headers = await _headers(client, "offline-watermark@example.com")
    created_object = await client.post(
        "/v1/objects",
        headers=headers,
        json={"name": "证件袋"},
    )
    assert created_object.status_code == 201
    object_id = created_object.json()["id"]

    initial = await client.post(
        f"/v1/objects/{object_id}/locations",
        headers=headers,
        json={
            "location_text": "原来的柜子",
            "capture_source": "USER_TEXT",
            "recorded_at": "2026-09-17T01:00:00Z",
        },
    )
    assert initial.status_code == 201
    assert initial.json()["status"] == "CURRENT"

    invalidated = await client.post(
        f"/v1/objects/{object_id}/location/stale",
        headers=headers,
    )
    assert invalidated.status_code == 200

    delayed = await client.post(
        f"/v1/objects/{object_id}/locations",
        headers={**headers, "Idempotency-Key": "77777777-7777-4777-8777-777777777777"},
        json={
            "location_text": "离线时记录的旧位置",
            "capture_source": "USER_TEXT",
            "recorded_at": "2026-09-17T02:00:00Z",
        },
    )
    assert delayed.status_code == 201
    assert delayed.json()["status"] == "STALE"

    current = await client.get(f"/v1/objects/{object_id}/location", headers=headers)
    assert current.status_code == 404
