from uuid import UUID, uuid4

from app.core.db import SessionLocal
from app.models import Place


async def _new_user(client, nickname: str) -> tuple[dict[str, str], UUID]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, UUID(body["user_id"])


async def _create_object(client, headers: dict[str, str], name: str) -> None:
    response = await client.post("/v1/objects", headers=headers, json={"name": name})
    assert response.status_code == 201


def _add_place(user_id: UUID, name: str) -> None:
    with SessionLocal() as db:
        db.add(
            Place(
                id=uuid4(),
                user_id=user_id,
                name=name,
                user_name=name,
                is_user_named=True,
            )
        )
        db.commit()


async def test_intent_router_routes_existing_trusted_capabilities(client, auth_headers):
    await _create_object(client, auth_headers, "护照")

    object_route = await client.post(
        "/v1/intent/route",
        headers=auth_headers,
        json={"question": "我的护照放在哪里？"},
    )
    assert object_route.status_code == 200
    assert object_route.json() == {
        "intent": "FIND_OBJECT",
        "capability": "OBJECT_LOCATION_QUERY",
        "reason": "MATCHED",
    }

    event_route = await client.post(
        "/v1/intent/route",
        headers=auth_headers,
        json={"question": "老张什么时候来公司取合同？"},
    )
    assert event_route.status_code == 200
    assert event_route.json()["intent"] == "FIND_EVENT"
    assert event_route.json()["capability"] == "MEMORY_QUERY"

    memory_route = await client.post(
        "/v1/intent/route",
        headers=auth_headers,
        json={"question": "帮我查一下记录，老张合同"},
    )
    assert memory_route.status_code == 200
    assert memory_route.json()["intent"] == "MEMORY_SEARCH"
    assert memory_route.json()["capability"] == "MEMORY_QUERY"


async def test_place_route_is_owner_scoped_and_more_specific_than_event(client):
    headers_a, user_a = await _new_user(client, "intent-place-a")
    headers_b, _ = await _new_user(client, "intent-place-b")
    _add_place(user_a, "公司")

    own = await client.post(
        "/v1/intent/route",
        headers=headers_a,
        json={"question": "我什么时候去过公司？"},
    )
    assert own.status_code == 200
    assert own.json() == {
        "intent": "FIND_PLACE",
        "capability": "PLACE_HISTORY_QUERY",
        "reason": "MATCHED",
    }


    # A known Place name alone must not steal a generic event-time request.
    event_at_place = await client.post(
        "/v1/intent/route",
        headers=headers_a,
        json={"question": "老张什么时候来公司取合同？"},
    )
    assert event_at_place.status_code == 200
    assert event_at_place.json()["intent"] == "FIND_EVENT"
    assert event_at_place.json()["capability"] == "MEMORY_QUERY"

    place_location = await client.post(
        "/v1/intent/route",
        headers=headers_a,
        json={"question": "公司在哪里？"},
    )
    assert place_location.status_code == 200
    assert place_location.json()["intent"] == "FIND_PLACE"

    foreign = await client.post(
        "/v1/intent/route",
        headers=headers_b,
        json={"question": "公司在哪里？"},
    )
    assert foreign.status_code == 200
    assert foreign.json()["intent"] == "UNKNOWN"
    assert foreign.json()["capability"] is None


async def test_ambiguous_unsupported_and_weak_input_fail_closed(client):
    headers, user_id = await _new_user(client, "intent-ambiguous")
    await _create_object(client, headers, "钥匙")
    _add_place(user_id, "公司")

    ambiguous = await client.post(
        "/v1/intent/route",
        headers=headers,
        json={"question": "钥匙放在哪里，我什么时候去过公司？"},
    )
    assert ambiguous.status_code == 200
    assert ambiguous.json() == {
        "intent": "UNKNOWN",
        "capability": None,
        "reason": "AMBIGUOUS",
    }

    unsupported = await client.post(
        "/v1/intent/route",
        headers=headers,
        json={"question": "提醒我明天拿钥匙"},
    )
    assert unsupported.status_code == 200
    assert unsupported.json()["intent"] == "UNKNOWN"
    assert unsupported.json()["reason"] == "UNSUPPORTED"

    weak = await client.post(
        "/v1/intent/route",
        headers=headers,
        json={"question": "今天天气怎么样"},
    )
    assert weak.status_code == 200
    assert weak.json()["intent"] == "UNKNOWN"
    assert weak.json()["reason"] == "NO_SUPPORTED_RULE"


async def test_router_addition_does_not_change_existing_query_routes(client, auth_headers):
    object_id_response = await client.post(
        "/v1/objects",
        headers=auth_headers,
        json={"name": "身份证"},
    )
    assert object_id_response.status_code == 201
    object_id = object_id_response.json()["id"]

    location = await client.post(
        f"/v1/objects/{object_id}/locations",
        headers=auth_headers,
        json={"location_text": "书房抽屉"},
    )
    assert location.status_code == 201

    object_query = await client.post(
        "/v1/memory/query",
        headers=auth_headers,
        json={"question": "我的身份证在哪里？"},
    )
    assert object_query.status_code == 200
    assert object_query.json()["intent"] == "FIND_OBJECT"
    assert object_query.json()["can_answer"] is True

    memory = await client.post(
        "/v1/memories",
        headers=auth_headers,
        json={"content": "老张周五下午来公司取合同"},
    )
    assert memory.status_code == 201

    memory_query = await client.post(
        "/v1/memory/query",
        headers=auth_headers,
        json={"question": "老张合同"},
    )
    assert memory_query.status_code == 200
    assert memory_query.json()["intent"] == "MEMORY_SEARCH"
    assert memory_query.json()["can_answer"] is True

    places = await client.get("/v1/location/places", headers=auth_headers)
    assert places.status_code == 200
