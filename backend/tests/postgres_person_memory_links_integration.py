"""PostgreSQL concurrency and owner-FK gate for V2-002 Person Memory Links."""

from __future__ import annotations

from threading import Barrier, Thread
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.db import SessionLocal
from app.models import Memory, User
from app.person_memory_models import PersonMemoryLink, PersonMemoryRelationKind
from app.person_memory_schemas import PersonMemoryLinkCreate, PersonMemoryLinkPatch
from app.person_models import Person
from app.services.memory_service import get_memory_for_user, soft_delete_memory
from app.services.person_memory_service import (
    PersonMemoryLinkError,
    create_person_memory_link,
    patch_person_memory_link,
)
from app.services.person_service import delete_person


def _seed_owner(label: str) -> UUID:
    user_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname=label))
        db.commit()
    return user_id


def _seed_pair(user_id: UUID, suffix: str) -> tuple[UUID, UUID]:
    person_id = uuid4()
    memory_id = uuid4()
    with SessionLocal() as db:
        db.add(
            Person(
                id=person_id,
                user_id=user_id,
                display_name=f"person-{suffix}",
            )
        )
        db.add(
            Memory(
                id=memory_id,
                user_id=user_id,
                content=f"memory-{suffix}",
            )
        )
        db.commit()
    return person_id, memory_id


def _duplicate_create_converges(
    user_id: UUID,
    person_id: UUID,
    memory_id: UUID,
) -> None:
    barrier = Barrier(2)
    results: list[str] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                link = create_person_memory_link(
                    db,
                    user_id=user_id,
                    person_id=person_id,
                    memory_id=memory_id,
                    payload=PersonMemoryLinkCreate(
                        relation_kind=PersonMemoryRelationKind.RELATED
                    ),
                )
                results.append(str(link.id))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [Thread(target=worker), Thread(target=worker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    if errors:
        raise errors[0]

    assert len(results) == 2
    assert results[0] == results[1]
    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(PersonMemoryLink).where(
                    PersonMemoryLink.user_id == user_id,
                    PersonMemoryLink.person_id == person_id,
                    PersonMemoryLink.memory_id == memory_id,
                )
            ).all()
        )
        assert len(rows) == 1


def _same_revision_patch_single_winner(
    user_id: UUID,
    person_id: UUID,
    memory_id: UUID,
) -> None:
    barrier = Barrier(2)
    outcomes: list[str] = []
    errors: list[BaseException] = []

    def worker(kind: PersonMemoryRelationKind) -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                try:
                    link = patch_person_memory_link(
                        db,
                        user_id=user_id,
                        person_id=person_id,
                        memory_id=memory_id,
                        payload=PersonMemoryLinkPatch(
                            relation_kind=kind,
                            expected_revision=0,
                        ),
                    )
                    outcomes.append(f"ok:{link.relation_kind.value}:{link.revision}")
                except PersonMemoryLinkError as exc:
                    outcomes.append(f"err:{exc.code}")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        Thread(target=worker, args=(PersonMemoryRelationKind.MET,)),
        Thread(target=worker, args=(PersonMemoryRelationKind.MET,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    if errors:
        raise errors[0]

    assert outcomes.count("ok:MET:1") == 1
    assert outcomes.count("err:PERSON_MEMORY_LINK_REVISION_CONFLICT") == 1
    with SessionLocal() as db:
        link = db.scalar(
            select(PersonMemoryLink).where(
                PersonMemoryLink.user_id == user_id,
                PersonMemoryLink.person_id == person_id,
                PersonMemoryLink.memory_id == memory_id,
            )
        )
        assert link is not None
        assert link.relation_kind == PersonMemoryRelationKind.MET
        assert link.revision == 1


def _create_vs_memory_delete_never_leaves_visible_link(
    user_id: UUID,
    person_id: UUID,
    memory_id: UUID,
) -> None:
    barrier = Barrier(2)
    errors: list[BaseException] = []

    def creator() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                try:
                    create_person_memory_link(
                        db,
                        user_id=user_id,
                        person_id=person_id,
                        memory_id=memory_id,
                        payload=PersonMemoryLinkCreate(
                            relation_kind=PersonMemoryRelationKind.MET
                        ),
                    )
                except PersonMemoryLinkError as exc:
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
            select(PersonMemoryLink.id).where(
                PersonMemoryLink.user_id == user_id,
                PersonMemoryLink.memory_id == memory_id,
            )
        ) is None


def _create_vs_person_delete_never_leaves_orphan(
    user_id: UUID,
    person_id: UUID,
    memory_id: UUID,
) -> None:
    barrier = Barrier(2)
    errors: list[BaseException] = []

    def creator() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                try:
                    create_person_memory_link(
                        db,
                        user_id=user_id,
                        person_id=person_id,
                        memory_id=memory_id,
                        payload=PersonMemoryLinkCreate(
                            relation_kind=PersonMemoryRelationKind.RELATED
                        ),
                    )
                except PersonMemoryLinkError as exc:
                    assert exc.code == "PERSON_NOT_FOUND"
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def deleter() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                delete_person(db, user_id=user_id, person_id=person_id)
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
        assert db.get(Person, person_id) is None
        assert db.scalar(
            select(PersonMemoryLink.id).where(
                PersonMemoryLink.person_id == person_id
            )
        ) is None
        memory = db.get(Memory, memory_id)
        assert memory is not None
        assert memory.is_deleted is False


def _cross_owner_composite_fk_rejected(
    owner_a: UUID,
    owner_b: UUID,
    person_a: UUID,
    memory_b: UUID,
) -> None:
    with SessionLocal() as db:
        db.add(
            PersonMemoryLink(
                user_id=owner_a,
                person_id=person_a,
                memory_id=memory_b,
                relation_kind=PersonMemoryRelationKind.RELATED,
                revision=0,
            )
        )
        try:
            db.commit()
            raise AssertionError("cross-owner PersonMemoryLink unexpectedly committed")
        except IntegrityError:
            db.rollback()

    with SessionLocal() as db:
        assert db.scalar(
            select(PersonMemoryLink.id).where(
                PersonMemoryLink.user_id == owner_a,
                PersonMemoryLink.person_id == person_a,
                PersonMemoryLink.memory_id == memory_b,
            )
        ) is None
        assert db.get(User, owner_b) is not None


def main() -> None:
    owner_a = _seed_owner("person-memory-pg-a")
    owner_b = _seed_owner("person-memory-pg-b")

    duplicate_person, duplicate_memory = _seed_pair(owner_a, "duplicate")
    _duplicate_create_converges(owner_a, duplicate_person, duplicate_memory)
    _same_revision_patch_single_winner(owner_a, duplicate_person, duplicate_memory)

    memory_race_person, memory_race_memory = _seed_pair(owner_a, "memory-race")
    _create_vs_memory_delete_never_leaves_visible_link(
        owner_a,
        memory_race_person,
        memory_race_memory,
    )

    person_race_person, person_race_memory = _seed_pair(owner_a, "person-race")
    _create_vs_person_delete_never_leaves_orphan(
        owner_a,
        person_race_person,
        person_race_memory,
    )

    foreign_person, _ = _seed_pair(owner_a, "fk-owner-a")
    _, foreign_memory = _seed_pair(owner_b, "fk-owner-b")
    _cross_owner_composite_fk_rejected(
        owner_a,
        owner_b,
        foreign_person,
        foreign_memory,
    )

    with SessionLocal() as cleanup:
        for user_id in (owner_a, owner_b):
            user = cleanup.get(User, user_id)
            if user is not None:
                cleanup.delete(user)
        cleanup.commit()


if __name__ == "__main__":
    main()
