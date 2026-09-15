from datetime import UTC, datetime, timedelta
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.db import SessionLocal
from app.models import (
    Memory,
    MemorySource,
    ObjectLocation,
    ObjectLocationStatus,
    SourceType,
)


async def _create_object(client: AsyncClient, auth_headers: dict[str, str], name: str) -> str:
    created = await client.post("/v1/objects", headers=auth_headers, json={"name": name})
    assert created.status_code == 201
    return created.json()["id"]


async def test_object_location_query_returns_latest_evidence(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    object_id = await _create_object(client, auth_headers, "护照")
    first = await client.post(
        f"/v1/objects/{object_id}/locations",
        headers=auth_headers,
        json={"location_text": "卧室床头柜"},
    )
    assert first.status_code == 201

    second = await client.post(
        f"/v1/objects/{object_id}/locations",
        headers=auth_headers,
        json={"location_text": "书房左侧柜子第二层"},
    )
    assert second.status_code == 201

    query = await client.post(
        "/v1/memory/query",
        headers=auth_headers,
        json={"question": "我的护照在哪里？"},
    )
    assert query.status_code == 200
    body = query.json()
    assert body["can_answer"] is True
    assert body["intent"] == "FIND_OBJECT"
    assert body["certainty"] == "confirmed"
    assert "书房左侧柜子第二层" in body["answer"]
    assert len(body["evidence"]) == 1


async def test_public_api_cannot_promote_ai_inference_to_confirmed(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    response = await client.post(
        "/v1/memories",
        headers=auth_headers,
        json={
            "content": "AI 猜测用户把银行卡放在抽屉",
            "source_type": "AI_INFERENCE",
            "confidence": 1.0,
            "is_confirmed": True,
        },
    )
    assert response.status_code == 422


async def test_ai_inference_without_confirmed_evidence_is_never_answered(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    user_id = (await client.post("/v1/auth/dev-token", json={"nickname": "AI Test"})).json()[
        "user_id"
    ]
    with SessionLocal() as db:
        memory = Memory(
            user_id=UUID(user_id),
            content="老王可能住在北京",
            source_type=SourceType.AI_INFERENCE,
            confidence=1.0,
            is_confirmed=True,
            occurred_at=datetime.now(UTC),
        )
        db.add(memory)
        db.flush()
        db.add(
            MemorySource(
                memory_id=memory.id,
                source_type=SourceType.AI_INFERENCE,
                confidence=1.0,
                raw_text="模型推断",
            )
        )
        db.commit()

    token = await client.post(
        "/v1/auth/dev-token",
        json={"user_id": user_id, "nickname": "AI Test"},
    )
    headers = {"Authorization": f"Bearer {token.json()['access_token']}"}
    query = await client.post(
        "/v1/memory/query",
        headers=headers,
        json={"question": "老王北京"},
    )
    assert query.status_code == 200
    assert query.json()["can_answer"] is False
    assert query.json()["reason"] == "NO_EVIDENCE"


async def test_no_evidence_means_no_personal_answer(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    query = await client.post(
        "/v1/memory/query",
        headers=auth_headers,
        json={"question": "我的银行卡放在哪里？"},
    )
    assert query.status_code == 200
    body = query.json()
    assert body["can_answer"] is False
    assert body["answer"] is None
    assert body["reason"] == "NO_EVIDENCE"


async def test_chinese_memory_query_matches_without_spaces_then_delete_hides_it(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    created = await client.post(
        "/v1/memories",
        headers=auth_headers,
        json={"content": "老张周五下午来公司取合同"},
    )
    assert created.status_code == 201
    memory_id = created.json()["id"]

    before_delete = await client.post(
        "/v1/memory/query",
        headers=auth_headers,
        json={"question": "老张合同"},
    )
    assert before_delete.status_code == 200
    assert before_delete.json()["can_answer"] is True
    assert memory_id in before_delete.json()["memory_ids"]

    deleted = await client.delete(f"/v1/memories/{memory_id}", headers=auth_headers)
    assert deleted.status_code == 204

    after_delete = await client.post(
        "/v1/memory/query",
        headers=auth_headers,
        json={"question": "老张合同"},
    )
    assert after_delete.status_code == 200
    assert after_delete.json()["can_answer"] is False


async def test_deleting_object_location_memory_prevents_future_answer(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    object_id = await _create_object(client, auth_headers, "身份证")
    location = await client.post(
        f"/v1/objects/{object_id}/locations",
        headers=auth_headers,
        json={"location_text": "书房抽屉"},
    )
    memory_id = location.json()["memory_id"]

    deleted = await client.delete(f"/v1/memories/{memory_id}", headers=auth_headers)
    assert deleted.status_code == 204

    query = await client.post(
        "/v1/memory/query",
        headers=auth_headers,
        json={"question": "我的身份证在哪里？"},
    )
    assert query.status_code == 200
    assert query.json()["can_answer"] is False


async def test_late_offline_object_location_cannot_replace_newer_current(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    object_id = await _create_object(client, auth_headers, "钥匙")
    now = datetime.now(UTC)
    newer = await client.post(
        f"/v1/objects/{object_id}/locations",
        headers=auth_headers,
        json={"location_text": "书房", "recorded_at": now.isoformat()},
    )
    assert newer.json()["status"] == "CURRENT"

    late_old = await client.post(
        f"/v1/objects/{object_id}/locations",
        headers=auth_headers,
        json={
            "location_text": "鞋柜",
            "recorded_at": (now - timedelta(days=1)).isoformat(),
        },
    )
    assert late_old.status_code == 201
    assert late_old.json()["status"] == "STALE"

    current = await client.get(f"/v1/objects/{object_id}/location", headers=auth_headers)
    assert current.status_code == 200
    assert current.json()["location_text"] == "书房"

    with SessionLocal() as db:
        current_rows = db.scalars(
            select(ObjectLocation).where(
                ObjectLocation.object_id == UUID(object_id),
                ObjectLocation.status == ObjectLocationStatus.CURRENT,
            )
        ).all()
        assert len(current_rows) == 1


def test_database_rejects_second_current_object_location():
    with SessionLocal() as db:
        current = db.scalar(
            select(ObjectLocation).where(
                ObjectLocation.status == ObjectLocationStatus.CURRENT
            )
        )
        if current is None:
            return
        duplicate = ObjectLocation(
            object_id=current.object_id,
            user_id=current.user_id,
            location_text="并发重复 CURRENT",
            recorded_at=current.recorded_at + timedelta(seconds=1),
            status=ObjectLocationStatus.CURRENT,
            memory_id=current.memory_id,
        )
        db.add(duplicate)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("database must enforce at most one CURRENT location per object")
