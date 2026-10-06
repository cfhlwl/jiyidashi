from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.life_stage_models import LifeStageEventLink
from app.services.data_deletion_service import USER_DATA_INVENTORY
from export_test_support import export_payload


async def _new_user(client, nickname: str) -> tuple[dict[str, str], UUID]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, UUID(body["user_id"])

async def _stage(
    client,
    headers: dict[str, str],
    *,
    kind: str = "WORK",
    title: str = "长期阶段",
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    **extra,
) -> dict:
    payload = {
        "stage_kind": kind,
        "title": title,
        "started_at": (started_at or datetime.now(UTC)).isoformat(),
        **extra,
    }
    if ended_at is not None:
        payload["ended_at"] = ended_at.isoformat()
    response = await client.post("/v1/life-stages", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()

async def _event(
    client,
    headers: dict[str, str],
    *,
    title: str = "人生事件",
    started_at: datetime | None = None,
    kind: str = "WORK",
) -> dict:
    response = await client.post(
        "/v1/life-events",
        headers=headers,
        json={
            "event_kind": kind,
            "title": title,
            "started_at": (started_at or datetime.now(UTC)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()

@pytest.mark.asyncio
async def test_life_stage_requires_authentication_and_forbids_owner_field(client):
    now = datetime.now(UTC)
    unauthenticated = await client.post(
        "/v1/life-stages",
        json={"stage_kind": "WORK", "title": "工作", "started_at": now.isoformat()},
    )
    assert unauthenticated.status_code in {401, 403}

    headers, user_id = await _new_user(client, "life-stage-owner-field")
    forged = await client.post(
        "/v1/life-stages",
        headers=headers,
        json={
            "stage_kind": "WORK",
            "title": "工作",
            "started_at": now.isoformat(),
            "user_id": str(user_id),
        },
    )
    assert forged.status_code == 422

@pytest.mark.asyncio
async def test_exact_six_kinds_and_public_projection(client):
    headers, _ = await _new_user(client, "life-stage-kinds")
    now = datetime.now(UTC)
    kinds = ["WORK", "EDUCATION", "FAMILY", "RESIDENCE", "TRAVEL", "OTHER"]
    created = []
    for index, kind in enumerate(kinds):
        extra = {"custom_label": "创业期"} if kind == "OTHER" else {}
        created.append(
            await _stage(
                client,
                headers,
                kind=kind,
                title=f"阶段-{index}",
                started_at=now + timedelta(minutes=index),
                **extra,
            )
        )

    assert {item["stage_kind"] for item in created} == set(kinds)
    assert set(created[0]) == {
        "id",
        "stage_kind",
        "title",
        "custom_label",
        "note",
        "started_at",
        "ended_at",
        "revision",
        "created_at",
        "updated_at",
    }
    assert "user_id" not in created[0]

    invalid = await client.post(
        "/v1/life-stages",
        headers=headers,
        json={
            "stage_kind": "HEALTH_AI",
            "title": "非法 taxonomy",
            "started_at": now.isoformat(),
        },
    )
    assert invalid.status_code == 422

@pytest.mark.asyncio
async def test_scalar_other_and_aware_time_contract(client):
    headers, _ = await _new_user(client, "life-stage-validation")
    now = datetime.now(UTC)

    cases = [
        {"stage_kind": "OTHER", "title": "其它", "started_at": now.isoformat()},
        {
            "stage_kind": "WORK",
            "title": "工作",
            "custom_label": "不允许",
            "started_at": now.isoformat(),
        },
        {"stage_kind": "WORK", "title": " ", "started_at": now.isoformat()},
        {
            "stage_kind": "WORK",
            "title": "工作",
            "note": " ",
            "started_at": now.isoformat(),
        },
        {
            "stage_kind": "WORK",
            "title": "工作",
            "started_at": "2026-09-28T12:00:00",
        },
        {
            "stage_kind": "WORK",
            "title": "工作",
            "started_at": now.isoformat(),
            "ended_at": (now - timedelta(seconds=1)).isoformat(),
        },
    ]
    for payload in cases:
        response = await client.post("/v1/life-stages", headers=headers, json=payload)
        assert response.status_code == 422, response.text

    point = await _stage(
        client,
        headers,
        kind="OTHER",
        title="  创业阶段  ",
        custom_label="  创业期  ",
        note="  用户声明  ",
        started_at=now,
        ended_at=now,
    )
    assert point["title"] == "创业阶段"
    assert point["custom_label"] == "创业期"
    assert point["note"] == "用户声明"

@pytest.mark.asyncio
async def test_overlap_same_kind_same_title_and_multiple_open_stages_are_allowed(client):
    headers, _ = await _new_user(client, "life-stage-overlap")
    start = datetime(2025, 1, 1, tzinfo=UTC)

    work_a = await _stage(
        client,
        headers,
        kind="WORK",
        title="同名阶段",
        started_at=start,
        ended_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    work_b = await _stage(
        client,
        headers,
        kind="WORK",
        title="同名阶段",
        started_at=start + timedelta(days=30),
    )
    family = await _stage(
        client,
        headers,
        kind="FAMILY",
        title="家庭阶段",
        started_at=start + timedelta(days=15),
    )
    residence = await _stage(
        client,
        headers,
        kind="RESIDENCE",
        title="居住阶段",
        started_at=start + timedelta(days=15),
    )

    assert work_a["id"] != work_b["id"]
    assert work_b["ended_at"] is None
    assert family["ended_at"] is None
    assert residence["ended_at"] is None

    listed = await client.get("/v1/life-stages?limit=100", headers=headers)
    assert listed.status_code == 200
    ids = {item["id"] for item in listed.json()}
    assert {work_a["id"], work_b["id"], family["id"], residence["id"]} <= ids

@pytest.mark.asyncio
async def test_owner_isolation_list_order_and_limit(client):
    headers_a, _ = await _new_user(client, "life-stage-list-a")
    headers_b, _ = await _new_user(client, "life-stage-list-b")
    now = datetime.now(UTC)

    older = await _stage(
        client,
        headers_a,
        title="older",
        started_at=now - timedelta(days=2),
    )
    newer = await _stage(client, headers_a, title="newer", started_at=now)
    foreign = await _stage(
        client,
        headers_b,
        title="secret",
        started_at=now + timedelta(days=1),
    )

    listed = await client.get("/v1/life-stages?limit=100", headers=headers_a)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [newer["id"], older["id"]]
    assert foreign["id"] not in listed.text

    denied = await client.get(f"/v1/life-stages/{foreign['id']}", headers=headers_a)
    assert denied.status_code == 404
    assert denied.json()["detail"] == "LIFE_STAGE_NOT_FOUND"
    assert (await client.get("/v1/life-stages?limit=101", headers=headers_a)).status_code == 422

@pytest.mark.asyncio
async def test_patch_revision_noop_null_and_other_transitions(client):
    headers, _ = await _new_user(client, "life-stage-patch")
    now = datetime.now(UTC)
    stage = await _stage(
        client,
        headers,
        kind="OTHER",
        title="创业",
        custom_label="创业期",
        note="备注",
        started_at=now,
        ended_at=now + timedelta(days=30),
    )

    noop = await client.patch(
        f"/v1/life-stages/{stage['id']}",
        headers=headers,
        json={"expected_revision": 0, "title": "创业"},
    )
    assert noop.status_code == 200
    assert noop.json()["revision"] == 0

    work = await client.patch(
        f"/v1/life-stages/{stage['id']}",
        headers=headers,
        json={
            "expected_revision": 0,
            "stage_kind": "WORK",
            "note": None,
            "ended_at": None,
        },
    )
    assert work.status_code == 200
    assert work.json()["stage_kind"] == "WORK"
    assert work.json()["custom_label"] is None
    assert work.json()["note"] is None
    assert work.json()["ended_at"] is None
    assert work.json()["revision"] == 1

    stale = await client.patch(
        f"/v1/life-stages/{stage['id']}",
        headers=headers,
        json={"expected_revision": 0, "title": "stale"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == "LIFE_STAGE_REVISION_CONFLICT"

    missing_label = await client.patch(
        f"/v1/life-stages/{stage['id']}",
        headers=headers,
        json={"expected_revision": 1, "stage_kind": "OTHER"},
    )
    assert missing_label.status_code == 422
    assert missing_label.json()["detail"] == "LIFE_STAGE_CUSTOM_LABEL_REQUIRED"

    restored = await client.patch(
        f"/v1/life-stages/{stage['id']}",
        headers=headers,
        json={
            "expected_revision": 1,
            "stage_kind": "OTHER",
            "custom_label": "自由职业期",
        },
    )
    assert restored.status_code == 200
    assert restored.json()["revision"] == 2

    for field in ("stage_kind", "title", "started_at"):
        invalid_null = await client.patch(
            f"/v1/life-stages/{stage['id']}",
            headers=headers,
            json={"expected_revision": 2, field: None},
        )
        assert invalid_null.status_code == 422

    invalid_range = await client.patch(
        f"/v1/life-stages/{stage['id']}",
        headers=headers,
        json={
            "expected_revision": 2,
            "started_at": (now + timedelta(days=90)).isoformat(),
            "ended_at": now.isoformat(),
        },
    )
    assert invalid_range.status_code == 422
    assert invalid_range.json()["detail"] == "LIFE_STAGE_TIME_RANGE_INVALID"

@pytest.mark.asyncio
async def test_event_evidence_is_explicit_without_time_overlap_or_memory_requirement(client):
    headers, _ = await _new_user(client, "life-stage-event-evidence")
    stage = await _stage(
        client,
        headers,
        kind="EDUCATION",
        title="大学阶段",
        started_at=datetime(2020, 9, 1, tzinfo=UTC),
        ended_at=datetime(2024, 6, 30, tzinfo=UTC),
    )
    far_future_event = await _event(
        client,
        headers,
        title="未来事件",
        started_at=datetime(2030, 1, 1, tzinfo=UTC),
        kind="GATHERING",
    )

    linked = await client.post(
        f"/v1/life-stages/{stage['id']}/events/{far_future_event['id']}",
        headers=headers,
    )
    assert linked.status_code == 201
    body = linked.json()
    assert set(body) == {
        "link_id",
        "life_event_id",
        "event_kind",
        "title",
        "custom_label",
        "note",
        "started_at",
        "ended_at",
        "place_id",
        "created_at",
    }
    assert body["life_event_id"] == far_future_event["id"]
    assert "revision" not in body
    assert "user_id" not in body

    # No LifeEventMemoryLink was required before the explicit stage-event assertion.
    with SessionLocal() as db:
        assert db.scalar(
            select(func.count()).select_from(LifeStageEventLink).where(
                LifeStageEventLink.life_stage_id == UUID(stage["id"])
            )
        ) == 1

@pytest.mark.asyncio
async def test_duplicate_link_converges_cross_owner_rejected_and_order_is_canonical(client):
    headers_a, _ = await _new_user(client, "life-stage-link-a")
    headers_b, _ = await _new_user(client, "life-stage-link-b")
    now = datetime.now(UTC)
    stage = await _stage(client, headers_a, started_at=now - timedelta(days=100))
    older = await _event(
        client,
        headers_a,
        title="older",
        started_at=now - timedelta(days=2),
    )
    newer = await _event(client, headers_a, title="newer", started_at=now)
    foreign = await _event(client, headers_b, title="foreign", started_at=now)

    first = await client.post(
        f"/v1/life-stages/{stage['id']}/events/{older['id']}",
        headers=headers_a,
    )
    assert first.status_code == 201
    replay = await client.post(
        f"/v1/life-stages/{stage['id']}/events/{older['id']}",
        headers=headers_a,
    )
    assert replay.status_code == 201
    assert replay.json()["link_id"] == first.json()["link_id"]

    second = await client.post(
        f"/v1/life-stages/{stage['id']}/events/{newer['id']}",
        headers=headers_a,
    )
    assert second.status_code == 201

    denied = await client.post(
        f"/v1/life-stages/{stage['id']}/events/{foreign['id']}",
        headers=headers_a,
    )
    assert denied.status_code == 404
    assert denied.json()["detail"] == "LIFE_EVENT_NOT_FOUND"

    listed = await client.get(
        f"/v1/life-stages/{stage['id']}/events?limit=100",
        headers=headers_a,
    )
    assert listed.status_code == 200
    assert [row["life_event_id"] for row in listed.json()] == [newer["id"], older["id"]]
    assert (await client.get(
        f"/v1/life-stages/{stage['id']}/events?limit=101",
        headers=headers_a,
    )).status_code == 422

@pytest.mark.asyncio
async def test_unlink_only_removes_link(client):
    headers, _ = await _new_user(client, "life-stage-unlink")
    stage = await _stage(client, headers)
    event = await _event(client, headers)
    assert (await client.post(
        f"/v1/life-stages/{stage['id']}/events/{event['id']}",
        headers=headers,
    )).status_code == 201

    unlinked = await client.delete(
        f"/v1/life-stages/{stage['id']}/events/{event['id']}",
        headers=headers,
    )
    assert unlinked.status_code == 204
    assert (await client.get(f"/v1/life-stages/{stage['id']}", headers=headers)).status_code == 200
    assert (await client.get(f"/v1/life-events/{event['id']}", headers=headers)).status_code == 200
    assert (await client.get(
        f"/v1/life-stages/{stage['id']}/events",
        headers=headers,
    )).json() == []

@pytest.mark.asyncio
async def test_life_event_delete_cleans_stage_links_but_stage_survives(client):
    headers, _ = await _new_user(client, "life-stage-event-delete")
    stage = await _stage(client, headers)
    event = await _event(client, headers)
    assert (await client.post(
        f"/v1/life-stages/{stage['id']}/events/{event['id']}",
        headers=headers,
    )).status_code == 201

    deleted = await client.delete(f"/v1/life-events/{event['id']}", headers=headers)
    assert deleted.status_code == 204
    assert (await client.get(f"/v1/life-stages/{stage['id']}", headers=headers)).status_code == 200
    assert (await client.get(
        f"/v1/life-stages/{stage['id']}/events",
        headers=headers,
    )).json() == []

@pytest.mark.asyncio
async def test_life_stage_delete_cleans_links_but_event_survives(client):
    headers, _ = await _new_user(client, "life-stage-delete")
    stage = await _stage(client, headers)
    event = await _event(client, headers)
    assert (await client.post(
        f"/v1/life-stages/{stage['id']}/events/{event['id']}",
        headers=headers,
    )).status_code == 201

    deleted = await client.delete(f"/v1/life-stages/{stage['id']}", headers=headers)
    assert deleted.status_code == 204
    assert (await client.get(f"/v1/life-events/{event['id']}", headers=headers)).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(
            select(func.count()).select_from(LifeStageEventLink).where(
                LifeStageEventLink.life_stage_id == UUID(stage["id"])
            )
        ) == 0

@pytest.mark.asyncio
async def test_export_contains_stage_sections_owner_scoped_and_no_memory_duplication(client):
    headers_a, _ = await _new_user(client, "life-stage-export-a")
    headers_b, _ = await _new_user(client, "life-stage-export-b")
    now = datetime.now(UTC)

    stage_a = await _stage(
        client,
        headers_a,
        kind="RESIDENCE",
        title="上海生活",
        started_at=now - timedelta(days=300),
    )
    event_a = await _event(client, headers_a, title="搬家", started_at=now)
    assert (await client.post(
        f"/v1/life-stages/{stage_a['id']}/events/{event_a['id']}",
        headers=headers_a,
    )).status_code == 201

    stage_b = await _stage(client, headers_b, title="B secret stage", started_at=now)
    event_b = await _event(client, headers_b, title="B secret event", started_at=now)
    assert (await client.post(
        f"/v1/life-stages/{stage_b['id']}/events/{event_b['id']}",
        headers=headers_b,
    )).status_code == 201

    body, exported_text = await export_payload(client, headers_a)
    assert len(body["life_stages"]) == 1
    assert body["life_stages"][0]["id"] == stage_a["id"]
    assert "user_id" not in body["life_stages"][0]
    assert len(body["life_stage_event_links"]) == 1
    assert set(body["life_stage_event_links"][0]) == {
        "id",
        "life_stage_id",
        "life_event_id",
        "created_at",
    }
    assert "memory_id" not in body["life_stage_event_links"][0]
    assert "B secret stage" not in exported_text
    assert "B secret event" not in exported_text

    deleted_event = await client.delete(
        f"/v1/life-events/{event_a['id']}",
        headers=headers_a,
    )
    assert deleted_event.status_code == 204
    after_body, _ = await export_payload(client, headers_a)
    assert len(after_body["life_stages"]) == 1
    assert after_body["life_stage_event_links"] == []

def test_inventory_and_no_ai_summary_graph_promotion_scope_locks():
    assert "life_stage_event_links" in USER_DATA_INVENTORY
    assert "life_stages" in USER_DATA_INVENTORY

    root = Path(__file__).resolve().parents[1]
    forbidden_creators = [
        "app/services/daily_summary_service.py",
        "app/services/monthly_summary_service.py",
        "app/services/annual_summary_service.py",
        "app/services/memory_rag_service.py",
        "app/services/entity_memory_pipeline_adapter.py",
        "app/services/entity_extraction_service.py",
        "app/services/memory_pipeline.py",
        "app/services/life_event_service.py",
    ]
    for relative in forbidden_creators:
        source = (root / relative).read_text()
        assert "create_life_stage" not in source
        assert "LifeStage(" not in source

    graph_service = (root / "app/services/graph_projection_service.py").read_text()
    graph_schema = (root / "app/graph_schemas.py").read_text()
    assert "LifeStage" not in graph_service
    assert "LIFE_STAGE" not in graph_schema

    stage_service = (root / "app/services/life_stage_service.py").read_text()
    assert "create_life_event(" not in stage_service
    assert "LifeEvent(" not in stage_service
    assert "Memory" not in stage_service
