from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.idempotency_models import ClientMutation
from app.models import Memory, MemorySource, MemoryType, SourceType, User
from app.services.memory_pipeline import (
    BasicMemoryNormalizer,
    ClassifiedMemoryCandidate,
    EvidenceDecision,
    ExtractedMemoryCandidate,
    MemoryPipeline,
    MemoryPipelineInput,
    MemoryPipelineStage,
    MemoryPipelineStageFailure,
    MemoryPipelineStageStatus,
    MemoryPipelineStatus,
    PipelineEvidence,
    SQLAlchemyMemoryPipelineStore,
    StoreDecision,
)
from app.services.memory_service import get_memory_for_user
from app.services.query_service import query_memory


class DeterministicExtractor:
    def __init__(self, candidate: ExtractedMemoryCandidate | None):
        self.candidate = candidate
        self.calls = 0

    async def extract(self, normalized, *, context):
        del normalized, context
        self.calls += 1
        return self.candidate


class DeterministicClassifier:
    def __init__(self, candidate: ClassifiedMemoryCandidate):
        self.candidate = candidate
        self.calls = 0

    async def classify(self, extracted):
        self.calls += 1
        return self.candidate


class FailingExtractor:
    async def extract(self, normalized, *, context):
        del normalized, context
        raise MemoryPipelineStageFailure(
            MemoryPipelineStage.EXTRACT,
            "EXTRACTOR_FAILED",
            retryable=True,
        )


def _create_user(db, label: str) -> UUID:
    user = User(nickname=label, timezone="Asia/Shanghai", locale="zh-CN")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.id


def _capture(
    user_id: UUID,
    *,
    execution_id: UUID | None = None,
    text: str = "  老张 周五 来公司取合同  ",
    evidence: PipelineEvidence | None = None,
) -> MemoryPipelineInput:
    return MemoryPipelineInput(
        execution_id=execution_id or uuid4(),
        user_id=user_id,
        original_text=text,
        occurred_at=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
        evidence=evidence,
        metadata={"capture_channel": "test"},
    )


def _evidence(
    *,
    source_type: SourceType = SourceType.USER_TEXT,
    confidence: float = 1.0,
    raw_text: str = "  老张 周五 来公司取合同  ",
) -> PipelineEvidence:
    return PipelineEvidence(
        source_type=source_type,
        source_id="capture:test:1",
        raw_text=raw_text,
        confidence=confidence,
    )


def _extracted(content: str = "老张周五来公司取合同") -> ExtractedMemoryCandidate:
    return ExtractedMemoryCandidate(
        content=content,
        title="合同安排",
        confidence=0.9,
        attributes={"kind": "event_candidate"},
    )


def _classified(
    content: str = "老张周五来公司取合同",
    *,
    trust_class: str = "inference",
) -> ClassifiedMemoryCandidate:
    return ClassifiedMemoryCandidate(
        content=content,
        memory_type=MemoryType.EVENT,
        title="合同安排",
        confidence=0.9,
        attributes={"classification": "event"},
        trust_class=trust_class,  # type: ignore[arg-type]
    )


def _pipeline(db, *, extractor=None, classifier=None) -> MemoryPipeline:
    return MemoryPipeline(
        normalizer=BasicMemoryNormalizer(),
        extractor=extractor or DeterministicExtractor(_extracted()),
        classifier=classifier or DeterministicClassifier(_classified()),
        store=SQLAlchemyMemoryPipelineStore(db),
    )


def test_pipeline_cannot_weaken_existing_evidence_threshold():
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="min_evidence_confidence"):
            MemoryPipeline(
                normalizer=BasicMemoryNormalizer(),
                extractor=DeterministicExtractor(_extracted()),
                classifier=DeterministicClassifier(_classified()),
                store=SQLAlchemyMemoryPipelineStore(db),
                min_evidence_confidence=0.59,
            )


