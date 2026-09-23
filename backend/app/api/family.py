from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.family_models import FamilyPermissionCode
from app.schemas import TodayFootprintResponse
from app.services.family_sensitive_read_service import (
    FamilySensitiveReadError,
    get_family_current_location,
    get_family_memories,
    get_family_today_footprint,
)
from app.services.family_service import (
    FamilyServiceError,
    accept_invite,
    create_family,
    create_invite,
    get_family,
    list_permissions,
    remove_member,
    replace_permissions,
    revoke_invite,
)

router = APIRouter(prefix="/family", tags=["family"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]


class FamilyMemberResponse(BaseModel):
    user_id: UUID
    role: str
    created_at: datetime


class FamilyResponse(BaseModel):
    family_id: UUID
    current_user_role: str
    members: list[FamilyMemberResponse]


class FamilyInviteResponse(BaseModel):
    invite_id: UUID
    token: str
    expires_at: datetime


class FamilyInviteAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=512)


class FamilyPermissionReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    permissions: list[FamilyPermissionCode] = Field(default_factory=list, max_length=4)


class FamilyPermissionResponse(BaseModel):
    grantee_user_id: UUID
    permissions: list[FamilyPermissionCode]


class FamilyCurrentLocationResponse(BaseModel):
    resource_owner_user_id: UUID
    latitude: float
    longitude: float
    accuracy: float | None
    recorded_at: datetime
    fresh_until: datetime


class FamilyMemoryResponse(BaseModel):
    memory_id: UUID
    memory_type: str
    title: str | None
    content: str
    occurred_at: datetime
    source_type: str
    is_confirmed: bool
    edit_revision: int
    created_at: datetime


def _raise(exc: FamilyServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


def _family_response(view) -> FamilyResponse:
    return FamilyResponse(
        family_id=view.family_id,
        current_user_role=view.current_user_role,
        members=[
            FamilyMemberResponse(
                user_id=item.user_id,
                role=item.role,
                created_at=item.created_at,
            )
            for item in view.members
        ],
    )


@router.post("", response_model=FamilyResponse, status_code=status.HTTP_201_CREATED)
def create_current_family(user_id: CurrentUser, db: DbSession) -> FamilyResponse:
    try:
        return _family_response(create_family(db, user_id=user_id))
    except FamilyServiceError as exc:
        _raise(exc)


@router.get("", response_model=FamilyResponse)
def get_current_family(user_id: CurrentUser, db: DbSession) -> FamilyResponse:
    try:
        return _family_response(get_family(db, user_id=user_id))
    except FamilyServiceError as exc:
        _raise(exc)


@router.post(
    "/invites",
    response_model=FamilyInviteResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_family_invite(user_id: CurrentUser, db: DbSession) -> FamilyInviteResponse:
    try:
        result = create_invite(db, user_id=user_id)
    except FamilyServiceError as exc:
        _raise(exc)
    return FamilyInviteResponse(
        invite_id=result.invite_id,
        token=result.token,
        expires_at=result.expires_at,
    )


@router.post("/invites/accept", response_model=FamilyResponse)
def accept_family_invite(
    payload: FamilyInviteAcceptRequest,
    user_id: CurrentUser,
    db: DbSession,
) -> FamilyResponse:
    try:
        return _family_response(
            accept_invite(
                db,
                user_id=user_id,
                token=payload.token,
            )
        )
    except FamilyServiceError as exc:
        _raise(exc)


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_family_invite(
    invite_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
) -> Response:
    try:
        revoke_invite(db, user_id=user_id, invite_id=invite_id)
    except FamilyServiceError as exc:
        _raise(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/members/{target_user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_family_member(
    target_user_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
) -> Response:
    try:
        remove_member(
            db,
            actor_user_id=user_id,
            target_user_id=target_user_id,
        )
    except FamilyServiceError as exc:
        _raise(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/permissions", response_model=list[FamilyPermissionResponse])
def get_family_permissions(
    user_id: CurrentUser,
    db: DbSession,
) -> list[FamilyPermissionResponse]:
    try:
        rows = list_permissions(db, resource_owner_user_id=user_id)
    except FamilyServiceError as exc:
        _raise(exc)
    return [
        FamilyPermissionResponse(
            grantee_user_id=item.grantee_user_id,
            permissions=[FamilyPermissionCode(code) for code in item.permission_codes],
        )
        for item in rows
    ]


@router.put(
    "/permissions/{grantee_user_id}",
    response_model=FamilyPermissionResponse,
)
def put_family_permissions(
    grantee_user_id: UUID,
    payload: FamilyPermissionReplaceRequest,
    user_id: CurrentUser,
    db: DbSession,
) -> FamilyPermissionResponse:
    try:
        result = replace_permissions(
            db,
            resource_owner_user_id=user_id,
            grantee_user_id=grantee_user_id,
            permission_codes=[item.value for item in payload.permissions],
        )
    except FamilyServiceError as exc:
        _raise(exc)
    return FamilyPermissionResponse(
        grantee_user_id=result.grantee_user_id,
        permissions=[FamilyPermissionCode(code) for code in result.permission_codes],
    )


@router.get(
    "/members/{resource_owner_user_id}/current-location",
    response_model=FamilyCurrentLocationResponse,
)
def family_member_current_location(
    resource_owner_user_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
) -> FamilyCurrentLocationResponse:
    try:
        result = get_family_current_location(
            db,
            resource_owner_user_id=resource_owner_user_id,
            grantee_user_id=user_id,
        )
    except FamilySensitiveReadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    return FamilyCurrentLocationResponse(**result.__dict__)


@router.get(
    "/members/{resource_owner_user_id}/memories",
    response_model=list[FamilyMemoryResponse],
)
def family_member_memories(
    resource_owner_user_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
) -> list[FamilyMemoryResponse]:
    try:
        rows = get_family_memories(
            db,
            resource_owner_user_id=resource_owner_user_id,
            grantee_user_id=user_id,
            limit=limit,
        )
    except FamilySensitiveReadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    return [FamilyMemoryResponse(**item.__dict__) for item in rows]


@router.get(
    "/members/{resource_owner_user_id}/today/footprint",
    response_model=TodayFootprintResponse,
)
def family_member_today_footprint(
    resource_owner_user_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
) -> TodayFootprintResponse:
    try:
        return get_family_today_footprint(
            db,
            resource_owner_user_id=resource_owner_user_id,
            grantee_user_id=user_id,
        )
    except FamilySensitiveReadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
