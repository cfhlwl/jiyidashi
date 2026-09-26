from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.models import Memory
from app.person_memory_models import PersonMemoryLink
from app.person_relationship_models import PersonRelationship


async def _new_user(client, nickname: str) -> tuple[dict[str, str], UUID]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, UUID(body["user_id"])


async def _person(client, headers: dict[str, str], name: str) -> dict:
    response = await client.post(
        "/v1/people",
        headers=headers,
        json={"display_name": name},
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_relationship_requires_authentication(client):
    response = await client.post(
        "/v1/people/relationships",
        json={
            "person_a_id": str(uuid4()),
            "person_b_id": str(uuid4()),
            "relationship_kind": "FRIEND",
        },
    )
    assert response.status_code in {401, 403}


@pytest.mark.asyncio
async def test_relationship_crud_is_owner_scoped_canonical_and_revision_safe(client):
    headers_a, user_a = await _new_user(client, "relationship-a")
    headers_b, _ = await _new_user(client, "relationship-b")
    person_a = await _person(client, headers_a, "老王")
    person_b = await _person(client, headers_a, "小李")
    foreign = await _person(client, headers_b, "B secret")

    forged = await client.post(
        "/v1/people/relationships",
        headers=headers_a,
        json={
            "person_a_id": person_a["id"],
            "person_b_id": person_b["id"],
            "relationship_kind": "FRIEND",
            "user_id": str(user_a),
        },
    )
    assert forged.status_code == 422

    self_edge = await client.post(
        "/v1/people/relationships",
        headers=headers_a,
        json={
            "person_a_id": person_a["id"],
            "person_b_id": person_a["id"],
            "relationship_kind": "FRIEND",
        },
    )
    assert self_edge.status_code == 422

    foreign_edge = await client.post(
        "/v1/people/relationships",
        headers=headers_a,
        json={
            "person_a_id": person_a["id"],
            "person_b_id": foreign["id"],
            "relationship_kind": "FRIEND",
        },
    )
    assert foreign_edge.status_code == 404
    assert foreign_edge.json()["detail"] == "PERSON_NOT_FOUND"

    invalid_other = await client.post(
        "/v1/people/relationships",
        headers=headers_a,
        json={
            "person_a_id": person_a["id"],
            "person_b_id": person_b["id"],
            "relationship_kind": "OTHER",
        },
    )
    assert invalid_other.status_code == 422

    invalid_label = await client.post(
        "/v1/people/relationships",
        headers=headers_a,
        json={
            "person_a_id": person_a["id"],
            "person_b_id": person_b["id"],
            "relationship_kind": "FRIEND",
            "custom_label": "邻居",
        },
    )
    assert invalid_label.status_code == 422

    created = await client.post(
        "/v1/people/relationships",
        headers=headers_a,
        json={
            "person_a_id": person_a["id"],
            "person_b_id": person_b["id"],
            "relationship_kind": "OTHER",
            "custom_label": "  老 邻居  ",
            "note": "明确维护的关系",
        },
    )
    assert created.status_code == 201
    edge = created.json()
    assert edge["relationship_kind"] == "OTHER"
    assert edge["custom_label"] == "老 邻居"
    assert edge["revision"] == 0
    assert {edge["person_a_id"], edge["person_b_id"]} == {
        person_a["id"],
        person_b["id"],
    }

    reversed_retry = await client.post(
        "/v1/people/relationships",
        headers=headers_a,
        json={
            "person_a_id": person_b["id"],
            "person_b_id": person_a["id"],
            "relationship_kind": "OTHER",
            "custom_label": "老 邻居",
            "note": "明确维护的关系",
        },
    )
    assert reversed_retry.status_code == 201
    assert reversed_retry.json()["id"] == edge["id"]

    conflicting = await client.post(
        "/v1/people/relationships",
        headers=headers_a,
        json={
            "person_a_id": person_b["id"],
            "person_b_id": person_a["id"],
            "relationship_kind": "COLLEAGUE",
        },
    )
    assert conflicting.status_code == 409
    assert conflicting.json()["detail"] == "PERSON_RELATIONSHIP_CONFLICT"

    patched = await client.patch(
        f"/v1/people/relationships/{edge['id']}",
        headers=headers_a,
        json={
            "expected_revision": 0,
            "relationship_kind": "FRIEND",
            "note": None,
        },
    )
    assert patched.status_code == 200
    assert patched.json()["relationship_kind"] == "FRIEND"
    assert patched.json()["custom_label"] is None
    assert patched.json()["note"] is None
    assert patched.json()["revision"] == 1

    illegal_patch_label = await client.patch(
        f"/v1/people/relationships/{edge['id']}",
        headers=headers_a,
        json={
            "expected_revision": 1,
            "custom_label": "不应接受",
        },
    )
    assert illegal_patch_label.status_code == 422

    stale = await client.patch(
        f"/v1/people/relationships/{edge['id']}",
        headers=headers_a,
        json={
            "expected_revision": 0,
            "relationship_kind": "FAMILY",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == "PERSON_RELATIONSHIP_REVISION_CONFLICT"

    foreign_get = await client.get(
        f"/v1/people/relationships/{edge['id']}",
        headers=headers_b,
    )
    assert foreign_get.status_code == 404

    projection = await client.get(
        f"/v1/people/{person_a['id']}/relationships?limit=10",
        headers=headers_a,
    )
    assert projection.status_code == 200
    rows = projection.json()
    assert len(rows) == 1
    assert rows[0]["relationship_id"] == edge["id"]
    assert rows[0]["other_person"] == {
        "id": person_b["id"],
        "display_name": "小李",
    }
    assert "note" not in rows[0]["other_person"]
    assert (
        await client.get(
            f"/v1/people/{person_a['id']}/relationships?limit=101",
            headers=headers_a,
        )
    ).status_code == 422

    deleted = await client.delete(
        f"/v1/people/relationships/{edge['id']}",
        headers=headers_a,
    )
    assert deleted.status_code == 204
    with SessionLocal() as db:
        assert db.get(PersonRelationship, UUID(edge["id"])) is None


@pytest.mark.asyncio
async def test_relationship_is_independent_from_memory_links(client):
    headers, user_id = await _new_user(client, "relationship-independent")
    person_a = await _person(client, headers, "甲")
    person_b = await _person(client, headers, "乙")
    memory = await client.post(
        "/v1/memories",
        headers=headers,
        json={
            "content": "甲和乙同一条记忆",
            "memory_type": "NOTE",
            "occurred_at": datetime.now(UTC).isoformat(),
        },
    )
    assert memory.status_code == 201
    memory_id = memory.json()["id"]

    link_a = await client.post(
        f"/v1/people/{person_a['id']}/memories/{memory_id}",
        headers=headers,
        json={"relation_kind": "RELATED"},
    )
    link_b = await client.post(
        f"/v1/people/{person_b['id']}/memories/{memory_id}",
        headers=headers,
        json={"relation_kind": "MET"},
    )
    assert link_a.status_code == 201
    assert link_b.status_code == 201

    with SessionLocal() as db:
        assert db.scalar(
            select(func.count(PersonRelationship.id)).where(
                PersonRelationship.user_id == user_id
            )
        ) == 0
        before_links = db.scalar(
            select(func.count(PersonMemoryLink.id)).where(
                PersonMemoryLink.user_id == user_id
            )
        )
        before_memories = db.scalar(
            select(func.count(Memory.id)).where(Memory.user_id == user_id)
        )

    edge = await client.post(
        "/v1/people/relationships",
        headers=headers,
        json={
            "person_a_id": person_a["id"],
            "person_b_id": person_b["id"],
            "relationship_kind": "COLLEAGUE",
        },
    )
    assert edge.status_code == 201
    patched = await client.patch(
        f"/v1/people/relationships/{edge.json()['id']}",
        headers=headers,
        json={
            "expected_revision": 0,
            "relationship_kind": "CLASSMATE",
        },
    )
    assert patched.status_code == 200
    deleted = await client.delete(
        f"/v1/people/relationships/{edge.json()['id']}",
        headers=headers,
    )
    assert deleted.status_code == 204

    with SessionLocal() as db:
        assert db.scalar(
            select(func.count(PersonMemoryLink.id)).where(
                PersonMemoryLink.user_id == user_id
            )
        ) == before_links == 2
        assert db.scalar(
            select(func.count(Memory.id)).where(Memory.user_id == user_id)
        ) == before_memories == 1


@pytest.mark.asyncio
async def test_person_delete_removes_relationship_but_preserves_other_person(client):
    headers, _ = await _new_user(client, "relationship-person-delete")
    person_a = await _person(client, headers, "待删")
    person_b = await _person(client, headers, "保留")
    edge = await client.post(
        "/v1/people/relationships",
        headers=headers,
        json={
            "person_a_id": person_a["id"],
            "person_b_id": person_b["id"],
            "relationship_kind": "FAMILY",
        },
    )
    assert edge.status_code == 201

    deleted = await client.delete(f"/v1/people/{person_a['id']}", headers=headers)
    assert deleted.status_code == 204

    assert (
        await client.get(
            f"/v1/people/relationships/{edge.json()['id']}",
            headers=headers,
        )
    ).status_code == 404
    survivor = await client.get(f"/v1/people/{person_b['id']}", headers=headers)
    assert survivor.status_code == 200


@pytest.mark.asyncio
async def test_relationship_export_is_owner_scoped(client):
    headers_a, _ = await _new_user(client, "relationship-export-a")
    headers_b, _ = await _new_user(client, "relationship-export-b")
    a1 = await _person(client, headers_a, "A1")
    a2 = await _person(client, headers_a, "A2")
    b1 = await _person(client, headers_b, "B secret 1")
    b2 = await _person(client, headers_b, "B secret 2")

    edge_a = await client.post(
        "/v1/people/relationships",
        headers=headers_a,
        json={
            "person_a_id": a1["id"],
            "person_b_id": a2["id"],
            "relationship_kind": "OTHER",
            "custom_label": "客户",
            "note": "A private edge note",
        },
    )
    edge_b = await client.post(
        "/v1/people/relationships",
        headers=headers_b,
        json={
            "person_a_id": b1["id"],
            "person_b_id": b2["id"],
            "relationship_kind": "FRIEND",
            "note": "B secret relationship",
        },
    )
    assert edge_a.status_code == 201
    assert edge_b.status_code == 201

    exported = await client.get("/v1/export/data", headers=headers_a)
    assert exported.status_code == 200
    rows = exported.json()["person_relationships"]
    assert len(rows) == 1
    assert rows[0]["id"] == edge_a.json()["id"]
    assert rows[0]["relationship_kind"] == "OTHER"
    assert rows[0]["custom_label"] == "客户"
    assert rows[0]["note"] == "A private edge note"
    assert "B secret relationship" not in exported.text
