from httpx import AsyncClient


async def _stage1_headers(client: AsyncClient, email: str) -> dict[str, str]:
    response = await client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "correct-horse-battery-staple",
            "nickname": "闭环用户",
            "timezone": "Asia/Shanghai",
            "locale": "zh-CN",
        },
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_formal_user_can_record_and_retrieve_text_memory(client: AsyncClient):
    headers = await _stage1_headers(client, "stage1-memory@example.com")

    created = await client.post(
        "/v1/memories",
        headers=headers,
        json={
            "memory_type": "NOTE",
            "content": "老张周五下午来公司取合同",
            "capture_source": "USER_TEXT",
        },
    )
    assert created.status_code == 201

    # [人工注释][S1-003][S1-012] 正式账号必须走同一可信 Evidence 查询链，不允许另开低可信捷径。
    query = await client.post(
        "/v1/memory/query",
        headers=headers,
        json={"question": "老张合同"},
    )
    assert query.status_code == 200
    body = query.json()
    assert body["can_answer"] is True
    assert body["evidence"]
    assert body["memory_ids"] == [created.json()["id"]]


async def test_formal_user_object_location_query_returns_evidence(client: AsyncClient):
    headers = await _stage1_headers(client, "stage1-object@example.com")

    object_response = await client.post(
        "/v1/objects",
        headers=headers,
        json={"name": "护照", "category": "证件"},
    )
    assert object_response.status_code == 201
    object_id = object_response.json()["id"]

    location = await client.post(
        f"/v1/objects/{object_id}/locations",
        headers=headers,
        json={
            "location_text": "书房左侧柜子第二层",
            "capture_source": "USER_TEXT",
        },
    )
    assert location.status_code == 201

    # [人工注释][S1-009][S1-010][S1-014] 物品闭环必须返回事实答案和可追溯 Evidence。
    query = await client.post(
        "/v1/memory/query",
        headers=headers,
        json={"question": "我的护照在哪里？"},
    )
    assert query.status_code == 200
    body = query.json()
    assert body["can_answer"] is True
    assert "书房左侧柜子第二层" in body["answer"]
    assert body["certainty"] in {"confirmed", "evidenced"}
    assert len(body["evidence"]) >= 1
    assert body["evidence"][0]["excerpt"]
    assert body["evidence"][0]["occurred_at"]


async def test_formal_user_query_without_evidence_still_refuses_to_guess(client: AsyncClient):
    headers = await _stage1_headers(client, "stage1-no-evidence@example.com")

    query = await client.post(
        "/v1/memory/query",
        headers=headers,
        json={"question": "我的银行卡放在哪里？"},
    )
    assert query.status_code == 200
    body = query.json()
    assert body["can_answer"] is False
    assert body["answer"] is None
    assert body["reason"] == "NO_EVIDENCE"
