import re
from datetime import datetime
from uuid import UUID

from sqlalchemy import desc, exists, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Memory,
    MemorySource,
    MemoryType,
    ObjectItem,
    ObjectLocation,
    ObjectLocationStatus,
    SourceType,
)
from app.schemas import Evidence, MemoryQueryResponse

OBJECT_LOCATION_MARKERS = (
    "在哪",
    "哪里",
    "何处",
    "什么地方",
    "放哪",
    "放在",
    "位置",
)
CJK_RUN = re.compile(r"[\u3400-\u9fff]+")


def _compact_text(text: str) -> str:
    value = text.strip().lower()
    return re.sub(r"[\s？?。！!，,：:；;]+", "", value)


def _has_object_location_intent(question: str) -> bool:
    return any(marker in question for marker in OBJECT_LOCATION_MARKERS)


def _resolve_object(
    db: Session,
    user_id: UUID,
    question: str,
) -> tuple[ObjectItem | None, bool]:
    # [人工注释][S1-PR3-FIX-005] Object 身份必须在查位置之前唯一解析。
    # 子串重叠时只接受唯一的最长/最具体匹配；同等最佳无法唯一判断时宁可 NO_EVIDENCE。
    compact_question = _compact_text(question)
    if not compact_question:
        return None, False

    objects = db.scalars(
        select(ObjectItem).where(ObjectItem.user_id == user_id)
    ).all()
    matched = [
        (item, _compact_text(item.name))
        for item in objects
        if _compact_text(item.name) and _compact_text(item.name) in compact_question
    ]
    if not matched:
        return None, False

    best_length = max(len(normalized_name) for _, normalized_name in matched)
    best_matches = [
        item for item, normalized_name in matched if len(normalized_name) == best_length
    ]
    if len(best_matches) != 1:
        return None, True
    return best_matches[0], False


def _eligible_memory_exists() -> exists:
    return exists(
        select(MemorySource.id).where(
            MemorySource.memory_id == Memory.id,
            MemorySource.source_type != SourceType.AI_INFERENCE,
            MemorySource.confidence >= 0.6,
        )
    )


def _best_memory_source(db: Session, memory_id: UUID) -> MemorySource | None:
    # [人工注释][S1-FIX-002] 查询响应必须返回真正参与 Evidence gate 的 MemorySource，
    # 不得用 MEMORY / OBJECT_LOCATION 这种实体 kind 冒充来源。
    return db.scalar(
        select(MemorySource)
        .where(
            MemorySource.memory_id == memory_id,
            MemorySource.source_type != SourceType.AI_INFERENCE,
            MemorySource.confidence >= 0.6,
        )
        .order_by(desc(MemorySource.confidence), desc(MemorySource.created_at))
        .limit(1)
    )


def _search_terms(question: str) -> list[str]:
    """Create deterministic terms that work for both Chinese and spaced text.

    Chinese does not have whitespace word boundaries. Bigrams make queries such
    as “老张合同” match “老张周五下午来公司取合同” without requiring an LLM.
    """

    terms: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        value = value.strip().lower()
        if len(value) >= 2 and value not in seen:
            seen.add(value)
            terms.append(value)

    for token in re.split(r"[\s，。！？,.!?：:；;]+", question):
        add(token)

    for run in CJK_RUN.findall(question):
        if len(run) <= 3:
            add(run)
        for index in range(max(0, len(run) - 1)):
            add(run[index : index + 2])

    return terms[:16]


def query_memory(
    db: Session,
    user_id: UUID,
    question: str,
) -> MemoryQueryResponse:
    clean_question = question.strip()

    if _has_object_location_intent(clean_question):
        matched_object, is_ambiguous = _resolve_object(db, user_id, clean_question)
        if is_ambiguous:
            # [人工注释][S1-PR3-FIX-005] 同等最佳 Object 无法唯一解析时禁止按位置时间猜答案。
            return _no_evidence("FIND_OBJECT")
        if matched_object is not None:
            # [人工注释][S1-011] 已有 Object + 位置意图时，结构化 CURRENT 状态是最终事实源。
            # Object 存在但没有 CURRENT 必须直接 NO_EVIDENCE，严禁历史位置 Memory fallback。
            return _find_object(db, user_id, matched_object)

    return _search_memories(db, user_id, clean_question)


