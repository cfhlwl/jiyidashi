from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.data_deletion_models import DataDeletionStatus
from app.deps import get_authenticated_user_id
from app.services.data_deletion_service import DataDeletionError, delete_all_user_data
from app.services.object_storage import ObjectStorage, get_object_storage

router = APIRouter(prefix="/data", tags=["data"])
AuthenticatedUser = Annotated[UUID, Depends(get_authenticated_user_id)]
DbSession = Annotated[Session, Depends(get_db)]
Storage = Annotated[ObjectStorage, Depends(get_object_storage)]


class DataDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    # [人工注释][S1-021] destructive confirmation is an exact protocol value, not a
    # truthy boolean; accidental/malformed callers must fail schema validation before mutation.
    confirmation: Literal["DELETE_MY_DATA"]


class DataDeleteResponse(BaseModel):
    request_id: UUID
    status: DataDeletionStatus
    completed: bool
    retry_after_seconds: int | None = None
    deleted_counts: dict[str, int]


@router.post("/delete", response_model=DataDeleteResponse)
def delete_current_user_data(
    payload: DataDeleteRequest,
    response: Response,
    user_id: AuthenticatedUser,
    db: DbSession,
    storage: Storage,
) -> DataDeleteResponse:
    # This endpoint intentionally bypasses the normal data-access deletion gate so the same
    # authenticated account can retry a partially completed deletion operation.
    try:
        result = delete_all_user_data(
            db,
            user_id=user_id,
            request_id=payload.request_id,
            storage=storage,
        )
    except DataDeletionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc

    if not result.completed:
        response.status_code = status.HTTP_202_ACCEPTED
    return DataDeleteResponse(
        request_id=result.request_id,
        status=result.status,
        completed=result.completed,
        retry_after_seconds=result.retry_after_seconds,
        deleted_counts=result.deleted_counts,
    )
