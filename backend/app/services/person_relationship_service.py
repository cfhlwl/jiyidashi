from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.person_models import Person
from app.person_relationship_models import PersonRelationship, PersonRelationshipKind
from app.person_relationship_schemas import (
    PersonRelationshipCreate,
    PersonRelationshipOtherPerson,
    PersonRelationshipPatch,
    PersonRelationshipProjection,
    PersonRelationshipRead,
)


class PersonRelationshipError(RuntimeError):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def canonical_person_pair(person_a_id: UUID, person_b_id: UUID) -> tuple[UUID, UUID]:
    if person_a_id == person_b_id:
        raise PersonRelationshipError("PERSON_RELATIONSHIP_SELF_EDGE", 422)
    if person_a_id.bytes < person_b_id.bytes:
        return person_a_id, person_b_id
    return person_b_id, person_a_id


def _load_person(
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
        raise PersonRelationshipError("PERSON_NOT_FOUND", 404)
    return person


def _lock_canonical_people(
    db: Session,
    *,
    user_id: UUID,
    person_a_id: UUID,
    person_b_id: UUID,
) -> tuple[Person, Person]:
    low_id, high_id = canonical_person_pair(person_a_id, person_b_id)
    low = _load_person(db, user_id=user_id, person_id=low_id, for_update=True)
    high = _load_person(db, user_id=user_id, person_id=high_id, for_update=True)
    return low, high


def _load_relationship(
    db: Session,
    *,
    user_id: UUID,
    relationship_id: UUID,
    for_update: bool,
) -> PersonRelationship:
    statement = select(PersonRelationship).where(
        PersonRelationship.id == relationship_id,
        PersonRelationship.user_id == user_id,
    )
    if for_update:
        statement = statement.with_for_update()
    edge = db.scalar(statement)
    if edge is None:
        raise PersonRelationshipError("PERSON_RELATIONSHIP_NOT_FOUND", 404)
    return edge


def _normalize_payload(
    kind: PersonRelationshipKind,
    custom_label: str | None,
) -> str | None:
    if kind == PersonRelationshipKind.OTHER:
        if custom_label is None or not custom_label.strip():
            raise PersonRelationshipError("PERSON_RELATIONSHIP_CUSTOM_LABEL_REQUIRED", 422)
        return " ".join(custom_label.strip().split())
    return None


def create_person_relationship(
    db: Session,
    *,
    user_id: UUID,
    payload: PersonRelationshipCreate,
) -> PersonRelationship:
    low, high = _lock_canonical_people(
        db,
        user_id=user_id,
        person_a_id=payload.person_a_id,
        person_b_id=payload.person_b_id,
    )
    custom_label = _normalize_payload(payload.relationship_kind, payload.custom_label)

    existing = db.scalar(
        select(PersonRelationship)
        .where(
            PersonRelationship.user_id == user_id,
            PersonRelationship.person_low_id == low.id,
            PersonRelationship.person_high_id == high.id,
        )
        .with_for_update()
    )
    if existing is not None:
        same_payload = (
            existing.relationship_kind == payload.relationship_kind
            and existing.custom_label == custom_label
            and existing.note == payload.note
        )
        if same_payload:
            db.commit()
            return existing
        db.rollback()
        raise PersonRelationshipError("PERSON_RELATIONSHIP_CONFLICT", 409)

    edge = PersonRelationship(
        user_id=user_id,
        person_low_id=low.id,
        person_high_id=high.id,
        relationship_kind=payload.relationship_kind,
        custom_label=custom_label,
        note=payload.note,
        revision=0,
    )
    db.add(edge)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        current = db.scalar(
            select(PersonRelationship).where(
                PersonRelationship.user_id == user_id,
                PersonRelationship.person_low_id == low.id,
                PersonRelationship.person_high_id == high.id,
            )
        )
        if current is not None:
            same_payload = (
                current.relationship_kind == payload.relationship_kind
                and current.custom_label == custom_label
                and current.note == payload.note
            )
            if same_payload:
                return current
        raise PersonRelationshipError("PERSON_RELATIONSHIP_CONFLICT", 409) from exc
    db.refresh(edge)
    return edge


def relationship_read(edge: PersonRelationship) -> PersonRelationshipRead:
    return PersonRelationshipRead(
        id=edge.id,
        person_a_id=edge.person_low_id,
        person_b_id=edge.person_high_id,
        relationship_kind=edge.relationship_kind,
        custom_label=edge.custom_label,
        note=edge.note,
        revision=edge.revision,
        created_at=edge.created_at,
        updated_at=edge.updated_at,
    )


def get_person_relationship(
    db: Session,
    *,
    user_id: UUID,
    relationship_id: UUID,
) -> PersonRelationship:
    return _load_relationship(
        db,
        user_id=user_id,
        relationship_id=relationship_id,
        for_update=False,
    )


def patch_person_relationship(
    db: Session,
    *,
    user_id: UUID,
    relationship_id: UUID,
    payload: PersonRelationshipPatch,
) -> PersonRelationship:
    edge = _load_relationship(
        db,
        user_id=user_id,
        relationship_id=relationship_id,
        for_update=False,
    )
    # Lock the endpoint Persons before locking the edge so all graph mutations use
    # one canonical order even when a caller addresses the relationship by edge id.
    low, high = _lock_canonical_people(
        db,
        user_id=user_id,
        person_a_id=edge.person_low_id,
        person_b_id=edge.person_high_id,
    )
    edge = _load_relationship(
        db,
        user_id=user_id,
        relationship_id=relationship_id,
        for_update=True,
    )
    if edge.person_low_id != low.id or edge.person_high_id != high.id:
        db.rollback()
        raise PersonRelationshipError("PERSON_RELATIONSHIP_NOT_FOUND", 404)
    if edge.revision != payload.expected_revision:
        db.rollback()
        raise PersonRelationshipError("PERSON_RELATIONSHIP_REVISION_CONFLICT", 409)

    fields = payload.model_fields_set
    next_kind = (
        payload.relationship_kind
        if "relationship_kind" in fields
        else edge.relationship_kind
    )
    if next_kind == PersonRelationshipKind.OTHER:
        next_label = (
            payload.custom_label
            if "custom_label" in fields
            else edge.custom_label
        )
        next_label = _normalize_payload(next_kind, next_label)
    else:
        if "custom_label" in fields and payload.custom_label is not None:
            db.rollback()
            raise PersonRelationshipError(
                "PERSON_RELATIONSHIP_CUSTOM_LABEL_ONLY_FOR_OTHER",
                422,
            )
        next_label = None

    next_note = payload.note if "note" in fields else edge.note
    changed = (
        next_kind != edge.relationship_kind
        or next_label != edge.custom_label
        or next_note != edge.note
    )
    if changed:
        edge.relationship_kind = next_kind
        edge.custom_label = next_label
        edge.note = next_note
        edge.revision += 1
        edge.updated_at = datetime.now(UTC)

    db.commit()
    db.refresh(edge)
    return edge


def delete_person_relationship(
    db: Session,
    *,
    user_id: UUID,
    relationship_id: UUID,
) -> None:
    edge = _load_relationship(
        db,
        user_id=user_id,
        relationship_id=relationship_id,
        for_update=False,
    )
    _lock_canonical_people(
        db,
        user_id=user_id,
        person_a_id=edge.person_low_id,
        person_b_id=edge.person_high_id,
    )
    edge = _load_relationship(
        db,
        user_id=user_id,
        relationship_id=relationship_id,
        for_update=True,
    )
    db.delete(edge)
    db.commit()


def list_person_relationships(
    db: Session,
    *,
    user_id: UUID,
    person_id: UUID,
    limit: int,
) -> list[PersonRelationshipProjection]:
    owner_person = _load_person(
        db,
        user_id=user_id,
        person_id=person_id,
        for_update=False,
    )
    edges = list(
        db.scalars(
            select(PersonRelationship)
            .where(
                PersonRelationship.user_id == user_id,
                or_(
                    PersonRelationship.person_low_id == owner_person.id,
                    PersonRelationship.person_high_id == owner_person.id,
                ),
            )
            .order_by(
                PersonRelationship.created_at.desc(),
                PersonRelationship.id.desc(),
            )
            .limit(limit)
        ).all()
    )
    other_ids = [
        edge.person_high_id
        if edge.person_low_id == owner_person.id
        else edge.person_low_id
        for edge in edges
    ]
    people = {
        person.id: person
        for person in db.scalars(
            select(Person).where(
                Person.user_id == user_id,
                Person.id.in_(other_ids),
            )
        ).all()
    }
    result: list[PersonRelationshipProjection] = []
    for edge, other_id in zip(edges, other_ids, strict=True):
        other = people.get(other_id)
        if other is None:
            continue
        result.append(
            PersonRelationshipProjection(
                relationship_id=edge.id,
                relationship_kind=edge.relationship_kind,
                custom_label=edge.custom_label,
                note=edge.note,
                revision=edge.revision,
                other_person=PersonRelationshipOtherPerson(
                    id=other.id,
                    display_name=other.display_name,
                ),
                created_at=edge.created_at,
                updated_at=edge.updated_at,
            )
        )
    return result


def delete_relationships_for_person(
    db: Session,
    *,
    user_id: UUID,
    person_id: UUID,
) -> int:
    result = db.execute(
        delete(PersonRelationship).where(
            PersonRelationship.user_id == user_id,
            or_(
                PersonRelationship.person_low_id == person_id,
                PersonRelationship.person_high_id == person_id,
            ),
        )
    )
    return int(result.rowcount or 0)
