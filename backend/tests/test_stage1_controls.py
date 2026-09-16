from datetime import UTC, datetime, timedelta

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

    # [人工注释][S1-011] 明确失效后，多种位置问法都必须由结构化状态拦截，
    # 不能再通过普通 Memory 搜索把历史位置当成“当前位置”回答。
    for question in ("旅行护照在哪里？", "旅行护照在什么地方？"):
        after = await client.post(
            "/v1/memory/query",
            headers=auth_headers,
            json={"question": question},
        )
        assert after.status_code == 200
        assert after.json()["can_answer"] is False
        assert after.json()["reason"] == "NO_EVIDENCE"
        assert after.json()["intent"] == "FIND_OBJECT"


async def test_location_wording_without_matching_object_still_searches_normal_memory(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    # [人工注释][S1-011] “哪里”本身不能把所有查询都误判为 FIND_OBJECT。
    # 没有匹配 Object 时，普通 NOTE 仍应继续走 Memory Evidence 搜索。
    created = await client.post(
        "/v1/memories",
        headers=auth_headers,
        json={
            "content": "老张在上海办公室工作",
            "capture_source": "USER_TEXT",
        },
    )
    assert created.status_code == 201

    query = await client.post(
        "/v1/memory/query",
        headers=auth_headers,
        json={"question": "老张在哪里工作？"},
    )
    assert query.status_code == 200
    assert query.json()["can_answer"] is True
    assert query.json()["intent"] == "MEMORY_SEARCH"
    assert "上海办公室" in query.json()["answer"]


async def test_overlapping_object_names_choose_unique_most_specific_object(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    # [人工注释][S1-PR3-FIX-005] “护照”是“旅行护照”的子串时，
    # 必须先唯一解析更具体 Object，不能按两个 Object 的位置更新时间选答案。
    generic = await client.post(
        "/v1/objects",
        headers=auth_headers,
        json={"name": "护照"},
    )
    specific = await client.post(
        "/v1/objects",
        headers=auth_headers,
        json={"name": "旅行护照"},
    )
    assert generic.status_code == 201
    assert specific.status_code == 201

    now = datetime.now(UTC)
    specific_location = await client.post(
        f"/v1/objects/{specific.json()['id']}/locations",
        headers=auth_headers,
        json={
            "location_text": "书房",
            "capture_source": "USER_TEXT",
            "recorded_at": (now - timedelta(hours=2)).isoformat(),
        },
    )
    generic_location = await client.post(
        f"/v1/objects/{generic.json()['id']}/locations",
        headers=auth_headers,
        json={
            "location_text": "鞋柜",
            "capture_source": "USER_TEXT",
            "recorded_at": (now - timedelta(hours=1)).isoformat(),
        },
    )
    assert specific_location.status_code == 201
    assert generic_location.status_code == 201

    query = await client.post(
        "/v1/memory/query",
        headers=auth_headers,
        json={"question": "旅行护照在哪里？"},
    )
    assert query.status_code == 200
    payload = query.json()
    assert payload["can_answer"] is True
    assert payload["intent"] == "FIND_OBJECT"
    assert "旅行护照" in payload["answer"]
    assert "书房" in payload["answer"]
    assert "鞋柜" not in payload["answer"]


async def test_specific_stale_object_never_falls_back_to_shorter_current_object(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    # [人工注释][S1-PR3-FIX-005] 更具体 Object 一旦 STALE，
    # 不允许退回其较短子串 Object 的合法 CURRENT 来制造跨对象错误答案。
    generic = await client.post(
        "/v1/objects",
        headers=auth_headers,
        json={"name": "护照"},
    )
    specific = await client.post(
        "/v1/objects",
        headers=auth_headers,
        json={"name": "旅行护照"},
    )
    assert generic.status_code == 201
    assert specific.status_code == 201

    now = datetime.now(UTC)
    specific_location = await client.post(
        f"/v1/objects/{specific.json()['id']}/locations",
        headers=auth_headers,
        json={
            "location_text": "书房",
            "capture_source": "USER_TEXT",
            "recorded_at": (now - timedelta(hours=2)).isoformat(),
        },
    )
    generic_location = await client.post(
        f"/v1/objects/{generic.json()['id']}/locations",
        headers=auth_headers,
        json={
            "location_text": "鞋柜",
            "capture_source": "USER_TEXT",
            "recorded_at": (now - timedelta(hours=1)).isoformat(),
        },
    )
    assert specific_location.status_code == 201
    assert generic_location.status_code == 201

    stale = await client.post(
        f"/v1/objects/{specific.json()['id']}/location/stale",
        headers=auth_headers,
    )
    assert stale.status_code == 200

    query = await client.post(
        "/v1/memory/query",
        headers=auth_headers,
        json={"question": "旅行护照在哪里？"},
    )
    assert query.status_code == 200
    payload = query.json()
    assert payload["can_answer"] is False
    assert payload["reason"] == "NO_EVIDENCE"
    assert payload["intent"] == "FIND_OBJECT"


async def test_equal_best_object_matches_return_no_evidence(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    # [人工注释][S1-PR3-FIX-005] 两个同等具体 Object 都出现在问题中时，
    # 当前单对象查询协议无法唯一判断用户目标，可信规则要求不猜测。
    first = await client.post(
        "/v1/objects",
        headers=auth_headers,
        json={"name": "旅行护照"},
    )
    second = await client.post(
        "/v1/objects",
        headers=auth_headers,
        json={"name": "备用钥匙"},
    )
    assert first.status_code == 201
    assert second.status_code == 201

    first_location = await client.post(
        f"/v1/objects/{first.json()['id']}/locations",
        headers=auth_headers,
        json={"location_text": "书房", "capture_source": "USER_TEXT"},
    )
    second_location = await client.post(
        f"/v1/objects/{second.json()['id']}/locations",
        headers=auth_headers,
        json={"location_text": "玄关", "capture_source": "USER_TEXT"},
    )
    assert first_location.status_code == 201
    assert second_location.status_code == 201

    query = await client.post(
        "/v1/memory/query",
        headers=auth_headers,
        json={"question": "旅行护照和备用钥匙在哪里？"},
    )
    assert query.status_code == 200
    payload = query.json()
    assert payload["can_answer"] is False
    assert payload["reason"] == "NO_EVIDENCE"
    assert payload["intent"] == "FIND_OBJECT"


async def test_stale_watermark_blocks_late_offline_location_from_becoming_current(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    # [人工注释][S1-011] 用户明确失效形成时间水位；CURRENT 为空也不能让更早的离线位置复活。
    created = await client.post(
        "/v1/objects",
        headers=auth_headers,
        json={"name": "备用钥匙"},
    )
    object_id = created.json()["id"]
    current_time = datetime.now(UTC)

    current = await client.post(
        f"/v1/objects/{object_id}/locations",
        headers=auth_headers,
        json={
            "location_text": "书房",
            "capture_source": "USER_TEXT",
            "recorded_at": current_time.isoformat(),
        },
    )
    assert current.status_code == 201
    assert current.json()["status"] == "CURRENT"

    stale = await client.post(
        f"/v1/objects/{object_id}/location/stale",
        headers=auth_headers,
    )
    assert stale.status_code == 200

    late_old = await client.post(
        f"/v1/objects/{object_id}/locations",
        headers=auth_headers,
        json={
            "location_text": "卧室",
            "capture_source": "USER_TEXT",
            "recorded_at": (current_time - timedelta(hours=1)).isoformat(),
        },
    )
    assert late_old.status_code == 201
    assert late_old.json()["status"] == "STALE"

    current_after = await client.get(
        f"/v1/objects/{object_id}/location",
        headers=auth_headers,
    )
    assert current_after.status_code == 404

    query = await client.post(
        "/v1/memory/query",
        headers=auth_headers,
        json={"question": "备用钥匙在什么地方？"},
    )
    assert query.status_code == 200
    assert query.json()["can_answer"] is False
    assert query.json()["reason"] == "NO_EVIDENCE"


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
