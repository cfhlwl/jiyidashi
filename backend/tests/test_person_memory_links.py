from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.models import Memory, MemorySource
from app.person_memory_models import PersonMemoryLink
from app.person_models import Person


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
) -> dict:
    response = await client.post(
        "/v1/memories",
        headers=headers,
        json={
            "content": content,
            "memory_type": "NOTE",
            "occurred_at": occurred_at.isoformat(),
        },
    )
    assert response.status_code == 201
    return response.json()


async def _person(client, headers: dict[str, str], name: str) -> dict:
    response = await client.post(
        "/v1/people",
        headers=headers,
        json={"display_name": name},
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_person_memory_link_requires_authentication(client):
    person_id = uuid4()
    memory_id = uuid4()
    response = await client.post(
        f"/v1/people/{person_id}/memories/{memory_id}",
        json={"relation_kind": "RELATED"},
    )
    assert response.status_code in {401, 403}


@pytest.mark.asyncio
async def test_explicit_links_are_owner_scoped_duplicate_safe_and_revision_bound(client):
    headers_a, user_a = await _new_user(client, "link-owner-a")
    headers_b, _ = await _new_user(client, "link-owner-b")
    now = datetime.now(UTC)

    person_a = await _person(client, headers_a, "老王")
    person_b = await _person(client, headers_b, "老王")
    memory_a = await _memory(
        client,
        headers_a,
        content="今天和老王喝咖啡",
        occurred_at=now,
    )
    memory_b = await _memory(
        client,
        headers_b,
        content="B private memory",
        occurred_at=now,
    )

    created = await client.post(
        f"/v1/people/{person_a['id']}/memories/{memory_a['id']}",
        headers=headers_a,
        json={"relation_kind": "MET"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["relation_kind"] == "MET"
    assert body["revision"] == 0

    replay = await client.post(
        f"/v1/people/{person_a['id']}/memories/{memory_a['id']}",
        headers=headers_a,
        json={"relation_kind": "MET"},
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == body["id"]

    conflicting_create = await client.post(
        f"/v1/people/{person_a['id']}/memories/{memory_a['id']}",
        headers=headers_a,
        json={"relation_kind": "RELATED"},
    )
    assert conflicting_create.status_code == 409
    assert conflicting_create.json()["detail"] == "PERSON_MEMORY_LINK_RELATION_CONFLICT"

    foreign_person = await client.post(
        f"/v1/people/{person_b['id']}/memories/{memory_a['id']}",
        headers=headers_a,
        json={"relation_kind": "RELATED"},
    )
    assert foreign_person.status_code == 404
    assert foreign_person.json()["detail"] == "PERSON_NOT_FOUND"

    foreign_memory = await client.post(
        f"/v1/people/{person_a['id']}/memories/{memory_b['id']}",
        headers=headers_a,
        json={"relation_kind": "RELATED"},
    )
    assert foreign_memory.status_code == 404
    assert foreign_memory.json()["detail"] == "MEMORY_NOT_FOUND"

    patched = await client.patch(
        f"/v1/people/{person_a['id']}/memories/{memory_a['id']}",
        headers=headers_a,
        json={"relation_kind": "RELATED", "expected_revision": 0},
    )
    assert patched.status_code == 200
    assert patched.json()["relation_kind"] == "RELATED"
    assert patched.json()["revision"] == 1

    stale = await client.patch(
        f"/v1/people/{person_a['id']}/memories/{memory_a['id']}",
        headers=headers_a,
        json={"relation_kind": "MET", "expected_revision": 0},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == "PERSON_MEMORY_LINK_REVISION_CONFLICT"

    with SessionLocal() as db:
        assert db.scalar(
            select(func.count(PersonMemoryLink.id)).where(
                PersonMemoryLink.user_id == user_a
            )
        ) == 1


@pytest.mark.asyncio
async def test_person_timeline_and_interactions_use_memory_occurred_at_only(client):
    headers, _ = await _new_user(client, "link-timeline")
    now = datetime.now(UTC)
    person_a = await _person(client, headers, "甲")
    person_b = await _person(client, headers, "乙")

    older = await _memory(
        client,
        headers,
        content="较早见到甲",
        occurred_at=now - timedelta(days=5),
    )
    newer_related = await _memory(
        client,
        headers,
        content="较新的相关记录",
        occurred_at=now - timedelta(days=1),
    )
    newest_met = await _memory(
        client,
        headers,
        content="最新见到乙",
        occurred_at=now,
    )

    for person, memory, kind in [
        (person_a, older, "MET"),
        (person_a, newer_related, "RELATED"),
        (person_b, newest_met, "MET"),
    ]:
        response = await client.post(
            f"/v1/people/{person['id']}/memories/{memory['id']}",
            headers=headers,
            json={"relation_kind": kind},
        )
        assert response.status_code == 201

    timeline = await client.get(
        f"/v1/people/{person_a['id']}/memories?limit=10",
        headers=headers,
    )
    assert timeline.status_code == 200
    rows = timeline.json()
    assert [row["memory_id"] for row in rows] == [
        newer_related["id"],
        older["id"],
    ]
    assert rows[0]["relation_kind"] == "RELATED"
    assert rows[0]["occurred_at"] == newer_related["occurred_at"]
    assert rows[0]["memory_content"] == "较新的相关记录"

    interactions = await client.get("/v1/people/interactions?limit=10", headers=headers)
    assert interactions.status_code == 200
    met_rows = interactions.json()
    assert [row["memory_id"] for row in met_rows] == [
        newest_met["id"],
        older["id"],
    ]
    assert [row["person_display_name"] for row in met_rows] == ["乙", "甲"]
    assert all(row["relation_kind"] == "MET" for row in met_rows)

    assert (await client.get(
        f"/v1/people/{person_a['id']}/memories?limit=101",
        headers=headers,
    )).status_code == 422
    assert (await client.get(
        "/v1/people/interactions?limit=101",
        headers=headers,
    )).status_code == 422


@pytest.mark.asyncio
async def test_memory_edit_preserves_link_but_both_delete_paths_remove_it(client):
    headers, _ = await _new_user(client, "link-memory-lifecycle")
    now = datetime.now(UTC)
    person = await _person(client, headers, "张老师")

    ordinary = await _memory(
        client,
        headers,
        content="普通删除前",
        occurred_at=now,
    )
    linked = await client.post(
        f"/v1/people/{person['id']}/memories/{ordinary['id']}",
        headers=headers,
        json={"relation_kind": "RELATED"},
    )
    assert linked.status_code == 201
    link_id = UUID(linked.json()["id"])

    edited = await client.patch(
        f"/v1/memories/{ordinary['id']}",
        headers=headers,
        json={"expected_revision": 0, "content": "普通删除前，已编辑"},
    )
    assert edited.status_code == 200
    with SessionLocal() as db:
        assert db.get(PersonMemoryLink, link_id) is not None

    deleted = await client.delete(f"/v1/memories/{ordinary['id']}", headers=headers)
    assert deleted.status_code == 204
    with SessionLocal() as db:
        assert db.get(PersonMemoryLink, link_id) is None

    feedback_memory = await _memory(
        client,
        headers,
        content="反馈删除",
        occurred_at=now + timedelta(minutes=1),
    )
    linked_feedback = await client.post(
        f"/v1/people/{person['id']}/memories/{feedback_memory['id']}",
        headers=headers,
        json={"relation_kind": "MET"},
    )
    assert linked_feedback.status_code == 201
    feedback_link_id = UUID(linked_feedback.json()["id"])

    feedback_deleted = await client.post(
        f"/v1/memories/{feedback_memory['id']}/feedback",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"action": "DELETE", "expected_revision": 0},
    )
    assert feedback_deleted.status_code == 201
    with SessionLocal() as db:
        assert db.get(PersonMemoryLink, feedback_link_id) is None


@pytest.mark.asyncio
async def test_person_delete_removes_links_without_deleting_memory(client):
    headers, _ = await _new_user(client, "link-person-delete")
    person = await _person(client, headers, "待删人物")
    memory = await _memory(
        client,
        headers,
        content="Memory must survive Person delete",
        occurred_at=datetime.now(UTC),
    )
    linked = await client.post(
        f"/v1/people/{person['id']}/memories/{memory['id']}",
        headers=headers,
        json={"relation_kind": "RELATED"},
    )
    assert linked.status_code == 201
    link_id = UUID(linked.json()["id"])

    deleted = await client.delete(f"/v1/people/{person['id']}", headers=headers)
    assert deleted.status_code == 204

    with SessionLocal() as db:
        assert db.get(PersonMemoryLink, link_id) is None
        row = db.get(Memory, UUID(memory["id"]))
        assert row is not None
        assert row.is_deleted is False


@pytest.mark.asyncio
async def test_link_mutations_create_no_memory_or_evidence(client):
    headers, user_id = await _new_user(client, "link-no-memory-side-effect")
    person = await _person(client, headers, "明确人物")
    memory = await _memory(
        client,
        headers,
        content="already existing source memory",
        occurred_at=datetime.now(UTC),
    )

    with SessionLocal() as db:
        before_memory = db.scalar(
            select(func.count(Memory.id)).where(Memory.user_id == user_id)
        )
        before_source = db.scalar(
            select(func.count(MemorySource.id))
            .join(Memory, Memory.id == MemorySource.memory_id)
            .where(Memory.user_id == user_id)
        )

    created = await client.post(
        f"/v1/people/{person['id']}/memories/{memory['id']}",
        headers=headers,
        json={"relation_kind": "MET"},
    )
    assert created.status_code == 201
    patched = await client.patch(
        f"/v1/people/{person['id']}/memories/{memory['id']}",
        headers=headers,
        json={"relation_kind": "RELATED", "expected_revision": 0},
    )
    assert patched.status_code == 200

    with SessionLocal() as db:
        after_memory = db.scalar(
            select(func.count(Memory.id)).where(Memory.user_id == user_id)
        )
        after_source = db.scalar(
            select(func.count(MemorySource.id))
            .join(Memory, Memory.id == MemorySource.memory_id)
            .where(Memory.user_id == user_id)
        )
    assert before_memory == after_memory == 1
    assert before_source == after_source == 1
