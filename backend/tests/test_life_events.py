from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.life_event_models import LifeEvent, LifeEventMemoryLink
from app.models import Memory, MemoryType, Place, SourceType
from app.services.data_deletion_service import USER_DATA_INVENTORY


async def _new_user(client, nickname: str) -> tuple[dict[str, str], UUID]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, UUID(body["user_id"])


async def _memory(
    client,
    headers: dict[str, str],
    *,
    content: str,
    occurred_at: datetime,
    memory_type: str = "NOTE",
) -> dict:
    response = await client.post(
        "/v1/memories",
        headers=headers,
        json={
            "content": content,
            "memory_type": memory_type,
            "occurred_at": occurred_at.isoformat(),
        },
    )
    assert response.status_code == 201
    return response.json()


async def _event(
    client,
    headers: dict[str, str],
    *,
    kind: str = "TRAVEL",
    title: str = "一次旅行",
    started_at: datetime | None = None,
    **extra,
) -> dict:
    payload = {
        "event_kind": kind,
        "title": title,
        "started_at": (started_at or datetime.now(UTC)).isoformat(),
        **extra,
    }
    response = await client.post("/v1/life-events", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_life_event_requires_authentication_and_forbids_owner_field(client):
    now = datetime.now(UTC)
    unauthenticated = await client.post(
        "/v1/life-events",
        json={"event_kind": "TRAVEL", "title": "旅行", "started_at": now.isoformat()},
    )
    assert unauthenticated.status_code in {401, 403}

    headers, user_id = await _new_user(client, "life-event-owner-field")
    forged = await client.post(
        "/v1/life-events",
        headers=headers,
        json={
            "event_kind": "TRAVEL",
            "title": "旅行",
            "started_at": now.isoformat(),
            "user_id": str(user_id),
        },
    )
    assert forged.status_code == 422


@pytest.mark.asyncio
async def test_exact_seven_kinds_and_public_projection(client):
    headers, _ = await _new_user(client, "life-event-kinds")
    now = datetime.now(UTC)
    kinds = [
        "TRAVEL",
        "MEDICAL",
        "GATHERING",
        "WORK",
        "EDUCATION",
        "FAMILY",
        "OTHER",
    ]
    created = []
    for index, kind in enumerate(kinds):
        extra = {"custom_label": "婚礼"} if kind == "OTHER" else {}
        created.append(
            await _event(
                client,
                headers,
                kind=kind,
                title=f"事件-{index}",
                started_at=now + timedelta(minutes=index),
                **extra,
            )
        )

    assert {item["event_kind"] for item in created} == set(kinds)
    assert set(created[0]) == {
        "id",
        "event_kind",
        "title",
        "custom_label",
        "note",
        "started_at",
        "ended_at",
        "place_id",
        "revision",
        "created_at",
        "updated_at",
    }
    assert "user_id" not in created[0]

    invalid = await client.post(
        "/v1/life-events",
        headers=headers,
        json={
            "event_kind": "BIRTHDAY_AI",
            "title": "非法 taxonomy",
            "started_at": now.isoformat(),
        },
    )
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_title_other_note_and_aware_time_contract(client):
    headers, _ = await _new_user(client, "life-event-validation")
    now = datetime.now(UTC)

    cases = [
        {
            "event_kind": "OTHER",
            "title": "其它",
            "started_at": now.isoformat(),
        },
        {
            "event_kind": "TRAVEL",
            "title": "旅行",
            "custom_label": "不允许",
            "started_at": now.isoformat(),
        },
        {
            "event_kind": "TRAVEL",
            "title": " ",
            "started_at": now.isoformat(),
        },
        {
            "event_kind": "TRAVEL",
            "title": "旅行",
            "note": " ",
            "started_at": now.isoformat(),
        },
        {
            "event_kind": "TRAVEL",
            "title": "旅行",
            "started_at": "2026-09-27T12:00:00",
        },
        {
            "event_kind": "TRAVEL",
            "title": "旅行",
            "started_at": now.isoformat(),
            "ended_at": (now - timedelta(seconds=1)).isoformat(),
        },
    ]
    for payload in cases:
        response = await client.post("/v1/life-events", headers=headers, json=payload)
        assert response.status_code == 422, response.text

    point = await _event(
        client,
        headers,
        kind="OTHER",
        title="  婚礼  ",
        custom_label="  婚礼  ",
        note="  家庭聚会  ",
        started_at=now,
        ended_at=now.isoformat(),
    )
    assert point["title"] == "婚礼"
    assert point["custom_label"] == "婚礼"
    assert point["note"] == "家庭聚会"


@pytest.mark.asyncio
async def test_same_title_allowed_list_order_owner_isolation_and_limit(client):
    headers_a, _ = await _new_user(client, "life-event-list-a")
    headers_b, _ = await _new_user(client, "life-event-list-b")
    now = datetime.now(UTC)

    older = await _event(
        client,
        headers_a,
        title="同名事件",
        started_at=now - timedelta(days=2),
    )
    newer = await _event(
        client,
        headers_a,
        title="同名事件",
        started_at=now,
    )
    foreign = await _event(
        client,
        headers_b,
        title="B private",
        started_at=now + timedelta(days=1),
    )

    listed = await client.get("/v1/life-events?limit=100", headers=headers_a)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [newer["id"], older["id"]]
    assert foreign["id"] not in listed.text

    denied = await client.get(f"/v1/life-events/{foreign['id']}", headers=headers_a)
    assert denied.status_code == 404
    assert denied.json()["detail"] == "LIFE_EVENT_NOT_FOUND"

    assert (await client.get("/v1/life-events?limit=101", headers=headers_a)).status_code == 422


@pytest.mark.asyncio
async def test_place_owner_validation_and_clear(client):
    headers_a, user_a = await _new_user(client, "life-event-place-a")
    _, user_b = await _new_user(client, "life-event-place-b")
    place_a = uuid4()
    place_b = uuid4()
    with SessionLocal() as db:
        db.add_all(
            [
                Place(id=place_a, user_id=user_a, name="A place"),
                Place(id=place_b, user_id=user_b, name="B place"),
            ]
        )
        db.commit()

    now = datetime.now(UTC)
    event = await _event(
        client,
        headers_a,
        started_at=now,
        place_id=str(place_a),
    )
    assert event["place_id"] == str(place_a)

    foreign = await client.post(
        "/v1/life-events",
        headers=headers_a,
        json={
            "event_kind": "TRAVEL",
            "title": "foreign place",
            "started_at": now.isoformat(),
            "place_id": str(place_b),
        },
    )
    assert foreign.status_code == 404
    assert foreign.json()["detail"] == "PLACE_NOT_FOUND"

    cleared = await client.patch(
        f"/v1/life-events/{event['id']}",
        headers=headers_a,
        json={"expected_revision": 0, "place_id": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["place_id"] is None
    assert cleared.json()["revision"] == 1


@pytest.mark.asyncio
async def test_patch_revision_noop_null_and_other_transitions(client):
    headers, _ = await _new_user(client, "life-event-patch")
    now = datetime.now(UTC)
    event = await _event(
        client,
        headers,
        kind="OTHER",
        title="婚礼",
        custom_label="婚礼",
        note="备注",
        started_at=now,
        ended_at=(now + timedelta(hours=2)).isoformat(),
    )

    noop = await client.patch(
        f"/v1/life-events/{event['id']}",
        headers=headers,
        json={"expected_revision": 0, "title": "婚礼"},
    )
    assert noop.status_code == 200
    assert noop.json()["revision"] == 0

    family = await client.patch(
        f"/v1/life-events/{event['id']}",
        headers=headers,
        json={
            "expected_revision": 0,
            "event_kind": "FAMILY",
            "note": None,
            "ended_at": None,
        },
    )
    assert family.status_code == 200
    assert family.json()["event_kind"] == "FAMILY"
    assert family.json()["custom_label"] is None
    assert family.json()["note"] is None
    assert family.json()["ended_at"] is None
    assert family.json()["revision"] == 1

    stale = await client.patch(
        f"/v1/life-events/{event['id']}",
        headers=headers,
        json={"expected_revision": 0, "title": "stale"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == "LIFE_EVENT_REVISION_CONFLICT"

    missing_label = await client.patch(
        f"/v1/life-events/{event['id']}",
        headers=headers,
        json={"expected_revision": 1, "event_kind": "OTHER"},
    )
    assert missing_label.status_code == 422
    assert missing_label.json()["detail"] == "LIFE_EVENT_CUSTOM_LABEL_REQUIRED"

    restored_other = await client.patch(
        f"/v1/life-events/{event['id']}",
        headers=headers,
        json={
            "expected_revision": 1,
            "event_kind": "OTHER",
            "custom_label": "纪念日",
        },
    )
    assert restored_other.status_code == 200
    assert restored_other.json()["custom_label"] == "纪念日"
    assert restored_other.json()["revision"] == 2

    invalid_range = await client.patch(
        f"/v1/life-events/{event['id']}",
        headers=headers,
        json={
            "expected_revision": 2,
            "started_at": (now + timedelta(days=2)).isoformat(),
            "ended_at": now.isoformat(),
        },
    )
    assert invalid_range.status_code == 422
    assert invalid_range.json()["detail"] == "LIFE_EVENT_TIME_RANGE_INVALID"


@pytest.mark.asyncio
async def test_evidence_requires_confirmed_owner_memory_and_duplicate_converges(client):
    headers_a, user_a = await _new_user(client, "life-event-evidence-a")
    headers_b, _ = await _new_user(client, "life-event-evidence-b")
    now = datetime.now(UTC)
    event = await _event(client, headers_a, title="证据事件", started_at=now)
    memory_a = await _memory(
        client,
        headers_a,
        content="A evidence",
        occurred_at=now - timedelta(minutes=1),
    )
    memory_b = await _memory(
        client,
        headers_b,
        content="B private evidence",
        occurred_at=now,
    )

    created = await client.post(
        f"/v1/life-events/{event['id']}/memories/{memory_a['id']}",
        headers=headers_a,
    )
    assert created.status_code == 201
    body = created.json()
    assert set(body) == {
        "link_id",
        "memory_id",
        "memory_type",
        "title",
        "content",
        "occurred_at",
        "source_type",
        "created_at",
    }
    assert body["memory_id"] == memory_a["id"]
    assert body["content"] == "A evidence"

    replay = await client.post(
        f"/v1/life-events/{event['id']}/memories/{memory_a['id']}",
        headers=headers_a,
    )
    assert replay.status_code == 201
    assert replay.json()["link_id"] == body["link_id"]

    foreign = await client.post(
        f"/v1/life-events/{event['id']}/memories/{memory_b['id']}",
        headers=headers_a,
    )
    assert foreign.status_code == 404
    assert foreign.json()["detail"] == "MEMORY_NOT_FOUND"

    unconfirmed_id = uuid4()
    with SessionLocal() as db:
        db.add(
            Memory(
                id=unconfirmed_id,
                user_id=user_a,
                memory_type=MemoryType.NOTE,
                content="AI candidate",
                occurred_at=now,
                source_type=SourceType.AI_INFERENCE,
                confidence=0.5,
                is_confirmed=False,
            )
        )
        db.commit()

    unconfirmed = await client.post(
        f"/v1/life-events/{event['id']}/memories/{unconfirmed_id}",
        headers=headers_a,
    )
    assert unconfirmed.status_code == 404
    assert unconfirmed.json()["detail"] == "MEMORY_NOT_FOUND"


@pytest.mark.asyncio
async def test_evidence_order_unlink_and_delete_lifecycle(client):
    headers, _ = await _new_user(client, "life-event-evidence-lifecycle")
    now = datetime.now(UTC)
    event = await _event(client, headers, title="证据生命周期", started_at=now)
    older = await _memory(
        client,
        headers,
        content="older",
        occurred_at=now - timedelta(days=1),
    )
    newer = await _memory(
        client,
        headers,
        content="newer",
        occurred_at=now,
    )

    links = []
    for memory in (older, newer):
        response = await client.post(
            f"/v1/life-events/{event['id']}/memories/{memory['id']}",
            headers=headers,
        )
        assert response.status_code == 201
        links.append(response.json())

    listed = await client.get(
        f"/v1/life-events/{event['id']}/memories?limit=100",
        headers=headers,
    )
    assert listed.status_code == 200
    assert [row["memory_id"] for row in listed.json()] == [newer["id"], older["id"]]
    assert (await client.get(
        f"/v1/life-events/{event['id']}/memories?limit=101",
        headers=headers,
    )).status_code == 422

    unlink = await client.delete(
        f"/v1/life-events/{event['id']}/memories/{older['id']}",
        headers=headers,
    )
    assert unlink.status_code == 204
    assert (await client.get(f"/v1/memories/{older['id']}", headers=headers)).status_code == 200
    assert (await client.get(f"/v1/life-events/{event['id']}", headers=headers)).status_code == 200

    deleted_memory = await client.delete(f"/v1/memories/{newer['id']}", headers=headers)
    assert deleted_memory.status_code == 204
    after_memory_delete = await client.get(
        f"/v1/life-events/{event['id']}/memories",
        headers=headers,
    )
    assert after_memory_delete.status_code == 200
    assert after_memory_delete.json() == []

    survivor = await _memory(
        client,
        headers,
        content="survives LifeEvent delete",
        occurred_at=now + timedelta(minutes=1),
    )
    linked = await client.post(
        f"/v1/life-events/{event['id']}/memories/{survivor['id']}",
        headers=headers,
    )
    assert linked.status_code == 201
    delete_event = await client.delete(f"/v1/life-events/{event['id']}", headers=headers)
    assert delete_event.status_code == 204
    assert (await client.get(f"/v1/memories/{survivor['id']}", headers=headers)).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(
            select(func.count(LifeEventMemoryLink.id)).where(
                LifeEventMemoryLink.life_event_id == UUID(event["id"])
            )
        ) == 0


@pytest.mark.asyncio
async def test_export_contains_life_events_and_never_reexposes_deleted_evidence(client):
    headers_a, _ = await _new_user(client, "life-event-export-a")
    headers_b, _ = await _new_user(client, "life-event-export-b")
    now = datetime.now(UTC)
    event_a = await _event(client, headers_a, title="A exported event", started_at=now)
    memory_a = await _memory(
        client,
        headers_a,
        content="A exported evidence",
        occurred_at=now,
    )
    assert (await client.post(
        f"/v1/life-events/{event_a['id']}/memories/{memory_a['id']}",
        headers=headers_a,
    )).status_code == 201

    event_b = await _event(client, headers_b, title="B secret event", started_at=now)
    memory_b = await _memory(
        client,
        headers_b,
        content="B secret evidence",
        occurred_at=now,
    )
    assert (await client.post(
        f"/v1/life-events/{event_b['id']}/memories/{memory_b['id']}",
        headers=headers_b,
    )).status_code == 201

    exported = await client.get("/v1/export/data", headers=headers_a)
    assert exported.status_code == 200
    body = exported.json()
    assert len(body["life_events"]) == 1
    assert body["life_events"][0]["id"] == event_a["id"]
    assert "user_id" not in body["life_events"][0]
    assert len(body["life_event_memory_links"]) == 1
    assert body["life_event_memory_links"][0]["memory_id"] == memory_a["id"]
    assert "user_id" not in body["life_event_memory_links"][0]
    assert "B secret event" not in exported.text
    assert "B secret evidence" not in exported.text

    assert (await client.delete(
        f"/v1/memories/{memory_a['id']}",
        headers=headers_a,
    )).status_code == 204
    after = await client.get("/v1/export/data", headers=headers_a)
    assert after.status_code == 200
    assert len(after.json()["life_events"]) == 1
    assert after.json()["life_event_memory_links"] == []


@pytest.mark.asyncio
async def test_explicit_life_event_writes_do_not_create_or_mutate_memories(client):
    headers, user_id = await _new_user(client, "life-event-no-memory-side-effects")
    now = datetime.now(UTC)
    memory = await _memory(
        client,
        headers,
        content="existing evidence",
        occurred_at=now,
        memory_type="EVENT",
    )
    with SessionLocal() as db:
        before_count = db.scalar(
            select(func.count(Memory.id)).where(Memory.user_id == user_id)
        )
        before = db.get(Memory, UUID(memory["id"]))
        assert before is not None
        before_content = before.content
        before_revision = before.edit_revision

    event = await _event(client, headers, title="structured LifeEvent", started_at=now)
    assert (await client.post(
        f"/v1/life-events/{event['id']}/memories/{memory['id']}",
        headers=headers,
    )).status_code == 201

    with SessionLocal() as db:
        after_count = db.scalar(
            select(func.count(Memory.id)).where(Memory.user_id == user_id)
        )
        after = db.get(Memory, UUID(memory["id"]))
        assert after is not None
        assert before_count == after_count == 1
        assert after.content == before_content
        assert after.edit_revision == before_revision
        assert db.scalar(
            select(func.count(LifeEvent.id)).where(LifeEvent.user_id == user_id)
        ) == 1


def test_life_event_inventory_graph_and_inference_scope_locks():
    assert "life_events" in USER_DATA_INVENTORY
    assert "life_event_memory_links" in USER_DATA_INVENTORY

    root = Path(__file__).resolve().parents[1]
    graph_service = (root / "app/services/graph_projection_service.py").read_text()
    graph_schema = (root / "app/graph_schemas.py").read_text()
    assert "Memory.memory_type == MemoryType.EVENT" in graph_service
    assert "LIFE_EVENT" not in graph_schema
    assert "LifeEvent" not in graph_service

    for relative in [
        "app/services/entity_memory_pipeline_adapter.py",
        "app/services/memory_pipeline.py",
        "app/services/memory_rag_service.py",
    ]:
        source = (root / relative).read_text()
        assert "create_life_event" not in source
        assert "LifeEvent(" not in source

    life_service = (root / "app/services/life_event_service.py").read_text()
    assert "create_trusted_memory" not in life_service
    assert "create_user_memory" not in life_service