@pytest.mark.asyncio
async def test_pipeline_stores_inference_candidate_with_original_evidence():
    with SessionLocal() as db:
        user_id = _create_user(db, "pipeline-happy")
        capture = _capture(user_id, evidence=_evidence())
        result = await _pipeline(db).run(capture)

        assert result.status == MemoryPipelineStatus.STORED
        assert result.store_decision == StoreDecision.STORE
        assert result.evidence_decision == EvidenceDecision.ELIGIBLE
        assert result.memory_id is not None
        assert [state.stage for state in result.stages] == list(MemoryPipelineStage)
        assert all(
            state.status == MemoryPipelineStageStatus.COMPLETED
            for state in result.stages
        )

        memory = db.scalar(select(Memory).where(Memory.id == result.memory_id))
        assert memory is not None
        assert memory.user_id == user_id
        assert memory.source_type == SourceType.AI_INFERENCE
        assert memory.is_confirmed is False
        assert memory.confidence == 0.5
        assert memory.memory_type == MemoryType.EVENT
        assert memory.metadata_json["memory_pipeline"]["trust_class"] == "inference"

        source = db.scalar(
            select(MemorySource).where(MemorySource.memory_id == memory.id)
        )
        assert source is not None
        assert source.source_type == SourceType.USER_TEXT
        assert source.source_id == "capture:test:1"
        # Normalization changes processing text but must never destroy original Evidence.
        assert source.raw_text == "  老张 周五 来公司取合同  "
        assert source.confidence == 1.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("evidence", "decision"),
    [
        (None, EvidenceDecision.MISSING),
        (
            _evidence(source_type=SourceType.AI_INFERENCE),
            EvidenceDecision.AI_ONLY,
        ),
        (_evidence(confidence=0.59), EvidenceDecision.LOW_CONFIDENCE),
    ],
)
async def test_no_eligible_evidence_means_no_memory(evidence, decision):
    with SessionLocal() as db:
        user_id = _create_user(db, f"pipeline-no-evidence-{decision.value}")
        before = db.scalar(
            select(func.count(Memory.id)).where(Memory.user_id == user_id)
        )

        result = await _pipeline(db).run(_capture(user_id, evidence=evidence))

        assert result.status == MemoryPipelineStatus.SKIPPED
        assert result.evidence_decision == decision
        assert result.store_decision == StoreDecision.SKIP_NO_EVIDENCE
        assert result.memory_id is None
        after = db.scalar(
            select(func.count(Memory.id)).where(Memory.user_id == user_id)
        )
        assert after == before


@pytest.mark.asyncio
async def test_malformed_evidence_fails_at_evidence_stage_after_prior_stages():
    with SessionLocal() as db:
        user_id = _create_user(db, "pipeline-invalid-evidence")
        malformed = PipelineEvidence(
            source_type=SourceType.USER_TEXT,
            source_id="capture:test:bad",
            raw_text="原始记录",
            confidence=float("nan"),
        )

        result = await _pipeline(db).run(_capture(user_id, evidence=malformed))

        assert result.status == MemoryPipelineStatus.FAILED
        assert result.error_code == "PIPELINE_EVIDENCE_INVALID"
        assert [state.stage for state in result.stages[:-1]] == [
            MemoryPipelineStage.CAPTURE,
            MemoryPipelineStage.NORMALIZE,
            MemoryPipelineStage.EXTRACT,
            MemoryPipelineStage.CLASSIFY,
        ]
        assert all(
            state.status == MemoryPipelineStageStatus.COMPLETED
            for state in result.stages[:-1]
        )
        assert result.stages[-1].stage == MemoryPipelineStage.EVIDENCE
        assert result.stages[-1].status == MemoryPipelineStageStatus.FAILED
        assert db.scalar(
            select(func.count(Memory.id)).where(Memory.user_id == user_id)
        ) == 0


@pytest.mark.parametrize(
    "evidence",
    [
        _evidence(source_type=SourceType.AI_INFERENCE),
        _evidence(confidence=0.59),
    ],
)
def test_store_boundary_rejects_ineligible_evidence_when_called_directly(evidence):
    with SessionLocal() as db:
        user_id = _create_user(db, "pipeline-store-bypass")
        capture = _capture(user_id, evidence=evidence)
        store = SQLAlchemyMemoryPipelineStore(db)

        with pytest.raises(MemoryPipelineStageFailure) as exc_info:
            store.store(
                capture=capture,
                candidate=_classified(),
                evidence=evidence,
            )

        assert exc_info.value.stage == MemoryPipelineStage.STORE
        assert exc_info.value.code == "PIPELINE_STORE_EVIDENCE_REJECTED"
        assert db.scalar(
            select(func.count(Memory.id)).where(Memory.user_id == user_id)
        ) == 0


