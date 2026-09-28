from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.db import SessionLocal
from app.models import Memory, MemorySource, SourceType, User
from app.person_duration_models import PersonKnownDurationStatus
from app.person_memory_models import PersonMemoryLink, PersonMemoryRelationKind
from app.person_models import Person
from app.services.person_duration_service import (
    MAX_DURATION_EVIDENCE_SCAN,
    PersonDurationError,
    get_person_known_duration,
)


def _seed_person(db, label: str = "friend") -> tuple[User, Person]:
    user = User(id=uuid4(), nickname=f"user-{label}")
    person = Person(id=uuid4(), user_id=user.id, display_name=label)
    db.add_all([user, person])
    db.commit()
    return user, person


def _memory(
    db,
    *,
    user_id,
    person_id,
    occurred_at: datetime,
    relation_kind: PersonMemoryRelationKind,
    trusted: bool = True,
    source_type: SourceType = SourceType.USER_TEXT,
    confidence: float = 1.0,
) -> tuple[Memory, PersonMemoryLink]:
    memory = Memory(
        id=uuid4(),
        user_id=user_id,
        content=f"evidence-{uuid4()}",
        occurred_at=occurred_at,
        source_type=source_type,
        confidence=confidence,
        is_confirmed=trusted,
        is_deleted=False,
    )
    db.add(memory)
    db.flush()
    if trusted:
        db.add(
            MemorySource(
                id=uuid4(),
                memory_id=memory.id,
                source_type=source_type,
                confidence=confidence,
                raw_text="private raw source",
            )
        )
    link = PersonMemoryLink(
        id=uuid4(),
        user_id=user_id,
        person_id=person_id,
        memory_id=memory.id,
        relation_kind=relation_kind,
    )
    db.add(link)
    db.commit()
    return memory, link


def test_met_is_only_known_duration_authority_and_older_related_does_not_move_origin():
    as_of = datetime(2026, 9, 28, 12, tzinfo=UTC)
    with SessionLocal() as db:
        user, person = _seed_person(db, "Alice")
        related, _ = _memory(
            db,
            user_id=user.id,
            person_id=person.id,
            occurred_at=as_of - timedelta(days=1000),
            relation_kind=PersonMemoryRelationKind.RELATED,
        )
        met, _ = _memory(
            db,
            user_id=user.id,
            person_id=person.id,
            occurred_at=as_of - timedelta(days=365, hours=12),
            relation_kind=PersonMemoryRelationKind.MET,
        )

        result = get_person_known_duration(
            db, user_id=user.id, person_id=person.id, now=as_of
        )

        assert result.status == PersonKnownDurationStatus.KNOWN_SINCE_MET
        assert result.at_least_since_at == met.occurred_at.replace(tzinfo=UTC)
        assert result.elapsed_days == 365
        assert result.earliest_related_at is None
        assert result.evidence is not None
        assert result.evidence.relation_kind == PersonMemoryRelationKind.MET
        assert result.evidence.memory_id == met.id
        assert result.evidence.memory_id != related.id


def test_related_only_never_returns_known_duration():
    as_of = datetime(2026, 9, 28, tzinfo=UTC)
    with SessionLocal() as db:
        user, person = _seed_person(db, "Bob")
        related, _ = _memory(
            db,
            user_id=user.id,
            person_id=person.id,
            occurred_at=as_of - timedelta(days=50),
            relation_kind=PersonMemoryRelationKind.RELATED,
        )
        result = get_person_known_duration(
            db, user_id=user.id, person_id=person.id, now=as_of
        )
        assert result.status == PersonKnownDurationStatus.RELATED_EVIDENCE_ONLY
        assert result.at_least_since_at is None
        assert result.elapsed_days is None
        assert result.earliest_related_at == related.occurred_at.replace(tzinfo=UTC)
        assert result.evidence is not None
        assert result.evidence.relation_kind == PersonMemoryRelationKind.RELATED


def test_future_evidence_is_ignored_and_no_trusted_evidence_is_typed():
    as_of = datetime(2026, 9, 28, tzinfo=UTC)
    with SessionLocal() as db:
        user, person = _seed_person(db, "Future")
        _memory(
            db,
            user_id=user.id,
            person_id=person.id,
            occurred_at=as_of + timedelta(seconds=1),
            relation_kind=PersonMemoryRelationKind.MET,
        )
        _memory(
            db,
            user_id=user.id,
            person_id=person.id,
            occurred_at=as_of + timedelta(days=1),
            relation_kind=PersonMemoryRelationKind.RELATED,
        )
        result = get_person_known_duration(
            db, user_id=user.id, person_id=person.id, now=as_of
        )
        assert result.status == PersonKnownDurationStatus.NO_TRUSTED_EVIDENCE
        assert result.evidence is None


