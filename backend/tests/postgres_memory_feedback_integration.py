"""PostgreSQL invariants for S3-018 Memory Feedback."""

from __future__ import annotations

from threading import Barrier, Thread
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.idempotency_models import ClientMutation
from app.memory_feedback_contracts import MemoryFeedbackCreate
from app.memory_feedback_models import MemoryFeedback, MemoryFeedbackAction
from app.models import Memory, User
from app.services.data_deletion_service import delete_all_user_data
from app.services.idempotency_service import (
    IdempotencyConflict,
    execute_idempotent_mutation,
)
from app.services.memory_feedback_service import (
    MemoryFeedbackConflict,
    apply_memory_feedback,
    get_memory_feedback_for_user,
)


class EmptyStorage:
    def iter_object_keys(self, prefix: str):
        return iter(())

    def delete_object(self, object_key: str) -> None:
        return None


def _execute_feedback(
    db,
    *,
    owner: UUID,
    memory_id: UUID,
    client_uuid: UUID,
    payload: MemoryFeedbackCreate,
) -> MemoryFeedback:
    fingerprint_payload = {
        "memory_id": str(memory_id),
        **payload.model_dump(mode="json"),
    }
    return execute_idempotent_mutation(
        db,
        user_id=owner,
        operation_type="MEMORY_FEEDBACK",
        client_uuid=client_uuid,
        fingerprint_payload=fingerprint_payload,
        resource_type="MEMORY_FEEDBACK",
        create_resource=lambda session: apply_memory_feedback(
            session,
            user_id=owner,
            memory_id=memory_id,
            client_uuid=client_uuid,
            payload=payload,
        ),
        resource_id=lambda feedback: feedback.id,
        load_resource=lambda session, resource_id: get_memory_feedback_for_user(
            session,
            user_id=owner,
            feedback_id=resource_id,
        ),
    )


def _seed_memory(nickname: str, content: str) -> tuple[UUID, UUID]:
    owner = uuid4()
    memory_id = uuid4()
    with SessionLocal() as seed:
        seed.add(User(id=owner, nickname=nickname))
        seed.flush()
        seed.add(Memory(id=memory_id, user_id=owner, content=content))
        seed.commit()
    return owner, memory_id


def _cleanup_user(owner: UUID) -> None:
    with SessionLocal() as cleanup:
        user = cleanup.get(User, owner)
        if user is not None:
            cleanup.delete(user)
            cleanup.commit()


def _same_key_same_correct_replays_one_success() -> None:
    owner, memory_id = _seed_memory("feedback-same-correct", "revision zero")
    client_uuid = uuid4()
    start = Barrier(2)
    results: list[tuple[UUID, int | None]] = []
    errors: list[BaseException] = []

    payload = MemoryFeedbackCreate(
        action=MemoryFeedbackAction.CORRECT,
        expected_revision=0,
        content="corrected once",
    )

    def worker() -> None:
        try:
            start.wait(timeout=15)
            with SessionLocal() as db:
                feedback = _execute_feedback(
                    db,
                    owner=owner,
                    memory_id=memory_id,
                    client_uuid=client_uuid,
                    payload=payload,
                )
                results.append((feedback.id, feedback.result_revision))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    first = Thread(target=worker, name="same-key-correct-first")
    second = Thread(target=worker, name="same-key-correct-second")
    first.start()
    second.start()
    first.join(timeout=20)
    second.join(timeout=20)
    assert not first.is_alive()
    assert not second.is_alive()
    if errors:
        raise errors[0]

    assert len(results) == 2
    assert len({item[0] for item in results}) == 1
    assert [item[1] for item in results] == [1, 1]

    with SessionLocal() as verify:
        memory = verify.get(Memory, memory_id)
        assert memory is not None
        assert memory.edit_revision == 1
        assert memory.content == "corrected once"
        assert (
            verify.scalar(
                select(func.count(MemoryFeedback.id)).where(
                    MemoryFeedback.user_id == owner,
                    MemoryFeedback.memory_id == memory_id,
                    MemoryFeedback.action == MemoryFeedbackAction.CORRECT.value,
                )
            )
            == 1
        )
        assert (
            verify.scalar(
                select(func.count(ClientMutation.id)).where(
                    ClientMutation.user_id == owner,
                    ClientMutation.operation_type == "MEMORY_FEEDBACK",
                    ClientMutation.client_uuid == client_uuid,
                )
            )
            == 1
        )
    _cleanup_user(owner)