@pytest.mark.asyncio
async def test_no_extracted_candidate_skips_classify_evidence_and_store():
    with SessionLocal() as db:
        user_id = _create_user(db, "pipeline-no-candidate")
        classifier = DeterministicClassifier(_classified())
        result = await _pipeline(
            db,
            extractor=DeterministicExtractor(None),
            classifier=classifier,
        ).run(_capture(user_id, evidence=_evidence()))

        assert result.status == MemoryPipelineStatus.SKIPPED
        assert result.store_decision == StoreDecision.SKIP_NO_CANDIDATE
        assert classifier.calls == 0
        assert result.stages[-1].stage == MemoryPipelineStage.STORE
        assert result.stages[-1].status == MemoryPipelineStageStatus.SKIPPED
        assert db.scalar(
            select(func.count(Memory.id)).where(Memory.user_id == user_id)
        ) == 0


@pytest.mark.asyncio
async def test_stage_failure_fails_closed_without_synthetic_fallback_fact():
    with SessionLocal() as db:
        user_id = _create_user(db, "pipeline-stage-failure")
        result = await _pipeline(
            db,
            extractor=FailingExtractor(),
        ).run(_capture(user_id, evidence=_evidence()))

        assert result.status == MemoryPipelineStatus.FAILED
        assert result.error_code == "EXTRACTOR_FAILED"
        assert result.retryable is True
        assert result.store_decision == StoreDecision.FAILED
        assert result.stages[-1].stage == MemoryPipelineStage.EXTRACT
        assert result.stages[-1].status == MemoryPipelineStageStatus.FAILED
        assert db.scalar(
            select(func.count(Memory.id)).where(Memory.user_id == user_id)
        ) == 0


@pytest.mark.asyncio
async def test_classifier_cannot_promote_inference_to_confirmed_fact():
    with SessionLocal() as db:
        user_id = _create_user(db, "pipeline-trust-escalation")
        result = await _pipeline(
            db,
            classifier=DeterministicClassifier(
                _classified(trust_class="confirmed")
            ),
        ).run(_capture(user_id, evidence=_evidence()))

        assert result.status == MemoryPipelineStatus.FAILED
        assert result.error_code == "PIPELINE_TRUST_ESCALATION_REJECTED"
        assert result.stages[-1].stage == MemoryPipelineStage.CLASSIFY
        assert db.scalar(
            select(func.count(Memory.id)).where(Memory.user_id == user_id)
        ) == 0


@pytest.mark.asyncio
async def test_same_execution_replay_returns_same_memory_without_duplicate_evidence():
    with SessionLocal() as db:
        user_id = _create_user(db, "pipeline-replay")
        execution_id = uuid4()
        capture = _capture(
            user_id,
            execution_id=execution_id,
            evidence=_evidence(),
        )
        pipeline = _pipeline(db)

        first = await pipeline.run(capture)
        second = await pipeline.run(capture)

        assert first.status == MemoryPipelineStatus.STORED
        assert second.status == MemoryPipelineStatus.STORED
        assert first.memory_id == second.memory_id
        assert db.scalar(
            select(func.count(Memory.id)).where(Memory.user_id == user_id)
        ) == 1
        assert db.scalar(
            select(func.count(MemorySource.id))
            .join(Memory, Memory.id == MemorySource.memory_id)
            .where(Memory.user_id == user_id)
        ) == 1
        assert db.scalar(
            select(func.count(ClientMutation.id)).where(
                ClientMutation.user_id == user_id,
                ClientMutation.operation_type == "MEMORY_PIPELINE_STORE_V1",
                ClientMutation.client_uuid == execution_id,
            )
        ) == 1


@pytest.mark.asyncio
async def test_execution_id_reuse_with_changed_fact_fails_closed():
    with SessionLocal() as db:
        user_id = _create_user(db, "pipeline-replay-conflict")
        execution_id = uuid4()
        pipeline = _pipeline(db)

        first = await pipeline.run(
            _capture(
                user_id,
                execution_id=execution_id,
                evidence=_evidence(),
            )
        )
        changed = await pipeline.run(
            _capture(
                user_id,
                execution_id=execution_id,
                text="完全不同的输入",
                evidence=_evidence(raw_text="完全不同的输入"),
            )
        )

        assert first.status == MemoryPipelineStatus.STORED
        assert changed.status == MemoryPipelineStatus.FAILED
        assert changed.error_code == "PIPELINE_REPLAY_CONFLICT"
        assert changed.stages[-1].stage == MemoryPipelineStage.STORE
        assert db.scalar(
            select(func.count(Memory.id)).where(Memory.user_id == user_id)
        ) == 1


