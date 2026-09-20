from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models import Place, Visit
from app.schemas import PlaceDetailResponse, PlaceDetailVisitRead, PlaceRead

_CURSOR_VERSION = 1


@dataclass(frozen=True)
class PlaceDetailError(RuntimeError):
    code: str
    status_code: int


@dataclass(frozen=True)
class PlaceDetailCursorError(ValueError):
    code: str = "PLACE_DETAIL_CURSOR_INVALID"


@dataclass(frozen=True)
class _VisitCursor:
    arrived_at: datetime
    visit_id: UUID


def _as_utc(value: datetime) -> datetime:
    # SQLite tests may round-trip timezone-aware DB timestamps as naive values;
    # production PostgreSQL preserves offsets. Treat DB-naive values as UTC only.
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _encode_cursor(visit: Visit) -> str:
    payload = {
        "v": _CURSOR_VERSION,
        "t": _as_utc(visit.arrived_at).isoformat(),
        "id": str(visit.id),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value: str | None) -> _VisitCursor | None:
    if value is None:
        return None
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode((value + padding).encode("ascii")).decode("utf-8")
        )
        # [人工注释][S2-013] opaque cursor 与 Timeline 使用相同 fail-closed 原则：
        # base64/JSON 合法但顶层不是 object 也只能作为协议错误返回 422。
        if not isinstance(payload, dict):
            raise ValueError("cursor payload must be a JSON object")
        if payload.get("v") != _CURSOR_VERSION:
            raise ValueError("unsupported cursor version")
        arrived_at = datetime.fromisoformat(payload["t"])
        if arrived_at.tzinfo is None or arrived_at.utcoffset() is None:
            raise ValueError("cursor timestamp must be timezone-aware")
        return _VisitCursor(
            arrived_at=arrived_at.astimezone(UTC),
            visit_id=UUID(payload["id"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PlaceDetailCursorError() from exc


def _visit_read(visit: Visit) -> PlaceDetailVisitRead:
    return PlaceDetailVisitRead(
        id=visit.id,
        arrived_at=_as_utc(visit.arrived_at),
        left_at=None if visit.left_at is None else _as_utc(visit.left_at),
        duration_seconds=visit.duration_seconds,
        confidence=visit.confidence,
        source=visit.source,
        finalized_at=(
            None if visit.finalized_at is None else _as_utc(visit.finalized_at)
        ),
        visit_finalized=visit.finalized_at is not None,
    )


def get_place_detail(
    db: Session,
    *,
    user_id: UUID,
    place_id: UUID,
    limit: int,
    cursor_value: str | None,
) -> PlaceDetailResponse:
    place = db.scalar(
        select(Place).where(
            Place.id == place_id,
            Place.user_id == user_id,
        )
    )
    if place is None:
        # [人工注释][S2-013] unknown 与 cross-owner 都统一 404；绝不通过状态码
        # 暴露“这个 Place 是否属于另一个账号”。
        raise PlaceDetailError("PLACE_NOT_FOUND", 404)

    cursor = _decode_cursor(cursor_value)
    query = select(Visit).where(
        Visit.user_id == user_id,
        Visit.place_id == place_id,
    )
    if cursor is not None:
        query = query.where(
            or_(
                Visit.arrived_at < cursor.arrived_at,
                and_(
                    Visit.arrived_at == cursor.arrived_at,
                    Visit.id < cursor.visit_id,
                ),
            )
        )

    rows = list(
        db.scalars(
            query.order_by(Visit.arrived_at.desc(), Visit.id.desc()).limit(limit + 1)
        )
    )
    page = rows[:limit]
    next_cursor = _encode_cursor(page[-1]) if len(rows) > limit and page else None

    return PlaceDetailResponse(
        place=PlaceRead.model_validate(place),
        visits=[_visit_read(visit) for visit in page],
        next_cursor=next_cursor,
    )
