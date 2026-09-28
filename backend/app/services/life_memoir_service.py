from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.life_memoir_models import (
    LifeMemoirChapterResponse,
    LifeMemoirChapterStatus,
    LifeMemoirCitation,
    LifeMemoirStageIndexItem,
    LifeMemoirStageIndexResponse,
)
from app.life_stage_models import LifeStage
from app.long_term_reasoning_models import LongTermReasoningStatus
from app.services.ai_gateway import AIGateway
from app.services.long_term_reasoning_service import reason_about_life_stage

_STAGE_CURSOR_VERSION = 1

LIFE_MEMOIR_QUESTION = (
    "请仅根据提供的证据，把这个人生阶段整理成一段简洁、事实性的回忆录章节。\n"
    "只陈述证据中明确存在的内容；不要补充未出现的人物、地点、事件、因果、情绪或时间。\n"
    "不要把 ended_at=null 推断为阶段仍在持续。"
)


class LifeMemoirError(RuntimeError):
    def __init__(self, code: str, status_code: int = 422):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class _StageCursor:
    started_at: datetime
    life_stage_id: UUID


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _encode_stage_cursor(item: LifeMemoirStageIndexItem) -> str:
    payload = {
        "v": _STAGE_CURSOR_VERSION,
        "t": _as_utc(item.started_at).isoformat(),
        "id": str(item.life_stage_id),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_stage_cursor(value: str | None) -> _StageCursor | None:
    if value is None:
        return None
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode((value + padding).encode("ascii")).decode("utf-8")
        )
        if not isinstance(payload, dict):
            raise ValueError("cursor payload must be an object")
        if payload.get("v") != _STAGE_CURSOR_VERSION:
            raise ValueError("unsupported cursor version")
        started_at = datetime.fromisoformat(payload["t"])
        if started_at.tzinfo is None or started_at.utcoffset() is None:
            raise ValueError("cursor timestamp must be timezone-aware")
        return _StageCursor(
            started_at=started_at.astimezone(UTC),
            life_stage_id=UUID(payload["id"]),
        )
    except (
        binascii.Error,
        KeyError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise LifeMemoirError("LIFE_MEMOIR_STAGE_CURSOR_INVALID") from exc


def list_life_memoir_stages(
    db: Session,
    *,
    user_id: UUID,
    limit: int,
    cursor_value: str | None = None,
) -> LifeMemoirStageIndexResponse:
    cursor = _decode_stage_cursor(cursor_value)

    query = select(LifeStage).where(LifeStage.user_id == user_id)
    if cursor is not None:
        query = query.where(
            or_(
                LifeStage.started_at > cursor.started_at,
                and_(
                    LifeStage.started_at == cursor.started_at,
                    LifeStage.id > cursor.life_stage_id,
                ),
            )
        )

    rows = list(
        db.scalars(
            query.order_by(LifeStage.started_at.asc(), LifeStage.id.asc()).limit(
                limit + 1
            )
        )
    )
    page_rows = rows[:limit]
    items = [
        LifeMemoirStageIndexItem(
            life_stage_id=row.id,
            stage_kind=row.stage_kind,
            title=row.title,
            custom_label=row.custom_label,
            started_at=_as_utc(row.started_at),
            ended_at=None if row.ended_at is None else _as_utc(row.ended_at),
        )
        for row in page_rows
    ]
    next_cursor = None
    if len(rows) > limit and items:
        next_cursor = _encode_stage_cursor(items[-1])

    return LifeMemoirStageIndexResponse(
        items=items,
        next_cursor=next_cursor,
    )


def _chapter_status(reasoning_status: LongTermReasoningStatus) -> LifeMemoirChapterStatus:
    if reasoning_status == LongTermReasoningStatus.ANSWERED:
        return LifeMemoirChapterStatus.CHAPTER_READY
    if reasoning_status == LongTermReasoningStatus.NO_ANSWERABLE_EVIDENCE:
        return LifeMemoirChapterStatus.CHAPTER_EMPTY
    return LifeMemoirChapterStatus.CHAPTER_PARTIAL


async def build_life_memoir_chapter(
    db: Session,
    *,
    user_id: UUID,
    life_stage_id: UUID,
    ai_gateway: AIGateway,
) -> LifeMemoirChapterResponse:
    result = await reason_about_life_stage(
        db,
        user_id=user_id,
        life_stage_id=life_stage_id,
        question=LIFE_MEMOIR_QUESTION,
        ai_gateway=ai_gateway,
    )
    return LifeMemoirChapterResponse(
        status=_chapter_status(result.status),
        life_stage_id=life_stage_id,
        reasoning_status=result.status,
        narrative=result.answer if result.status == LongTermReasoningStatus.ANSWERED else None,
        citations=[
            LifeMemoirCitation(
                slot=item.slot,
                kind=item.kind,
                life_stage_id=item.life_stage_id,
                life_event_id=item.life_event_id,
                memory_id=item.memory_id,
                memory_source_id=item.memory_source_id,
                memory_trust_state=item.memory_trust_state,
            )
            for item in result.citations
        ],
    )
