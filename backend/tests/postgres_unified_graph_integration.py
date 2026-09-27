"""PostgreSQL consistency gate for V2-004 unified graph projection."""

from __future__ import annotations

from threading import Barrier, Event, Thread
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from app.core.db import SessionLocal
from app.graph_schemas import GraphNodeKind
from app.models import (
    Memory,
    MemoryType,
    ObjectItem,
    ObjectLocation,
    ObjectLocationStatus,
    Place,
    User,
)
from app.person_models import Person
from app.person_relationship_models import PersonRelationship, PersonRelationshipKind
from app.services import graph_projection_service
from app.services.graph_projection_service import (
    GraphProjectionError,
    get_graph_neighborhood,
)
from app.services.memory_service import get_memory_for_user, soft_delete_memory
from app.services.person_service import delete_person


def _seed_user(label: str) -> UUID:
    user_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname=label))
        db.commit()
    return user_id


def _read_vs_person_delete(user_id: UUID) -> None:
    person_a = uuid4()
    person_b = uuid4()
    low_id, high_id = sorted((person_a, person_b), key=lambda value: value.bytes)
    with SessionLocal() as db:
        db.add_all(
            [
                Person(id=person_a, user_id=user_id, display_name="A"),
                Person(id=person_b, user_id=user_id, display_name="B"),
            ]
        )
        db.flush()
        db.add(
            PersonRelationship(
                user_id=user_id,
                person_low_id=low_id,
                person_high_id=high_id,
                relationship_kind=PersonRelationshipKind.FRIEND,
                revision=0,
            )
        )
        db.commit()

    center_locked = Event()
    writer_blocked = Event()
    errors: list[BaseException] = []
    original_person_edges = graph_projection_service._person_edges

    def gated_person_edges(*args, **kwargs):
        # get_graph_neighborhood has already loaded the center with FOR SHARE.
        center_locked.set()
        assert writer_blocked.wait(timeout=10)
        return original_person_edges(*args, **kwargs)

    graph_projection_service._person_edges = gated_person_edges

    def writer() -> None:
        try:
            assert center_locked.wait(timeout=10)
            with SessionLocal() as db:
                db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                try:
                    delete_person(db, user_id=user_id, person_id=person_a)
                    raise AssertionError(
                        "Person delete committed while graph center FOR SHARE was held"
                    )
                except OperationalError as exc:
                    db.rollback()
                    assert "lock timeout" in str(exc).lower()
                    writer_blocked.set()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
            writer_blocked.set()

    thread = Thread(target=writer)
    thread.start()
    try:
        with SessionLocal() as db:
            result = get_graph_neighborhood(
                db,
                user_id=user_id,
                kind=GraphNodeKind.PERSON,
                entity_id=person_a,
                limit=20,
            )
            assert result.center.id == person_a
            assert any(
                edge.authority_ref is not None for edge in result.edges
            )
    finally:
        graph_projection_service._person_edges = original_person_edges

    thread.join(timeout=15)
    assert not thread.is_alive()
    if errors:
        raise errors[0]
    assert writer_blocked.is_set()

    # Once the read transaction releases its share lock, the exact same canonical
    # writer must be able to commit; every later graph read then fails closed.
    with SessionLocal() as db:
        delete_person(db, user_id=user_id, person_id=person_a)

    with SessionLocal() as db:
        try:
            get_graph_neighborhood(
                db,
                user_id=user_id,
                kind=GraphNodeKind.PERSON,
                entity_id=person_a,
                limit=20,
            )
            raise AssertionError("deleted Person remained graph-readable")
        except GraphProjectionError as exc:
            assert exc.code == "GRAPH_NODE_NOT_FOUND"
        assert db.scalar(
            select(PersonRelationship.id).where(
                PersonRelationship.user_id == user_id,
                (
                    (PersonRelationship.person_low_id == person_a)
                    | (PersonRelationship.person_high_id == person_a)
                ),
            )
        ) is None


