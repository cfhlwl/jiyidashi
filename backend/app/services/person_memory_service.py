from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Memory
from app.person_memory_models import PersonMemoryLink, PersonMemoryRelationKind
from app.person_models import Person
from app.person_memory_schemas import (
    PersonInteractionRow,
    PersonMemoryLinkCreate,
    PersonMemoryLinkPatch,
    PersonMemoryTimelineRow,
)


class PersonMemoryLinkError(RuntimeError):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _load_memory_for_link(
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
    )
    if for_update:
        statement = statement.with_for_update()
    memory = db.scalar(statement)
    if memory is None:
        raise PersonMemoryLinkError("MEMORY_NOT_FOUND", 404)
    return memory


def _load_person_for_link(
    db: Session,
    *,
    user_id: UUID,
    person_id: UUID,
    for_update: bool,
) -> Person:
    statement = select(Person).where(
        Person.id == person_id,
        Person.user_id == user_id,
    )
    if for_update:
        statement = statement.with_for_update()
    person = db.scalar(statement)
    if person is None:
        raise PersonMemoryLinkError("PERSON_NOT_FOUND", 404)
    return person


def _load_link(
    db: Session,
    *,
    user_id: UUID,
    person_id: UUID,
    memory_id: UUID,
    for_update: bool,
) -> PersonMemoryLink:
    statement = select(PersonMemoryLink).where(
        PersonMemoryLink.user_id == user_id,
        PersonMemoryLink.person_id == person_id,
        PersonMemoryLink.memory_id == memory_id,
    )
    if for_update:
        statement = statement.with_for_update()
    link = db.scalar(statement)
    if link is None:
        raise PersonMemoryLinkError("PERSON_MEMORY_LINK_NOT_FOUND", 404)
    return link


def create_person_memory_link(
    db: Session,
    *,
    user_id: UUID,
    person_id: UUID,
    memory_id: UUID,
    payload: PersonMemoryLinkCreate,
) -> PersonMemoryLink:
    # All mutations touching both authorities use one lock order:
    # Memory -> Person -> Link. This also serializes against Memory soft-delete.
    _load_memory_for_link(
        db,
        user_id=user_id,
        memory_id=memory_id,
        for_update=True,
    )
    _load_person_for_link(
        db,
        user_id=user_id,
        person_id=person_id,
        for_update=True,
    )

    existing = db.scalar(
        select(PersonMemoryLink)
        .where(
            PersonMemoryLink.user_id == user_id,
            PersonMemoryLink.person_id == person_id,
            PersonMemoryLink.memory_id == memory_id,
        )
        .with_for_update()
    )
    if existing is not None:
        if existing.relation_kind == payload.relation_kind:
            db.commit()
            return existing
        db.rollback()
        raise PersonMemoryLinkError("PERSON_MEMORY_LINK_RELATION_CONFLICT", 409)

    link = PersonMemoryLink(
        user_id=user_id,
        person_id=person_id,
        memory_id=memory_id,
        relation_kind=payload.relation_kind,
        revision=0,
    )
    db.add(link)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # DB uniqueness is a final race backstop. Re-resolve owner-scoped state
        # so duplicate same-relation creates converge without masking conflicts.
        current = db.scalar(
            select(PersonMemoryLink).where(
                PersonMemoryLink.user_id == user_id,
                PersonMemoryLink.person_id == person_id,
                PersonMemoryLink.memory_id == memory_id,
            )
        )
        if current is not None and current.relation_kind == payload.relation_kind:
            return current
        raise PersonMemoryLinkError("PERSON_MEMORY_LINK_RELATION_CONFLICT", 409) from exc
    db.refresh(link)
    return link


def patch_person_memory_link(
    db: Session,
    *,
    user_id: UUID,
    person_id: UUID,
    memory_id: UUID,
    payload: PersonMemoryLinkPatch,
) -> PersonMemoryLink:
    _load_memory_for_link(
        db,
        user_id=user_id,
        memory_id=memory_id,
        for_update=True,
    )
    _load_person_for_link(
        db,
        user_id=user_id,
        person_id=person_id,
        for_update=True,
    )
    link = _load_link(
        db,
        user_id=user_id,
        person_id=person_id,
        memory_id=memory_id,
        for_update=True,
    )
    if link.revision != payload.expected_revision:
        db.rollback()
        raise PersonMemoryLinkError("PERSON_MEMORY_LINK_REVISION_CONFLICT", 409)
    if link.relation_kind != payload.relation_kind:
        link.relation_kind = payload.relation_kind
        link.revision += 1
        link.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(link)
    return link


