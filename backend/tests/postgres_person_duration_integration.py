"""Real PostgreSQL read-boundary races for V2-008 Person Known Duration V1."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from uuid import UUID, uuid4

from sqlalchemy import select

import app.services.person_duration_service as duration_service
from app.core.db import SessionLocal
from app.models import Memory, MemorySource, SourceType, User
from app.person_duration_models import PersonKnownDurationStatus
from app.person_memory_models import PersonMemoryLink, PersonMemoryRelationKind
from app.person_memory_schemas import PersonMemoryLinkCreate, PersonMemoryLinkPatch
from app.person_models import Person
from app.services.memory_service import get_memory_for_user, soft_delete_memory
from app.services.person_memory_service import (
    create_person_memory_link,
    patch_person_memory_link,
)


AS_OF = datetime(2026, 9, 28, 12, tzinfo=UTC)


def _seed(label: str) -> tuple[UUID, UUID, UUID]:
    user_id = uuid4()
    person_id = uuid4()
    memory_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname=label))
        db.add(Person(id=person_id, user_id=user_id, display_name=label))
        db.add(
            Memory(
                id=memory_id,
                user_id=user_id,
                content=f"{label}-met",
                occurred_at=AS_OF - timedelta(days=100),
                source_type=SourceType.USER_TEXT,
                confidence=1.0,
                is_confirmed=True,
            )
        )
        db.flush()
        db.add(
            MemorySource(
                memory_id=memory_id,
                source_type=SourceType.USER_TEXT,
                confidence=1.0,
            )
        )
        db.add(
            PersonMemoryLink(
                user_id=user_id,
                person_id=person_id,
                memory_id=memory_id,
                relation_kind=PersonMemoryRelationKind.MET,
            )
        )
        db.commit()
    return user_id, person_id, memory_id


def _run_paused_after_first_selection(
    user_id: UUID,
    person_id: UUID,
    mutate,
):
    first_done = Event()
    release = Event()
    results = []
    errors: list[BaseException] = []
    original = duration_service._derive_once
    calls = 0

    def wrapped(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 1:
            first_done.set()
            assert release.wait(timeout=15)
        return result

    duration_service._derive_once = wrapped

    def reader() -> None:
        try:
            with SessionLocal() as db:
                results.append(
                    duration_service.get_person_known_duration(
                        db,
                        user_id=user_id,
                        person_id=person_id,
                        now=AS_OF,
                    )
                )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = Thread(target=reader)
    try:
        thread.start()
        assert first_done.wait(timeout=15)
        mutate()
        release.set()
        thread.join(timeout=20)
        assert not thread.is_alive()
        if errors:
            raise errors[0]
        assert len(results) == 1
        return results[0]
    finally:
        release.set()
        duration_service._derive_once = original
        thread.join(timeout=5)


def _cleanup(user_id: UUID) -> None:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is not None:
            db.delete(user)
            db.commit()


def _selected_met_soft_delete_does_not_publish_deleted_evidence() -> None:
    user_id, person_id, memory_id = _seed("duration-soft-delete")

    def mutate() -> None:
        with SessionLocal() as db:
            memory = get_memory_for_user(db, user_id, memory_id, for_update=True)
            assert memory is not None
            soft_delete_memory(db, memory)
            db.commit()

    try:
        result = _run_paused_after_first_selection(user_id, person_id, mutate)
        assert result.status == PersonKnownDurationStatus.NO_TRUSTED_EVIDENCE
        assert result.evidence is None
        assert result.elapsed_days is None
    finally:
        _cleanup(user_id)


def _selected_met_to_related_does_not_publish_stale_met_duration() -> None:
    user_id, person_id, memory_id = _seed("duration-link-patch")

    def mutate() -> None:
        with SessionLocal() as db:
            current = db.scalar(
                select(PersonMemoryLink).where(
                    PersonMemoryLink.user_id == user_id,
                    PersonMemoryLink.person_id == person_id,
                    PersonMemoryLink.memory_id == memory_id,
                )
            )
            assert current is not None
            patch_person_memory_link(
                db,
                user_id=user_id,
                person_id=person_id,
                memory_id=memory_id,
                payload=PersonMemoryLinkPatch(
                    relation_kind=PersonMemoryRelationKind.RELATED,
                    expected_revision=current.revision,
                ),
            )

    try:
        result = _run_paused_after_first_selection(user_id, person_id, mutate)
        assert result.status == PersonKnownDurationStatus.RELATED_EVIDENCE_ONLY
        assert result.at_least_since_at is None
        assert result.elapsed_days is None
        assert result.evidence is not None
        assert result.evidence.relation_kind == PersonMemoryRelationKind.RELATED
    finally:
        _cleanup(user_id)


def _earlier_met_added_before_final_return_is_selected() -> None:
    user_id, person_id, later_memory_id = _seed("duration-earlier-link")
    earlier_memory_id = uuid4()
    with SessionLocal() as db:
        db.add(
            Memory(
                id=earlier_memory_id,
                user_id=user_id,
                content="earlier trusted met",
                occurred_at=AS_OF - timedelta(days=500),
                source_type=SourceType.USER_TEXT,
                confidence=1.0,
                is_confirmed=True,
            )
        )
        db.flush()
        db.add(
            MemorySource(
                memory_id=earlier_memory_id,
                source_type=SourceType.USER_TEXT,
                confidence=1.0,
            )
        )
        db.commit()

    def mutate() -> None:
        with SessionLocal() as db:
            create_person_memory_link(
                db,
                user_id=user_id,
                person_id=person_id,
                memory_id=earlier_memory_id,
                payload=PersonMemoryLinkCreate(
                    relation_kind=PersonMemoryRelationKind.MET
                ),
            )

    try:
        result = _run_paused_after_first_selection(user_id, person_id, mutate)
        assert result.status == PersonKnownDurationStatus.KNOWN_SINCE_MET
        assert result.evidence is not None
        assert result.evidence.memory_id == earlier_memory_id
        assert result.evidence.memory_id != later_memory_id
        assert result.elapsed_days == 500
    finally:
        _cleanup(user_id)


def main() -> None:
    _selected_met_soft_delete_does_not_publish_deleted_evidence()
    _selected_met_to_related_does_not_publish_stale_met_duration()
    _earlier_met_added_before_final_return_is_selected()


if __name__ == "__main__":
    main()
