from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.life_event_models import LifeEvent, LifeEventKind, LifeEventMemoryLink
from app.life_event_schemas import (
    LifeEventCreate,
    LifeEventMemoryEvidenceRead,
    LifeEventPatch,
    LifeEventRead,
)
from app.life_stage_models import LifeStageEventLink
from app.models import Memory, Place


class LifeEventError(RuntimeError):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _same_datetime(left: datetime | None, right: datetime | None) -> bool:
    if left is None or right is None:
        return left is right
    return _as_utc(left) == _as_utc(right)


def _load_place(
    db: Session,
    *,
    user_id: UUID,
    place_id: UUID,
) -> Place:
    place = db.scalar(
        select(Place).where(
            Place.id == place_id,
            Place.user_id == user_id,
        )
    )
    if place is None:
        raise LifeEventError("PLACE_NOT_FOUND", 404)
    return place


def _load_event(
    db: Session,
    *,
    user_id: UUID,
    life_event_id: UUID,
    for_update: bool,
) -> LifeEvent:
    statement = select(LifeEvent).where(
        LifeEvent.id == life_event_id,
        LifeEvent.user_id == user_id,
    )
    if for_update:
        statement = statement.with_for_update()
    event = db.scalar(statement)
    if event is None:
        raise LifeEventError("LIFE_EVENT_NOT_FOUND", 404)
    return event


def _load_memory_for_evidence(
    db: Session,
    *,
    user_id: UUID,
    memory_id: UUID,
    for_update: bool,
) -> Memory:
    statement = select(Memory).where(
        Memory.id == memory_id,
        Memory.user_id == user_id,
        Memory.is_deleted.is_(False),
        Memory.is_confirmed.is_(True),
    )
    if for_update:
        statement = statement.with_for_update()
    memory = db.scalar(statement)
    if memory is None:
        raise LifeEventError("MEMORY_NOT_FOUND", 404)
    return memory


def _load_link(
    db: Session,
    *,
    user_id: UUID,
    life_event_id: UUID,
    memory_id: UUID,
    for_update: bool,
) -> LifeEventMemoryLink:
    statement = select(LifeEventMemoryLink).where(
        LifeEventMemoryLink.user_id == user_id,
        LifeEventMemoryLink.life_event_id == life_event_id,
        LifeEventMemoryLink.memory_id == memory_id,
    )
    if for_update:
        statement = statement.with_for_update()
    link = db.scalar(statement)
    if link is None:
        raise LifeEventError("LIFE_EVENT_MEMORY_LINK_NOT_FOUND", 404)
    return link


def _validate_final_state(
    *,
    event_kind: LifeEventKind,
    custom_label: str | None,
    started_at: datetime,
    ended_at: datetime | None,
) -> None:
    if event_kind == LifeEventKind.OTHER:
        if custom_label is None:
            raise LifeEventError("LIFE_EVENT_CUSTOM_LABEL_REQUIRED", 422)
    elif custom_label is not None:
        raise LifeEventError("LIFE_EVENT_CUSTOM_LABEL_ONLY_FOR_OTHER", 422)

    if ended_at is not None and _as_utc(ended_at) < _as_utc(started_at):
        raise LifeEventError("LIFE_EVENT_TIME_RANGE_INVALID", 422)


def life_event_read(event: LifeEvent) -> LifeEventRead:
    return LifeEventRead(
        id=event.id,
        event_kind=event.event_kind,
        title=event.title,
        custom_label=event.custom_label,
        note=event.note,
        started_at=event.started_at,
        ended_at=event.ended_at,
        place_id=event.place_id,
        revision=event.revision,
        created_at=event.created_at,
        updated_at=event.updated_at,
    )


