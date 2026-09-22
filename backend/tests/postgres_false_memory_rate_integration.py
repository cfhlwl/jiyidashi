"""PostgreSQL invariants for S3-019 False Memory Rate."""

from __future__ import annotations

from uuid import UUID, uuid4

from app.core.db import SessionLocal
from app.false_memory_rate_models import FalseMemoryRateStatus
from app.memory_feedback_models import MemoryFeedback, MemoryFeedbackAction
from app.models import Memory, User
from app.services.account_deletion_service import delete_current_account
from app.services.data_deletion_service import delete_all_user_data
from app.services.false_memory_rate_service import compute_false_memory_rate


class EmptyStorage:
    def iter_object_keys(self, prefix: str):
        return iter(())

    def delete_object(self, object_key: str) -> None:
        return None


def _seed_owner(label: str) -> tuple[UUID, UUID]:
    owner = uuid4()
    memory_id = uuid4()
    with SessionLocal() as seed:
        seed.add(User(id=owner, nickname=f"fmr-{label}"))
        seed.flush()
        seed.add(Memory(id=memory_id, user_id=owner, content=f"memory-{label}"))
        seed.commit()
    return owner, memory_id


def _feedback(
    *,
    owner: UUID,
    memory_id: UUID,
    revision: int,
    action: MemoryFeedbackAction,
    result_revision: int | None = None,
) -> None:
    with SessionLocal() as db:
        db.add(
            MemoryFeedback(
                user_id=owner,
                memory_id=memory_id,
                client_uuid=uuid4(),
                memory_revision=revision,
                result_revision=result_revision,
                action=action.value,
            )
        )
        db.commit()


def _cleanup(owner: UUID) -> None:
    with SessionLocal() as db:
        user = db.get(User, owner)
        if user is not None:
            db.delete(user)
            db.commit()


def _canonical_revision_aggregation_and_owner_isolation() -> None:
    owner, memory_id = _seed_owner("canonical")
    other, other_memory_id = _seed_owner("other")

    _feedback(
        owner=owner,
        memory_id=memory_id,
        revision=0,
        action=MemoryFeedbackAction.CONFIRM,
    )
    _feedback(
        owner=owner,
        memory_id=memory_id,
        revision=0,
        action=MemoryFeedbackAction.CORRECT,
        result_revision=1,
    )
    _feedback(
        owner=owner,
        memory_id=memory_id,
        revision=0,
        action=MemoryFeedbackAction.DELETE,
    )
    _feedback(
        owner=owner,
        memory_id=memory_id,
        revision=1,
        action=MemoryFeedbackAction.CONFIRM,
    )
    _feedback(
        owner=owner,
        memory_id=memory_id,
        revision=2,
        action=MemoryFeedbackAction.DELETE,
    )
    _feedback(
        owner=other,
        memory_id=other_memory_id,
        revision=0,
        action=MemoryFeedbackAction.CORRECT,
        result_revision=1,
    )

    with SessionLocal() as db:
        result = compute_false_memory_rate(db, user_id=owner)

    assert result.status == FalseMemoryRateStatus.READY
    assert result.false_revisions == 1
    assert result.confirmed_true_revisions == 1
    assert result.judged_revisions == 2
    assert result.delete_only_revisions == 1
    assert result.false_memory_rate == 0.5

    _cleanup(owner)
    _cleanup(other)


def _data_delete_removes_metric_authority() -> None:
    owner, memory_id = _seed_owner("data-delete")
    _feedback(
        owner=owner,
        memory_id=memory_id,
        revision=0,
        action=MemoryFeedbackAction.CORRECT,
        result_revision=1,
    )

    with SessionLocal() as db:
        assert compute_false_memory_rate(db, user_id=owner).false_revisions == 1
        deletion = delete_all_user_data(
            db,
            user_id=owner,
            request_id=uuid4(),
            storage=EmptyStorage(),
        )
        assert deletion.completed is True
        result = compute_false_memory_rate(db, user_id=owner)

    assert result.status == FalseMemoryRateStatus.NO_JUDGED_REVISIONS
    assert result.judged_revisions == 0
    _cleanup(owner)


def _account_delete_removes_metric_authority() -> None:
    owner, memory_id = _seed_owner("account-delete")
    _feedback(
        owner=owner,
        memory_id=memory_id,
        revision=0,
        action=MemoryFeedbackAction.CONFIRM,
    )

    with SessionLocal() as db:
        before = compute_false_memory_rate(db, user_id=owner)
        assert before.confirmed_true_revisions == 1

        deleted = delete_current_account(
            db,
            user_id=owner,
            request_id=uuid4(),
            storage=EmptyStorage(),
            local_cleanup_ready=True,
        )
        assert deleted.completed is True

        after = compute_false_memory_rate(db, user_id=owner)

    assert after.status == FalseMemoryRateStatus.NO_JUDGED_REVISIONS
    assert after.judged_revisions == 0


def main() -> None:
    _canonical_revision_aggregation_and_owner_isolation()
    _data_delete_removes_metric_authority()
    _account_delete_removes_metric_authority()


if __name__ == "__main__":
    main()
