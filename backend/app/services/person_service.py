from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.person_models import Person, PersonAlias
from app.person_schemas import PersonCreate, PersonPatch


class PersonServiceError(RuntimeError):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def normalize_person_text(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _canonical_aliases(values: list[str]) -> list[tuple[str, str]]:
    # Normalization is only a duplicate key. It never merges two Person rows or
    # transliterates names, and the first explicit spelling is retained.
    unique: dict[str, str] = {}
    for value in values:
        alias = " ".join(value.strip().split())
        normalized = normalize_person_text(alias)
        if normalized and normalized not in unique:
            unique[normalized] = alias
    return [(alias, normalized) for normalized, alias in unique.items()]


def _aliases_for_person(db: Session, user_id: UUID, person_id: UUID) -> list[PersonAlias]:
    return list(
        db.scalars(
            select(PersonAlias)
            .where(
                PersonAlias.user_id == user_id,
                PersonAlias.person_id == person_id,
            )
            .order_by(PersonAlias.normalized_alias, PersonAlias.id)
        ).all()
    )


def load_person(db: Session, *, user_id: UUID, person_id: UUID, for_update: bool = False) -> Person:
    statement = select(Person).where(Person.id == person_id, Person.user_id == user_id)
    if for_update:
        statement = statement.with_for_update()
    person = db.scalar(statement)
    if person is None:
        raise PersonServiceError("PERSON_NOT_FOUND", 404)
    return person


def list_people(db: Session, *, user_id: UUID, limit: int) -> list[Person]:
    return list(
        db.scalars(
            select(Person)
            .where(Person.user_id == user_id)
            .order_by(Person.display_name, Person.created_at, Person.id)
            .limit(limit)
        ).all()
    )


def aliases_by_person(
    db: Session, *, user_id: UUID, person_ids: list[UUID]
) -> dict[UUID, list[PersonAlias]]:
    if not person_ids:
        return {}
    rows = list(
        db.scalars(
            select(PersonAlias)
            .where(
                PersonAlias.user_id == user_id,
                PersonAlias.person_id.in_(person_ids),
            )
            .order_by(PersonAlias.person_id, PersonAlias.normalized_alias, PersonAlias.id)
        ).all()
    )
    result: dict[UUID, list[PersonAlias]] = {person_id: [] for person_id in person_ids}
    for row in rows:
        result.setdefault(row.person_id, []).append(row)
    return result


def _replace_aliases(
    db: Session,
    *,
    person: Person,
    aliases: list[str],
) -> None:
    db.execute(
        delete(PersonAlias).where(
            PersonAlias.user_id == person.user_id,
            PersonAlias.person_id == person.id,
        )
    )
    for alias, normalized in _canonical_aliases(aliases):
        db.add(
            PersonAlias(
                user_id=person.user_id,
                person_id=person.id,
                alias=alias,
                normalized_alias=normalized,
            )
        )


def create_person(db: Session, *, user_id: UUID, payload: PersonCreate) -> Person:
    person = Person(
        user_id=user_id,
        display_name=payload.display_name,
        relationship_label=payload.relationship_label,
        note=payload.note,
        revision=0,
    )
    db.add(person)
    db.flush()
    _replace_aliases(db, person=person, aliases=payload.aliases)
    db.commit()
    db.refresh(person)
    return person


def patch_person(
    db: Session,
    *,
    user_id: UUID,
    person_id: UUID,
    payload: PersonPatch,
) -> Person:
    person = load_person(db, user_id=user_id, person_id=person_id, for_update=True)
    if person.revision != payload.expected_revision:
        db.rollback()
        raise PersonServiceError("PERSON_REVISION_CONFLICT", 409)

    changed = False
    fields = payload.model_fields_set
    if "display_name" in fields and payload.display_name != person.display_name:
        person.display_name = payload.display_name
        changed = True
    if "relationship_label" in fields and payload.relationship_label != person.relationship_label:
        person.relationship_label = payload.relationship_label
        changed = True
    if "note" in fields and payload.note != person.note:
        person.note = payload.note
        changed = True
    if "aliases" in fields:
        current = {
            row.normalized_alias: row.alias
            for row in _aliases_for_person(db, user_id, person_id)
        }
        requested = {
            normalized: alias for alias, normalized in _canonical_aliases(payload.aliases or [])
        }
        if current != requested:
            _replace_aliases(db, person=person, aliases=payload.aliases or [])
            changed = True

    if changed:
        person.revision += 1
        person.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(person)
    return person


def delete_person(db: Session, *, user_id: UUID, person_id: UUID) -> None:
    person = load_person(db, user_id=user_id, person_id=person_id, for_update=True)
    db.delete(person)
    db.commit()