def _same_key_same_delete_replays_one_audit() -> None:
    owner, memory_id = _seed_memory("feedback-same-delete", "delete once")
    client_uuid = uuid4()
    start = Barrier(2)
    results: list[UUID] = []
    errors: list[BaseException] = []

    payload = MemoryFeedbackCreate(
        action=MemoryFeedbackAction.DELETE,
        expected_revision=0,
    )

    def worker() -> None:
        try:
            start.wait(timeout=15)
            with SessionLocal() as db:
                feedback = _execute_feedback(
                    db,
                    owner=owner,
                    memory_id=memory_id,
                    client_uuid=client_uuid,
                    payload=payload,
                )
                results.append(feedback.id)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    first = Thread(target=worker, name="same-key-delete-first")
    second = Thread(target=worker, name="same-key-delete-second")
    first.start()
    second.start()
    first.join(timeout=20)
    second.join(timeout=20)
    assert not first.is_alive()
    assert not second.is_alive()
    if errors:
        raise errors[0]

    assert len(results) == 2
    assert len(set(results)) == 1

    with SessionLocal() as verify:
        memory = verify.get(Memory, memory_id)
        assert memory is not None
        assert memory.is_deleted is True
        assert (
            verify.scalar(
                select(func.count(MemoryFeedback.id)).where(
                    MemoryFeedback.user_id == owner,
                    MemoryFeedback.memory_id == memory_id,
                    MemoryFeedback.action == MemoryFeedbackAction.DELETE.value,
                )
            )
            == 1
        )
        assert (
            verify.scalar(
                select(func.count(ClientMutation.id)).where(
                    ClientMutation.user_id == owner,
                    ClientMutation.operation_type == "MEMORY_FEEDBACK",
                    ClientMutation.client_uuid == client_uuid,
                )
            )
            == 1
        )
    _cleanup_user(owner)


def _same_key_different_request_has_stable_idempotency_conflict() -> None:
    owner, memory_id = _seed_memory("feedback-key-conflict", "revision zero")
    client_uuid = uuid4()
    start = Barrier(2)
    successes: list[UUID] = []
    conflicts: list[str] = []
    errors: list[BaseException] = []

    def worker(content: str) -> None:
        payload = MemoryFeedbackCreate(
            action=MemoryFeedbackAction.CORRECT,
            expected_revision=0,
            content=content,
        )
        try:
            start.wait(timeout=15)
            with SessionLocal() as db:
                try:
                    feedback = _execute_feedback(
                        db,
                        owner=owner,
                        memory_id=memory_id,
                        client_uuid=client_uuid,
                        payload=payload,
                    )
                    successes.append(feedback.id)
                except IdempotencyConflict as exc:
                    db.rollback()
                    conflicts.append(exc.detail)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    first = Thread(target=worker, args=("first payload",), name="key-conflict-first")
    second = Thread(target=worker, args=("second payload",), name="key-conflict-second")
    first.start()
    second.start()
    first.join(timeout=20)
    second.join(timeout=20)
    assert not first.is_alive()
    assert not second.is_alive()
    if errors:
        raise errors[0]

    assert len(successes) == 1
    assert conflicts == ["IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST"]

    with SessionLocal() as verify:
        memory = verify.get(Memory, memory_id)
        assert memory is not None
        assert memory.edit_revision == 1
        assert memory.content in {"first payload", "second payload"}
        assert (
            verify.scalar(
                select(func.count(MemoryFeedback.id)).where(
                    MemoryFeedback.user_id == owner,
                    MemoryFeedback.memory_id == memory_id,
                )
            )
            == 1
        )
        assert (
            verify.scalar(
                select(func.count(ClientMutation.id)).where(
                    ClientMutation.user_id == owner,
                    ClientMutation.operation_type == "MEMORY_FEEDBACK",
                    ClientMutation.client_uuid == client_uuid,
                )
            )
            == 1
        )
    _cleanup_user(owner)


