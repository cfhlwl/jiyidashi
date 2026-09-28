"""Deterministic Person known-duration derived from explicit trusted Person↔Memory evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Memory
from app.person_duration_models import (
    PersonKnownDurationEvidence,
    PersonKnownDurationRead,
    PersonKnownDurationStatus,
)
from app.person_memory_models import PersonMemoryLink, PersonMemoryRelationKind
from app.person_models import Person
from app.services.answer_trust_service import resolve_memory_answer_trust

MAX_DURATION_EVIDENCE_SCAN = 256


class PersonDurationError(RuntimeError):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class _RelationSelection:
    incomplete: bool
    evidence: PersonKnownDurationEvidence | None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _load_person(db: Session, *, user_id: UUID, person_id: UUID) -> Person:
    person = db.scalar(
        select(Person).where(Person.id == person_id, Person.user_id == user_id)
    )
    if person is None:
        raise PersonDurationError("PERSON_NOT_FOUND", 404)
    return person


def _select_relation(
    db: Session,
    *,
    user_id: UUID,
    person_id: UUID,
    relation_kind: PersonMemoryRelationKind,
    as_of: datetime,
) -> _RelationSelection:
    rows = db.execute(
        select(
            PersonMemoryLink.id,
            PersonMemoryLink.memory_id,
            Memory.occurred_at,
        )
        .join(
            Memory,
            (Memory.id == PersonMemoryLink.memory_id)
            & (Memory.user_id == PersonMemoryLink.user_id),
        )
        .where(
            PersonMemoryLink.user_id == user_id,
            PersonMemoryLink.person_id == person_id,
            PersonMemoryLink.relation_kind == relation_kind,
            Memory.user_id == user_id,
            Memory.is_deleted.is_(False),
            Memory.occurred_at <= as_of,
        )
        .order_by(
            Memory.occurred_at.asc(),
            Memory.id.asc(),
            PersonMemoryLink.id.asc(),
        )
        .limit(MAX_DURATION_EVIDENCE_SCAN + 1)
    ).all()

    for link_id, memory_id, occurred_at in rows[:MAX_DURATION_EVIDENCE_SCAN]:
        trust = resolve_memory_answer_trust(
            db,
            user_id=user_id,
            memory_id=memory_id,
        )
        if (
            trust.can_answer
            and trust.memory_id == memory_id
            and trust.evidence_source_id is not None
        ):
            return _RelationSelection(
                incomplete=False,
                evidence=PersonKnownDurationEvidence(
                    person_memory_link_id=link_id,
                    memory_id=memory_id,
                    memory_source_id=trust.evidence_source_id,
                    relation_kind=relation_kind,
                    trust_state=trust.state,
                    occurred_at=_utc(occurred_at),
                ),
            )

    if len(rows) > MAX_DURATION_EVIDENCE_SCAN:
        return _RelationSelection(incomplete=True, evidence=None)
    return _RelationSelection(incomplete=False, evidence=None)


def _derive_once(
    db: Session,
    *,
    user_id: UUID,
    person: Person,
    as_of: datetime,
) -> PersonKnownDurationRead:
    met = _select_relation(
        db,
        user_id=user_id,
        person_id=person.id,
        relation_kind=PersonMemoryRelationKind.MET,
        as_of=as_of,
    )
    if met.incomplete:
        return _empty(
            status=PersonKnownDurationStatus.EVIDENCE_INCOMPLETE,
            person=person,
            as_of=as_of,
        )
    if met.evidence is not None:
        since = _utc(met.evidence.occurred_at)
        elapsed_days = max(0, int((as_of - since).total_seconds() // 86400))
        return PersonKnownDurationRead(
            status=PersonKnownDurationStatus.KNOWN_SINCE_MET,
            person_id=person.id,
            display_name=person.display_name,
            as_of=as_of,
            at_least_since_at=since,
            elapsed_days=elapsed_days,
            earliest_related_at=None,
            evidence=met.evidence,
        )

    related = _select_relation(
        db,
        user_id=user_id,
        person_id=person.id,
        relation_kind=PersonMemoryRelationKind.RELATED,
        as_of=as_of,
    )
    if related.incomplete:
        return _empty(
            status=PersonKnownDurationStatus.EVIDENCE_INCOMPLETE,
            person=person,
            as_of=as_of,
        )
    if related.evidence is not None:
        return PersonKnownDurationRead(
            status=PersonKnownDurationStatus.RELATED_EVIDENCE_ONLY,
            person_id=person.id,
            display_name=person.display_name,
            as_of=as_of,
            at_least_since_at=None,
            elapsed_days=None,
            earliest_related_at=_utc(related.evidence.occurred_at),
            evidence=related.evidence,
        )
    return _empty(
        status=PersonKnownDurationStatus.NO_TRUSTED_EVIDENCE,
        person=person,
        as_of=as_of,
    )


def _empty(
    *,
    status: PersonKnownDurationStatus,
    person: Person,
    as_of: datetime,
) -> PersonKnownDurationRead:
    return PersonKnownDurationRead(
        status=status,
        person_id=person.id,
        display_name=person.display_name,
        as_of=as_of,
        at_least_since_at=None,
        elapsed_days=None,
        earliest_related_at=None,
        evidence=None,
    )


def _authority_key(result: PersonKnownDurationRead) -> tuple:
    evidence = result.evidence
    return (
        result.status,
        result.person_id,
        result.display_name,
        result.at_least_since_at,
        result.elapsed_days,
        result.earliest_related_at,
        None if evidence is None else evidence.person_memory_link_id,
        None if evidence is None else evidence.memory_id,
        None if evidence is None else evidence.memory_source_id,
        None if evidence is None else evidence.relation_kind,
        None if evidence is None else evidence.trust_state,
        None if evidence is None else evidence.occurred_at,
    )


def get_person_known_duration(
    db: Session,
    *,
    user_id: UUID,
    person_id: UUID,
    now: datetime | None = None,
) -> PersonKnownDurationRead:
    """Return a no-guess, read-only acquaintance lower bound.

    The full selection is re-run before publication so a selected link/source/time must
    still be canonical. One bounded restart is permitted when authority changes.
    """

    person = _load_person(db, user_id=user_id, person_id=person_id)
    as_of = _utc(now or datetime.now(UTC))

    first = _derive_once(db, user_id=user_id, person=person, as_of=as_of)
    confirm = _derive_once(db, user_id=user_id, person=person, as_of=as_of)
    if _authority_key(first) == _authority_key(confirm):
        return confirm

    restarted = _derive_once(db, user_id=user_id, person=person, as_of=as_of)
    final_confirm = _derive_once(db, user_id=user_id, person=person, as_of=as_of)
    if _authority_key(restarted) == _authority_key(final_confirm):
        return final_confirm

    return _empty(
        status=PersonKnownDurationStatus.EVIDENCE_INCOMPLETE,
        person=person,
        as_of=as_of,
    )