def delete_person_memory_link(
    db: Session,
    *,
    user_id: UUID,
    person_id: UUID,
    memory_id: UUID,
) -> None:
    _load_memory_for_link(
        db,
        user_id=user_id,
        memory_id=memory_id,
        for_update=True,
    )
    _load_person_for_link(
        db,
        user_id=user_id,
        person_id=person_id,
        for_update=True,
    )
    link = _load_link(
        db,
        user_id=user_id,
        person_id=person_id,
        memory_id=memory_id,
        for_update=True,
    )
    db.delete(link)
    db.commit()


def list_person_memory_timeline(
    db: Session,
    *,
    user_id: UUID,
    person_id: UUID,
    limit: int,
) -> list[PersonMemoryTimelineRow]:
    _load_person_for_link(
        db,
        user_id=user_id,
        person_id=person_id,
        for_update=False,
    )
    rows = db.execute(
        select(PersonMemoryLink, Memory)
        .join(
            Memory,
            (Memory.id == PersonMemoryLink.memory_id)
            & (Memory.user_id == PersonMemoryLink.user_id),
        )
        .where(
            PersonMemoryLink.user_id == user_id,
            PersonMemoryLink.person_id == person_id,
            Memory.is_deleted.is_(False),
        )
        .order_by(
            Memory.occurred_at.desc(),
            Memory.id.desc(),
            PersonMemoryLink.id.desc(),
        )
        .limit(limit)
    ).all()
    return [
        PersonMemoryTimelineRow(
            id=link.id,
            person_id=link.person_id,
            memory_id=link.memory_id,
            relation_kind=link.relation_kind,
            revision=link.revision,
            created_at=link.created_at,
            updated_at=link.updated_at,
            occurred_at=memory.occurred_at,
            memory_title=memory.title,
            memory_content=memory.content,
            memory_type=memory.memory_type,
        )
        for link, memory in rows
    ]


def list_recent_person_interactions(
    db: Session,
    *,
    user_id: UUID,
    limit: int,
) -> list[PersonInteractionRow]:
    rows = db.execute(
        select(PersonMemoryLink, Memory, Person)
        .join(
            Memory,
            (Memory.id == PersonMemoryLink.memory_id)
            & (Memory.user_id == PersonMemoryLink.user_id),
        )
        .join(
            Person,
            (Person.id == PersonMemoryLink.person_id)
            & (Person.user_id == PersonMemoryLink.user_id),
        )
        .where(
            PersonMemoryLink.user_id == user_id,
            PersonMemoryLink.relation_kind == PersonMemoryRelationKind.MET,
            Memory.is_deleted.is_(False),
        )
        .order_by(
            Memory.occurred_at.desc(),
            Memory.id.desc(),
            PersonMemoryLink.id.desc(),
        )
        .limit(limit)
    ).all()
    return [
        PersonInteractionRow(
            id=link.id,
            person_id=link.person_id,
            memory_id=link.memory_id,
            relation_kind=link.relation_kind,
            revision=link.revision,
            created_at=link.created_at,
            updated_at=link.updated_at,
            person_display_name=person.display_name,
            occurred_at=memory.occurred_at,
        )
        for link, memory, person in rows
    ]


def delete_links_for_memory(db: Session, *, user_id: UUID, memory_id: UUID) -> int:
    result = db.execute(
        delete(PersonMemoryLink).where(
            PersonMemoryLink.user_id == user_id,
            PersonMemoryLink.memory_id == memory_id,
        )
    )
    return int(result.rowcount or 0)


def delete_links_for_person(db: Session, *, user_id: UUID, person_id: UUID) -> int:
    result = db.execute(
        delete(PersonMemoryLink).where(
            PersonMemoryLink.user_id == user_id,
            PersonMemoryLink.person_id == person_id,
        )
    )
    return int(result.rowcount or 0)
