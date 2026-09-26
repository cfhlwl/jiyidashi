"""PostgreSQL concurrency gate for V2-001 Person foundation."""

from threading import Barrier, Thread
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.db import SessionLocal
from app.models import User
from app.person_models import Person, PersonAlias
from app.person_schemas import PersonCreate, PersonPatch
from app.services.person_service import (
    PersonServiceError,
    create_person,
    delete_person,
    patch_person,
)


def _seed_person(user_id):
    with SessionLocal() as db:
        return create_person(
            db,
            user_id=user_id,
            payload=PersonCreate(display_name="老王", aliases=["王老师"]),
        ).id


def _same_revision_patch_single_winner(user_id, person_id) -> None:
    barrier = Barrier(2)
    results: list[str] = []
    errors: list[BaseException] = []

    def worker(note: str) -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                try:
                    person = patch_person(
                        db,
                        user_id=user_id,
                        person_id=person_id,
                        payload=PersonPatch(expected_revision=0, note=note),
                    )
                    results.append(f"ok:{person.note}:{person.revision}")
                except PersonServiceError as exc:
                    results.append(f"err:{exc.code}")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        Thread(target=worker, args=("writer-a",), name="person-patch-a"),
        Thread(target=worker, args=("writer-b",), name="person-patch-b"),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    if errors:
        raise errors[0]

    assert len([item for item in results if item.startswith("ok:")]) == 1
    assert results.count("err:PERSON_REVISION_CONFLICT") == 1
    with SessionLocal() as db:
        person = db.get(Person, person_id)
        assert person is not None
        assert person.revision == 1
        assert person.note in {"writer-a", "writer-b"}


def _delete_vs_patch_never_resurrects(user_id, person_id) -> None:
    with SessionLocal() as reset:
        person = reset.get(Person, person_id)
        assert person is not None
        person.revision = 2
        person.note = "before-race"
        reset.commit()

    barrier = Barrier(2)
    outcomes: list[str] = []
    errors: list[BaseException] = []

    def deleter() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                try:
                    delete_person(db, user_id=user_id, person_id=person_id)
                    outcomes.append("deleted")
                except PersonServiceError as exc:
                    outcomes.append(f"delete:{exc.code}")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def patcher() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                try:
                    patch_person(
                        db,
                        user_id=user_id,
                        person_id=person_id,
                        payload=PersonPatch(expected_revision=2, note="late-patch"),
                    )
                    outcomes.append("patched")
                except PersonServiceError as exc:
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
        assert db.get(Person, person_id) is None
        assert db.scalar(
            select(PersonAlias.id).where(PersonAlias.person_id == person_id).limit(1)
        ) is None


def _alias_owner_composite_fk_rejects_cross_owner_binding(
    owner_id,
    foreign_id,
    person_id,
) -> None:
    with SessionLocal() as db:
        db.add(
            PersonAlias(
                user_id=foreign_id,
                person_id=person_id,
                alias="越权别名",
                normalized_alias="越权别名",
            )
        )
        try:
            db.commit()
            raise AssertionError("cross-owner PersonAlias unexpectedly committed")
        except IntegrityError:
            db.rollback()

    with SessionLocal() as db:
        person = db.get(Person, person_id)
        assert person is not None
        assert person.user_id == owner_id
        assert db.scalar(
            select(PersonAlias.id).where(
                PersonAlias.person_id == person_id,
                PersonAlias.user_id == foreign_id,
            )
        ) is None


def main() -> None:
    user_id = uuid4()
    foreign_id = uuid4()
    with SessionLocal() as db:
        db.add_all(
            [
                User(id=user_id, nickname="person-pg-owner"),
                User(id=foreign_id, nickname="person-pg-foreign"),
            ]
        )
        db.commit()

    person_id = _seed_person(user_id)
    _alias_owner_composite_fk_rejects_cross_owner_binding(
        user_id,
        foreign_id,
        person_id,
    )
    _same_revision_patch_single_winner(user_id, person_id)
    _delete_vs_patch_never_resurrects(user_id, person_id)

    with SessionLocal() as cleanup:
        for target in (user_id, foreign_id):
            user = cleanup.get(User, target)
            if user is not None:
                cleanup.delete(user)
        cleanup.commit()


if __name__ == "__main__":
    main()
