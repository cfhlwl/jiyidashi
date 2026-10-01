from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy.orm import Session

from app.services.time_service import local_today


class DateParseStatus(StrEnum):
    MATCHED = "MATCHED"
    INVALID = "INVALID"
    FUTURE = "FUTURE"
    NO_MATCH = "NO_MATCH"


@dataclass(frozen=True)
class DateParseResult:
    status: DateParseStatus
    day: date | None = None
    matched_text: str | None = None

    @property
    def matched(self) -> bool:
        return self.status == DateParseStatus.MATCHED and self.day is not None


_ISO_DATE = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
_CHINESE_YMD = re.compile(r"(?<!\d)(\d{4})年(\d{1,2})月(\d{1,2})[日号]")
_MONTH_DAY = re.compile(r"(?<!\d)(\d{1,2})月(\d{1,2})[日号]")
_DAY_ONLY = re.compile(r"(?<![\d月年])(\d{1,2})[号日](?!\d)")
_WEEKDAY = re.compile(r"(上周|本周)([一二三四五六日天])")
_WEEKDAY_INDEX = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
}


def _result_for_day(day: date, matched_text: str, today: date) -> DateParseResult:
    if day > today:
        return DateParseResult(
            status=DateParseStatus.FUTURE,
            day=day,
            matched_text=matched_text,
        )
    return DateParseResult(
        status=DateParseStatus.MATCHED,
        day=day,
        matched_text=matched_text,
    )


def _invalid(matched_text: str) -> DateParseResult:
    return DateParseResult(
        status=DateParseStatus.INVALID,
        matched_text=matched_text,
    )


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _most_recent_month_day(today: date, month: int, day: int) -> date | None:
    # Search backward so leap-day expressions deterministically resolve to the most
    # recent valid occurrence rather than becoming an LLM ambiguity.
    for year in range(today.year, today.year - 9, -1):
        candidate = _safe_date(year, month, day)
        if candidate is not None and candidate <= today:
            return candidate
    return None


def _most_recent_day_of_month(today: date, day: int) -> date | None:
    if day < 1 or day > 31:
        return None
    year = today.year
    month = today.month
    for _ in range(24):
        candidate = _safe_date(year, month, day)
        if candidate is not None and candidate <= today:
            return candidate
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return None


def parse_date_expression(
    question: str,
    *,
    today: date,
) -> DateParseResult:
    clean = question.strip()
    if not clean:
        return DateParseResult(status=DateParseStatus.NO_MATCH)

    # Relative expressions are exact and take precedence over incidental digits.
    if "前天" in clean:
        return DateParseResult(
            status=DateParseStatus.MATCHED,
            day=today - timedelta(days=2),
            matched_text="前天",
        )
    if "昨天" in clean:
        return DateParseResult(
            status=DateParseStatus.MATCHED,
            day=today - timedelta(days=1),
            matched_text="昨天",
        )
    if "今天" in clean:
        return DateParseResult(
            status=DateParseStatus.MATCHED,
            day=today,
            matched_text="今天",
        )

    matched = _ISO_DATE.search(clean)
    if matched:
        raw = matched.group(0)
        candidate = _safe_date(
            int(matched.group(1)),
            int(matched.group(2)),
            int(matched.group(3)),
        )
        if candidate is None:
            return _invalid(raw)
        return _result_for_day(candidate, raw, today)

    matched = _CHINESE_YMD.search(clean)
    if matched:
        raw = matched.group(0)
        candidate = _safe_date(
            int(matched.group(1)),
            int(matched.group(2)),
            int(matched.group(3)),
        )
        if candidate is None:
            return _invalid(raw)
        return _result_for_day(candidate, raw, today)

    matched = _WEEKDAY.search(clean)
    if matched:
        raw = matched.group(0)
        monday = today - timedelta(days=today.weekday())
        if matched.group(1) == "上周":
            monday -= timedelta(days=7)
        candidate = monday + timedelta(days=_WEEKDAY_INDEX[matched.group(2)])
        return _result_for_day(candidate, raw, today)

    matched = _MONTH_DAY.search(clean)
    if matched:
        raw = matched.group(0)
        month = int(matched.group(1))
        day = int(matched.group(2))
        if month < 1 or month > 12 or day < 1 or day > 31:
            return _invalid(raw)
        candidate = _most_recent_month_day(today, month, day)
        if candidate is None:
            return _invalid(raw)
        return DateParseResult(
            status=DateParseStatus.MATCHED,
            day=candidate,
            matched_text=raw,
        )

    matched = _DAY_ONLY.search(clean)
    if matched:
        raw = matched.group(0)
        candidate = _most_recent_day_of_month(today, int(matched.group(1)))
        if candidate is None:
            return _invalid(raw)
        return DateParseResult(
            status=DateParseStatus.MATCHED,
            day=candidate,
            matched_text=raw,
        )

    return DateParseResult(status=DateParseStatus.NO_MATCH)


def resolve_user_date_expression(
    db: Session,
    *,
    user_id: UUID,
    question: str,
    reference_utc: datetime | None = None,
) -> DateParseResult:
    reference = reference_utc or datetime.now(UTC)
    return parse_date_expression(
        question,
        today=local_today(db, user_id, reference),
    )