def _event_read_vs_soft_delete(user_id: UUID) -> None:
    event_id = uuid4()
    place_id = uuid4()
    with SessionLocal() as db:
        db.add(Place(id=place_id, user_id=user_id, name="event-place"))
        db.add(
            Memory(
                id=event_id,
                user_id=user_id,
                memory_type=MemoryType.EVENT,
                title="event",
                content="event",
                is_confirmed=True,
                is_deleted=False,
                place_id=place_id,
            )
        )
        db.commit()

    center_locked = Event()
    writer_blocked = Event()
    errors: list[BaseException] = []
    original_event_edges = graph_projection_service._event_edges

    def gated_event_edges(*args, **kwargs):
        # The trusted EVENT center has already been read and share-locked. Force
        # the invalidating writer to reach its conflicting FOR UPDATE first.
        center_locked.set()
        assert writer_blocked.wait(timeout=10)
        return original_event_edges(*args, **kwargs)

    graph_projection_service._event_edges = gated_event_edges

    def writer() -> None:
        try:
            assert center_locked.wait(timeout=10)
            with SessionLocal() as db:
                db.execute(text("SET LOCAL lock_timeout = '250ms'"))
                try:
                    memory = get_memory_for_user(
                        db,
                        user_id,
                        event_id,
                        for_update=True,
                    )
                    assert memory is not None
                    soft_delete_memory(db, memory)
                    db.commit()
                    raise AssertionError(
                        "EVENT soft-delete committed while graph center "
                        "FOR SHARE was held"
                    )
                except OperationalError as exc:
                    db.rollback()
                    assert "lock timeout" in str(exc).lower()
                    writer_blocked.set()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
            writer_blocked.set()

    thread = Thread(target=writer)
    thread.start()
    try:
        with SessionLocal() as db:
            result = get_graph_neighborhood(
                db,
                user_id=user_id,
                kind=GraphNodeKind.EVENT,
                entity_id=event_id,
                limit=20,
            )
            assert result.center.id == event_id
            assert any(
                edge.edge_kind.value == "EVENT_PLACE"
                for edge in result.edges
            )
    finally:
        graph_projection_service._event_edges = original_event_edges

    thread.join(timeout=15)
    assert not thread.is_alive()
    if errors:
        raise errors[0]
    assert writer_blocked.is_set()

    with SessionLocal() as db:
        memory = get_memory_for_user(
            db,
            user_id,
            event_id,
            for_update=True,
        )
        assert memory is not None
        soft_delete_memory(db, memory)
        db.commit()

    with SessionLocal() as db:
        try:
            get_graph_neighborhood(
                db,
                user_id=user_id,
                kind=GraphNodeKind.EVENT,
                entity_id=event_id,
                limit=20,
            )
            raise AssertionError("soft-deleted EVENT remained graph-readable")
        except GraphProjectionError as exc:
            assert exc.code == "GRAPH_NODE_NOT_FOUND"


def _object_read_vs_stale_transition(user_id: UUID) -> None:
    place_id = uuid4()
    object_id = uuid4()
    location_id = uuid4()
    with SessionLocal() as db:
        db.add(Place(id=place_id, user_id=user_id, name="place"))
        db.add(
            ObjectItem(
                id=object_id,
                user_id=user_id,
                name="keys",
                normalized_name="keys",
            )
        )
        db.flush()
        db.add(
            ObjectLocation(
                id=location_id,
                user_id=user_id,
                object_id=object_id,
                location_text="drawer",
                place_id=place_id,
                status=ObjectLocationStatus.CURRENT,
            )
        )
        db.commit()

    barrier = Barrier(2)
    errors: list[BaseException] = []

    def reader() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                result = get_graph_neighborhood(
                    db,
                    user_id=user_id,
                    kind=GraphNodeKind.OBJECT,
                    entity_id=object_id,
                    limit=20,
                )
                assert result.center.id == object_id
                assert all(edge.source.id == object_id for edge in result.edges)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def staler() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                location = db.scalar(
                    select(ObjectLocation)
                    .where(
                        ObjectLocation.id == location_id,
                        ObjectLocation.user_id == user_id,
                    )
                    .with_for_update()
                )
                assert location is not None
                location.status = ObjectLocationStatus.STALE
                db.commit()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [Thread(target=reader), Thread(target=staler)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    if errors:
        raise errors[0]

    with SessionLocal() as db:
        result = get_graph_neighborhood(
            db,
            user_id=user_id,
            kind=GraphNodeKind.OBJECT,
            entity_id=object_id,
            limit=20,
        )
        assert result.edges == []
        assert result.nodes == []


def main() -> None:
    user_id = _seed_user("unified-graph-pg")
    _read_vs_person_delete(user_id)
    _event_read_vs_soft_delete(user_id)
    _object_read_vs_stale_transition(user_id)

    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is not None:
            db.delete(user)
            db.commit()


if __name__ == "__main__":
    main()
