from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import (
    Memory,
    MemoryType,
    ObjectItem,
    ObjectLocation,
    ObjectLocationStatus,
    Place,
    SourceType,
)
from app.person_memory_models import PersonMemoryLink, PersonMemoryRelationKind
from app.person_models import Person
from app.person_relationship_models import PersonRelationship, PersonRelationshipKind


async def _new_user(client, nickname: str) -> tuple[dict[str, str], UUID]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, UUID(body["user_id"])


def _seed_graph(user_id: UUID) -> dict[str, UUID]:
    now = datetime.now(UTC)
    ids = {name: uuid4() for name in (
        "person_a",
        "person_b",
        "person_c",
        "place",
        "object",
        "event",
        "event_unconfirmed",
        "note",
        "relationship_ab",
        "relationship_ac",
        "person_event",
        "person_unconfirmed",
        "person_note",
        "object_location",
    )}
    low_ab, high_ab = sorted((ids["person_a"], ids["person_b"]), key=lambda value: value.bytes)
    low_ac, high_ac = sorted((ids["person_a"], ids["person_c"]), key=lambda value: value.bytes)

    with SessionLocal() as db:
        db.add_all([
            Person(id=ids["person_a"], user_id=user_id, display_name="甲", note="private-person-note"),
            Person(id=ids["person_b"], user_id=user_id, display_name="乙", note="private-person-note-b"),
            Person(id=ids["person_c"], user_id=user_id, display_name="丙"),
            Place(
                id=ids["place"],
                user_id=user_id,
                name="可信地点",
                latitude=40.123,
                longitude=116.456,
                address="private-address",
            ),
            ObjectItem(
                id=ids["object"],
                user_id=user_id,
                name="钥匙",
                normalized_name="钥匙",
                description="private-object-description",
            ),
            Memory(
                id=ids["event"],
                user_id=user_id,
                memory_type=MemoryType.EVENT,
                title=None,
                content="这是一个已经确认的事件，完整内容不应该从图谱接口泄漏给客户端，只允许有限标题预览。",
                occurred_at=now,
                is_confirmed=True,
                is_deleted=False,
                place_id=ids["place"],
            ),
            Memory(
                id=ids["event_unconfirmed"],
                user_id=user_id,
                memory_type=MemoryType.EVENT,
                title="未确认事件",
                content="AI inferred",
                occurred_at=now + timedelta(minutes=1),
                source_type=SourceType.AI_INFERENCE,
                is_confirmed=False,
                is_deleted=False,
            ),
            Memory(
                id=ids["note"],
                user_id=user_id,
                memory_type=MemoryType.NOTE,
                title="普通笔记",
                content="not an event",
                occurred_at=now + timedelta(minutes=2),
                is_confirmed=True,
                is_deleted=False,
            ),
        ])
        db.flush()
        db.add_all([
            PersonRelationship(
                id=ids["relationship_ab"],
                user_id=user_id,
                person_low_id=low_ab,
                person_high_id=high_ab,
                relationship_kind=PersonRelationshipKind.FRIEND,
                note="private-edge-note",
                revision=0,
                created_at=now - timedelta(minutes=2),
            ),
            PersonRelationship(
                id=ids["relationship_ac"],
                user_id=user_id,
                person_low_id=low_ac,
                person_high_id=high_ac,
                relationship_kind=PersonRelationshipKind.COLLEAGUE,
                revision=0,
                created_at=now - timedelta(minutes=1),
            ),
            PersonMemoryLink(
                id=ids["person_event"],
                user_id=user_id,
                person_id=ids["person_a"],
                memory_id=ids["event"],
                relation_kind=PersonMemoryRelationKind.MET,
                revision=0,
                created_at=now,
            ),
            PersonMemoryLink(
                id=ids["person_unconfirmed"],
                user_id=user_id,
                person_id=ids["person_a"],
                memory_id=ids["event_unconfirmed"],
                relation_kind=PersonMemoryRelationKind.RELATED,
                revision=0,
                created_at=now + timedelta(minutes=1),
            ),
            PersonMemoryLink(
                id=ids["person_note"],
                user_id=user_id,
                person_id=ids["person_a"],
                memory_id=ids["note"],
                relation_kind=PersonMemoryRelationKind.RELATED,
                revision=0,
                created_at=now + timedelta(minutes=2),
            ),
            ObjectLocation(
                id=ids["object_location"],
                user_id=user_id,
                object_id=ids["object"],
                memory_id=None,
                location_text="抽屉",
                place_id=ids["place"],
                recorded_at=now,
                status=ObjectLocationStatus.CURRENT,
            ),
        ])
        db.commit()
    return ids


@pytest.mark.asyncio
async def test_graph_requires_authentication(client):
    response = await client.get(
        f"/v1/graph/neighborhood/PERSON/{uuid4()}",
    )
    assert response.status_code in {401, 403}


