from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.person_memory_schemas import (
    PersonInteractionRow,
    PersonMemoryLinkCreate,
    PersonMemoryLinkPatch,
    PersonMemoryLinkRead,
    PersonMemoryTimelineRow,
)
from app.person_models import Person
from app.person_relationship_schemas import (
    PersonRelationshipCreate,
    PersonRelationshipPatch,
    PersonRelationshipProjection,
    PersonRelationshipRead,
)
from app.person_schemas import PersonCreate, PersonPatch, PersonRead
from app.services.person_memory_service import (
    PersonMemoryLinkError,
    create_person_memory_link,
    delete_person_memory_link,
    list_person_memory_timeline,
    list_recent_person_interactions,
    patch_person_memory_link,
)
from app.services.person_relationship_service import (
    PersonRelationshipError,
    create_person_relationship,
    delete_person_relationship,
    get_person_relationship,
    list_person_relationships,
    patch_person_relationship,
    relationship_read,
)
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


def _raise_person_memory_error(exc: PersonMemoryLinkError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


def _raise_person_relationship_error(exc: PersonRelationshipError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


def _read(person: Person, aliases) -> PersonRead:
    return PersonRead(
        id=person.id,
        display_name=person.display_name,
        relationship_label=person.relationship_label,
        note=person.note,
        aliases=[alias.alias for alias in aliases],
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
    aliases = aliases_by_person(
        db,
        user_id=user_id,
        person_ids=[item.id for item in people],
    )
    return [_read(item, aliases.get(item.id, [])) for item in people]


@router.post(
    "/relationships",
    response_model=PersonRelationshipRead,
    status_code=status.HTTP_201_CREATED,
)
def create_person_relationship_route(
    payload: PersonRelationshipCreate,
    user_id: CurrentUser,
    db: DbSession,
) -> PersonRelationshipRead:
    try:
        edge = create_person_relationship(db, user_id=user_id, payload=payload)
    except PersonRelationshipError as exc:
        _raise_person_relationship_error(exc)
    return relationship_read(edge)


@router.get(
    "/relationships/{relationship_id}",
    response_model=PersonRelationshipRead,
)
def get_person_relationship_route(
    relationship_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
) -> PersonRelationshipRead:
    try:
        edge = get_person_relationship(
            db,
            user_id=user_id,
            relationship_id=relationship_id,
        )
    except PersonRelationshipError as exc:
        _raise_person_relationship_error(exc)
    return relationship_read(edge)


@router.patch(
    "/relationships/{relationship_id}",
    response_model=PersonRelationshipRead,
)
def patch_person_relationship_route(
    relationship_id: UUID,
    payload: PersonRelationshipPatch,
    user_id: CurrentUser,
    db: DbSession,
) -> PersonRelationshipRead:
    try:
        edge = patch_person_relationship(
            db,
            user_id=user_id,
            relationship_id=relationship_id,
            payload=payload,
        )
    except PersonRelationshipError as exc:
        _raise_person_relationship_error(exc)
    return relationship_read(edge)


@router.delete(
    "/relationships/{relationship_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_person_relationship_route(
    relationship_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
) -> Response:
    try:
        delete_person_relationship(
            db,
            user_id=user_id,
            relationship_id=relationship_id,
        )
    except PersonRelationshipError as exc:
        _raise_person_relationship_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/interactions", response_model=list[PersonInteractionRow])
def list_person_interactions_route(
    user_id: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[PersonInteractionRow]:
    return list_recent_person_interactions(db, user_id=user_id, limit=limit)


@router.post(
    "/{person_id}/memories/{memory_id}",
    response_model=PersonMemoryLinkRead,
    status_code=status.HTTP_201_CREATED,
)
def create_person_memory_link_route(
    person_id: UUID,
    memory_id: UUID,
    payload: PersonMemoryLinkCreate,
    user_id: CurrentUser,
    db: DbSession,
) -> PersonMemoryLinkRead:
    try:
        return create_person_memory_link(
            db,
            user_id=user_id,
            person_id=person_id,
            memory_id=memory_id,
            payload=payload,
        )
    except PersonMemoryLinkError as exc:
        _raise_person_memory_error(exc)


@router.patch(
    "/{person_id}/memories/{memory_id}",
    response_model=PersonMemoryLinkRead,
)
def patch_person_memory_link_route(
    person_id: UUID,
    memory_id: UUID,
    payload: PersonMemoryLinkPatch,
    user_id: CurrentUser,
    db: DbSession,
) -> PersonMemoryLinkRead:
    try:
        return patch_person_memory_link(
            db,
            user_id=user_id,
            person_id=person_id,
            memory_id=memory_id,
            payload=payload,
        )
    except PersonMemoryLinkError as exc:
        _raise_person_memory_error(exc)


@router.delete(
    "/{person_id}/memories/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_person_memory_link_route(
    person_id: UUID,
    memory_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
) -> Response:
    try:
        delete_person_memory_link(
            db,
            user_id=user_id,
            person_id=person_id,
            memory_id=memory_id,
        )
    except PersonMemoryLinkError as exc:
        _raise_person_memory_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{person_id}/memories",
    response_model=list[PersonMemoryTimelineRow],
)
def list_person_memory_timeline_route(
    person_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[PersonMemoryTimelineRow]:
    try:
        return list_person_memory_timeline(
            db,
            user_id=user_id,
            person_id=person_id,
            limit=limit,
        )
    except PersonMemoryLinkError as exc:
        _raise_person_memory_error(exc)


@router.get(
    "/{person_id}/relationships",
    response_model=list[PersonRelationshipProjection],
)
def list_person_relationships_route(
    person_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[PersonRelationshipProjection]:
    try:
        return list_person_relationships(
            db,
            user_id=user_id,
            person_id=person_id,
            limit=limit,
        )
    except PersonRelationshipError as exc:
        _raise_person_relationship_error(exc)


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
