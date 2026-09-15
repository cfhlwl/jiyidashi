from httpx import AsyncClient


async def test_object_location_query_returns_latest_evidence(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    created = await client.post(
        "/v1/objects",
        headers=auth_headers,
        json={"name": "护照"},
    )
    assert created.status_code == 201
    object_id = created.json()["id"]

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
    assert "书房左侧柜子第二层" in body["answer"]
    assert len(body["evidence"]) == 1


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


async def test_deleted_memory_is_not_returned_by_search(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    created = await client.post(
        "/v1/memories",
        headers=auth_headers,
        json={
            "content": "老张周五下午来公司取合同",
            "source_type": "USER_TEXT",
        },
    )
    assert created.status_code == 201
    memory_id = created.json()["id"]

    deleted = await client.delete(
        f"/v1/memories/{memory_id}",
        headers=auth_headers,
    )
    assert deleted.status_code == 204

    query = await client.post(
        "/v1/memory/query",
        headers=auth_headers,
        json={"question": "老张合同"},
    )
    assert query.status_code == 200
    assert query.json()["can_answer"] is False
