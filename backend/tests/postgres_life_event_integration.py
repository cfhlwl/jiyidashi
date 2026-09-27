"""PostgreSQL concurrency and owner-FK gate for V2-005 LifeEvent foundation."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Barrier, Thread
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.db import SessionLocal
from app.life_event_models import LifeEvent, LifeEventKind, LifeEventMemoryLink
from app.life_event_schemas import LifeEventCreate, LifeEventPatch
from app.models import Memory, Place, User
from app.services.life_event_service import (
    LifeEventError,
    create_life_event,
    create_life_event_memory_link,
    delete_life_event,
    patch_life_event,
)
from app.services.memory_service import get_memory_for_user, soft_delete_memory


def _seed_owner(label: str) -> UUID:
    user_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname=label))
        db.commit()
    return user_id


def _seed_event(user_id: UUID, title: str) -> UUID:
    with SessionLocal() as db:
        event = create_life_event(
            db,
            user_id=user_id,
            payload=LifeEventCreate(
                event_kind=LifeEventKind.WORK,
                title=title,
                started_at=datetime.now(UTC),
            ),
        )
        return event.id


def _seed_memory(user_id: UUID, suffix: str) -> UUID:
    memory_id = uuid4()
    with SessionLocal() as db:
        db.add(
            Memory(
                id=memory_id,
                user_id=user_id,
                content=f"evidence-{suffix}",
                occurred_at=datetime.now(UTC),
                is_confirmed=True,
            )
        )
        db.commit()
    return memory_id


def _patch_patch_single_winner(user_id: UUID, event_id: UUID) -> None:
    barrier = Barrier(2)
    outcomes: list[str] = []
    errors: list[BaseException] = []

    def worker(note: str) -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                try:
                    event = patch_life_event(
                        db,
                        user_id=user_id,
                        life_event_id=event_id,
                        payload=LifeEventPatch(expected_revision=0, note=note),
                    )
                    outcomes.append(f"ok:{event.note}:{event.revision}")
                except LifeEventError as exc:
                    outcomes.append(f"err:{exc.code}")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        Thread(target=worker, args=("writer-a",)),
        Thread(target=worker, args=("writer-b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    if errors:
        raise errors[0]

    assert len([item for item in outcomes if item.startswith("ok:")]) == 1
    assert outcomes.count("err:LIFE_EVENT_REVISION_CONFLICT") == 1
    with SessionLocal() as db:
        event = db.get(LifeEvent, event_id)
        assert event is not None
        assert event.revision == 1
        assert event.note in {"writer-a", "writer-b"}


def _delete_patch_no_resurrection(user_id: UUID, event_id: UUID) -> None:
    with SessionLocal() as db:
        event = db.get(LifeEvent, event_id)
        assert event is not None
        event.revision = 4
        event.note = "before-delete-race"
        db.commit()

    barrier = Barrier(2)
    outcomes: list[str] = []
    errors: list[BaseException] = []

    def deleter() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                try:
                    delete_life_event(db, user_id=user_id, life_event_id=event_id)
                    outcomes.append("deleted")
                except LifeEventError as exc:
                    outcomes.append(f"delete:{exc.code}")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def patcher() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                try:
                    patch_life_event(
                        db,
                        user_id=user_id,
                        life_event_id=event_id,
                        payload=LifeEventPatch(
                            expected_revision=4,
                            note="late-patch",
                        ),
                    )
                    outcomes.append("patched")
                except LifeEventError as exc:
                    outcomes.append(f"patch:{exc.code}")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [Thread(target=deleter), Thread(target=patcher)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    if errors:
        raise errors[0]

    assert "deleted" in outcomes
    with SessionLocal() as db:
        assert db.get(LifeEvent, event_id) is None


def _evidence_vs_memory_delete(
    user_id: UUID,
    event_id: UUID,
    memory_id: UUID,
) -> None:
    barrier = Barrier(2)
    errors: list[BaseException] = []

    def creator() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                try:
                    create_life_event_memory_link(
                        db,
                        user_id=user_id,
                        life_event_id=event_id,
                        memory_id=memory_id,
                    )
                except LifeEventError as exc:
                    assert exc.code == "MEMORY_NOT_FOUND"
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def deleter() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                memory = get_memory_for_user(
                    db,
                    user_id,
                    memory_id,
                    for_update=True,
                )
                assert memory is not None
                soft_delete_memory(db, memory)
                db.commit()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [Thread(target=creator), Thread(target=deleter)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    if errors:
        raise errors[0]

    with SessionLocal() as db:
        memory = db.get(Memory, memory_id)
        assert memory is not None
        assert memory.is_deleted is True
        assert db.scalar(
            select(LifeEventMemoryLink.id).where(
                LifeEventMemoryLink.user_id == user_id,
                LifeEventMemoryLink.memory_id == memory_id,
            )
        ) is None


def _evidence_vs_event_delete(
    user_id: UUID,
    event_id: UUID,
    memory_id: UUID,
) -> None:
    barrier = Barrier(2)
    errors: list[BaseException] = []

    def creator() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                try:
                    create_life_event_memory_link(
                        db,
                        user_id=user_id,
                        life_event_id=event_id,
                        memory_id=memory_id,
                    )
                except LifeEventError as exc:
                    assert exc.code == "LIFE_EVENT_NOT_FOUND"
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def deleter() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                delete_life_event(db, user_id=user_id, life_event_id=event_id)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [Thread(target=creator), Thread(target=deleter)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    if errors:
        raise errors[0]

    with SessionLocal() as db:
        assert db.get(LifeEvent, event_id) is None
        assert db.scalar(
            select(LifeEventMemoryLink.id).where(
                LifeEventMemoryLink.life_event_id == event_id
            )
        ) is None
        memory = db.get(Memory, memory_id)
        assert memory is not None
        assert memory.is_deleted is False


def _owner_composite_fks_reject_cross_owner(
    owner_a: UUID,
    owner_b: UUID,
) -> None:
    place_b = uuid4()
    memory_b = uuid4()
    event_a = _seed_event(owner_a, "owner-a-event")
    with SessionLocal() as db:
        db.add(Place(id=place_b, user_id=owner_b, name="foreign-place"))
        db.add(
            Memory(
                id=memory_b,
                user_id=owner_b,
                content="foreign-memory",
                is_confirmed=True,
            )
        )
        db.commit()

    with SessionLocal() as db:
        db.add(
            LifeEvent(
                user_id=owner_a,
                event_kind=LifeEventKind.TRAVEL,
                title="bad-place-binding",
                started_at=datetime.now(UTC),
                place_id=place_b,
                revision=0,
            )
        )
        try:
            db.commit()
            raise AssertionError("cross-owner LifeEvent.place_id unexpectedly committed")
        except IntegrityError:
            db.rollback()

    with SessionLocal() as db:
        db.add(
            LifeEventMemoryLink(
                user_id=owner_a,
                life_event_id=event_a,
                memory_id=memory_b,
            )
        )
        try:
            db.commit()
            raise AssertionError("cross-owner LifeEventMemoryLink unexpectedly committed")
        except IntegrityError:
            db.rollback()


def main() -> None:
    owner_a = _seed_owner("life-event-pg-a")
    owner_b = _seed_owner("life-event-pg-b")

    patch_event = _seed_event(owner_a, "patch-race")
    _patch_patch_single_winner(owner_a, patch_event)

    delete_event_id = _seed_event(owner_a, "delete-race")
    _delete_patch_no_resurrection(owner_a, delete_event_id)

    memory_race_event = _seed_event(owner_a, "memory-delete-race")
    memory_race_memory = _seed_memory(owner_a, "memory-delete")
    _evidence_vs_memory_delete(owner_a, memory_race_event, memory_race_memory)

    event_delete_id = _seed_event(owner_a, "event-delete-race")
    event_delete_memory = _seed_memory(owner_a, "event-delete")
    _evidence_vs_event_delete(owner_a, event_delete_id, event_delete_memory)

    _owner_composite_fks_reject_cross_owner(owner_a, owner_b)

    with SessionLocal() as cleanup:
        for target in (owner_a, owner_b):
            user = cleanup.get(User, target)
            if user is not None:
                cleanup.delete(user)
        cleanup.commit()

    print("PostgreSQL LifeEvent V2-005 concurrency PASS")


if __name__ == "__main__":
    main()
