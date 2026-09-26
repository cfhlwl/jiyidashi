from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.person_models import Person
from app.person_schemas import PersonAliasRead, PersonCreate, PersonPatch, PersonRead
from app.services.person_service import (
    PersonServiceError,
    aliases_by_person,
    create_person,
    delete_person,
    list_people,
    load_person,
    patch_person,
)

router = APIRouter(prefix="/people", tags=["people"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]


def _raise_person_error(exc: PersonServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


def _read(person: Person, aliases) -> PersonRead:
    return PersonRead(
        id=person.id,
        display_name=person.display_name,
        relationship_label=person.relationship_label,
        note=person.note,
        aliases=[PersonAliasRead.model_validate(alias) for alias in aliases],
        revision=person.revision,
        created_at=person.created_at,
        updated_at=person.updated_at,
    )


@router.post("", response_model=PersonRead, status_code=status.HTTP_201_CREATED)
def create_person_route(
    payload: PersonCreate,
    user_id: CurrentUser,
    db: DbSession,
) -> PersonRead:
    person = create_person(db, user_id=user_id, payload=payload)
    aliases = aliases_by_person(db, user_id=user_id, person_ids=[person.id])[person.id]
    return _read(person, aliases)


@router.get("", response_model=list[PersonRead])
def list_people_route(
    user_id: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[PersonRead]:
    people = list_people(db, user_id=user_id, limit=limit)
    aliases = aliases_by_person(db, user_id=user_id, person_ids=[item.id for item in people])
    return [_read(item, aliases.get(item.id, [])) for item in people]


@router.get("/{person_id}", response_model=PersonRead)
def get_person_route(
    person_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
) -> PersonRead:
    try:
        person = load_person(db, user_id=user_id, person_id=person_id)
    except PersonServiceError as exc:
        _raise_person_error(exc)
    aliases = aliases_by_person(db, user_id=user_id, person_ids=[person.id])[person.id]
    return _read(person, aliases)


@router.patch("/{person_id}", response_model=PersonRead)
def patch_person_route(
    person_id: UUID,
    payload: PersonPatch,
    user_id: CurrentUser,
    db: DbSession,
) -> PersonRead:
    try:
        person = patch_person(db, user_id=user_id, person_id=person_id, payload=payload)
    except PersonServiceError as exc:
        _raise_person_error(exc)
    aliases = aliases_by_person(db, user_id=user_id, person_ids=[person.id])[person.id]
    return _read(person, aliases)


@router.delete("/{person_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_person_route(
    person_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
) -> Response:
    try:
        delete_person(db, user_id=user_id, person_id=person_id)
    except PersonServiceError as exc:
        _raise_person_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
