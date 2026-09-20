import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.db import SessionLocal
from app.entity_models import EntityKind, EntityLinkReason, EntityLinkStatus
from app.models import Memory, MemorySource, ObjectItem, Place
from app.services.ai_gateway import AIGateway, DeterministicAIProvider
from app.services.entity_extraction_service import (
    EntityExtractionError,
    extract_and_link_entities,
    extract_entity_candidates,
)


def _settings() -> Settings:
    return Settings(
        app_env="test",
        ai_provider="disabled",
        ai_max_input_chars=10000,
        ai_max_output_tokens=1024,
    )


def _gateway(output: dict | str) -> tuple[AIGateway, DeterministicAIProvider]:
    output_text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
    provider = DeterministicAIProvider(output_text=output_text)
    return AIGateway(_settings(), provider), provider


async def _new_user(client, nickname: str) -> UUID:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    return UUID(response.json()["user_id"])


async def test_extraction_uses_ai_gateway_and_retains_inference_provenance():
    text = "明天下午把护照带到公司找老张开会"
    gateway, provider = _gateway(
        {
            "entities": [
                {"kind": "TIME", "text": "明天下午"},
                {"kind": "OBJECT", "text": "护照"},
                {"kind": "PLACE", "text": "公司"},
                {"kind": "PERSON", "text": "老张"},
                {"kind": "EVENT", "text": "开会"},
            ]
        }
    )

    result = await extract_entity_candidates(text=text, gateway=gateway)

    assert [candidate.kind for candidate in result.candidates] == [
        EntityKind.TIME,
        EntityKind.OBJECT,
        EntityKind.PLACE,
        EntityKind.PERSON,
        EntityKind.EVENT,
    ]
    assert result.candidates[1].normalized_text == "护照"
    assert all(candidate.provenance.trust_class == "inference" for candidate in result.candidates)
    assert all(
        candidate.provenance.gateway_request_id
        == result.candidates[0].provenance.gateway_request_id
        for candidate in result.candidates
    )
    assert result.candidates[0].provenance.provider == "deterministic"
    assert result.candidates[0].provenance.model == "fixture"
    assert provider.requests[0].purpose == "entity.extract"
    assert provider.requests[0].input_text == text
    assert "do not return IDs" in provider.requests[0].system_instruction


@pytest.mark.parametrize(
    ("output", "code"),
    [
        ("not-json", "ENTITY_EXTRACTION_INVALID_RESPONSE"),
        ({}, "ENTITY_EXTRACTION_INVALID_RESPONSE"),
        (
            {"entities": [{"kind": "OBJECT", "text": "护照", "entity_id": str(uuid4())}]},
            "ENTITY_EXTRACTION_INVALID_RESPONSE",
        ),
        (
            {"entities": [{"kind": "UNSUPPORTED", "text": "护照"}]},
            "ENTITY_EXTRACTION_INVALID_RESPONSE",
        ),
        (
            {"entities": [{"kind": "OBJECT", "text": "银行卡"}]},
            "ENTITY_EXTRACTION_NON_LITERAL_CANDIDATE",
        ),
        (
            {"entities": [{"kind": "OBJECT", "text": "护照"}], "owner_id": str(uuid4())},
            "ENTITY_EXTRACTION_INVALID_RESPONSE",
        ),
    ],
)
async def test_untrusted_provider_response_is_strict_and_fail_closed(output, code):
    gateway, _ = _gateway(output)

    with pytest.raises(EntityExtractionError) as exc_info:
        await extract_entity_candidates(text="我的护照在抽屉", gateway=gateway)

    assert exc_info.value.code == code