def test_s3_013_excludes_unconfirmed_ai_and_low_confidence_then_uses_later_trusted_met():
    as_of = datetime(2026, 9, 28, tzinfo=UTC)
    with SessionLocal() as db:
        user, person = _seed_person(db, "Trust")
        _memory(
            db,
            user_id=user.id,
            person_id=person.id,
            occurred_at=as_of - timedelta(days=400),
            relation_kind=PersonMemoryRelationKind.MET,
            trusted=False,
        )
        _memory(
            db,
            user_id=user.id,
            person_id=person.id,
            occurred_at=as_of - timedelta(days=300),
            relation_kind=PersonMemoryRelationKind.MET,
            source_type=SourceType.AI_INFERENCE,
        )
        _memory(
            db,
            user_id=user.id,
            person_id=person.id,
            occurred_at=as_of - timedelta(days=200),
            relation_kind=PersonMemoryRelationKind.MET,
            confidence=0.1,
        )
        trusted, _ = _memory(
            db,
            user_id=user.id,
            person_id=person.id,
            occurred_at=as_of - timedelta(days=100),
            relation_kind=PersonMemoryRelationKind.MET,
        )
        result = get_person_known_duration(
            db, user_id=user.id, person_id=person.id, now=as_of
        )
        assert result.status == PersonKnownDurationStatus.KNOWN_SINCE_MET
        assert result.evidence is not None
        assert result.evidence.memory_id == trusted.id


def test_earliest_occurred_at_then_uuid_then_link_id_is_deterministic():
    as_of = datetime(2026, 9, 28, tzinfo=UTC)
    same_time = as_of - timedelta(days=10)
    with SessionLocal() as db:
        user, person = _seed_person(db, "Tie")
        high_id = uuid4()
        low_id = uuid4()
        if str(low_id) > str(high_id):
            low_id, high_id = high_id, low_id

        high = Memory(
            id=high_id,
            user_id=user.id,
            content="high",
            occurred_at=same_time,
            source_type=SourceType.USER_TEXT,
            confidence=1.0,
            is_confirmed=True,
        )
        low = Memory(
            id=low_id,
            user_id=user.id,
            content="low",
            occurred_at=same_time,
            source_type=SourceType.USER_TEXT,
            confidence=1.0,
            is_confirmed=True,
        )
        db.add_all([high, low])
        db.flush()
        db.add_all([
            MemorySource(memory_id=high.id, source_type=SourceType.USER_TEXT, confidence=1.0),
            MemorySource(memory_id=low.id, source_type=SourceType.USER_TEXT, confidence=1.0),
            PersonMemoryLink(user_id=user.id, person_id=person.id, memory_id=high.id, relation_kind=PersonMemoryRelationKind.MET),
            PersonMemoryLink(user_id=user.id, person_id=person.id, memory_id=low.id, relation_kind=PersonMemoryRelationKind.MET),
        ])
        db.commit()
        result = get_person_known_duration(
            db, user_id=user.id, person_id=person.id, now=as_of
        )
        assert result.evidence is not None
        assert str(result.evidence.memory_id) == str(low_id)


def test_met_cap_plus_one_is_incomplete_and_does_not_fall_back_to_related():
    as_of = datetime(2026, 9, 28, tzinfo=UTC)
    with SessionLocal() as db:
        user, person = _seed_person(db, "Cap")
        for index in range(MAX_DURATION_EVIDENCE_SCAN + 1):
            _memory(
                db,
                user_id=user.id,
                person_id=person.id,
                occurred_at=as_of - timedelta(days=MAX_DURATION_EVIDENCE_SCAN + 10 - index),
                relation_kind=PersonMemoryRelationKind.MET,
                trusted=False,
            )
        _memory(
            db,
            user_id=user.id,
            person_id=person.id,
            occurred_at=as_of - timedelta(days=2000),
            relation_kind=PersonMemoryRelationKind.RELATED,
        )
        result = get_person_known_duration(
            db, user_id=user.id, person_id=person.id, now=as_of
        )
        assert result.status == PersonKnownDurationStatus.EVIDENCE_INCOMPLETE
        assert result.evidence is None
        assert result.earliest_related_at is None


