from __future__ import annotations

import inspect
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.core.db import SessionLocal
from app.models import (
    Memory,
    MemoryEdit,
    MemorySource,
    MemoryType,
    ObjectItem,
    ObjectLocation,
    ObjectLocationStatus,
    SourceType,
    User,
)
from app.services.answer_trust_service import (
    AnswerTrustReason,
    AnswerTrustState,
    resolve_memory_answer_trust,
    resolve_object_location_answer_trust,
)
from app.services.evidence_ranking_service import (
    EvidenceRankClass,
    rank_evidence_sources,
)
from app.services.query_service import query_memory


def _owner(db, label: str) -> UUID:
    user = User(nickname=f"answer-trust-{label}")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.id


def _memory(
    db,
    user_id: UUID,
    *,
    content: str,
    source_type: SourceType = SourceType.USER_TEXT,
    confidence: float = 1.0,
    confirmed: bool = True,
    deleted: bool = False,
    metadata: dict | None = None,
    memory_type: MemoryType = MemoryType.NOTE,
) -> Memory:
    memory = Memory(
        user_id=user_id,
        memory_type=memory_type,
        content=content,
        source_type=source_type,
        confidence=confidence,
        is_confirmed=confirmed,
        is_deleted=deleted,
        metadata_json=metadata or {},
    )
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


