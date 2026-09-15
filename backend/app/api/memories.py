from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.models import Memory
from app.schemas import (
    DaySummaryResponse,
    MemoryCreate,
    MemoryQueryRequest,
    MemoryQueryResponse,
    MemoryRead,
)
from app.services.memory_service import create_user_memory, get_memory_for_user, soft_delete_memory
from app.services.query_service import query_memory
from app.services.time_service import local_today, user_day_bounds_utc

router = APIRouter(tags=["memories"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]


@router.post("/memories", response_model=MemoryRead, status_code=status.HTTP_201_CREATED)
def create_memory_endpoint(
    payload: MemoryCreate,
    user_id: CurrentUser,
    db: DbSession,
) -> Memory:
    memory = create_user_memory(db, user_id, payload)
    db.commit()
    db.refresh(memory)
    return memory


@router.get("/memories/{memory_id}", response_model=MemoryRead)
def get_memory_endpoint(memory_id: UUID, user_id: CurrentUser, db: DbSession) -> Memory:
    memory = get_memory_for_user(db, user_id, memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="MEMORY_NOT_FOUND")
    return memory


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory_endpoint(memory_id: UUID, user_id: CurrentUser, db: DbSession) -> None:
    memory = get_memory_for_user(db, user_id, memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="MEMORY_NOT_FOUND")

    soft_delete_memory(db, memory)
    db.commit()


@router.get("/timeline", response_model=list[MemoryRead])
def timeline(
    user_id: CurrentUser,
    db: DbSession,
    day: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[Memory]:
    query = select(Memory).where(
        Memory.user_id == user_id,
        Memory.is_deleted.is_(False),
    )
    if day is not None:
        start, end = user_day_bounds_utc(db, user_id, day)
        query = query.where(Memory.occurred_at >= start, Memory.occurred_at < end)

    return list(db.scalars(query.order_by(Memory.occurred_at.desc()).limit(limit)).all())


@router.post("/memory/query", response_model=MemoryQueryResponse)
def memory_query(
    payload: MemoryQueryRequest,
    user_id: CurrentUser,
    db: DbSession,
) -> MemoryQueryResponse:
    return query_memory(db, user_id, payload.question)


@router.get("/memory/summarize/day", response_model=DaySummaryResponse)
def summarize_day(
    user_id: CurrentUser,
    db: DbSession,
    day: Annotated[date | None, Query()] = None,
) -> DaySummaryResponse:
    effective_day = day or local_today(db, user_id)
    start, end = user_day_bounds_utc(db, user_id, effective_day)

    memory_count = db.scalar(
        select(func.count(Memory.id)).where(
            Memory.user_id == user_id,
            Memory.is_deleted.is_(False),
            Memory.occurred_at >= start,
            Memory.occurred_at < end,
        )
    )
    memories = db.scalars(
        select(Memory)
        .where(
            Memory.user_id == user_id,
            Memory.is_deleted.is_(False),
            Memory.occurred_at >= start,
            Memory.occurred_at < end,
        )
        .order_by(Memory.occurred_at.asc())
        .limit(8)
    ).all()

    if not memories:
        summary = "今天还没有留下可总结的记忆。"
    else:
        snippets = "；".join(item.content[:50] for item in memories[:4])
        summary = f"今天留下了 {len(memories)} 条主要记录：{snippets}"

    return DaySummaryResponse(
        date=effective_day.isoformat(),
        memory_count=int(memory_count or 0),
        place_count=0,
        summary=summary,
    )
