"""PostgreSQL concurrency and integrity gate for V2-003 Person Relationships."""

from __future__ import annotations

from threading import Barrier, Thread
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.db import SessionLocal
from app.models import User
from app.person_models import Person
from app.person_relationship_models import PersonRelationship, PersonRelationshipKind
from app.person_relationship_schemas import (
    PersonRelationshipCreate,
    PersonRelationshipPatch,
)
from app.services.person_relationship_service import (
    PersonRelationshipError,
    create_person_relationship,
    patch_person_relationship,
)
from app.services.person_service import delete_person


def _seed_owner(label: str) -> UUID:
    user_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname=label))
        db.commit()
    return user_id


def _seed_people(user_id: UUID, suffix: str) -> tuple[UUID, UUID]:
    first_id = uuid4()
    second_id = uuid4()
    with SessionLocal() as db:
        db.add_all(
            [
                Person(id=first_id, user_id=user_id, display_name=f"{suffix}-a"),
                Person(id=second_id, user_id=user_id, display_name=f"{suffix}-b"),
            ]
        )
        db.commit()
    return first_id, second_id


def _reversed_create_converges(
    user_id: UUID,
    person_a: UUID,
    person_b: UUID,
) -> None:
    barrier = Barrier(2)
    results: list[str] = []
    errors: list[BaseException] = []

    def worker(a_id: UUID, b_id: UUID) -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                edge = create_person_relationship(
                    db,
                    user_id=user_id,
                    payload=PersonRelationshipCreate(
                        person_a_id=a_id,
                        person_b_id=b_id,
                        relationship_kind=PersonRelationshipKind.FRIEND,
                    ),
                )
                results.append(str(edge.id))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        Thread(target=worker, args=(person_a, person_b)),
        Thread(target=worker, args=(person_b, person_a)),
    ]
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
                select(PersonRelationship).where(
                    PersonRelationship.user_id == user_id,
                )
            ).all()
        )
        assert len(rows) == 1
        edge = rows[0]
        assert edge.person_low_id.bytes < edge.person_high_id.bytes


def _same_payload_retry_same_id(
    user_id: UUID,
    person_a: UUID,
    person_b: UUID,
) -> None:
    with SessionLocal() as db:
        first = create_person_relationship(
            db,
            user_id=user_id,
            payload=PersonRelationshipCreate(
                person_a_id=person_a,
                person_b_id=person_b,
                relationship_kind=PersonRelationshipKind.OTHER,
                custom_label="邻居",
                note="explicit",
            ),
        )
        first_id = first.id

    with SessionLocal() as db:
        second = create_person_relationship(
            db,
            user_id=user_id,
            payload=PersonRelationshipCreate(
                person_a_id=person_b,
                person_b_id=person_a,
                relationship_kind=PersonRelationshipKind.OTHER,
                custom_label="邻居",
                note="explicit",
            ),
        )
        assert second.id == first_id


