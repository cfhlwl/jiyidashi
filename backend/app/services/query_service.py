import re
from uuid import UUID

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from app.models import Memory, ObjectItem, ObjectLocation, ObjectLocationStatus
from app.schemas import Evidence, MemoryQueryResponse

OBJECT_QUERY_MARKERS = ("在哪", "哪里", "放哪", "放在什么", "位置")


def _normalize_object_name(text: str) -> str:
    value = text.strip()
    value = re.sub(r"[？?。！!，,]", "", value)
    value = re.sub(r"^(我的|我那|请问|帮我找一下|帮我找找)", "", value)
    for phrase in (
        "现在放在哪里",
        "现在在哪里",
        "放在哪里",
        "放哪儿了",
        "放哪了",
        "在哪里",
        "在哪儿",
        "在哪",
        "的位置",
        "位置",
    ):
        value = value.replace(phrase, "")
    return value.strip()


def query_memory(
    db: Session,
    user_id: UUID,
    question: str,
) -> MemoryQueryResponse:
    clean_question = question.strip()

    if any(marker in clean_question for marker in OBJECT_QUERY_MARKERS):
        result = _find_object(db, user_id, clean_question)
        if result.can_answer:
            return result

    return _search_memories(db, user_id, clean_question)


def _find_object(
    db: Session,
    user_id: UUID,
    question: str,
) -> MemoryQueryResponse:
    object_name = _normalize_object_name(question)
    if not object_name:
        return _no_evidence("FIND_OBJECT")

    objects = (
        db.scalars(
            select(ObjectItem).where(
                ObjectItem.user_id == user_id,
                or_(
                    ObjectItem.normalized_name == object_name.lower(),
                    ObjectItem.name.ilike(f"%{object_name}%"),
                ),
            )
        )
    ).all()

    if not objects:
        return _no_evidence("FIND_OBJECT")

    object_ids = [item.id for item in objects]
    location = db.scalar(
        select(ObjectLocation)
        .where(
            ObjectLocation.user_id == user_id,
            ObjectLocation.object_id.in_(object_ids),
            ObjectLocation.status == ObjectLocationStatus.CURRENT,
        )
        .order_by(desc(ObjectLocation.recorded_at))
        .limit(1)
    )
    if location is None:
        return _no_evidence("FIND_OBJECT")

    matched_object = next(item for item in objects if item.id == location.object_id)
    answer = (
        f"你最后一次记录“{matched_object.name}”的位置是："
        f"{location.location_text}。"
    )
    evidence = Evidence(
        kind="OBJECT_LOCATION",
        id=location.id,
        occurred_at=location.recorded_at,
        excerpt=f"{matched_object.name}：{location.location_text}",
        confidence=location.confidence,
    )
    return MemoryQueryResponse(
        answer=answer,
        can_answer=True,
        certainty="confirmed" if location.confidence >= 0.9 else "evidence",
        intent="FIND_OBJECT",
        evidence=[evidence],
        memory_ids=[location.memory_id] if location.memory_id else [],
    )


def _search_memories(
    db: Session,
    user_id: UUID,
    question: str,
) -> MemoryQueryResponse:
    # Foundation implementation: deterministic evidence retrieval only.
    # LLM/RAG can be added later, but it must consume these results instead
    # of inventing personal history by itself.
    tokens = [
        token
        for token in re.split(r"[\s，。！？,.!?]+", question)
        if len(token.strip()) >= 2
    ]
    if not tokens:
        return _no_evidence("MEMORY_SEARCH")

    filters = [Memory.content.ilike(f"%{token}%") for token in tokens[:6]]
    memories = (
        db.scalars(
            select(Memory)
            .where(
                Memory.user_id == user_id,
                Memory.is_deleted.is_(False),
                or_(*filters),
                Memory.confidence >= 0.6,
            )
            .order_by(desc(Memory.occurred_at))
            .limit(5)
        )
    ).all()

    if not memories:
        return _no_evidence("MEMORY_SEARCH")

    evidence = [
        Evidence(
            kind="MEMORY",
            id=item.id,
            occurred_at=item.occurred_at,
            excerpt=item.content[:240],
            confidence=item.confidence,
        )
        for item in memories
    ]
    latest = memories[0]
    answer = f"我找到了 {len(memories)} 条相关记录。最近一条是：{latest.content}"
    return MemoryQueryResponse(
        answer=answer,
        can_answer=True,
        certainty="evidence",
        intent="MEMORY_SEARCH",
        evidence=evidence,
        memory_ids=[item.id for item in memories],
    )


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
