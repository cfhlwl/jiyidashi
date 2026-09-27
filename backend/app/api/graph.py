from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.graph_schemas import GraphNeighborhood, GraphNodeKind
from app.services.graph_projection_service import (
    GraphProjectionError,
    get_graph_neighborhood,
)

router = APIRouter(prefix="/graph", tags=["graph"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]


@router.get(
    "/neighborhood/{kind}/{entity_id}",
    response_model=GraphNeighborhood,
)
def graph_neighborhood_route(
    kind: GraphNodeKind,
    entity_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> GraphNeighborhood:
    try:
        return get_graph_neighborhood(
            db,
            user_id=user_id,
            kind=kind,
            entity_id=entity_id,
            limit=limit,
        )
    except GraphProjectionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