def _conflicting_create_has_one_winner(
    user_id: UUID,
    person_a: UUID,
    person_b: UUID,
) -> None:
    barrier = Barrier(2)
    outcomes: list[str] = []
    errors: list[BaseException] = []

    def worker(kind: PersonRelationshipKind) -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                try:
                    edge = create_person_relationship(
                        db,
                        user_id=user_id,
                        payload=PersonRelationshipCreate(
                            person_a_id=person_a,
                            person_b_id=person_b,
                            relationship_kind=kind,
                        ),
                    )
                    outcomes.append(f"ok:{edge.relationship_kind.value}")
                except PersonRelationshipError as exc:
                    outcomes.append(f"err:{exc.code}")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        Thread(target=worker, args=(PersonRelationshipKind.FAMILY,)),
        Thread(target=worker, args=(PersonRelationshipKind.COLLEAGUE,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    if errors:
        raise errors[0]

    assert len([item for item in outcomes if item.startswith("ok:")]) == 1
    assert outcomes.count("err:PERSON_RELATIONSHIP_CONFLICT") == 1


def _same_revision_patch_single_winner(
    user_id: UUID,
    relationship_id: UUID,
) -> None:
    barrier = Barrier(2)
    outcomes: list[str] = []
    errors: list[BaseException] = []

    def worker(kind: PersonRelationshipKind) -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                try:
                    edge = patch_person_relationship(
                        db,
                        user_id=user_id,
                        relationship_id=relationship_id,
                        payload=PersonRelationshipPatch(
                            expected_revision=0,
                            relationship_kind=kind,
                        ),
                    )
                    outcomes.append(f"ok:{edge.relationship_kind.value}:{edge.revision}")
                except PersonRelationshipError as exc:
                    outcomes.append(f"err:{exc.code}")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        Thread(target=worker, args=(PersonRelationshipKind.FAMILY,)),
        Thread(target=worker, args=(PersonRelationshipKind.CLASSMATE,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    if errors:
        raise errors[0]

    assert len([item for item in outcomes if item.startswith("ok:")]) == 1
    assert outcomes.count("err:PERSON_RELATIONSHIP_REVISION_CONFLICT") == 1
    with SessionLocal() as db:
        edge = db.get(PersonRelationship, relationship_id)
        assert edge is not None
        assert edge.revision == 1


def _create_vs_person_delete(
    user_id: UUID,
    person_a: UUID,
    person_b: UUID,
    delete_id: UUID,
) -> None:
    barrier = Barrier(2)
    errors: list[BaseException] = []

    def creator() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                try:
                    create_person_relationship(
                        db,
                        user_id=user_id,
                        payload=PersonRelationshipCreate(
                            person_a_id=person_a,
                            person_b_id=person_b,
                            relationship_kind=PersonRelationshipKind.FRIEND,
                        ),
                    )
                except PersonRelationshipError as exc:
                    assert exc.code == "PERSON_NOT_FOUND"
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def deleter() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                delete_person(db, user_id=user_id, person_id=delete_id)
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
        assert db.get(Person, delete_id) is None
        assert db.scalar(
            select(PersonRelationship.id).where(
                PersonRelationship.user_id == user_id,
                (
                    (PersonRelationship.person_low_id == delete_id)
                    | (PersonRelationship.person_high_id == delete_id)
                ),
            )
        ) is None


def _cross_owner_fk_rejected(
    owner_a: UUID,
    person_a: UUID,
    person_b_foreign: UUID,
) -> None:
    low_id, high_id = sorted(
        (person_a, person_b_foreign),
        key=lambda value: value.bytes,
    )
    with SessionLocal() as db:
        db.add(
            PersonRelationship(
                user_id=owner_a,
                person_low_id=low_id,
                person_high_id=high_id,
                relationship_kind=PersonRelationshipKind.FRIEND,
                revision=0,
            )
        )
        try:
            db.commit()
            raise AssertionError("cross-owner PersonRelationship unexpectedly committed")
        except IntegrityError:
            db.rollback()


def _self_edge_rejected(user_id: UUID, person_id: UUID) -> None:
    with SessionLocal() as db:
        db.add(
            PersonRelationship(
                user_id=user_id,
                person_low_id=person_id,
                person_high_id=person_id,
                relationship_kind=PersonRelationshipKind.FRIEND,
                revision=0,
            )
        )
        try:
            db.commit()
            raise AssertionError("self PersonRelationship unexpectedly committed")
        except IntegrityError:
            db.rollback()


def main() -> None:
    owner_a = _seed_owner("relationship-pg-a")
    owner_b = _seed_owner("relationship-pg-b")

    pair_a, pair_b = _seed_people(owner_a, "reverse")
    _reversed_create_converges(owner_a, pair_a, pair_b)

    retry_a, retry_b = _seed_people(owner_a, "retry")
    _same_payload_retry_same_id(owner_a, retry_a, retry_b)

    conflict_a, conflict_b = _seed_people(owner_a, "conflict")
    _conflicting_create_has_one_winner(owner_a, conflict_a, conflict_b)

    patch_a, patch_b = _seed_people(owner_a, "patch")
    with SessionLocal() as db:
        patch_edge = create_person_relationship(
            db,
            user_id=owner_a,
            payload=PersonRelationshipCreate(
                person_a_id=patch_a,
                person_b_id=patch_b,
                relationship_kind=PersonRelationshipKind.FRIEND,
            ),
        )
        patch_edge_id = patch_edge.id
    _same_revision_patch_single_winner(owner_a, patch_edge_id)

    delete_a, delete_b = _seed_people(owner_a, "delete-a")
    _create_vs_person_delete(owner_a, delete_a, delete_b, delete_a)

    delete_c, delete_d = _seed_people(owner_a, "delete-b")
    _create_vs_person_delete(owner_a, delete_c, delete_d, delete_d)

    foreign_a, _ = _seed_people(owner_a, "owner-a")
    foreign_b, _ = _seed_people(owner_b, "owner-b")
    _cross_owner_fk_rejected(owner_a, foreign_a, foreign_b)

    self_person, _ = _seed_people(owner_a, "self")
    _self_edge_rejected(owner_a, self_person)

    with SessionLocal() as cleanup:
        for user_id in (owner_a, owner_b):
            user = cleanup.get(User, user_id)
            if user is not None:
                cleanup.delete(user)
        cleanup.commit()


if __name__ == "__main__":
    main()
