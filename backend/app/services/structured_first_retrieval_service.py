"""Internal S3-010 Structured First Retrieval.

This seam returns typed candidates only. Retrieval tier/score never promotes Memory or
Evidence trust, and this module intentionally does not generate user-facing answers.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import replace
from uuid import UUID

from sqlalchemy import and_, case, func, literal, or_, select
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.embedding_gateway import EmbeddingGateway, EmbeddingGatewayError
from app.embedding_models import MemoryEmbedding
from app.models import (
    Memory,
    MemoryType,
    ObjectItem,
    ObjectLocation,
    ObjectLocationStatus,
    SourceType,
)
from app.retrieval_models import (
    LLMFallbackStatus,
    RetrievalCandidate,
    RetrievalMetrics,
    RetrievalResult,
    RetrievalScoreKind,
    RetrievalTier,
    StructuredResolutionStatus,
    VectorRetrievalStatus,
)
from app.services.embedding_service import (
    build_memory_embedding_text,
    memory_embedding_fingerprint,
)
from app.services.evidence_ranking_service import (
    EvidenceRankedSource,
    rank_evidence_sources,
)

_OBJECT_LOCATION_MARKERS = (
    "在哪",
    "哪里",
    "何处",
    "什么地方",
    "放哪",
    "放在",
    "位置",
    "where is",
    "where's",
)
_CJK_RUN = re.compile(r"[\u3400-\u9fff]+")
_CLEAN_SEPARATORS = re.compile(r"[\s？?。！!，,：:；;、]+")
_MAX_QUERY_TERMS = 16
_DEFAULT_TOP_K = 5
_MAX_TOP_K = 10
_MAX_STRUCTURED_OBJECT_CANDIDATES = 32
_VECTOR_VALIDATION_PAGE_SIZE = 8
_MAX_VECTOR_VALIDATION_SCAN_ROWS = 32
_SQL_COMPACT_SEPARATORS = (
    " ",
    "\t",
    "\n",
    "\r",
    "？",
    "?",
    "。",
    "！",
    "!",
    "，",
    ",",
    "：",
    ":",
    "；",
    ";",
    "、",
)


class RetrievalError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _engine_bind(db: Session):
    bind = db.get_bind()
    return bind.engine if isinstance(bind, Connection) else bind


def _read_session(db: Session) -> Session:
    # [人工注释][S3-010] Retrieval 只读取已持久化状态，故意使用独立、autoflush=False
    # Session：调用方 pending/dirty 状态既不会被 flush，也不会污染候选集。
    return Session(
        bind=_engine_bind(db),
        autoflush=False,
        expire_on_commit=False,
    )


def _compact_text(value: str) -> str:
    return _CLEAN_SEPARATORS.sub("", value.strip().lower())


def _has_object_location_intent(question: str) -> bool:
    lowered = question.lower()
    compact = _compact_text(question)
    return any(
        marker.lower() in lowered if " " in marker else _compact_text(marker) in compact
        for marker in _OBJECT_LOCATION_MARKERS
    )


def _search_terms(question: str) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        normalized = value.strip().lower()
        if len(normalized) >= 2 and normalized not in seen:
            seen.add(normalized)
            terms.append(normalized)

    for token in re.split(r"[\s，。！？,.!?：:；;]+", question):
        add(token)
    for run in _CJK_RUN.findall(question):
        if len(run) <= 3:
            add(run)
        for index in range(max(0, len(run) - 1)):
            add(run[index : index + 2])
    return tuple(terms[:_MAX_QUERY_TERMS])


def _sql_compact_object_name():
    # normalized_name 已把任意 whitespace 统一成普通空格；SQL 只需再移除与
    # _compact_text 相同的可见分隔符即可，不会因 tab/newline 形式差异漏候选。
    value = func.lower(ObjectItem.normalized_name)
    for separator in _SQL_COMPACT_SEPARATORS:
        value = func.replace(value, separator, "")
    return value


def _resolve_object(
    db: Session,
    *,
    user_id: UUID,
    question: str,
) -> tuple[ObjectItem | None, bool, bool]:
    compact_question = _compact_text(question)
    if not compact_question:
        return None, False, False

    compact_name = _sql_compact_object_name()
    dialect_name = db.get_bind().dialect.name
    if dialect_name == "postgresql":
        contains_name = func.strpos(literal(compact_question), compact_name) > 0
    elif dialect_name == "sqlite":
        contains_name = func.instr(literal(compact_question), compact_name) > 0
    else:
        contains_name = literal(compact_question).contains(compact_name)

    # [人工注释][S3-010-FIX-002] 先让数据库只返回“对象名确实是 query 子串”的
    # owner-scoped 候选，再用 cap+1 探测是否越界；禁止把整个 Object catalog 拉进 Python。
    objects = list(
        db.scalars(
            select(ObjectItem)
            .where(
                ObjectItem.user_id == user_id,
                compact_name != "",
                contains_name,
            )
            .order_by(
                func.length(compact_name).desc(),
                ObjectItem.id.asc(),
            )
            .limit(_MAX_STRUCTURED_OBJECT_CANDIDATES + 1)
        )
    )
    if len(objects) > _MAX_STRUCTURED_OBJECT_CANDIDATES:
        return None, False, True

    matched = [
        (item, _compact_text(item.name))
        for item in objects
        if _compact_text(item.name) and _compact_text(item.name) in compact_question
    ]
    if not matched:
        return None, False, False

    best_length = max(len(normalized) for _, normalized in matched)
    best = [item for item, normalized in matched if len(normalized) == best_length]
    if len(best) != 1:
        return None, True, False
    return best[0], False, False


def _ranked_evidence_by_memory(
    db: Session,
    *,
    user_id: UUID,
    memory_ids: Sequence[UUID],
) -> dict[UUID, tuple[EvidenceRankedSource, ...]]:
    ranked = rank_evidence_sources(
        db,
        user_id=user_id,
        memory_ids=memory_ids,
    )
    grouped: dict[UUID, list[EvidenceRankedSource]] = {}
    for item in ranked:
        grouped.setdefault(item.memory_id, []).append(item)
    return {memory_id: tuple(items) for memory_id, items in grouped.items()}


def _answer_eligible(
    memory: Memory,
    ranked_sources: Sequence[EvidenceRankedSource],
) -> bool:
    # [人工注释][S3-010] Retrieval 只复述现有 answer trust gate；tier/score 不得把
    # unconfirmed/AI-only Memory 晋级成可回答状态。
    if (
        not memory.is_confirmed
        or memory.source_type == SourceType.AI_INFERENCE
        or float(memory.confidence) < 0.6
    ):
        return False
    return any(
        source.source_type != SourceType.AI_INFERENCE and source.confidence >= 0.6
        for source in ranked_sources
    )


def _candidate(
    *,
    memory: Memory,
    tier: RetrievalTier,
    score_kind: RetrievalScoreKind,
    score: float,
    rank: int,
    ranked_sources: Sequence[EvidenceRankedSource],
    structured_ref_type: str | None = None,
    structured_ref_id: UUID | None = None,
    embedding_validated: bool | None = None,
) -> RetrievalCandidate:
    best = ranked_sources[0] if ranked_sources else None
    return RetrievalCandidate(
        memory_id=memory.id,
        retrieval_tier=tier,
        score_kind=score_kind,
        retrieval_score=float(score),
        rank_within_tier=rank,
        structured_ref_type=structured_ref_type,
        structured_ref_id=structured_ref_id,
        embedding_fingerprint_validated=embedding_validated,
        evidence_rank_class=None if best is None else best.rank_class,
        best_memory_source_id=None if best is None else best.memory_source_id,
        answer_eligible=_answer_eligible(memory, ranked_sources),
    )


def _structured_candidates(
    caller_db: Session,
    *,
    user_id: UUID,
    question: str,
) -> tuple[
    StructuredResolutionStatus,
    tuple[RetrievalCandidate, ...],
]:
    if not _has_object_location_intent(question):
        return StructuredResolutionStatus.NOT_APPLICABLE, ()

    with _read_session(caller_db) as db:
        matched_object, ambiguous, limit_reached = _resolve_object(
            db,
            user_id=user_id,
            question=question,
        )
        if limit_reached:
            return StructuredResolutionStatus.CANDIDATE_LIMIT_REACHED, ()
        if ambiguous:
            # A recognized but ambiguous structured identity is fail-closed. Lower tiers
            # must not guess which authoritative Object the user meant.
            return StructuredResolutionStatus.TERMINAL_MISS, ()
        if matched_object is None:
            return StructuredResolutionStatus.NOT_APPLICABLE, ()

        row = db.execute(
            select(ObjectLocation, Memory)
            .join(Memory, Memory.id == ObjectLocation.memory_id)
            .where(
                ObjectLocation.user_id == user_id,
                ObjectLocation.object_id == matched_object.id,
                ObjectLocation.status == ObjectLocationStatus.CURRENT,
                Memory.user_id == user_id,
                Memory.is_deleted.is_(False),
            )
            .order_by(ObjectLocation.recorded_at.desc(), ObjectLocation.id.desc())
            .limit(1)
        ).first()
        if row is None:
            # [人工注释][S3-010] Object 已权威解析但 CURRENT 不存在时必须终止；
            # KEYWORD/VECTOR 都不得把 STALE/UNKNOWN 的 backing Memory 复活成当前位置。
            return StructuredResolutionStatus.TERMINAL_MISS, ()

        location, memory = row
        evidence = _ranked_evidence_by_memory(
            db,
            user_id=user_id,
            memory_ids=[memory.id],
        ).get(memory.id, ())
        return (
            StructuredResolutionStatus.RESOLVED,
            (
                _candidate(
                    memory=memory,
                    tier=RetrievalTier.STRUCTURED,
                    score_kind=RetrievalScoreKind.STRUCTURED_MATCH,
                    score=1.0,
                    rank=1,
                    ranked_sources=evidence,
                    structured_ref_type="OBJECT_LOCATION",
                    structured_ref_id=location.id,
                ),
            ),
        )


def _keyword_candidates(
    caller_db: Session,
    *,
    user_id: UUID,
    terms: tuple[str, ...],
    top_k: int,
) -> tuple[RetrievalCandidate, ...]:
    if not terms:
        return ()

    matches = [
        or_(
            Memory.content.ilike(f"%{term}%"),
            Memory.title.ilike(f"%{term}%"),
        )
        for term in terms
    ]
    score_parts = [case((match, 1), else_=0) for match in matches]
    score_expr = score_parts[0]
    for part in score_parts[1:]:
        score_expr = score_expr + part

    with _read_session(caller_db) as db:
        # [人工注释][S3-010] keyword score 必须在 LIMIT 之前由数据库确定；
        # 不能先截取未排序候选再在 Python 评分，否则大数据集的候选池本身不稳定。
        rows = db.execute(
            select(Memory, score_expr.label("keyword_score"))
            .where(
                Memory.user_id == user_id,
                Memory.is_deleted.is_(False),
                Memory.memory_type != MemoryType.OBJECT_LOCATION,
                or_(*matches),
            )
            .order_by(
                score_expr.desc(),
                Memory.occurred_at.desc(),
                Memory.id.asc(),
            )
            .limit(top_k)
        ).all()
        selected = [
            (memory, int(score))
            for memory, score in rows
            if int(score) > 0
        ]
        evidence = _ranked_evidence_by_memory(
            db,
            user_id=user_id,
            memory_ids=[memory.id for memory, _ in selected],
        )

        return tuple(
            _candidate(
                memory=memory,
                tier=RetrievalTier.KEYWORD,
                score_kind=RetrievalScoreKind.KEYWORD_MATCH_COUNT,
                score=float(score),
                rank=index,
                ranked_sources=evidence.get(memory.id, ()),
            )
            for index, (memory, score) in enumerate(selected, start=1)
        )


async def _vector_candidates(
    caller_db: Session,
    *,
    user_id: UUID,
    question: str,
    gateway: EmbeddingGateway,
    top_k: int,
) -> tuple[
    VectorRetrievalStatus,
    str | None,
    tuple[RetrievalCandidate, ...],
]:
    if _engine_bind(caller_db).dialect.name != "postgresql":
        return VectorRetrievalStatus.DATABASE_UNSUPPORTED, None, ()

    # Provider I/O runs before opening the short-lived vector read transaction.
    try:
        inference = await gateway.embed(question)
    except EmbeddingGatewayError as exc:
        return VectorRetrievalStatus.PROVIDER_FAILED, exc.code, ()

    query_vector = list(inference.vector)
    with _read_session(caller_db) as db:
        distance_expr = MemoryEmbedding.embedding.cosine_distance(query_vector)
        distance = distance_expr.label("cosine_distance")
        validated: list[tuple[Memory, float]] = []
        seen: set[UUID] = set()
        scanned_rows = 0
        cursor_distance: float | None = None
        cursor_memory_id: UUID | None = None
        exhausted = False

        while scanned_rows < _MAX_VECTOR_VALIDATION_SCAN_ROWS:
            page_limit = min(
                _VECTOR_VALIDATION_PAGE_SIZE,
                _MAX_VECTOR_VALIDATION_SCAN_ROWS - scanned_rows,
            )
            page_query = (
                select(MemoryEmbedding, Memory, distance)
                .join(
                    Memory,
                    and_(
                        Memory.id == MemoryEmbedding.memory_id,
                        Memory.user_id == MemoryEmbedding.user_id,
                    ),
                )
                .where(
                    MemoryEmbedding.user_id == user_id,
                    Memory.user_id == user_id,
                    Memory.is_deleted.is_(False),
                    Memory.memory_type != MemoryType.OBJECT_LOCATION,
                    MemoryEmbedding.model == gateway.model,
                    MemoryEmbedding.dimensions == gateway.dimensions,
                    MemoryEmbedding.memory_revision == Memory.edit_revision,
                )
            )
            if cursor_distance is not None and cursor_memory_id is not None:
                # [人工注释][S3-010-FIX-001] fingerprint 只能在 Python 用当前
                # canonical Memory 重算，因此必须按 (distance, memory_id) 有界 keyset
                # 翻页；不能 LIMIT 一页后让 stale nearest rows 遮住后面的合法候选。
                page_query = page_query.where(
                    or_(
                        distance_expr > cursor_distance,
                        and_(
                            distance_expr == cursor_distance,
                            Memory.id > cursor_memory_id,
                        ),
                    )
                )

            rows = db.execute(
                page_query
                .order_by(distance_expr.asc(), Memory.id.asc())
                .limit(page_limit)
            ).all()
            if not rows:
                exhausted = True
                break

            scanned_rows += len(rows)
            last_distance = float(rows[-1][2])
            if not math.isfinite(last_distance):
                # A non-finite ordering cursor cannot be paged safely. Treat the bounded
                # validation window as exhausted by policy rather than guessing beyond it.
                return VectorRetrievalStatus.VALIDATION_SCAN_LIMIT_REACHED, None, ()
            cursor_distance = last_distance
            cursor_memory_id = rows[-1][1].id

            for embedding, memory, raw_distance in rows:
                if memory.id in seen:
                    continue
                numeric_distance = float(raw_distance)
                if not math.isfinite(numeric_distance):
                    continue
                expected_fingerprint = memory_embedding_fingerprint(
                    build_memory_embedding_text(memory)
                )
                if embedding.content_fingerprint != expected_fingerprint:
                    continue
                seen.add(memory.id)
                validated.append((memory, 1.0 - numeric_distance))
                if len(validated) >= top_k:
                    break

            if len(validated) >= top_k:
                break
            if len(rows) < page_limit:
                exhausted = True
                break

        if len(validated) >= top_k or exhausted:
            status = VectorRetrievalStatus.SUCCESS
        else:
            status = VectorRetrievalStatus.VALIDATION_SCAN_LIMIT_REACHED

        if not validated:
            if status == VectorRetrievalStatus.SUCCESS:
                return VectorRetrievalStatus.NO_USABLE_CANDIDATE, None, ()
            return status, None, ()

        evidence = _ranked_evidence_by_memory(
            db,
            user_id=user_id,
            memory_ids=[memory.id for memory, _ in validated],
        )
        candidates = tuple(
            _candidate(
                memory=memory,
                tier=RetrievalTier.VECTOR,
                score_kind=RetrievalScoreKind.COSINE_SIMILARITY,
                score=similarity,
                rank=index,
                ranked_sources=evidence.get(memory.id, ()),
                embedding_validated=True,
            )
            for index, (memory, similarity) in enumerate(validated, start=1)
        )
        return status, None, candidates


def _dedupe_candidates(
    candidates: Sequence[RetrievalCandidate],
) -> tuple[RetrievalCandidate, ...]:
    # [人工注释][S3-010] dedup 规则只认 authoritative memory_id，并保留当前 tier
    # 已确定的首个/最高优先候选；不跨 tier 混分，也不重新解释 retrieval score。
    seen: set[UUID] = set()
    deduped: list[RetrievalCandidate] = []
    for candidate in candidates:
        if candidate.memory_id in seen:
            continue
        seen.add(candidate.memory_id)
        deduped.append(
            replace(candidate, rank_within_tier=len(deduped) + 1)
        )
    return tuple(deduped)


def _result(
    *,
    candidates: tuple[RetrievalCandidate, ...],
    selected_tier: RetrievalTier | None,
    structured_status: StructuredResolutionStatus,
    vector_status: VectorRetrievalStatus,
    vector_error_code: str | None,
    query_terms: tuple[str, ...],
    structured_count: int = 0,
    keyword_count: int = 0,
    vector_count: int = 0,
) -> RetrievalResult:
    deduped = _dedupe_candidates(candidates)
    if selected_tier == RetrievalTier.STRUCTURED:
        structured_count = len(deduped)
    elif selected_tier == RetrievalTier.KEYWORD:
        keyword_count = len(deduped)
    elif selected_tier == RetrievalTier.VECTOR:
        vector_count = len(deduped)

    return RetrievalResult(
        candidates=deduped,
        selected_tier=selected_tier,
        structured_status=structured_status,
        vector_status=vector_status,
        vector_error_code=vector_error_code,
        llm_fallback_status=LLMFallbackStatus.NOT_ATTEMPTED,
        query_terms=query_terms,
        metrics=RetrievalMetrics(
            structured_candidates=structured_count,
            keyword_candidates=keyword_count,
            vector_candidates=vector_count,
        ),
    )


async def retrieve_memories(
    db: Session,
    *,
    user_id: UUID,
    question: str,
    gateway: EmbeddingGateway,
    top_k: int = _DEFAULT_TOP_K,
) -> RetrievalResult:
    """Return persisted owner-scoped candidates using fixed tier precedence."""

    clean_question = question.strip()
    if not clean_question:
        raise RetrievalError("RETRIEVAL_QUERY_EMPTY")
    if top_k < 1 or top_k > _MAX_TOP_K:
        raise RetrievalError("RETRIEVAL_TOP_K_INVALID")

    terms = _search_terms(clean_question)
    structured_status, structured = _structured_candidates(
        db,
        user_id=user_id,
        question=clean_question,
    )
    if structured:
        return _result(
            candidates=structured[:top_k],
            selected_tier=RetrievalTier.STRUCTURED,
            structured_status=structured_status,
            vector_status=VectorRetrievalStatus.NOT_NEEDED,
            vector_error_code=None,
            query_terms=terms,
            structured_count=len(structured[:top_k]),
        )
    if structured_status in {
        StructuredResolutionStatus.TERMINAL_MISS,
        StructuredResolutionStatus.CANDIDATE_LIMIT_REACHED,
    }:
        return _result(
            candidates=(),
            selected_tier=RetrievalTier.STRUCTURED,
            structured_status=structured_status,
            vector_status=VectorRetrievalStatus.NOT_NEEDED,
            vector_error_code=None,
            query_terms=terms,
        )

    keyword = _keyword_candidates(
        db,
        user_id=user_id,
        terms=terms,
        top_k=top_k,
    )
    if keyword:
        return _result(
            candidates=keyword,
            selected_tier=RetrievalTier.KEYWORD,
            structured_status=structured_status,
            vector_status=VectorRetrievalStatus.NOT_NEEDED,
            vector_error_code=None,
            query_terms=terms,
            keyword_count=len(keyword),
        )

    vector_status, vector_error_code, vector = await _vector_candidates(
        db,
        user_id=user_id,
        question=clean_question,
        gateway=gateway,
        top_k=top_k,
    )
    if vector or vector_status == VectorRetrievalStatus.VALIDATION_SCAN_LIMIT_REACHED:
        return _result(
            candidates=vector,
            selected_tier=RetrievalTier.VECTOR,
            structured_status=structured_status,
            vector_status=vector_status,
            vector_error_code=vector_error_code,
            query_terms=terms,
            vector_count=len(vector),
        )

    # [人工注释][S3-010] LLM query rewrite 明确后置：本 PR 保留 typed handoff，
    # 不允许 provider 返回 Memory/Entity IDs、trust label 或答案文本。
    return _result(
        candidates=(),
        selected_tier=None,
        structured_status=structured_status,
        vector_status=vector_status,
        vector_error_code=vector_error_code,
        query_terms=terms,
    )