@pytest.mark.asyncio
async def test_same_execution_id_is_isolated_per_owner():
    execution_id = uuid4()
    with SessionLocal() as db:
        owner_a = _create_user(db, "pipeline-owner-a")
        owner_b = _create_user(db, "pipeline-owner-b")
        pipeline = _pipeline(db)

        a = await pipeline.run(
            _capture(owner_a, execution_id=execution_id, evidence=_evidence())
        )
        b = await pipeline.run(
            _capture(owner_b, execution_id=execution_id, evidence=_evidence())
        )

        assert a.memory_id is not None
        assert b.memory_id is not None
        assert a.memory_id != b.memory_id
        assert get_memory_for_user(db, owner_a, b.memory_id) is None
        assert get_memory_for_user(db, owner_b, a.memory_id) is None


@pytest.mark.asyncio
async def test_stored_inference_with_real_evidence_is_still_not_answerable():
    with SessionLocal() as db:
        user_id = _create_user(db, "pipeline-query-gate")
        result = await _pipeline(
            db,
            extractor=DeterministicExtractor(_extracted("银行卡可能在书房抽屉")),
            classifier=DeterministicClassifier(
                _classified("银行卡可能在书房抽屉")
            ),
        ).run(
            _capture(
                user_id,
                text="银行卡可能在书房抽屉",
                evidence=_evidence(raw_text="我记得银行卡可能在书房抽屉"),
            )
        )
        assert result.status == MemoryPipelineStatus.STORED

        response = query_memory(db, user_id, "银行卡抽屉")
        assert response.can_answer is False
        assert response.reason == "NO_EVIDENCE"


@pytest.mark.asyncio
async def test_day_summary_excludes_unconfirmed_pipeline_inference(
    client: AsyncClient,
):
    token = await client.post(
        "/v1/auth/dev-token",
        json={"nickname": "pipeline-summary-gate"},
    )
    assert token.status_code == 200
    body = token.json()
    user_id = UUID(body["user_id"])
    headers = {"Authorization": f"Bearer {body['access_token']}"}

    trusted = await client.post(
        "/v1/memories",
        headers=headers,
        json={
            "content": "今天确认收到客户合同",
            "occurred_at": "2026-09-20T11:00:00Z",
            "capture_source": "USER_TEXT",
        },
    )
    assert trusted.status_code == 201

    with SessionLocal() as db:
        result = await _pipeline(
            db,
            extractor=DeterministicExtractor(
                _extracted("老张下周可能来公司签合同")
            ),
            classifier=DeterministicClassifier(
                _classified("老张下周可能来公司签合同")
            ),
        ).run(
            _capture(
                user_id,
                text="老张下周可能来公司签合同",
                evidence=_evidence(raw_text="用户原始记录：老张下周可能来公司签合同"),
            )
        )
        assert result.status == MemoryPipelineStatus.STORED
        inferred = db.scalar(select(Memory).where(Memory.id == result.memory_id))
        assert inferred is not None
        assert inferred.source_type == SourceType.AI_INFERENCE
        assert inferred.is_confirmed is False

    summary = await client.get(
        "/v1/memory/summarize/day",
        headers=headers,
        params={"day": "2026-09-20"},
    )
    assert summary.status_code == 200
    summary_body = summary.json()
    assert summary_body["memory_count"] == 1
    assert "今天确认收到客户合同" in summary_body["summary"]
    assert "老张下周可能来公司签合同" not in summary_body["summary"]


@pytest.mark.asyncio
async def test_naive_capture_time_fails_before_any_stage_side_effect():
    with SessionLocal() as db:
        user_id = _create_user(db, "pipeline-naive-time")
        capture = MemoryPipelineInput(
            execution_id=uuid4(),
            user_id=user_id,
            original_text="测试",
            occurred_at=datetime(2026, 9, 20, 12, 0),
            evidence=_evidence(raw_text="测试"),
        )

        result = await _pipeline(db).run(capture)

        assert result.status == MemoryPipelineStatus.FAILED
        assert result.error_code == "PIPELINE_CAPTURE_TIME_INVALID"
        assert result.stages[-1].stage == MemoryPipelineStage.CAPTURE
        assert db.scalar(
            select(func.count(Memory.id)).where(Memory.user_id == user_id)
        ) == 0