@pytest.mark.asyncio
async def test_graph_centers_are_owner_scoped_and_foreign_ids_fail_closed(client):
    headers_a, user_a = await _new_user(client, "graph-owner-a")
    headers_b, user_b = await _new_user(client, "graph-owner-b")
    ids_a = _seed_graph(user_a)
    ids_b = _seed_graph(user_b)

    for kind, entity_id in [
        ("PERSON", ids_b["person_a"]),
        ("PLACE", ids_b["place"]),
        ("OBJECT", ids_b["object"]),
        ("EVENT", ids_b["event"]),
    ]:
        response = await client.get(
            f"/v1/graph/neighborhood/{kind}/{entity_id}",
            headers=headers_a,
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "GRAPH_NODE_NOT_FOUND"

    own = await client.get(
        f"/v1/graph/neighborhood/PERSON/{ids_a['person_a']}",
        headers=headers_a,
    )
    assert own.status_code == 200


@pytest.mark.asyncio
async def test_person_projection_is_one_hop_trusted_and_private(client):
    headers, user_id = await _new_user(client, "graph-person")
    ids = _seed_graph(user_id)

    response = await client.get(
        f"/v1/graph/neighborhood/PERSON/{ids['person_a']}?limit=100",
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()

    assert body["center"] == {
        "kind": "PERSON",
        "id": str(ids["person_a"]),
        "label": "甲",
        "occurred_at": None,
    }
    assert body["truncated"] is False
    edge_kinds = [edge["edge_kind"] for edge in body["edges"]]
    assert edge_kinds == sorted(edge_kinds)
    assert edge_kinds.count("PERSON_RELATIONSHIP") == 2
    assert edge_kinds.count("PERSON_EVENT") == 1

    node_keys = {(node["kind"], node["id"]) for node in body["nodes"]}
    assert ("EVENT", str(ids["event"])) in node_keys
    assert ("EVENT", str(ids["event_unconfirmed"])) not in node_keys
    assert ("PLACE", str(ids["place"])) not in node_keys
    assert ("OBJECT", str(ids["object"])) not in node_keys

    # A NOTE link is not retyped as an EVENT edge, and the unconfirmed AI EVENT is hidden.
    authority_refs = {edge["authority_ref"] for edge in body["edges"]}
    assert str(ids["person_note"]) not in authority_refs
    assert str(ids["person_unconfirmed"]) not in authority_refs

    payload = response.text
    assert "private-person-note" not in payload
    assert "private-edge-note" not in payload
    assert "private-address" not in payload
    assert "private-object-description" not in payload
    assert "40.123" not in payload
    assert "116.456" not in payload
    assert "这是一个已经确认的事件，完整内容不应该从图谱接口泄漏给客户端，只允许有限标题预览。" not in payload
    event_node = next(
        node for node in body["nodes"] if node["id"] == str(ids["event"])
    )
    assert len(event_node["label"]) <= 80


@pytest.mark.asyncio
async def test_event_and_place_projection_use_same_owner_authority(client):
    headers_a, user_a = await _new_user(client, "graph-event-a")
    _, user_b = await _new_user(client, "graph-event-b")
    ids = _seed_graph(user_a)

    foreign_place_id = uuid4()
    cross_owner_event_id = uuid4()
    with SessionLocal() as db:
        db.add(Place(id=foreign_place_id, user_id=user_b, name="foreign place"))
        db.add(
            Memory(
                id=cross_owner_event_id,
                user_id=user_a,
                memory_type=MemoryType.EVENT,
                title="cross-owner-place event",
                content="x",
                occurred_at=datetime.now(UTC),
                is_confirmed=True,
                is_deleted=False,
                place_id=foreign_place_id,
            )
        )
        db.commit()

    event = await client.get(
        f"/v1/graph/neighborhood/EVENT/{ids['event']}",
        headers=headers_a,
    )
    assert event.status_code == 200
    body = event.json()
    assert {edge["edge_kind"] for edge in body["edges"]} == {"PERSON_EVENT", "EVENT_PLACE"}
    assert ("PLACE", str(ids["place"])) in {
        (node["kind"], node["id"]) for node in body["nodes"]
    }

    cross_owner = await client.get(
        f"/v1/graph/neighborhood/EVENT/{cross_owner_event_id}",
        headers=headers_a,
    )
    assert cross_owner.status_code == 200
    assert all(edge["edge_kind"] != "EVENT_PLACE" for edge in cross_owner.json()["edges"])

    place = await client.get(
        f"/v1/graph/neighborhood/PLACE/{ids['place']}",
        headers=headers_a,
    )
    assert place.status_code == 200
    assert {edge["edge_kind"] for edge in place.json()["edges"]} == {
        "EVENT_PLACE",
        "OBJECT_PLACE",
    }


@pytest.mark.asyncio
async def test_object_place_projects_only_current_location(client):
    headers, user_id = await _new_user(client, "graph-object")
    ids = _seed_graph(user_id)

    current = await client.get(
        f"/v1/graph/neighborhood/OBJECT/{ids['object']}",
        headers=headers,
    )
    assert current.status_code == 200
    assert [edge["edge_kind"] for edge in current.json()["edges"]] == ["OBJECT_PLACE"]

    with SessionLocal() as db:
        location = db.get(ObjectLocation, ids["object_location"])
        assert location is not None
        location.status = ObjectLocationStatus.STALE
        db.commit()

    stale = await client.get(
        f"/v1/graph/neighborhood/OBJECT/{ids['object']}",
        headers=headers,
    )
    assert stale.status_code == 200
    assert stale.json()["edges"] == []
    assert stale.json()["nodes"] == []


@pytest.mark.asyncio
async def test_event_soft_delete_removes_event_node_and_edges(client):
    headers, user_id = await _new_user(client, "graph-event-delete")
    ids = _seed_graph(user_id)

    deleted = await client.delete(f"/v1/memories/{ids['event']}", headers=headers)
    assert deleted.status_code == 204

    event = await client.get(
        f"/v1/graph/neighborhood/EVENT/{ids['event']}",
        headers=headers,
    )
    assert event.status_code == 404

    person = await client.get(
        f"/v1/graph/neighborhood/PERSON/{ids['person_a']}",
        headers=headers,
    )
    assert person.status_code == 200
    refs = {edge["authority_ref"] for edge in person.json()["edges"]}
    assert str(ids["person_event"]) not in refs

    place = await client.get(
        f"/v1/graph/neighborhood/PLACE/{ids['place']}",
        headers=headers,
    )
    assert place.status_code == 200
    assert all(
        edge["authority_ref"] != str(ids["event"])
        for edge in place.json()["edges"]
    )


@pytest.mark.asyncio
async def test_relationship_patch_is_reflected_without_graph_write(client):
    headers, user_id = await _new_user(client, "graph-relationship-patch")
    ids = _seed_graph(user_id)

    patched = await client.patch(
        f"/v1/people/relationships/{ids['relationship_ab']}",
        headers=headers,
        json={
            "expected_revision": 0,
            "relationship_kind": "OTHER",
            "custom_label": "邻居",
        },
    )
    assert patched.status_code == 200

    graph = await client.get(
        f"/v1/graph/neighborhood/PERSON/{ids['person_a']}",
        headers=headers,
    )
    assert graph.status_code == 200
    edge = next(
        row
        for row in graph.json()["edges"]
        if row["authority_ref"] == str(ids["relationship_ab"])
    )
    assert edge["metadata"]["relationship_kind"] == "OTHER"
    assert edge["metadata"]["custom_label"] == "邻居"


@pytest.mark.asyncio
async def test_limit_and_truncated_are_deterministic(client):
    headers, user_id = await _new_user(client, "graph-limit")
    ids = _seed_graph(user_id)

    first = await client.get(
        f"/v1/graph/neighborhood/PERSON/{ids['person_a']}?limit=1",
        headers=headers,
    )
    second = await client.get(
        f"/v1/graph/neighborhood/PERSON/{ids['person_a']}?limit=1",
        headers=headers,
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["truncated"] is True
    assert len(first.json()["edges"]) == 1

    too_large = await client.get(
        f"/v1/graph/neighborhood/PERSON/{ids['person_a']}?limit=101",
        headers=headers,
    )
    assert too_large.status_code == 422


@pytest.mark.asyncio
async def test_unconfirmed_event_center_is_not_graph_authority(client):
    headers, user_id = await _new_user(client, "graph-unconfirmed-event")
    ids = _seed_graph(user_id)

    response = await client.get(
        f"/v1/graph/neighborhood/EVENT/{ids['event_unconfirmed']}",
        headers=headers,
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "GRAPH_NODE_NOT_FOUND"


@pytest.mark.asyncio
async def test_place_delete_removes_object_and_event_place_projection(client):
    headers, user_id = await _new_user(client, "graph-place-delete")
    ids = _seed_graph(user_id)

    with SessionLocal() as db:
        place = db.get(Place, ids["place"])
        assert place is not None
        db.delete(place)
        db.commit()

    missing = await client.get(
        f"/v1/graph/neighborhood/PLACE/{ids['place']}",
        headers=headers,
    )
    assert missing.status_code == 404

    object_graph = await client.get(
        f"/v1/graph/neighborhood/OBJECT/{ids['object']}",
        headers=headers,
    )
    assert object_graph.status_code == 200
    assert object_graph.json()["edges"] == []

    event_graph = await client.get(
        f"/v1/graph/neighborhood/EVENT/{ids['event']}",
        headers=headers,
    )
    assert event_graph.status_code == 200
    assert all(
        edge["edge_kind"] != "EVENT_PLACE"
        for edge in event_graph.json()["edges"]
    )
