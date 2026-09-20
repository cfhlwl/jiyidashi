from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models import Memory, Place, Visit
from app.schemas import TimelineItem, TimelineItemKind, TimelinePageResponse
from app.services.time_service import user_day_bounds_utc, user_timezone_name

_KIND_RANK = {
    TimelineItemKind.MEMORY: 1,
    TimelineItemKind.VISIT: 0,
}
_CURSOR_VERSION = 1


@dataclass(frozen=True)
class TimelineCursorError(ValueError):
    code: str = "TIMELINE_CURSOR_INVALID"


@dataclass(frozen=True)
class _TimelineCursor:
    occurred_at: datetime
    kind: TimelineItemKind
    resource_id: UUID


def _as_utc(value: datetime) -> datetime:
    # SQLite test storage can round-trip timezone-aware DateTime as naive; production
    # PostgreSQL keeps the offset. Timeline ordering treats any DB-naive value as UTC.
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _encode_cursor(item: TimelineItem) -> str:
    payload = {
        "v": _CURSOR_VERSION,
        "t": _as_utc(item.occurred_at).isoformat(),
        "k": item.kind.value,
        "id": str(item.id),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value: str | None) -> _TimelineCursor | None:
    if value is None:
        return None
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode((value + padding).encode("ascii")).decode("utf-8")
        )
        if payload.get("v") != _CURSOR_VERSION:
            raise ValueError("unsupported cursor version")
        occurred_at = datetime.fromisoformat(payload["t"])
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("cursor timestamp must be timezone-aware")
        return _TimelineCursor(
            occurred_at=occurred_at.astimezone(UTC),
            kind=TimelineItemKind(payload["k"]),
            resource_id=UUID(payload["id"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TimelineCursorError() from exc


def _before_cursor(column_time, column_id, kind: TimelineItemKind, cursor: _TimelineCursor):
    """SQL predicate matching the exact global descending timeline order."""

    rank = _KIND_RANK[kind]
    cursor_rank = _KIND_RANK[cursor.kind]
    earlier_time = column_time < cursor.occurred_at
    if rank < cursor_rank:
        # At the same timestamp this kind sorts after the cursor kind, so every row
        # of this kind belongs to the next page.
        return or_(earlier_time, column_time == cursor.occurred_at)
    if rank > cursor_rank:
        # At the same timestamp this kind sorts before the cursor kind and must not
        # be replayed on the next page.
        return earlier_time
    return or_(
        earlier_time,
        and_(
            column_time == cursor.occurred_at,
            column_id < cursor.resource_id,
        ),
    )


def _sort_key(item: TimelineItem) -> tuple[datetime, int, int]:
    return (
        _as_utc(item.occurred_at),
        _KIND_RANK[item.kind],
        item.id.int,
    )


def _memory_item(memory: Memory, place: Place | None) -> TimelineItem:
    return TimelineItem(
        kind=TimelineItemKind.MEMORY,
        id=memory.id,
        occurred_at=_as_utc(memory.occurred_at),
        place_id=memory.place_id,
        place_name=None if place is None else place.name,
        memory_type=memory.memory_type,
        title=memory.title,
        content=memory.content,
        source_type=memory.source_type,
        is_confirmed=memory.is_confirmed,
        confidence=memory.confidence,
    )


def _visit_item(visit: Visit, place: Place) -> TimelineItem:
    return TimelineItem(
        kind=TimelineItemKind.VISIT,
        id=visit.id,
        occurred_at=_as_utc(visit.arrived_at),
        ended_at=None if visit.left_at is None else _as_utc(visit.left_at),
        place_id=visit.place_id,
        place_name=place.name,
        confidence=visit.confidence,
        visit_source=visit.source,
        visit_finalized=visit.finalized_at is not None,
    )


def list_timeline(
    db: Session,
    *,
    user_id: UUID,
    day: date | None,
    limit: int,
    cursor_value: str | None,
) -> TimelinePageResponse:
    cursor = _decode_cursor(cursor_value)
    start: datetime | None = None
    end: datetime | None = None
    if day is not None:
        start, end = user_day_bounds_utc(db, user_id, day)

    memory_query = (
        select(Memory, Place)
        .outerjoin(
            Place,
            and_(
                Place.id == Memory.place_id,
                Place.user_id == user_id,
            ),
        )
        .where(
            Memory.user_id == user_id,
            Memory.is_deleted.is_(False),
        )
    )
    visit_query = (
        select(Visit, Place)
        .join(
            Place,
            and_(
                Place.id == Visit.place_id,
                Place.user_id == user_id,
            ),
        )
        .where(Visit.user_id == user_id)
    )

    if start is not None and end is not None:
        memory_query = memory_query.where(
            Memory.occurred_at >= start,
            Memory.occurred_at < end,
        )
        visit_query = visit_query.where(
            Visit.arrived_at >= start,
            Visit.arrived_at < end,
        )

    if cursor is not None:
        memory_query = memory_query.where(
            _before_cursor(
                Memory.occurred_at,
                Memory.id,
                TimelineItemKind.MEMORY,
                cursor,
            )
        )
        visit_query = visit_query.where(
            _before_cursor(
                Visit.arrived_at,
                Visit.id,
                TimelineItemKind.VISIT,
                cursor,
            )
        )

    # [人工注释][S2-011] 每个源各取 limit+1 就足够构造全局 top-N：
    # 任一源中排名超过 N 的行，不可能进入两个已排序源合并后的前 N。
    memory_rows = db.execute(
        memory_query.order_by(Memory.occurred_at.desc(), Memory.id.desc()).limit(limit + 1)
    ).all()
    visit_rows = db.execute(
        visit_query.order_by(Visit.arrived_at.desc(), Visit.id.desc()).limit(limit + 1)
    ).all()

    combined = [_memory_item(memory, place) for memory, place in memory_rows]
    combined.extend(_visit_item(visit, place) for visit, place in visit_rows)
    combined.sort(key=_sort_key, reverse=True)

    page_items = combined[:limit]
    next_cursor = None
    if len(combined) > limit and page_items:
        next_cursor = _encode_cursor(page_items[-1])

    return TimelinePageResponse(
        timezone=user_timezone_name(db, user_id),
        day=day,
        items=page_items,
        next_cursor=next_cursor,
    )
