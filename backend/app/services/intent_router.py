"""Deterministic owner-scoped routing to existing trusted capabilities.

This module may inspect known Object/Place names only to choose a control path. It
does not answer requests, mutate user data, call model providers, or perform entity
creation/linking; insufficient or mixed signals fail closed to UNKNOWN.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.intent_models import (
    IntentCapability,
    IntentKind,
    IntentRouteReason,
    IntentRouteResult,
)
from app.models import ObjectItem, Place

_OBJECT_LOCATION_MARKERS = (
    "在哪",
    "哪里",
    "何处",
    "什么地方",
    "放哪",
    "放在",
    "位置",
    "去哪了",
    "找不到",
    "where is",
    "where's",
)
_PLACE_HISTORY_MARKERS = (
    "去过",
    "到过",
    "待过",
    "去了哪里",
    "去哪里",
    "哪些地方",
    "什么地方去过",
    "足迹",
    "到访",
    "在哪待过",
    "where did i go",
    "places i visited",
)
_EVENT_MARKERS = (
    "什么时候",
    "哪天",
    "哪一天",
    "发生了什么",
    "发生过什么",
    "哪次",
    "上次什么时候",
    "when did",
    "what happened",
)
_MEMORY_SEARCH_MARKERS = (
    "查一下记录",
    "找一下记录",
    "搜索记录",
    "搜一下",
    "回忆",
    "记得",
    "记录里",
    "历史记录",
    "帮我查",
    "search my memories",
    "remember",
)
_UNSUPPORTED_ACTION_MARKERS = (
    "提醒我",
    "设置提醒",
    "创建提醒",
    "删除",
    "修改",
    "编辑",
    "新增",
    "创建",
    "remind me",
    "delete",
    "edit",
    "create",
)

_CLEAN_SEPARATORS = re.compile(r"[\\s？?。！!，,：:；;、]+")


def _normalize(value: str) -> str:
    lowered = value.strip().lower()
    return _CLEAN_SEPARATORS.sub("", lowered)


def _contains_marker(question: str, markers: Iterable[str]) -> bool:
    lowered = question.lower()
    compact = _normalize(question)
    for marker in markers:
        normalized_marker = marker.lower()
        if " " in normalized_marker:
            if normalized_marker in lowered:
                return True
        elif _normalize(normalized_marker) in compact:
            return True
    return False


def _known_name_match(question: str, names: Iterable[str]) -> tuple[bool, bool]:
    """Return (matched, ambiguous) using the unique longest known-name rule."""

    compact_question = _normalize(question)
    if not compact_question:
        return False, False

    matches: list[str] = []
    for name in names:
        normalized = _normalize(name)
        if normalized and normalized in compact_question:
            matches.append(normalized)

    if not matches:
        return False, False

    best_length = max(len(name) for name in matches)
    best = [name for name in matches if len(name) == best_length]
    # A duplicated best name is still ambiguous for routing because entity
    # extraction/linking belongs to S3-004/S3-005 and must not be guessed here.
    return len(best) == 1, len(best) != 1


def _unknown(reason: IntentRouteReason) -> IntentRouteResult:
    return IntentRouteResult(
        intent=IntentKind.UNKNOWN,
        capability=None,
        reason=reason,
    )


def route_intent(
    db: Session,
    *,
    user_id: UUID,
    question: str,
) -> IntentRouteResult:
    """Choose an existing trusted capability without inventing user facts.

    Specific trusted-domain signals take precedence over generic memory-search
    language. Mixed specific domains fail closed as UNKNOWN instead of guessing.
    """

    clean_question = question.strip()
    if not clean_question:
        return _unknown(IntentRouteReason.NO_SUPPORTED_RULE)

    if _contains_marker(clean_question, _UNSUPPORTED_ACTION_MARKERS):
        # Reminder creation and mutations are explicitly outside this foundation.
        return _unknown(IntentRouteReason.UNSUPPORTED)

    object_names = db.scalars(
        select(ObjectItem.name).where(ObjectItem.user_id == user_id)
    ).all()
    place_names = db.scalars(select(Place.name).where(Place.user_id == user_id)).all()

    object_match, object_ambiguous = _known_name_match(clean_question, object_names)
    place_match, place_ambiguous = _known_name_match(clean_question, place_names)

    object_signal = object_match and _contains_marker(
        clean_question,
        _OBJECT_LOCATION_MARKERS,
    )
    place_signal = (
        _contains_marker(clean_question, _PLACE_HISTORY_MARKERS)
        or (
            place_match
            and _contains_marker(
                clean_question,
                _OBJECT_LOCATION_MARKERS,
            )
        )
    )
    event_signal = _contains_marker(clean_question, _EVENT_MARKERS)
    memory_signal = _contains_marker(clean_question, _MEMORY_SEARCH_MARKERS)

    if (
        object_ambiguous
        and _contains_marker(clean_question, _OBJECT_LOCATION_MARKERS)
    ) or (
        place_ambiguous
        and _contains_marker(
            clean_question,
            _PLACE_HISTORY_MARKERS + _OBJECT_LOCATION_MARKERS + _EVENT_MARKERS,
        )
    ):
        return _unknown(IntentRouteReason.AMBIGUOUS)

    # A request spanning multiple specific domains is not safe to split here.
    # Future entity extraction/linking may make that possible in a separate line.
    if object_signal and place_signal:
        return _unknown(IntentRouteReason.AMBIGUOUS)

    if object_signal:
        return IntentRouteResult(
            intent=IntentKind.FIND_OBJECT,
            capability=IntentCapability.OBJECT_LOCATION_QUERY,
            reason=IntentRouteReason.MATCHED,
        )

    # Place/history is more specific than generic event language, e.g.
    # “我什么时候去过公司” must stay on the trusted Place/Visit path.
    if place_signal:
        return IntentRouteResult(
            intent=IntentKind.FIND_PLACE,
            capability=IntentCapability.PLACE_HISTORY_QUERY,
            reason=IntentRouteReason.MATCHED,
        )

    if event_signal:
        return IntentRouteResult(
            intent=IntentKind.FIND_EVENT,
            capability=IntentCapability.MEMORY_QUERY,
            reason=IntentRouteReason.MATCHED,
        )

    if memory_signal:
        return IntentRouteResult(
            intent=IntentKind.MEMORY_SEARCH,
            capability=IntentCapability.MEMORY_QUERY,
            reason=IntentRouteReason.MATCHED,
        )

    # Free-form text is intentionally not treated as a generic memory query.
    # Unsupported/weak input must remain UNKNOWN until a later explicit fallback exists.
    return _unknown(IntentRouteReason.NO_SUPPORTED_RULE)