def _find_object(
    db: Session,
    user_id: UUID,
    item: ObjectItem,
) -> MemoryQueryResponse:
    # [人工注释][S1-PR3-FIX-005] 位置查询只允许读取已唯一解析 Object 的 CURRENT，
    # 不能把多个子串匹配 Object 合并后再按 recorded_at 选择较新的另一个对象。
    location = db.scalar(
        select(ObjectLocation)
        .join(Memory, Memory.id == ObjectLocation.memory_id)
        .where(
            ObjectLocation.user_id == user_id,
            ObjectLocation.object_id == item.id,
            ObjectLocation.status == ObjectLocationStatus.CURRENT,
            Memory.user_id == user_id,
            Memory.is_deleted.is_(False),
            Memory.is_confirmed.is_(True),
            Memory.source_type != SourceType.AI_INFERENCE,
            _eligible_memory_exists(),
        )
        .order_by(desc(ObjectLocation.recorded_at))
        .limit(1)
    )
    if location is None or location.memory_id is None:
        return _no_evidence("FIND_OBJECT")

    source = _best_memory_source(db, location.memory_id)
    if source is None:
        return _no_evidence("FIND_OBJECT")

    answer = f"你最后一次记录“{item.name}”的位置是：{location.location_text}。"
    evidence = Evidence(
        kind="OBJECT_LOCATION",
        id=location.id,
        source_type=source.source_type,
        memory_source_id=source.id,
        occurred_at=location.recorded_at,
        excerpt=f"{item.name}：{location.location_text}",
        confidence=source.confidence,
    )
    return MemoryQueryResponse(
        answer=answer,
        can_answer=True,
        certainty="confirmed",
        intent="FIND_OBJECT",
        evidence=[evidence],
        memory_ids=[location.memory_id],
    )


def _search_memories(
    db: Session,
    user_id: UUID,
    question: str,
) -> MemoryQueryResponse:
    terms = _search_terms(question)
    if not terms:
        return _no_evidence("MEMORY_SEARCH")

    filters = [Memory.content.ilike(f"%{term}%") for term in terms]
    candidates = db.scalars(
        select(Memory)
        .where(
            Memory.user_id == user_id,
            Memory.memory_type != MemoryType.OBJECT_LOCATION,
            Memory.is_deleted.is_(False),
            Memory.is_confirmed.is_(True),
            Memory.source_type != SourceType.AI_INFERENCE,
            Memory.confidence >= 0.6,
            _eligible_memory_exists(),
            or_(*filters),
        )
        .order_by(desc(Memory.occurred_at))
        .limit(30)
    ).all()
    if not candidates:
        return _no_evidence("MEMORY_SEARCH")

    # [人工注释][S1-011] OBJECT_LOCATION backing Memory 不参与普通搜索。
    # 历史位置只能由结构化状态解释，避免 STALE/UNKNOWN 位置重新承担“当前位置事实源”。
    ranked = sorted(
        candidates,
        key=lambda item: (_term_score(item.content, terms), _sort_datetime(item.occurred_at)),
        reverse=True,
    )[:5]
    if not ranked or _term_score(ranked[0].content, terms) == 0:
        return _no_evidence("MEMORY_SEARCH")

    evidence: list[Evidence] = []
    answerable_memories: list[Memory] = []
    for item in ranked:
        source = _best_memory_source(db, item.id)
        if source is None:
            continue
        evidence.append(
            Evidence(
                kind="MEMORY",
                id=item.id,
                source_type=source.source_type,
                memory_source_id=source.id,
                occurred_at=item.occurred_at,
                excerpt=item.content[:240],
                confidence=source.confidence,
            )
        )
        answerable_memories.append(item)

    if not evidence:
        return _no_evidence("MEMORY_SEARCH")

    latest = answerable_memories[0]
    answer = f"我找到了 {len(answerable_memories)} 条相关记录。最相关的一条是：{latest.content}"
    return MemoryQueryResponse(
        answer=answer,
        can_answer=True,
        certainty="evidence",
        intent="MEMORY_SEARCH",
        evidence=evidence,
        memory_ids=[item.id for item in answerable_memories],
    )


def _term_score(content: str, terms: list[str]) -> int:
    lower_content = content.lower()
    return sum(1 for term in terms if term in lower_content)


def _sort_datetime(value: datetime) -> float:
    return value.timestamp()


def _no_evidence(intent: str) -> MemoryQueryResponse:
    return MemoryQueryResponse(
        answer=None,
        can_answer=False,
        certainty="unknown",
        reason="NO_EVIDENCE",
        intent=intent,
        evidence=[],
        memory_ids=[],
    )
