"""PostgreSQL concurrency and owner-FK gate for V2-006 LifeStage foundation."""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Barrier, Thread
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.db import SessionLocal
from app.life_event_models import LifeEvent, LifeEventKind
from app.life_event_schemas import LifeEventCreate
from app.life_stage_models import LifeStage, LifeStageEventLink, LifeStageKind
from app.life_stage_schemas import LifeStageCreate, LifeStagePatch
from app.models import User
from app.services.life_event_service import create_life_event, delete_life_event
from app.services.life_stage_service import (
    LifeStageError,
    create_life_stage,
    create_life_stage_event_link,
    delete_life_stage,
    patch_life_stage,
)


def _seed_owner(label: str) -> UUID:
    user_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname=label))
        db.commit()
    return user_id


def _seed_stage(user_id: UUID, title: str) -> UUID:
    with SessionLocal() as db:
        stage = create_life_stage(
            db,
            user_id=user_id,
            payload=LifeStageCreate(
                stage_kind=LifeStageKind.WORK,
                title=title,
                started_at=datetime.now(UTC),
            ),
        )
        return stage.id


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


def _patch_patch_single_winner(user_id: UUID, stage_id: UUID) -> None:
    barrier = Barrier(2)
    outcomes: list[str] = []
    errors: list[BaseException] = []

    def worker(note: str) -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                try:
                    stage = patch_life_stage(
                        db,
                        user_id=user_id,
                        life_stage_id=stage_id,
                        payload=LifeStagePatch(expected_revision=0, note=note),
                    )
                    outcomes.append(f"ok:{stage.note}:{stage.revision}")
                except LifeStageError as exc:
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
    assert outcomes.count("err:LIFE_STAGE_REVISION_CONFLICT") == 1
    with SessionLocal() as db:
        stage = db.get(LifeStage, stage_id)
        assert stage is not None
        assert stage.revision == 1
        assert stage.note in {"writer-a", "writer-b"}


def _delete_patch_no_resurrection(user_id: UUID, stage_id: UUID) -> None:
    with SessionLocal() as db:
        stage = db.get(LifeStage, stage_id)
        assert stage is not None
        stage.revision = 3
        stage.note = "before-delete-race"
        db.commit()

    barrier = Barrier(2)
    outcomes: list[str] = []
    errors: list[BaseException] = []

    def deleter() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                try:
                    delete_life_stage(db, user_id=user_id, life_stage_id=stage_id)
                    outcomes.append("deleted")
                except LifeStageError as exc:
                    outcomes.append(f"delete:{exc.code}")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def patcher() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                try:
                    patch_life_stage(
                        db,
                        user_id=user_id,
                        life_stage_id=stage_id,
                        payload=LifeStagePatch(expected_revision=3, note="late-patch"),
                    )
                    outcomes.append("patched")
                except LifeStageError as exc:
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
        assert db.get(LifeStage, stage_id) is None


def _link_vs_event_delete(
    user_id: UUID,
    stage_id: UUID,
    event_id: UUID,
) -> None:
    barrier = Barrier(2)
    errors: list[BaseException] = []

    def creator() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                try:
                    create_life_stage_event_link(
                        db,
                        user_id=user_id,
                        life_stage_id=stage_id,
                        life_event_id=event_id,
                    )
                except LifeStageError as exc:
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
        assert db.get(LifeStage, stage_id) is not None
        assert db.scalar(
            select(LifeStageEventLink.id).where(
                LifeStageEventLink.life_event_id == event_id
            )
        ) is None


def _link_vs_stage_delete(
    user_id: UUID,
    stage_id: UUID,
    event_id: UUID,
) -> None:
    barrier = Barrier(2)
    errors: list[BaseException] = []

    def creator() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                try:
                    create_life_stage_event_link(
                        db,
                        user_id=user_id,
                        life_stage_id=stage_id,
                        life_event_id=event_id,
                    )
                except LifeStageError as exc:
                    assert exc.code == "LIFE_STAGE_NOT_FOUND"
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def deleter() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                delete_life_stage(db, user_id=user_id, life_stage_id=stage_id)
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
        assert db.get(LifeStage, stage_id) is None
        assert db.get(LifeEvent, event_id) is not None
        assert db.scalar(
            select(LifeStageEventLink.id).where(
                LifeStageEventLink.life_stage_id == stage_id
            )
        ) is None


def _owner_composite_fks_reject_cross_owner(owner_a: UUID, owner_b: UUID) -> None:
    stage_a = _seed_stage(owner_a, "owner-a-stage")
    event_b = _seed_event(owner_b, "owner-b-event")

    with SessionLocal() as db:
        db.add(
            LifeStageEventLink(
                user_id=owner_a,
                life_stage_id=stage_a,
                life_event_id=event_b,
            )
        )
        try:
            db.commit()
            raise AssertionError("cross-owner LifeStageEventLink unexpectedly committed")
        except IntegrityError:
            db.rollback()


def main() -> None:
    owner_a = _seed_owner("life-stage-pg-a")
    owner_b = _seed_owner("life-stage-pg-b")

    patch_stage = _seed_stage(owner_a, "patch-race")
    _patch_patch_single_winner(owner_a, patch_stage)

    delete_stage_id = _seed_stage(owner_a, "delete-race")
    _delete_patch_no_resurrection(owner_a, delete_stage_id)

    event_delete_stage = _seed_stage(owner_a, "event-delete-race-stage")
    event_delete_event = _seed_event(owner_a, "event-delete-race-event")
    _link_vs_event_delete(owner_a, event_delete_stage, event_delete_event)

    stage_delete_stage = _seed_stage(owner_a, "stage-delete-race-stage")
    stage_delete_event = _seed_event(owner_a, "stage-delete-race-event")
    _link_vs_stage_delete(owner_a, stage_delete_stage, stage_delete_event)

    _owner_composite_fks_reject_cross_owner(owner_a, owner_b)

    with SessionLocal() as cleanup:
        for target in (owner_a, owner_b):
            user = cleanup.get(User, target)
            if user is not None:
                cleanup.delete(user)
        cleanup.commit()

    print("PostgreSQL LifeStage V2-006 concurrency PASS")


if __name__ == "__main__":
    main()