def create_life_event(
    db: Session,
    *,
    user_id: UUID,
    payload: LifeEventCreate,
) -> LifeEvent:
    if payload.place_id is not None:
        _load_place(db, user_id=user_id, place_id=payload.place_id)

    event = LifeEvent(
        user_id=user_id,
        event_kind=payload.event_kind,
        title=payload.title,
        custom_label=payload.custom_label,
        note=payload.note,
        started_at=payload.started_at,
        ended_at=payload.ended_at,
        place_id=payload.place_id,
        revision=0,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def list_life_events(
    db: Session,
    *,
    user_id: UUID,
    limit: int,
) -> list[LifeEvent]:
    return list(
        db.scalars(
            select(LifeEvent)
            .where(LifeEvent.user_id == user_id)
            .order_by(LifeEvent.started_at.desc(), LifeEvent.id.desc())
            .limit(limit)
        )
    )


def get_life_event(
    db: Session,
    *,
    user_id: UUID,
    life_event_id: UUID,
) -> LifeEvent:
    return _load_event(
        db,
        user_id=user_id,
        life_event_id=life_event_id,
        for_update=False,
    )


def patch_life_event(
    db: Session,
    *,
    user_id: UUID,
    life_event_id: UUID,
    payload: LifeEventPatch,
) -> LifeEvent:
    event = _load_event(
        db,
        user_id=user_id,
        life_event_id=life_event_id,
        for_update=True,
    )
    if event.revision != payload.expected_revision:
        db.rollback()
        raise LifeEventError("LIFE_EVENT_REVISION_CONFLICT", 409)

    fields = payload.model_fields_set
    final_kind = payload.event_kind if "event_kind" in fields else event.event_kind
    final_title = payload.title if "title" in fields else event.title
    final_note = payload.note if "note" in fields else event.note
    final_started_at = (
        payload.started_at if "started_at" in fields else event.started_at
    )
    final_ended_at = payload.ended_at if "ended_at" in fields else event.ended_at
    final_place_id = payload.place_id if "place_id" in fields else event.place_id

    if "custom_label" in fields:
        final_custom_label = payload.custom_label
    elif final_kind != LifeEventKind.OTHER and event.event_kind == LifeEventKind.OTHER:
        # Switching away from OTHER must never retain a stale OTHER label.
        final_custom_label = None
    else:
        final_custom_label = event.custom_label

    assert final_kind is not None
    assert final_title is not None
    assert final_started_at is not None
    _validate_final_state(
        event_kind=final_kind,
        custom_label=final_custom_label,
        started_at=final_started_at,
        ended_at=final_ended_at,
    )

    if "place_id" in fields and final_place_id is not None:
        _load_place(db, user_id=user_id, place_id=final_place_id)

    changed = (
        final_kind != event.event_kind
        or final_title != event.title
        or final_custom_label != event.custom_label
        or final_note != event.note
        or not _same_datetime(final_started_at, event.started_at)
        or not _same_datetime(final_ended_at, event.ended_at)
        or final_place_id != event.place_id
    )
    if not changed:
        db.commit()
        return event

    event.event_kind = final_kind
    event.title = final_title
    event.custom_label = final_custom_label
    event.note = final_note
    event.started_at = final_started_at
    event.ended_at = final_ended_at
    event.place_id = final_place_id
    event.revision += 1
    event.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(event)
    return event


def delete_life_event(
    db: Session,
    *,
    user_id: UUID,
    life_event_id: UUID,
) -> None:
    event = _load_event(
        db,
        user_id=user_id,
        life_event_id=life_event_id,
        for_update=True,
    )
    # Explicitly remove evidence in the same locked transaction. Do not rely only
    # on database ON DELETE CASCADE: application semantics stay identical on
    # SQLite tests and PostgreSQL production, and Memory rows are never touched.
    # V2-006 stage evidence shares this LifeEvent row lock, so no new stage
    # link can survive once deletion commits.
    db.execute(
        delete(LifeStageEventLink).where(
            LifeStageEventLink.user_id == user_id,
            LifeStageEventLink.life_event_id == life_event_id,
        )
    )
    db.execute(
        delete(LifeEventMemoryLink).where(
            LifeEventMemoryLink.user_id == user_id,
            LifeEventMemoryLink.life_event_id == life_event_id,
        )
    )
    db.delete(event)
    db.commit()


def _evidence_read(
    link: LifeEventMemoryLink,
    memory: Memory,
) -> LifeEventMemoryEvidenceRead:
    return LifeEventMemoryEvidenceRead(
        link_id=link.id,
        memory_id=memory.id,
        memory_type=memory.memory_type,
        title=memory.title,
        content=memory.content,
        occurred_at=memory.occurred_at,
        source_type=memory.source_type,
        created_at=link.created_at,
    )


def create_life_event_memory_link(
    db: Session,
    *,
    user_id: UUID,
    life_event_id: UUID,
    memory_id: UUID,
) -> LifeEventMemoryEvidenceRead:
    # Canonical mixed-authority lock order: Memory -> LifeEvent -> Link.
    memory = _load_memory_for_evidence(
        db,
        user_id=user_id,
        memory_id=memory_id,
        for_update=True,
    )
    _load_event(
        db,
        user_id=user_id,
        life_event_id=life_event_id,
        for_update=True,
    )

    existing = db.scalar(
        select(LifeEventMemoryLink)
        .where(
            LifeEventMemoryLink.user_id == user_id,
            LifeEventMemoryLink.life_event_id == life_event_id,
            LifeEventMemoryLink.memory_id == memory_id,
        )
        .with_for_update()
    )
    if existing is not None:
        db.commit()
        return _evidence_read(existing, memory)

    link = LifeEventMemoryLink(
        user_id=user_id,
        life_event_id=life_event_id,
        memory_id=memory_id,
    )
    db.add(link)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        current = db.scalar(
            select(LifeEventMemoryLink).where(
                LifeEventMemoryLink.user_id == user_id,
                LifeEventMemoryLink.life_event_id == life_event_id,
                LifeEventMemoryLink.memory_id == memory_id,
            )
        )
        if current is not None:
            current_memory = _load_memory_for_evidence(
                db,
                user_id=user_id,
                memory_id=memory_id,
                for_update=False,
            )
            return _evidence_read(current, current_memory)
        raise LifeEventError("LIFE_EVENT_MEMORY_LINK_CONFLICT", 409) from exc
    db.refresh(link)
    return _evidence_read(link, memory)


def list_life_event_memories(
    db: Session,
    *,
    user_id: UUID,
    life_event_id: UUID,
    limit: int,
) -> list[LifeEventMemoryEvidenceRead]:
    _load_event(
        db,
        user_id=user_id,
        life_event_id=life_event_id,
        for_update=False,
    )
    rows = db.execute(
        select(LifeEventMemoryLink, Memory)
        .join(
            Memory,
            (Memory.id == LifeEventMemoryLink.memory_id)
            & (Memory.user_id == LifeEventMemoryLink.user_id),
        )
        .where(
            LifeEventMemoryLink.user_id == user_id,
            LifeEventMemoryLink.life_event_id == life_event_id,
            Memory.is_deleted.is_(False),
            Memory.is_confirmed.is_(True),
        )
        .order_by(
            Memory.occurred_at.desc(),
            Memory.id.desc(),
            LifeEventMemoryLink.id.desc(),
        )
        .limit(limit)
    ).all()
    return [
        LifeEventMemoryEvidenceRead(
            link_id=link.id,
            memory_id=memory.id,
            memory_type=memory.memory_type,
            title=memory.title,
            content=memory.content,
            occurred_at=memory.occurred_at,
            source_type=memory.source_type,
            created_at=link.created_at,
        )
        for link, memory in rows
    ]


def delete_life_event_memory_link(
    db: Session,
    *,
    user_id: UUID,
    life_event_id: UUID,
    memory_id: UUID,
) -> None:
    _load_memory_for_evidence(
        db,
        user_id=user_id,
        memory_id=memory_id,
        for_update=True,
    )
    _load_event(
        db,
        user_id=user_id,
        life_event_id=life_event_id,
        for_update=True,
    )
    link = _load_link(
        db,
        user_id=user_id,
        life_event_id=life_event_id,
        memory_id=memory_id,
        for_update=True,
    )
    db.delete(link)
    db.commit()


def delete_links_for_memory(
    db: Session,
    *,
    user_id: UUID,
    memory_id: UUID,
) -> int:
    result = db.execute(
        delete(LifeEventMemoryLink).where(
            LifeEventMemoryLink.user_id == user_id,
            LifeEventMemoryLink.memory_id == memory_id,
        )
    )
    return int(result.rowcount or 0)