async def test_linker_uses_only_owner_scoped_unique_object_and_place(client):
    user_a = await _new_user(client, "entity-owner-a")
    user_b = await _new_user(client, "entity-owner-b")
    object_id = uuid4()
    place_id = uuid4()
    with SessionLocal() as db:
        db.add_all(
            [
                ObjectItem(
                    id=object_id,
                    user_id=user_a,
                    name="Work Laptop",
                    normalized_name="work laptop",
                ),
                Place(
                    id=place_id,
                    user_id=user_a,
                    name="公司",
                    user_name="公司",
                    is_user_named=True,
                ),
                ObjectItem(
                    id=uuid4(),
                    user_id=user_b,
                    name="护照",
                    normalized_name="护照",
                ),
                Place(
                    id=uuid4(),
                    user_id=user_b,
                    name="仓库",
                    user_name="仓库",
                    is_user_named=True,
                ),
            ]
        )
        db.commit()

    text = "work   laptop 放在公司；护照在仓库；老张明天来"
    gateway, _ = _gateway(
        {
            "entities": [
                {"kind": "OBJECT", "text": "work   laptop"},
                {"kind": "PLACE", "text": "公司"},
                {"kind": "OBJECT", "text": "护照"},
                {"kind": "PLACE", "text": "仓库"},
                {"kind": "PERSON", "text": "老张"},
                {"kind": "TIME", "text": "明天"},
            ]
        }
    )

    with SessionLocal() as db:
        result = await extract_and_link_entities(
            db,
            user_id=user_a,
            text=text,
            gateway=gateway,
        )

    by_text = {link.candidate.text: link for link in result.links}
    assert by_text["work   laptop"].status == EntityLinkStatus.LINKED
    assert by_text["work   laptop"].reason == EntityLinkReason.NORMALIZED_MATCH
    assert by_text["work   laptop"].linked_entity.entity_id == object_id
    assert by_text["公司"].status == EntityLinkStatus.LINKED
    assert by_text["公司"].reason == EntityLinkReason.EXACT_MATCH
    assert by_text["公司"].linked_entity.entity_id == place_id

    # These entities exist only for another owner and therefore remain unresolved.
    assert by_text["护照"].status == EntityLinkStatus.UNRESOLVED
    assert by_text["护照"].reason == EntityLinkReason.NO_MATCH
    assert by_text["仓库"].status == EntityLinkStatus.UNRESOLVED
    assert by_text["仓库"].reason == EntityLinkReason.NO_MATCH

    # Person/Time are candidates only in this foundation; no persistence model is invented.
    assert by_text["老张"].reason == EntityLinkReason.NOT_LINKABLE
    assert by_text["明天"].reason == EntityLinkReason.NOT_LINKABLE


async def test_duplicate_place_name_is_ambiguous_not_guessed(client):
    user_id = await _new_user(client, "entity-duplicate-place")
    with SessionLocal() as db:
        db.add_all(
            [
                Place(
                    id=uuid4(),
                    user_id=user_id,
                    name="咖啡店",
                    user_name="咖啡店",
                    is_user_named=True,
                ),
                Place(
                    id=uuid4(),
                    user_id=user_id,
                    name="咖啡店",
                    user_name="咖啡店",
                    is_user_named=True,
                ),
            ]
        )
        db.commit()

    gateway, _ = _gateway({"entities": [{"kind": "PLACE", "text": "咖啡店"}]})
    with SessionLocal() as db:
        result = await extract_and_link_entities(
            db,
            user_id=user_id,
            text="我今天去了咖啡店",
            gateway=gateway,
        )

    link = result.links[0]
    assert link.status == EntityLinkStatus.UNRESOLVED
    assert link.reason == EntityLinkReason.AMBIGUOUS
    assert link.linked_entity is None


async def test_extraction_and_linking_do_not_create_entities_or_memory(client):
    user_id = await _new_user(client, "entity-no-side-effects")
    gateway, _ = _gateway(
        {
            "entities": [
                {"kind": "OBJECT", "text": "新钥匙"},
                {"kind": "PLACE", "text": "新办公室"},
                {"kind": "PERSON", "text": "小王"},
            ]
        }
    )

    with SessionLocal() as db:
        before = {
            "objects": db.scalar(select(func.count()).select_from(ObjectItem)),
            "places": db.scalar(select(func.count()).select_from(Place)),
            "memories": db.scalar(select(func.count()).select_from(Memory)),
            "sources": db.scalar(select(func.count()).select_from(MemorySource)),
        }
        result = await extract_and_link_entities(
            db,
            user_id=user_id,
            text="新钥匙放到新办公室，交给小王",
            gateway=gateway,
        )
        after = {
            "objects": db.scalar(select(func.count()).select_from(ObjectItem)),
            "places": db.scalar(select(func.count()).select_from(Place)),
            "memories": db.scalar(select(func.count()).select_from(Memory)),
            "sources": db.scalar(select(func.count()).select_from(MemorySource)),
        }

    assert before == after
    assert all(link.status == EntityLinkStatus.UNRESOLVED for link in result.links)
    assert [link.reason for link in result.links] == [
        EntityLinkReason.NO_MATCH,
        EntityLinkReason.NO_MATCH,
        EntityLinkReason.NOT_LINKABLE,
    ]
