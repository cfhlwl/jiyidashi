from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.annual_memoir_models import (
    AnnualMemoirPhotoPage,
    AnnualMemoirRequest,
    AnnualMemoirResponse,
)
from app.core.db import get_db
from app.deps import get_current_user_id
from app.services.ai_gateway import AIEntitlementError, get_ai_gateway
from app.services.annual_memoir_service import (
    AnnualMemoirError,
    build_annual_memoir,
    list_annual_memoir_photos,
)
from app.services.api_abuse import enforce_authenticated_api_rate
from app.services.auth_rate_limit import ApiRouteClass

router = APIRouter(prefix="/memoirs", tags=["memoirs"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]


def _raise_annual_memoir_error(exc: AnnualMemoirError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


@router.post("/annual", response_model=AnnualMemoirResponse)
async def generate_annual_memoir(
    payload: AnnualMemoirRequest,
    request: Request,
    user_id: CurrentUser,
    db: DbSession,
) -> AnnualMemoirResponse:
    enforce_authenticated_api_rate(
        db,
        user_id=user_id,
        request=request,
        route_class=ApiRouteClass.EXPENSIVE_AI,
    )
    try:
        return await build_annual_memoir(
            db,
            user_id=user_id,
            target_year=payload.target_year,
            ai_gateway=get_ai_gateway(),
        )
    except AIEntitlementError as exc:
        if exc.code != "PROVIDER_CONCURRENCY_SATURATED":
            raise
        headers = (
            {"Retry-After": str(max(1, int(exc.retry_after)))}
            if exc.retry_after is not None
            else None
        )
        raise HTTPException(
            status_code=429,
            detail=exc.code,
            headers=headers,
        ) from exc
    except AnnualMemoirError as exc:
        _raise_annual_memoir_error(exc)


@router.get(
    "/annual/{target_year}/photos",
    response_model=AnnualMemoirPhotoPage,
)
def get_annual_memoir_photos(
    target_year: str,
    user_id: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 24,
    cursor: str | None = None,
) -> AnnualMemoirPhotoPage:
    try:
        return list_annual_memoir_photos(
            db,
            user_id=user_id,
            target_year=target_year,
            limit=limit,
            cursor_value=cursor,
        )
    except AnnualMemoirError as exc:
        _raise_annual_memoir_error(exc)
