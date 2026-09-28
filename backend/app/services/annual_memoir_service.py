from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.annual_memoir_models import (
    AnnualMemoirCitation,
    AnnualMemoirPhotoItem,
    AnnualMemoirPhotoPage,
    AnnualMemoirResponse,
    AnnualMemoirStatus,
)
from app.annual_summary_models import AnnualSummaryResult, AnnualSummaryStatus
from app.media_models import MediaAsset, MediaEvidenceLink, MediaKind, MediaStatus
from app.models import Memory, MemorySource, MemoryType
from app.services.ai_gateway import AIGateway
from app.services.annual_summary_service import summarize_year
from app.services.life_history_service import list_life_history_timeline
from app.services.time_service import user_timezone_name

_TARGET_YEAR_RE = re.compile(r"^(?P<year>\d{4})$")
_PHOTO_CURSOR_VERSION = 1
_PHOTO_PREVIEW_LIMIT = 24


class AnnualMemoirError(RuntimeError):
    def __init__(self, code: str, status_code: int = 422):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class _PhotoCursor:
    occurred_at: datetime
    memory_id: UUID
    media_id: UUID


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_target_year(value: str) -> int:
    if not isinstance(value, str):
        raise AnnualMemoirError("ANNUAL_MEMOIR_YEAR_INVALID")
    match = _TARGET_YEAR_RE.fullmatch(value)
    if match is None:
        raise AnnualMemoirError("ANNUAL_MEMOIR_YEAR_INVALID")
    year = int(match.group("year"))
    if not 1 <= year <= 9998:
        raise AnnualMemoirError("ANNUAL_MEMOIR_YEAR_INVALID")
    return year


def _local_year_boundary_utc(year: int, zone: ZoneInfo) -> datetime:
    boundary = datetime(year, 1, 1, tzinfo=zone)
    try:
        return boundary.astimezone(UTC)
    except OverflowError:
        if year == 1:
            return datetime.min.replace(tzinfo=UTC)
        raise


def _closed_year_context(
    db: Session,
    *,
    user_id: UUID,
    target_year: str,
    reference_utc: datetime,
) -> tuple[int, str, datetime, datetime]:
    year = _parse_target_year(target_year)
    timezone_name = user_timezone_name(db, user_id)
    zone = ZoneInfo(timezone_name)
    current_local_year = reference_utc.astimezone(zone).year
    if year >= current_local_year:
        raise AnnualMemoirError("ANNUAL_MEMOIR_YEAR_NOT_CLOSED")
    return (
        year,
        timezone_name,
        _local_year_boundary_utc(year, zone),
        _local_year_boundary_utc(year + 1, zone),
    )


