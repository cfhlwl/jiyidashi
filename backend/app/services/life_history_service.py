from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.life_event_models import LifeEvent
from app.life_history_models import (
    LifeHistoryItem,
    LifeHistoryItemKind,
    LifeHistoryTimelineResponse,
)
from app.life_stage_models import LifeStage
from app.services.time_service import user_timezone_name

_CURSOR_VERSION = 1
_KIND_RANK = {
    LifeHistoryItemKind.LIFE_EVENT: 2,
    LifeHistoryItemKind.LIFE_STAGE_ENDED: 1,
    LifeHistoryItemKind.LIFE_STAGE_STARTED: 0,
}


class LifeHistoryError(RuntimeError):
    def __init__(self, code: str, status_code: int = 422):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class _LifeHistoryCursor:
    occurred_at: datetime
    kind: LifeHistoryItemKind
    resource_id: UUID


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _resource_id(item: LifeHistoryItem) -> UUID:
    if item.kind == LifeHistoryItemKind.LIFE_EVENT:
        assert item.life_event_id is not None
        return item.life_event_id
    assert item.life_stage_id is not None
    return item.life_stage_id


def _encode_cursor(item: LifeHistoryItem) -> str:
    payload = {
        "v": _CURSOR_VERSION,
        "t": _as_utc(item.occurred_at).isoformat(),
        "k": item.kind.value,
        "id": str(_resource_id(item)),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value: str | None) -> _LifeHistoryCursor | None:
    if value is None:
        return None
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode((value + padding).encode("ascii")).decode("utf-8")
        )
        if not isinstance(payload, dict):
            raise ValueError("cursor payload must be object")
        if payload.get("v") != _CURSOR_VERSION:
            raise ValueError("unsupported cursor version")
        occurred_at = datetime.fromisoformat(payload["t"])
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("cursor timestamp must be timezone-aware")
        return _LifeHistoryCursor(
            occurred_at=occurred_at.astimezone(UTC),
            kind=LifeHistoryItemKind(payload["k"]),
            resource_id=UUID(payload["id"]),
        )
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LifeHistoryError("LIFE_HISTORY_CURSOR_INVALID") from exc


def _before_cursor(column_time, column_id, kind: LifeHistoryItemKind, cursor):
    rank = _KIND_RANK[kind]
    cursor_rank = _KIND_RANK[cursor.kind]
    earlier_time = column_time < cursor.occurred_at
    if rank < cursor_rank:
        return or_(earlier_time, column_time == cursor.occurred_at)
    if rank > cursor_rank:
        return earlier_time
    return or_(
        earlier_time,
        and_(
            column_time == cursor.occurred_at,
            column_id < cursor.resource_id,
        ),
    )


def _sort_key(item: LifeHistoryItem) -> tuple[datetime, int, int]:
    return (
        _as_utc(item.occurred_at),
        _KIND_RANK[item.kind],
        _resource_id(item).int,
    )


def _event_item(event: LifeEvent) -> LifeHistoryItem:
    return LifeHistoryItem(
        kind=LifeHistoryItemKind.LIFE_EVENT,
        occurred_at=_as_utc(event.started_at),
        title=event.title,
        custom_label=event.custom_label,
        life_event_id=event.id,
        event_kind=event.event_kind,
        event_ended_at=None if event.ended_at is None else _as_utc(event.ended_at),
        place_id=event.place_id,
    )


def _stage_item(stage: LifeStage, kind: LifeHistoryItemKind) -> LifeHistoryItem:
    occurred_at = (
        stage.started_at
        if kind == LifeHistoryItemKind.LIFE_STAGE_STARTED
        else stage.ended_at
    )
    assert occurred_at is not None
    return LifeHistoryItem(
        kind=kind,
        occurred_at=_as_utc(occurred_at),
        title=stage.title,
        custom_label=stage.custom_label,
        life_stage_id=stage.id,
        stage_kind=stage.stage_kind,
    )


