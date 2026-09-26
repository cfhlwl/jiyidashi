from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.models import Memory, MemorySource
from app.person_models import Person, PersonAlias


async def _new_user(client, nickname: str) -> tuple[dict[str, str], UUID]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, UUID(body["user_id"])


@pytest.mark.asyncio
async def test_people_require_authentication(client):
    response = await client.get("/v1/people")
    assert response.status_code in {401, 403}


@pytest.mark.asyncio
async def test_person_crud_is_owner_scoped_revision_safe_and_aliases_are_structured(client):
    headers_a, user_a = await _new_user(client, "person-a")
    headers_b, user_b = await _new_user(client, "person-b")

    forged = await client.post(
        "/v1/people",
        headers=headers_a,
        json={"display_name": "老王", "user_id": str(user_b)},
    )
    assert forged.status_code == 422

    created = await client.post(
        "/v1/people",
        headers=headers_a,
        json={
            "display_name": " 老王 ",
            "relationship_label": " 同事 ",
            "note": " 大学毕业后认识 ",
            "aliases": [" 王老师 ", "wang   lao shi", "WANG LAO SHI"],
        },
    )
    assert created.status_code == 201
    person = created.json()
    person_id = person["id"]
    assert person["display_name"] == "老王"
    assert person["relationship_label"] == "同事"
    assert person["note"] == "大学毕业后认识"
    assert [row["alias"] for row in person["aliases"]] == ["wang lao shi", "王老师"]
    assert person["revision"] == 0

    # Same owner and different owners may both have duplicate display names.
    same_name_a = await client.post(
        "/v1/people", headers=headers_a, json={"display_name": "老王"}
    )
    same_name_b = await client.post(
        "/v1/people", headers=headers_b, json={"display_name": "老王", "aliases": ["王老师"]}
    )
    assert same_name_a.status_code == 201
    assert same_name_b.status_code == 201
    assert same_name_a.json()["id"] != person_id

    cross_owner = await client.get(f"/v1/people/{person_id}", headers=headers_b)
    assert cross_owner.status_code == 404
    assert cross_owner.json()["detail"] == "PERSON_NOT_FOUND"

    listed_a = await client.get("/v1/people?limit=100", headers=headers_a)
    listed_b = await client.get("/v1/people?limit=100", headers=headers_b)
    assert listed_a.status_code == 200
    assert {row["id"] for row in listed_a.json()} == {person_id, same_name_a.json()["id"]}
    assert {row["id"] for row in listed_b.json()} == {same_name_b.json()["id"]}

    # Omitted fields remain unchanged; aliases=[] is the only clear operation.
    patched = await client.patch(
        f"/v1/people/{person_id}",
        headers=headers_a,
        json={"expected_revision": 0, "note": "新的备注"},
    )
    assert patched.status_code == 200
    assert patched.json()["relationship_label"] == "同事"
    assert len(patched.json()["aliases"]) == 2
    assert patched.json()["note"] == "新的备注"
    assert patched.json()["revision"] == 1

    stale = await client.patch(
        f"/v1/people/{person_id}",
        headers=headers_a,
        json={"expected_revision": 0, "display_name": "旧写入"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == "PERSON_REVISION_CONFLICT"

    null_aliases = await client.patch(
        f"/v1/people/{person_id}",
        headers=headers_a,
        json={"expected_revision": 1, "aliases": None},
    )
    assert null_aliases.status_code == 422

    cleared = await client.patch(
        f"/v1/people/{person_id}",
        headers=headers_a,
        json={
            "expected_revision": 1,
            "relationship_label": None,
            "note": None,
            "aliases": [],
        },
    )
    assert cleared.status_code == 200
    assert cleared.json()["relationship_label"] is None
    assert cleared.json()["note"] is None
    assert cleared.json()["aliases"] == []
    assert cleared.json()["revision"] == 2

    deleted = await client.delete(f"/v1/people/{person_id}", headers=headers_a)
    assert deleted.status_code == 204
    missing = await client.get(f"/v1/people/{person_id}", headers=headers_a)
    assert missing.status_code == 404
    with SessionLocal() as db:
        assert db.scalar(
            select(func.count()).select_from(PersonAlias).where(
                PersonAlias.person_id == UUID(person_id)
            )
        ) == 0
        assert db.scalar(select(Person.id).where(Person.user_id == user_b)) is not None


@pytest.mark.asyncio
async def test_person_profile_management_creates_no_memory_or_evidence(client):
    headers, user_id = await _new_user(client, "person-no-memory")
    with SessionLocal() as db:
        before_memories = db.scalar(
            select(func.count()).select_from(Memory).where(Memory.user_id == user_id)
        )
        before_sources = db.scalar(select(func.count()).select_from(MemorySource))

    created = await client.post(
        "/v1/people",
        headers=headers,
        json={"display_name": "张老师", "aliases": ["老师"]},
    )
    assert created.status_code == 201
    patched = await client.patch(
        f"/v1/people/{created.json()['id']}",
        headers=headers,
        json={"expected_revision": 0, "note": "用户自己维护的备注"},
    )
    assert patched.status_code == 200

    with SessionLocal() as db:
        after_memories = db.scalar(
            select(func.count()).select_from(Memory).where(Memory.user_id == user_id)
        )
        after_sources = db.scalar(select(func.count()).select_from(MemorySource))
    assert before_memories == after_memories
    assert before_sources == after_sources


@pytest.mark.asyncio
async def test_person_export_is_owner_scoped(client):
    headers_a, user_a = await _new_user(client, "person-export-a")
    headers_b, _ = await _new_user(client, "person-export-b")

    person_a = await client.post(
        "/v1/people",
        headers=headers_a,
        json={
            "display_name": "妈妈",
            "relationship_label": "家人",
            "note": "A private note",
            "aliases": ["母亲"],
        },
    )
    assert person_a.status_code == 201
    person_b = await client.post(
        "/v1/people",
        headers=headers_b,
        json={"display_name": "B secret person", "note": "B secret note"},
    )
    assert person_b.status_code == 201

    exported = await client.get("/v1/export/data", headers=headers_a)
    assert exported.status_code == 200
    people = exported.json()["people"]
    assert len(people) == 1
    assert people[0]["id"] == person_a.json()["id"]
    assert people[0]["display_name"] == "妈妈"
    assert people[0]["aliases"][0]["alias"] == "母亲"
    assert people[0]["revision"] == 0
    assert "normalized_alias" not in people[0]["aliases"]
    assert "B secret person" not in exported.text
    assert "B secret note" not in exported.text

    with SessionLocal() as db:
        assert db.scalar(select(Person.id).where(Person.user_id == user_a)) is not None