def _source(
    db,
    memory: Memory,
    source_type: SourceType,
    *,
    confidence: float = 1.0,
    raw_text: str = "evidence",
) -> MemorySource:
    source = MemorySource(
        memory_id=memory.id,
        source_type=source_type,
        confidence=confidence,
        raw_text=raw_text,
        created_at=datetime(2026, 9, 21, 9, 0, tzinfo=UTC),
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def test_typed_four_state_contract_and_can_answer_policy():
    assert {state.value for state in AnswerTrustState} == {
        "CONFIRMED",
        "EVIDENCE_SUPPORTED",
        "INFERENCE_ONLY",
        "NO_EVIDENCE",
    }

    with SessionLocal() as db:
        owner = _owner(db, "policy")
        memory = _memory(db, owner, content="用户记录")
        _source(db, memory, SourceType.USER_TEXT)
        resolution = resolve_memory_answer_trust(
            db,
            user_id=owner,
            memory_id=memory.id,
        )

        assert resolution.state == AnswerTrustState.EVIDENCE_SUPPORTED
        assert resolution.can_answer is True


def test_generic_confirmed_memory_with_qualifying_evidence_is_evidence_supported():
    with SessionLocal() as db:
        owner = _owner(db, "evidence-supported")
        memory = _memory(db, owner, content="普通可信记忆")
        source = _source(db, memory, SourceType.USER_TEXT, confidence=0.7)

        result = resolve_memory_answer_trust(db, user_id=owner, memory_id=memory.id)

        assert result.state == AnswerTrustState.EVIDENCE_SUPPORTED
        assert result.reason == AnswerTrustReason.MEMORY_EVIDENCE_SUPPORTED
        assert result.evidence_source_id == source.id
        assert result.can_answer is True


def test_unconfirmed_ai_memory_stays_inference_only_even_with_direct_ranked_evidence():
    with SessionLocal() as db:
        owner = _owner(db, "inference")
        memory = _memory(
            db,
            owner,
            content="AI 推测银行卡在抽屉",
            source_type=SourceType.AI_INFERENCE,
            confidence=0.99,
            confirmed=False,
        )
        direct = _source(db, memory, SourceType.USER_TEXT, confidence=1.0)

        ranked = rank_evidence_sources(db, user_id=owner, memory_ids=[memory.id])
        result = resolve_memory_answer_trust(db, user_id=owner, memory_id=memory.id)
        response = query_memory(db, owner, "银行卡抽屉")

        assert ranked[0].memory_source_id == direct.id
        assert ranked[0].rank_class == EvidenceRankClass.USER_DIRECT
        assert result.state == AnswerTrustState.INFERENCE_ONLY
        assert result.reason == AnswerTrustReason.MEMORY_INFERENCE_ONLY
        assert result.can_answer is False
        assert response.can_answer is False
        assert response.reason == "NO_EVIDENCE"


def test_unconfirmed_non_ai_memory_is_still_inference_only():
    with SessionLocal() as db:
        owner = _owner(db, "unconfirmed-non-ai")
        memory = _memory(
            db,
            owner,
            content="尚未确认的用户来源候选",
            source_type=SourceType.USER_TEXT,
            confidence=1.0,
            confirmed=False,
        )
        _source(db, memory, SourceType.USER_TEXT, confidence=1.0)

        result = resolve_memory_answer_trust(db, user_id=owner, memory_id=memory.id)

        assert result.state == AnswerTrustState.INFERENCE_ONLY
        assert result.reason == AnswerTrustReason.MEMORY_INFERENCE_ONLY
        assert result.can_answer is False


def test_high_ai_confidence_and_metadata_cannot_promote_state():
    with SessionLocal() as db:
        owner = _owner(db, "metadata-no-promotion")
        memory = _memory(
            db,
            owner,
            content="模型推断",
            source_type=SourceType.AI_INFERENCE,
            confidence=0.99,
            confirmed=False,
            metadata={
                "retrieval_score": 1.0,
                "vector_similarity": 1.0,
                "answer_trust_state": "CONFIRMED",
                "provider_confidence": 1.0,
            },
        )
        _source(db, memory, SourceType.AI_INFERENCE, confidence=0.99)

        result = resolve_memory_answer_trust(db, user_id=owner, memory_id=memory.id)

        assert result.state == AnswerTrustState.INFERENCE_ONLY
        assert result.can_answer is False


def test_resolver_contract_accepts_no_retrieval_or_model_score():
    parameters = set(inspect.signature(resolve_memory_answer_trust).parameters)
    assert parameters == {"db", "user_id", "memory_id"}


def test_no_qualifying_evidence_is_no_evidence():
    with SessionLocal() as db:
        owner = _owner(db, "no-evidence")
        memory = _memory(db, owner, content="没有足够证据")
        _source(db, memory, SourceType.AI_INFERENCE, confidence=0.99)

        result = resolve_memory_answer_trust(db, user_id=owner, memory_id=memory.id)

        assert result.state == AnswerTrustState.NO_EVIDENCE
        assert result.reason == AnswerTrustReason.MEMORY_NO_QUALIFYING_EVIDENCE
        assert result.can_answer is False


def test_low_memory_confidence_preserves_existing_gate():
    with SessionLocal() as db:
        owner = _owner(db, "low-memory-confidence")
        memory = _memory(db, owner, content="低可信 Memory", confidence=0.59)
        _source(db, memory, SourceType.USER_TEXT, confidence=1.0)

        result = resolve_memory_answer_trust(db, user_id=owner, memory_id=memory.id)

        assert result.state == AnswerTrustState.NO_EVIDENCE
        assert result.reason == AnswerTrustReason.MEMORY_TRUST_GATE_FAILED


def test_owner_isolation_and_deleted_memory_fail_closed():
    with SessionLocal() as db:
        owner_a = _owner(db, "owner-a")
        owner_b = _owner(db, "owner-b")
        foreign = _memory(db, owner_b, content="B 的 Memory")
        deleted = _memory(db, owner_a, content="已删除", deleted=True)
        _source(db, foreign, SourceType.USER_TEXT)
        _source(db, deleted, SourceType.USER_TEXT)

        cross_owner = resolve_memory_answer_trust(
            db,
            user_id=owner_a,
            memory_id=foreign.id,
        )
        deleted_result = resolve_memory_answer_trust(
            db,
            user_id=owner_a,
            memory_id=deleted.id,
        )

        assert cross_owner.state == AnswerTrustState.NO_EVIDENCE
        assert cross_owner.reason == AnswerTrustReason.MEMORY_UNAVAILABLE
        assert deleted_result.state == AnswerTrustState.NO_EVIDENCE
        assert deleted_result.reason == AnswerTrustReason.MEMORY_UNAVAILABLE


def test_current_content_edit_source_is_authoritative():
    with SessionLocal() as db:
        owner = _owner(db, "edit-source")
        memory = _memory(
            db,
            owner,
            content="当前正文",
            source_type=SourceType.USER_TEXT,
            confirmed=True,
        )
        old_source = _source(
            db,
            memory,
            SourceType.USER_PHOTO,
            confidence=1.0,
            raw_text="旧照片描述",
        )
        edit_source = _source(
            db,
            memory,
            SourceType.USER_TEXT,
            confidence=1.0,
            raw_text="当前正文",
        )
        db.add(
            MemoryEdit(
                memory_id=memory.id,
                user_id=owner,
                revision=1,
                previous_content="旧照片描述",
                new_content="当前正文",
                changed_title=False,
                changed_content=True,
                memory_source_id=edit_source.id,
            )
        )
        memory.edit_revision = 1
        db.commit()

        result = resolve_memory_answer_trust(db, user_id=owner, memory_id=memory.id)

        assert result.state == AnswerTrustState.EVIDENCE_SUPPORTED
        assert result.evidence_source_id == edit_source.id
        assert result.evidence_source_id != old_source.id


def test_latest_content_edit_with_missing_source_does_not_fall_back_to_older_revision():
    with SessionLocal() as db:
        owner = _owner(db, "latest-edit-missing-source")
        memory = _memory(db, owner, content="revision 2 current text")
        old_source = _source(
            db,
            memory,
            SourceType.USER_TEXT,
            confidence=1.0,
            raw_text="revision 1 text",
        )
        db.add_all(
            [
                MemoryEdit(
                    memory_id=memory.id,
                    user_id=owner,
                    revision=1,
                    previous_content="original",
                    new_content="revision 1 text",
                    changed_title=False,
                    changed_content=True,
                    memory_source_id=old_source.id,
                ),
                MemoryEdit(
                    memory_id=memory.id,
                    user_id=owner,
                    revision=2,
                    previous_content="revision 1 text",
                    new_content="revision 2 current text",
                    changed_title=False,
                    changed_content=True,
                    memory_source_id=None,
                ),
            ]
        )
        memory.edit_revision = 2
        db.commit()

        result = resolve_memory_answer_trust(db, user_id=owner, memory_id=memory.id)

        assert result.state == AnswerTrustState.NO_EVIDENCE
        assert result.reason == AnswerTrustReason.MEMORY_NO_QUALIFYING_EVIDENCE
        assert result.evidence_source_id is None


def test_broken_current_edit_source_fails_closed_instead_of_falling_back_to_old_evidence():
    with SessionLocal() as db:
        owner = _owner(db, "broken-edit")
        memory = _memory(db, owner, content="当前正文")
        _source(db, memory, SourceType.USER_PHOTO, confidence=1.0)
        ai_edit_source = _source(
            db,
            memory,
            SourceType.AI_INFERENCE,
            confidence=1.0,
            raw_text="不可信 edit source",
        )
        db.add(
            MemoryEdit(
                memory_id=memory.id,
                user_id=owner,
                revision=1,
                previous_content="旧正文",
                new_content="当前正文",
                changed_title=False,
                changed_content=True,
                memory_source_id=ai_edit_source.id,
            )
        )
        memory.edit_revision = 1
        db.commit()

        result = resolve_memory_answer_trust(db, user_id=owner, memory_id=memory.id)

        assert result.state == AnswerTrustState.NO_EVIDENCE
        assert result.reason == AnswerTrustReason.MEMORY_NO_QUALIFYING_EVIDENCE


def _structured_location(db, owner: UUID, *, status: ObjectLocationStatus):
    item = ObjectItem(
        user_id=owner,
        name="护照",
        normalized_name=f"passport-{uuid4()}",
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    memory = _memory(
        db,
        owner,
        content="护照在书房抽屉",
        memory_type=MemoryType.OBJECT_LOCATION,
    )
    source = _source(db, memory, SourceType.USER_TEXT, confidence=1.0)
    location = ObjectLocation(
        object_id=item.id,
        user_id=owner,
        memory_id=memory.id,
        location_text="书房抽屉",
        status=status,
        confidence=1.0,
    )
    db.add(location)
    db.commit()
    db.refresh(location)
    return location, memory, source


def test_current_structured_object_location_is_confirmed():
    with SessionLocal() as db:
        owner = _owner(db, "current-location")
        location, memory, source = _structured_location(
            db,
            owner,
            status=ObjectLocationStatus.CURRENT,
        )

        result = resolve_object_location_answer_trust(
            db,
            user_id=owner,
            object_location_id=location.id,
        )

        assert result.state == AnswerTrustState.CONFIRMED
        assert result.reason == AnswerTrustReason.CURRENT_OBJECT_LOCATION_CONFIRMED
        assert result.memory_id == memory.id
        assert result.evidence_source_id == source.id
        assert result.object_location_id == location.id
        assert result.can_answer is True


def test_stale_structured_object_location_cannot_be_confirmed():
    with SessionLocal() as db:
        owner = _owner(db, "stale-location")
        location, _, _ = _structured_location(
            db,
            owner,
            status=ObjectLocationStatus.STALE,
        )

        result = resolve_object_location_answer_trust(
            db,
            user_id=owner,
            object_location_id=location.id,
        )

        assert result.state == AnswerTrustState.NO_EVIDENCE
        assert result.reason == AnswerTrustReason.OBJECT_LOCATION_NOT_CURRENT
        assert result.can_answer is False


def test_dirty_caller_memory_identity_map_cannot_promote_persisted_inference():
    with SessionLocal() as db:
        owner = _owner(db, "persisted-memory-state")
        memory = _memory(
            db,
            owner,
            content="数据库里仍是 AI inference",
            source_type=SourceType.AI_INFERENCE,
            confidence=0.99,
            confirmed=False,
        )
        _source(db, memory, SourceType.USER_TEXT, confidence=1.0)

        # Dirty caller identity-map state must not become authoritative merely because
        # this Session already loaded the row.
        memory.is_confirmed = True
        memory.source_type = SourceType.USER_TEXT
        memory.confidence = 1.0
        before_dirty = set(db.dirty)

        result = resolve_memory_answer_trust(db, user_id=owner, memory_id=memory.id)

        assert result.state == AnswerTrustState.INFERENCE_ONLY
        assert result.reason == AnswerTrustReason.MEMORY_INFERENCE_ONLY
        assert result.can_answer is False
        assert set(db.dirty) == before_dirty
        assert memory in db.dirty


def test_dirty_caller_source_identity_map_cannot_promote_persisted_evidence():
    with SessionLocal() as db:
        owner = _owner(db, "persisted-source-state")
        memory = _memory(db, owner, content="可信 Memory 但 Evidence 仍不足")
        source = _source(
            db,
            memory,
            SourceType.USER_TEXT,
            confidence=0.59,
        )

        source.confidence = 1.0
        before_dirty = set(db.dirty)

        result = resolve_memory_answer_trust(db, user_id=owner, memory_id=memory.id)

        assert result.state == AnswerTrustState.NO_EVIDENCE
        assert result.reason == AnswerTrustReason.MEMORY_NO_QUALIFYING_EVIDENCE
        assert set(db.dirty) == before_dirty
        assert source in db.dirty


def test_answer_trust_read_path_does_not_autoflush_pending_or_dirty_state():
    with SessionLocal() as db:
        owner = _owner(db, "no-autoflush")
        memory = _memory(db, owner, content="已提交可信 Memory")
        committed = _source(db, memory, SourceType.USER_TEXT, confidence=0.8)

        dirty_owner = db.get(User, owner)
        assert dirty_owner is not None
        pending = MemorySource(
            id=uuid4(),
            memory_id=memory.id,
            source_type=SourceType.AI_INFERENCE,
            raw_text="pending source",
            confidence=0.99,
        )
        dirty_owner.nickname = "must-remain-dirty"
        db.add(pending)
        before_new = set(db.new)
        before_dirty = set(db.dirty)

        result = resolve_memory_answer_trust(db, user_id=owner, memory_id=memory.id)

        assert result.state == AnswerTrustState.EVIDENCE_SUPPORTED
        assert result.evidence_source_id == committed.id
        assert pending in db.new
        assert dirty_owner in db.dirty
        assert set(db.new) == before_new
        assert set(db.dirty) == before_dirty


def test_no_public_answer_trust_route():
    from app.main import app

    paths = {
        path
        for route in app.routes
        if (path := getattr(route, "path", None)) is not None
    }
    assert not any("answer-trust" in path or "trust-state" in path for path in paths)
