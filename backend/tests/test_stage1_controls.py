from httpx import AsyncClient


async def test_marking_object_location_stale_removes_current_answer(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    created = await client.post(
        "/v1/objects",
        headers=auth_headers,
        json={"name": "旅行护照"},
    )
    assert created.status_code == 201
    object_id = created.json()["id"]

    location = await client.post(
        f"/v1/objects/{object_id}/locations",
        headers=auth_headers,
        json={
            "location_text": "书房左侧柜子第二层",
            "capture_source": "USER_TEXT",
        },
    )
    assert location.status_code == 201

    before = await client.post(
        "/v1/memory/query",
        headers=auth_headers,
        json={"question": "旅行护照在哪里？"},
    )
    assert before.status_code == 200
    assert before.json()["can_answer"] is True

    stale = await client.post(
        f"/v1/objects/{object_id}/location/stale",
        headers=auth_headers,
    )
    assert stale.status_code == 200
    assert stale.json()["status"] == "STALE"

    # [人工注释][S1-011] 明确失效后，结构化对象查询必须直接 NO_EVIDENCE，
    # 不能再通过普通 Memory 搜索把历史位置当成“当前位置”回答。
    after = await client.post(
        "/v1/memory/query",
        headers=auth_headers,
        json={"question": "旅行护照在哪里？"},
    )
    assert after.status_code == 200
    assert after.json()["can_answer"] is False
    assert after.json()["reason"] == "NO_EVIDENCE"


async def test_deleted_memory_cannot_be_answered_again(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    created = await client.post(
        "/v1/memories",
        headers=auth_headers,
        json={
            "content": "项目蓝色合同放在会议室文件柜",
            "capture_source": "USER_TEXT",
        },
    )
    assert created.status_code == 201
    memory_id = created.json()["id"]

    before = await client.post(
        "/v1/memory/query",
        headers=auth_headers,
        json={"question": "蓝色合同文件柜"},
    )
    assert before.status_code == 200
    assert before.json()["can_answer"] is True

    deleted = await client.delete(
        f"/v1/memories/{memory_id}",
        headers=auth_headers,
    )
    assert deleted.status_code == 204

    # [人工注释][S1-019] 用户删除后所有检索路径都必须立即失效。
    after = await client.post(
        "/v1/memory/query",
        headers=auth_headers,
        json={"question": "蓝色合同文件柜"},
    )
    assert after.status_code == 200
    assert after.json()["can_answer"] is False
    assert after.json()["reason"] == "NO_EVIDENCE"