def _concurrent_different_corrections_conflict() -> None:
    owner, memory_id = _seed_memory("feedback-race", "revision zero")
    start = Barrier(2)
    results: list[int] = []
    conflicts: list[str] = []
    errors: list[BaseException] = []

    def worker(content: str) -> None:
        try:
            start.wait(timeout=15)
            with SessionLocal() as db:
                try:
                    feedback = apply_memory_feedback(
                        db,
                        user_id=owner,
                        memory_id=memory_id,
                        client_uuid=uuid4(),
                        payload=MemoryFeedbackCreate(
                            action=MemoryFeedbackAction.CORRECT,
                            expected_revision=0,
                            content=content,
                        ),
                    )
                    db.commit()
                    results.append(feedback.result_revision or -1)
                except MemoryFeedbackConflict as exc:
                    db.rollback()
                    conflicts.append(exc.code)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    first = Thread(target=worker, args=("first correction",), name="feedback-first")
    second = Thread(target=worker, args=("second correction",), name="feedback-second")
    first.start()
    second.start()
    first.join(timeout=20)
    second.join(timeout=20)
    assert not first.is_alive()
    assert not second.is_alive()
    if errors:
        raise errors[0]

    assert results == [1]
    assert conflicts == ["MEMORY_FEEDBACK_REVISION_CONFLICT"]

    with SessionLocal() as verify:
        memory = verify.get(Memory, memory_id)
        assert memory is not None
        assert memory.edit_revision == 1
        assert memory.content in {"first correction", "second correction"}
        assert (
            verify.scalar(
                select(func.count(MemoryFeedback.id)).where(
                    MemoryFeedback.user_id == owner,
                    MemoryFeedback.memory_id == memory_id,
                    MemoryFeedback.action == MemoryFeedbackAction.CORRECT.value,
                )
            )
            == 1
        )
    _cleanup_user(owner)


def _data_delete_removes_feedback_owner_only() -> None:
    owner = uuid4()
    other = uuid4()
    owner_memory = uuid4()
    other_memory = uuid4()

    with SessionLocal() as seed:
        seed.add_all(
            [
                User(id=owner, nickname="feedback-delete-owner"),
                User(id=other, nickname="feedback-delete-other"),
            ]
        )
        seed.flush()
        seed.add_all(
            [
                Memory(id=owner_memory, user_id=owner, content="owner"),
                Memory(id=other_memory, user_id=other, content="other"),
            ]
        )
        seed.flush()
        seed.add_all(
            [
                MemoryFeedback(
                    user_id=owner,
                    memory_id=owner_memory,
                    client_uuid=uuid4(),
                    memory_revision=0,
                    action=MemoryFeedbackAction.CONFIRM.value,
                ),
                MemoryFeedback(
                    user_id=other,
                    memory_id=other_memory,
                    client_uuid=uuid4(),
                    memory_revision=0,
                    action=MemoryFeedbackAction.CONFIRM.value,
                ),
            ]
        )
        seed.commit()

    with SessionLocal() as deleting:
        result = delete_all_user_data(
            deleting,
            user_id=owner,
            request_id=uuid4(),
            storage=EmptyStorage(),
        )
        assert result.completed is True
        assert result.deleted_counts["memory_feedbacks"] == 1

    with SessionLocal() as verify:
        assert (
            verify.scalar(
                select(func.count(MemoryFeedback.id)).where(
                    MemoryFeedback.user_id == owner
                )
            )
            == 0
        )
        assert (
            verify.scalar(
                select(func.count(MemoryFeedback.id)).where(
                    MemoryFeedback.user_id == other
                )
            )
            == 1
        )
        verify.delete(verify.get(User, owner))
        verify.delete(verify.get(User, other))
        verify.commit()


def main() -> None:
    _same_key_same_correct_replays_one_success()
    _same_key_same_delete_replays_one_audit()
    _same_key_different_request_has_stable_idempotency_conflict()
    _concurrent_different_corrections_conflict()
    _data_delete_removes_feedback_owner_only()


if __name__ == "__main__":
    main()
