from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import AuthenticatedClaims, get_current_user_id
from app.notification_schemas import (
    DevicePushRegistrationRequest,
    DevicePushStateRead,
)
from app.services.notification_service import (
    NotificationDeviceError,
    register_device_push,
    unregister_device_push,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]


def _raise_device_error(exc: NotificationDeviceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


@router.put("/device", response_model=DevicePushStateRead)
def put_notification_device(
    payload: DevicePushRegistrationRequest,
    claims: AuthenticatedClaims,
    user_id: CurrentUser,
    db: DbSession,
) -> DevicePushStateRead:
    try:
        return register_device_push(
            db,
            user_id=user_id,
            payload=payload,
            session_id=claims.session_id,
        )
    except NotificationDeviceError as exc:
        _raise_device_error(exc)


@router.delete("/device/{client_uuid}", response_model=DevicePushStateRead)
def delete_notification_device(
    client_uuid: Annotated[
        str,
        Path(
            min_length=1,
            max_length=80,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ],
    user_id: CurrentUser,
    db: DbSession,
) -> DevicePushStateRead:
    try:
        return unregister_device_push(
            db,
            user_id=user_id,
            client_uuid=client_uuid,
        )
    except NotificationDeviceError as exc:
        _raise_device_error(exc)
