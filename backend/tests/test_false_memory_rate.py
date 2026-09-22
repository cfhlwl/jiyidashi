from __future__ import annotations

import inspect
from uuid import UUID, uuid4

from app.core.db import SessionLocal
from app.false_memory_rate_models import FalseMemoryRateStatus
from app.memory_feedback_models import MemoryFeedback, MemoryFeedbackAction
from app.models import Memory, SourceType, User
from app.services.data_deletion_service import delete_all_user_data
from app.services.false_memory_rate_service import compute_false_memory_rate


class EmptyStorage:
    def iter_object_keys(self, prefix: str):
        return iter(())

    def delete_object(self, object_key: str) -> None:
        return None


def _owner(db, label: str) -> UUID:
    user = User(nickname=f"false-memory-rate-{label}")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.id


def _memory(
    db,
    user_id: UUID,
    *,
    content: str = "memory",
    confidence: float = 1.0,
    source_type: SourceType = SourceType.USER_TEXT,
) -> Memory:
    memory = Memory(
        user_id=user_id,
        content=content,
        confidence=confidence,
        source_type=source_type,
    )
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


def _feedback(
    db,
    *,
    user_id: UUID,
    memory_id: UUID,
    revision: int,
    action: MemoryFeedbackAction,
    result_revision: int | None = None,
) -> MemoryFeedback:
    row = MemoryFeedback(
        user_id=user_id,
        memory_id=memory_id,
        client_uuid=uuid4(),
        memory_revision=revision,
        result_revision=result_revision,
        action=action.value,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_no_feedback_returns_typed_no_observation_state():
    with SessionLocal() as db:
        owner = _owner(db, "none")

        result = compute_false_memory_rate(db, user_id=owner)

        assert result.status == FalseMemoryRateStatus.NO_JUDGED_REVISIONS
        assert result.false_revisions == 0
        assert result.confirmed_true_revisions == 0
        assert result.judged_revisions == 0
        assert result.delete_only_revisions == 0
        assert result.false_memory_rate is None


def test_one_confirm_is_zero_false_over_one_judged():
    with SessionLocal() as db:
        owner = _owner(db, "confirm")
        memory = _memory(db, owner)
        _feedback(
            db,
            user_id=owner,
            memory_id=memory.id,
            revision=0,
            action=MemoryFeedbackAction.CONFIRM,
        )

        result = compute_false_memory_rate(db, user_id=owner)

        assert result.status == FalseMemoryRateStatus.READY
        assert result.false_revisions == 0
        assert result.confirmed_true_revisions == 1
        assert result.judged_revisions == 1
        assert result.false_memory_rate == 0.0


def test_one_correct_is_one_false_over_one_judged():
    with SessionLocal() as db:
        owner = _owner(db, "correct")
        memory = _memory(db, owner)
        _feedback(
            db,
            user_id=owner,
            memory_id=memory.id,
            revision=0,
            action=MemoryFeedbackAction.CORRECT,
            result_revision=1,
        )

        result = compute_false_memory_rate(db, user_id=owner)

        assert result.status == FalseMemoryRateStatus.READY
        assert result.false_revisions == 1
        assert result.confirmed_true_revisions == 0
        assert result.judged_revisions == 1
        assert result.false_memory_rate == 1.0


def test_confirm_then_correct_same_revision_counts_exactly_one_false():
    with SessionLocal() as db:
        owner = _owner(db, "confirm-correct")
        memory = _memory(db, owner)
        _feedback(
            db,
            user_id=owner,
            memory_id=memory.id,
            revision=0,
            action=MemoryFeedbackAction.CONFIRM,
        )
        _feedback(
            db,
            user_id=owner,
            memory_id=memory.id,
            revision=0,
            action=MemoryFeedbackAction.CORRECT,
            result_revision=1,
        )

        result = compute_false_memory_rate(db, user_id=owner)

        assert result.false_revisions == 1
        assert result.confirmed_true_revisions == 0
        assert result.judged_revisions == 1
        assert result.false_memory_rate == 1.0


def test_delete_only_is_reported_but_excluded_from_judged_denominator():
    with SessionLocal() as db:
        owner = _owner(db, "delete-only")
        memory = _memory(db, owner)
        _feedback(
            db,
            user_id=owner,
            memory_id=memory.id,
            revision=0,
            action=MemoryFeedbackAction.DELETE,
        )

        result = compute_false_memory_rate(db, user_id=owner)

        assert result.status == FalseMemoryRateStatus.NO_JUDGED_REVISIONS
        assert result.delete_only_revisions == 1
        assert result.judged_revisions == 0
        assert result.false_memory_rate is None


def test_confirm_plus_delete_remains_confirmed_true_without_correct():
    with SessionLocal() as db:
        owner = _owner(db, "confirm-delete")
        memory = _memory(db, owner)
        _feedback(
            db,
            user_id=owner,
            memory_id=memory.id,
            revision=0,
            action=MemoryFeedbackAction.CONFIRM,
        )
        _feedback(
            db,
            user_id=owner,
            memory_id=memory.id,
            revision=0,
            action=MemoryFeedbackAction.DELETE,
        )

        result = compute_false_memory_rate(db, user_id=owner)

        assert result.confirmed_true_revisions == 1
        assert result.false_revisions == 0
        assert result.delete_only_revisions == 0


def test_correct_plus_delete_remains_false():
    with SessionLocal() as db:
        owner = _owner(db, "correct-delete")
        memory = _memory(db, owner)
        _feedback(
            db,
            user_id=owner,
            memory_id=memory.id,
            revision=0,
            action=MemoryFeedbackAction.CORRECT,
            result_revision=1,
        )
        _feedback(
            db,
            user_id=owner,
            memory_id=memory.id,
            revision=0,
            action=MemoryFeedbackAction.DELETE,
        )

        result = compute_false_memory_rate(db, user_id=owner)

        assert result.false_revisions == 1
        assert result.confirmed_true_revisions == 0
        assert result.delete_only_revisions == 0


def test_correction_result_revision_is_unjudged_until_explicit_feedback():
    with SessionLocal() as db:
        owner = _owner(db, "result-unjudged")
        memory = _memory(db, owner)
        _feedback(
            db,
            user_id=owner,
            memory_id=memory.id,
            revision=0,
            action=MemoryFeedbackAction.CORRECT,
            result_revision=1,
        )

        first = compute_false_memory_rate(db, user_id=owner)
        assert first.false_revisions == 1
        assert first.judged_revisions == 1

        _feedback(
            db,
            user_id=owner,
            memory_id=memory.id,
            revision=1,
            action=MemoryFeedbackAction.CONFIRM,
        )
        second = compute_false_memory_rate(db, user_id=owner)

        assert second.false_revisions == 1
        assert second.confirmed_true_revisions == 1
        assert second.judged_revisions == 2
        assert second.false_memory_rate == 0.5


def test_different_revisions_of_same_memory_are_independent_units():
    with SessionLocal() as db:
        owner = _owner(db, "revisions")
        memory = _memory(db, owner)
        _feedback(
            db,
            user_id=owner,
            memory_id=memory.id,
            revision=0,
            action=MemoryFeedbackAction.CONFIRM,
        )
        _feedback(
            db,
            user_id=owner,
            memory_id=memory.id,
            revision=1,
            action=MemoryFeedbackAction.CORRECT,
            result_revision=2,
        )

        result = compute_false_memory_rate(db, user_id=owner)

        assert result.false_revisions == 1
        assert result.confirmed_true_revisions == 1
        assert result.judged_revisions == 2
        assert result.false_memory_rate == 0.5


def test_cross_owner_feedback_is_excluded():
    with SessionLocal() as db:
        owner_a = _owner(db, "owner-a")
        owner_b = _owner(db, "owner-b")
        memory_a = _memory(db, owner_a)
        memory_b = _memory(db, owner_b)
        _feedback(
            db,
            user_id=owner_a,
            memory_id=memory_a.id,
            revision=0,
            action=MemoryFeedbackAction.CONFIRM,
        )
        _feedback(
            db,
            user_id=owner_b,
            memory_id=memory_b.id,
            revision=0,
            action=MemoryFeedbackAction.CORRECT,
            result_revision=1,
        )

        result = compute_false_memory_rate(db, user_id=owner_a)

        assert result.false_revisions == 0
        assert result.confirmed_true_revisions == 1
        assert result.judged_revisions == 1


def test_metric_does_not_depend_on_memory_content_confidence_or_source_type():
    with SessionLocal() as db:
        owner = _owner(db, "memory-independent")
        memory = _memory(
            db,
            owner,
            content="original",
            confidence=0.1,
            source_type=SourceType.AI_INFERENCE,
        )
        _feedback(
            db,
            user_id=owner,
            memory_id=memory.id,
            revision=0,
            action=MemoryFeedbackAction.CONFIRM,
        )

        first = compute_false_memory_rate(db, user_id=owner)

        memory.content = "dirty caller content"
        memory.confidence = 1.0
        memory.source_type = SourceType.USER_TEXT
        second = compute_false_memory_rate(db, user_id=owner)

        assert first == second
        assert memory in db.dirty


def test_pending_or_dirty_feedback_in_caller_session_is_not_metric_authority():
    with SessionLocal() as db:
        owner = _owner(db, "persisted-only")
        memory = _memory(db, owner)
        committed = _feedback(
            db,
            user_id=owner,
            memory_id=memory.id,
            revision=0,
            action=MemoryFeedbackAction.CONFIRM,
        )

        committed.action = MemoryFeedbackAction.CORRECT.value
        pending = MemoryFeedback(
            user_id=owner,
            memory_id=memory.id,
            client_uuid=uuid4(),
            memory_revision=1,
            action=MemoryFeedbackAction.CORRECT.value,
            result_revision=2,
        )
        db.add(pending)
        before_new = set(db.new)
        before_dirty = set(db.dirty)

        result = compute_false_memory_rate(db, user_id=owner)

        assert result.false_revisions == 0
        assert result.confirmed_true_revisions == 1
        assert set(db.new) == before_new
        assert set(db.dirty) == before_dirty


def test_data_delete_feedback_removal_changes_metric_to_no_observation():
    with SessionLocal() as db:
        owner = _owner(db, "data-delete")
        memory = _memory(db, owner)
        _feedback(
            db,
            user_id=owner,
            memory_id=memory.id,
            revision=0,
            action=MemoryFeedbackAction.CORRECT,
            result_revision=1,
        )
        assert compute_false_memory_rate(db, user_id=owner).false_revisions == 1

        result = delete_all_user_data(
            db,
            user_id=owner,
            request_id=uuid4(),
            storage=EmptyStorage(),
        )
        assert result.completed is True

        metric = compute_false_memory_rate(db, user_id=owner)
        assert metric.status == FalseMemoryRateStatus.NO_JUDGED_REVISIONS
        assert metric.judged_revisions == 0
        assert metric.false_memory_rate is None


def test_false_memory_rate_foundation_has_no_ai_or_public_api_path():
    import app.services.false_memory_rate_service as service_module
    from app.main import app

    source = inspect.getsource(service_module)
    assert "AIGateway" not in source
    assert "app.services.ai_gateway" not in source
    assert "Memory." not in source

    paths = {
        path
        for route in app.routes
        if isinstance((path := getattr(route, "path", None)), str)
    }
    assert all("false-memory" not in path for path in paths)
    assert all("false_memory" not in path for path in paths)