def _validate_years(
    *,
    start_year: int,
    end_year: int,
    current_local_year: int,
) -> None:
    if start_year > end_year:
        raise LifeHistoryError("LIFE_HISTORY_YEAR_RANGE_INVALID")
    if end_year - start_year + 1 > 10:
        raise LifeHistoryError("LIFE_HISTORY_YEAR_SPAN_TOO_LARGE")
    if end_year > current_local_year:
        raise LifeHistoryError("LIFE_HISTORY_FUTURE_YEAR_NOT_ALLOWED")


def list_life_history_timeline(
    db: Session,
    *,
    user_id: UUID,
    start_year: int,
    end_year: int,
    limit: int,
    cursor_value: str | None,
    reference_utc: datetime | None = None,
) -> LifeHistoryTimelineResponse:
    """Read current explicit long-term facts; the cursor is not a snapshot token."""

    as_of = _as_utc(reference_utc or datetime.now(UTC))
    timezone_name = user_timezone_name(db, user_id)
    zone = ZoneInfo(timezone_name)
    current_local_year = as_of.astimezone(zone).year
    _validate_years(
        start_year=start_year,
        end_year=end_year,
        current_local_year=current_local_year,
    )
    cursor = _decode_cursor(cursor_value)

    range_start_utc = datetime(start_year, 1, 1, tzinfo=zone).astimezone(UTC)
    range_end_utc = datetime(end_year + 1, 1, 1, tzinfo=zone).astimezone(UTC)

    event_query = select(LifeEvent).where(
        LifeEvent.user_id == user_id,
        LifeEvent.started_at >= range_start_utc,
        LifeEvent.started_at < range_end_utc,
        LifeEvent.started_at <= as_of,
    )
    stage_start_query = select(LifeStage).where(
        LifeStage.user_id == user_id,
        LifeStage.started_at >= range_start_utc,
        LifeStage.started_at < range_end_utc,
        LifeStage.started_at <= as_of,
    )
    stage_end_query = select(LifeStage).where(
        LifeStage.user_id == user_id,
        LifeStage.ended_at.is_not(None),
        LifeStage.ended_at >= range_start_utc,
        LifeStage.ended_at < range_end_utc,
        LifeStage.ended_at <= as_of,
    )

    if cursor is not None:
        event_query = event_query.where(
            _before_cursor(
                LifeEvent.started_at,
                LifeEvent.id,
                LifeHistoryItemKind.LIFE_EVENT,
                cursor,
            )
        )
        stage_start_query = stage_start_query.where(
            _before_cursor(
                LifeStage.started_at,
                LifeStage.id,
                LifeHistoryItemKind.LIFE_STAGE_STARTED,
                cursor,
            )
        )
        stage_end_query = stage_end_query.where(
            _before_cursor(
                LifeStage.ended_at,
                LifeStage.id,
                LifeHistoryItemKind.LIFE_STAGE_ENDED,
                cursor,
            )
        )

    event_rows = list(
        db.scalars(
            event_query.order_by(LifeEvent.started_at.desc(), LifeEvent.id.desc()).limit(
                limit + 1
            )
        )
    )
    stage_start_rows = list(
        db.scalars(
            stage_start_query.order_by(
                LifeStage.started_at.desc(),
                LifeStage.id.desc(),
            ).limit(limit + 1)
        )
    )
    stage_end_rows = list(
        db.scalars(
            stage_end_query.order_by(
                LifeStage.ended_at.desc(),
                LifeStage.id.desc(),
            ).limit(limit + 1)
        )
    )

    combined = [_event_item(row) for row in event_rows]
    combined.extend(
        _stage_item(row, LifeHistoryItemKind.LIFE_STAGE_STARTED)
        for row in stage_start_rows
    )
    combined.extend(
        _stage_item(row, LifeHistoryItemKind.LIFE_STAGE_ENDED)
        for row in stage_end_rows
    )
    combined.sort(key=_sort_key, reverse=True)

    items = combined[:limit]
    next_cursor = None
    if len(combined) > limit and items:
        next_cursor = _encode_cursor(items[-1])

    return LifeHistoryTimelineResponse(
        timezone=timezone_name,
        start_year=start_year,
        end_year=end_year,
        as_of=as_of,
        items=items,
        next_cursor=next_cursor,
    )