def test_trusted_met_before_cap_is_complete_even_with_later_tail():
    as_of = datetime(2026, 9, 28, tzinfo=UTC)
    with SessionLocal() as db:
        user, person = _seed_person(db, "CapHit")
        trusted, _ = _memory(
            db,
            user_id=user.id,
            person_id=person.id,
            occurred_at=as_of - timedelta(days=1000),
            relation_kind=PersonMemoryRelationKind.MET,
        )
        for index in range(MAX_DURATION_EVIDENCE_SCAN + 2):
            _memory(
                db,
                user_id=user.id,
                person_id=person.id,
                occurred_at=as_of - timedelta(days=900 - index),
                relation_kind=PersonMemoryRelationKind.MET,
                trusted=False,
            )
        result = get_person_known_duration(
            db, user_id=user.id, person_id=person.id, now=as_of
        )
        assert result.status == PersonKnownDurationStatus.KNOWN_SINCE_MET
        assert result.evidence is not None
        assert result.evidence.memory_id == trusted.id


@pytest.mark.asyncio
async def test_api_uses_current_user_and_cross_owner_is_person_not_found(client):
    token_a = await client.post("/v1/auth/dev-token", json={"nickname": "duration-api-a"})
    token_b = await client.post("/v1/auth/dev-token", json={"nickname": "duration-api-b"})
    assert token_a.status_code == 200
    assert token_b.status_code == 200
    headers_a = {"Authorization": f"Bearer {token_a.json()['access_token']}"}
    headers_b = {"Authorization": f"Bearer {token_b.json()['access_token']}"}

    created = await client.post(
        "/v1/people",
        headers=headers_a,
        json={"display_name": "API Person", "aliases": []},
    )
    assert created.status_code == 201
    person_id = created.json()["id"]

    own = await client.get(
        f"/v1/people/{person_id}/known-duration",
        headers=headers_a,
    )
    assert own.status_code == 200
    assert own.json()["status"] == "NO_TRUSTED_EVIDENCE"
    assert own.json()["person_id"] == person_id

    denied = await client.get(
        f"/v1/people/{person_id}/known-duration",
        headers=headers_b,
    )
    assert denied.status_code == 404
    assert denied.json()["detail"] == "PERSON_NOT_FOUND"


def test_owner_isolation_is_person_not_found():
    with SessionLocal() as db:
        owner, person = _seed_person(db, "Owner")
        other = User(id=uuid4(), nickname="other")
        db.add(other)
        db.commit()
        with pytest.raises(PersonDurationError) as exc:
            get_person_known_duration(
                db,
                user_id=other.id,
                person_id=person.id,
                now=datetime(2026, 9, 28, tzinfo=UTC),
            )
        assert exc.value.code == "PERSON_NOT_FOUND"
        assert exc.value.status_code == 404


def test_response_projection_has_no_memory_content_or_raw_source():
    as_of = datetime(2026, 9, 28, tzinfo=UTC)
    with SessionLocal() as db:
        user, person = _seed_person(db, "Projection")
        _memory(
            db,
            user_id=user.id,
            person_id=person.id,
            occurred_at=as_of - timedelta(days=1),
            relation_kind=PersonMemoryRelationKind.MET,
        )
        result = get_person_known_duration(
            db, user_id=user.id, person_id=person.id, now=as_of
        )
        payload = result.model_dump(mode="json")
        assert set(payload) == {
            "status",
            "person_id",
            "display_name",
            "as_of",
            "at_least_since_at",
            "elapsed_days",
            "earliest_related_at",
            "evidence",
        }
        assert payload["evidence"] is not None
        assert set(payload["evidence"]) == {
            "person_memory_link_id",
            "memory_id",
            "memory_source_id",
            "relation_kind",
            "trust_state",
            "occurred_at",
        }
        text = str(payload)
        assert "private raw source" not in text
        assert "evidence-" not in text


def test_exact_statuses_read_only_no_ai_graph_or_0025_migration():
    assert [item.value for item in PersonKnownDurationStatus] == [
        "KNOWN_SINCE_MET",
        "RELATED_EVIDENCE_ONLY",
        "NO_TRUSTED_EVIDENCE",
        "EVIDENCE_INCOMPLETE",
    ]

    root = Path(__file__).resolve().parents[1]
    source = (root / "app/services/person_duration_service.py").read_text()
    for forbidden in [
        "AIGateway",
        "EmbeddingGateway",
        "answer_from_memory_rag",
        "retrieve_memories",
        "PersonRelationship",
        "graph_projection",
        "LifeEvent",
        "LifeStage",
        ".commit(",
        ".add(",
        ".delete(",
        "Person.created_at",
        "PersonMemoryLink.created_at",
    ]:
        assert forbidden not in source
    assert "Memory.occurred_at" in source
    assert "resolve_memory_answer_trust" in source
    assert list((root / "migrations/versions").glob("0025*")) == []