def _encode_photo_cursor(item: AnnualMemoirPhotoItem) -> str:
    payload = {
        "v": _PHOTO_CURSOR_VERSION,
        "t": _as_utc(item.occurred_at).isoformat(),
        "m": str(item.memory_id),
        "i": str(item.media_id),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_photo_cursor(value: str | None) -> _PhotoCursor | None:
    if value is None:
        return None
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode((value + padding).encode("ascii")).decode("utf-8")
        )
        if not isinstance(payload, dict):
            raise ValueError("cursor payload must be an object")
        if payload.get("v") != _PHOTO_CURSOR_VERSION:
            raise ValueError("unsupported cursor version")
        occurred_at = datetime.fromisoformat(payload["t"])
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError("cursor timestamp must be timezone-aware")
        return _PhotoCursor(
            occurred_at=occurred_at.astimezone(UTC),
            memory_id=UUID(payload["m"]),
            media_id=UUID(payload["i"]),
        )
    except (
        binascii.Error,
        KeyError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise AnnualMemoirError("ANNUAL_MEMOIR_PHOTO_CURSOR_INVALID") from exc


def _after_photo_cursor(cursor: _PhotoCursor):
    return or_(
        Memory.occurred_at > cursor.occurred_at,
        and_(
            Memory.occurred_at == cursor.occurred_at,
            Memory.id > cursor.memory_id,
        ),
        and_(
            Memory.occurred_at == cursor.occurred_at,
            Memory.id == cursor.memory_id,
            MediaAsset.id > cursor.media_id,
        ),
    )


def _photo_item(memory: Memory, media: MediaAsset) -> AnnualMemoirPhotoItem:
    return AnnualMemoirPhotoItem(
        memory_id=memory.id,
        media_id=media.id,
        occurred_at=_as_utc(memory.occurred_at),
        title=memory.title,
        content_type=media.content_type,
    )


def list_annual_memoir_photos(
    db: Session,
    *,
    user_id: UUID,
    target_year: str,
    limit: int = _PHOTO_PREVIEW_LIMIT,
    cursor_value: str | None = None,
    reference_utc: datetime | None = None,
) -> AnnualMemoirPhotoPage:
    reference = _as_utc(reference_utc or datetime.now(UTC))
    _, timezone_name, start_utc, end_utc = _closed_year_context(
        db,
        user_id=user_id,
        target_year=target_year,
        reference_utc=reference,
    )
    cursor = _decode_photo_cursor(cursor_value)

    query = (
        select(Memory, MediaAsset)
        .join(
            MemorySource,
            MemorySource.memory_id == Memory.id,
        )
        .join(
            MediaEvidenceLink,
            MediaEvidenceLink.memory_source_id == MemorySource.id,
        )
        .join(
            MediaAsset,
            MediaAsset.id == MediaEvidenceLink.media_id,
        )
        .where(
            Memory.user_id == user_id,
            Memory.memory_type == MemoryType.PHOTO,
            Memory.is_deleted.is_(False),
            Memory.occurred_at >= start_utc,
            Memory.occurred_at < end_utc,
            MediaAsset.user_id == user_id,
            MediaAsset.kind == MediaKind.IMAGE,
            MediaAsset.status == MediaStatus.READY,
        )
    )
    if cursor is not None:
        query = query.where(_after_photo_cursor(cursor))

    rows = db.execute(
        query.order_by(
            Memory.occurred_at.asc(),
            Memory.id.asc(),
            MediaAsset.id.asc(),
        ).limit(limit + 1)
    ).all()
    page_rows = rows[:limit]
    items = [_photo_item(memory, media) for memory, media in page_rows]
    next_cursor = None
    if len(rows) > limit and items:
        next_cursor = _encode_photo_cursor(items[-1])

    return AnnualMemoirPhotoPage(
        timezone=timezone_name,
        target_year=target_year,
        items=items,
        next_cursor=next_cursor,
    )


def _citation_projection(result: AnnualSummaryResult) -> list[AnnualMemoirCitation]:
    return [
        AnnualMemoirCitation(
            slot=item.slot,
            kind=item.kind,
            memory_id=item.memory_id,
            visit_id=item.visit_id,
            trust_state=item.trust_state,
        )
        for item in result.citations
    ]


def _memoir_status(
    *,
    narrative_status: AnnualSummaryStatus,
    timeline_empty: bool,
    photos_empty: bool,
) -> AnnualMemoirStatus:
    if narrative_status == AnnualSummaryStatus.ANNUAL_SUMMARY_READY:
        return AnnualMemoirStatus.MEMOIR_READY
    if (
        narrative_status == AnnualSummaryStatus.NO_SUMMARIZABLE_EVIDENCE
        and timeline_empty
        and photos_empty
    ):
        return AnnualMemoirStatus.MEMOIR_EMPTY
    return AnnualMemoirStatus.MEMOIR_PARTIAL


async def build_annual_memoir(
    db: Session,
    *,
    user_id: UUID,
    target_year: str,
    ai_gateway: AIGateway,
    reference_utc: datetime | None = None,
) -> AnnualMemoirResponse:
    """Compose live authoritative components; this is not an immutable snapshot."""

    reference = _as_utc(reference_utc or datetime.now(UTC))
    year, _, _, _ = _closed_year_context(
        db,
        user_id=user_id,
        target_year=target_year,
        reference_utc=reference,
    )

    narrative = await summarize_year(
        db,
        user_id=user_id,
        ai_gateway=ai_gateway,
        target_year=target_year,
        reference_utc=reference,
    )
    timeline = list_life_history_timeline(
        db,
        user_id=user_id,
        start_year=year,
        end_year=year,
        limit=100,
        cursor_value=None,
        reference_utc=reference,
    )
    photos = list_annual_memoir_photos(
        db,
        user_id=user_id,
        target_year=target_year,
        limit=_PHOTO_PREVIEW_LIMIT,
        cursor_value=None,
        reference_utc=reference,
    )

    status = _memoir_status(
        narrative_status=narrative.status,
        timeline_empty=not timeline.items,
        photos_empty=not photos.items,
    )
    return AnnualMemoirResponse(
        status=status,
        target_year=target_year,
        timezone=narrative.timezone,
        narrative_status=narrative.status,
        narrative=narrative.summary,
        narrative_citations=_citation_projection(narrative),
        timeline_items=timeline.items,
        timeline_next_cursor=timeline.next_cursor,
        photo_items=photos.items,
        photo_next_cursor=photos.next_cursor,
    )
