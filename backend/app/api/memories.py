from datetime import UTC, date, datetime, time
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
from app.services.memory_service import create_memory, get_memory_for_user
from app.services.query_service import query_memory

router = APIRouter(tags=["memories"])


@router.post("/memories", response_model=MemoryRead, status_code=status.HTTP_201_CREATED)
def create_memory_endpoint(
    payload: MemoryCreate,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> Memory:
    memory = create_memory(db, user_id, payload)
    db.commit()
    db.refresh(memory)
    return memory


@router.get("/memories/{memory_id}", response_model=MemoryRead)
def get_memory_endpoint(
    memory_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> Memory:
    memory = get_memory_for_user(db, user_id, memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="MEMORY_NOT_FOUND")
    return memory


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory_endpoint(
    memory_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> None:
    memory = get_memory_for_user(db, user_id, memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="MEMORY_NOT_FOUND")

    memory.is_deleted = True
    db.commit()


@router.get("/timeline", response_model=list[MemoryRead])
def timeline(
    day: date | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> list[Memory]:
    query = select(Memory).where(
        Memory.user_id == user_id,
        Memory.is_deleted.is_(False),
    )
    if day is not None:
        start = datetime.combine(day, time.min, tzinfo=UTC)
        end = datetime.combine(day, time.max, tzinfo=UTC)
        query = query.where(Memory.occurred_at.between(start, end))

    result = db.scalars(query.order_by(Memory.occurred_at.desc()).limit(limit))
    return list(result.all())


@router.post("/memory/query", response_model=MemoryQueryResponse)
def memory_query(
    payload: MemoryQueryRequest,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> MemoryQueryResponse:
    return query_memory(db, user_id, payload.question)


@router.get("/memory/summarize/day", response_model=DaySummaryResponse)
def summarize_day(
    day: date = Query(default_factory=date.today),
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> DaySummaryResponse:
    start = datetime.combine(day, time.min, tzinfo=UTC)
    end = datetime.combine(day, time.max, tzinfo=UTC)

    memory_count = db.scalar(
        select(func.count(Memory.id)).where(
            Memory.user_id == user_id,
            Memory.is_deleted.is_(False),
            Memory.occurred_at.between(start, end),
        )
    )
    memories = (
        db.scalars(
            select(Memory)
            .where(
                Memory.user_id == user_id,
                Memory.is_deleted.is_(False),
                Memory.occurred_at.between(start, end),
            )
            .order_by(Memory.occurred_at.asc())
            .limit(8)
        )
    ).all()

    if not memories:
        summary = "今天还没有留下可总结的记忆。"
    else:
        snippets = "；".join(item.content[:50] for item in memories[:4])
        summary = f"今天留下了 {len(memories)} 条主要记录：{snippets}"

    return DaySummaryResponse(
        date=day.isoformat(),
        memory_count=int(memory_count or 0),
        place_count=0,
        summary=summary,
    )
