from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.entitlement_schemas import AIQuotaRead, EntitlementRead, QuotaRead
from app.services.entitlement_service import (
    EntitlementError,
    entitlement_snapshot,
)

router = APIRouter(prefix="/entitlements", tags=["entitlements"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/me", response_model=EntitlementRead)
def get_my_entitlement(
    user_id: CurrentUser,
    db: DbSession,
) -> EntitlementRead:
    try:
        snapshot = entitlement_snapshot(db, user_id=user_id)
    except EntitlementError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc

    return EntitlementRead(
        plan_code=snapshot.plan_code,
        capabilities=list(snapshot.capabilities),
        storage=QuotaRead(
            used=snapshot.storage_used_bytes,
            limit=snapshot.storage_limit_bytes,
        ),
        ai_requests=AIQuotaRead(
            used=snapshot.ai_requests_used,
            limit=snapshot.ai_requests_limit,
            period_start=snapshot.ai_period_start,
            period_end=snapshot.ai_period_end,
        ),
    )
