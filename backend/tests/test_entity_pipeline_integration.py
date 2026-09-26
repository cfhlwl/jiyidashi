import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.db import SessionLocal
from app.entity_models import EntityLinkReason, EntityLinkStatus
from app.idempotency_models import ClientMutation
from app.models import Memory, MemorySource, MemoryType, ObjectItem, Place, SourceType, User
from app.person_memory_models import PersonMemoryLink
from app.person_models import Person
from app.person_relationship_models import PersonRelationship
from app.services.ai_gateway import AIGateway, DeterministicAIProvider, DisabledAIProvider
from app.services.entity_memory_pipeline_adapter import EntityAnnotatedMemoryExtractor
from app.services.memory_pipeline import (
    BasicMemoryNormalizer,
    ClassifiedMemoryCandidate,
    EvidenceDecision,
    ExtractedMemoryCandidate,
    MemoryPipeline,
    MemoryPipelineExecutionContext,
    MemoryPipelineInput,
    MemoryPipelineStage,
    MemoryPipelineStageStatus,
    MemoryPipelineStatus,
    NormalizedMemoryInput,
    PipelineEvidence,
    SQLAlchemyMemoryPipelineStore,
    StoreDecision,
)


def _settings() -> Settings:
    return Settings(
        app_env="test",
        ai_provider="disabled",
        ai_max_input_chars=10000,
        ai_max_output_tokens=1024,
    )


def _gateway(output: dict) -> tuple[AIGateway, DeterministicAIProvider]:
    provider = DeterministicAIProvider(
        output_text=json.dumps(output, ensure_ascii=False)
    )
    return AIGateway(_settings(), provider), provider


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
    evidence: PipelineEvidence | None,
    metadata: dict[str, str] | None = None,
) -> MemoryPipelineInput:
    return MemoryPipelineInput(
        execution_id=execution_id or uuid4(),
        user_id=user_id,
        original_text="护照放在仓库，交给老张",
        occurred_at=datetime(2026, 9, 21, 1, 0, tzinfo=UTC),
        evidence=evidence,
        metadata=metadata or {"capture_channel": "integration-test"},
    )


def _evidence() -> PipelineEvidence:
    return PipelineEvidence(
        source_type=SourceType.USER_TEXT,
        source_id="capture:entity-pipeline:1",
        raw_text="护照放在仓库，交给老张",
        confidence=1.0,
    )


class CapturingDelegate:
    def __init__(self):
        self.contexts: list[MemoryPipelineExecutionContext] = []

    async def extract(self, normalized, *, context):
        self.contexts.append(context)
        return ExtractedMemoryCandidate(
            content=normalized.normalized_text,
            confidence=0.9,
            attributes={"kind": "event_candidate"},
        )


class DeterministicClassifier:
    async def classify(self, extracted):
        return ClassifiedMemoryCandidate(
            content=extracted.content,
            memory_type=MemoryType.EVENT,
            confidence=0.9,
            attributes={"classification": "event"},
        )


class MaliciousSourceRewritingNormalizer:
    async def normalize(self, capture):
        return NormalizedMemoryInput(
            original_text="护照放好了",
            normalized_text="护照放好了",
            occurred_at=capture.occurred_at,
            metadata=dict(capture.metadata),
        )


def _pipeline(db, gateway, delegate) -> MemoryPipeline:
    return MemoryPipeline(
        normalizer=BasicMemoryNormalizer(),
        extractor=EntityAnnotatedMemoryExtractor(
            db=db,
            gateway=gateway,
            delegate=delegate,
        ),
        classifier=DeterministicClassifier(),
        store=SQLAlchemyMemoryPipelineStore(db),
    )


@pytest.mark.asyncio
async def test_normalizer_cannot_rewrite_source_text_to_manufacture_entity_span():
    with SessionLocal() as db:
        owner = _create_user(db, "entity-pipeline-source-boundary")
        db.add(
            ObjectItem(
                id=uuid4(),
                user_id=owner,
                name="护照",
                normalized_name="护照",
            )
        )
        db.commit()
        gateway, provider = _gateway(
            {"entities": [{"kind": "OBJECT", "text": "护照"}]}
        )
        delegate = CapturingDelegate()
        capture = MemoryPipelineInput(
            execution_id=uuid4(),
            user_id=owner,
            original_text="东西放好了",
            occurred_at=datetime(2026, 9, 21, 1, 0, tzinfo=UTC),
            evidence=PipelineEvidence(
                source_type=SourceType.USER_TEXT,
                source_id="capture:entity-pipeline:source-boundary",
                raw_text="东西放好了",
                confidence=1.0,
            ),
            metadata={"capture_channel": "integration-test"},
        )
        pipeline = MemoryPipeline(
            normalizer=MaliciousSourceRewritingNormalizer(),
            extractor=EntityAnnotatedMemoryExtractor(
                db=db,
                gateway=gateway,
                delegate=delegate,
            ),
            classifier=DeterministicClassifier(),
            store=SQLAlchemyMemoryPipelineStore(db),
        )

        result = await pipeline.run(capture)

        assert result.status == MemoryPipelineStatus.FAILED
        assert result.error_code == "PIPELINE_NORMALIZE_INVALID"
        assert result.stages[-1].stage == MemoryPipelineStage.NORMALIZE
        assert result.stages[-1].status == MemoryPipelineStageStatus.FAILED
        assert provider.requests == []
        assert delegate.contexts == []
        assert result.entity_annotations == ()
        assert db.scalar(
            select(func.count(Memory.id)).where(Memory.user_id == owner)
        ) == 0


@pytest.mark.asyncio
async def test_entity_adapter_uses_trusted_owner_and_retains_inference_provenance():
    with SessionLocal() as db:
        owner_a = _create_user(db, "entity-pipeline-owner-a")
        owner_b = _create_user(db, "entity-pipeline-owner-b")
        passport_id = uuid4()
        db.add_all(
            [
                ObjectItem(
                    id=passport_id,
                    user_id=owner_a,
                    name="护照",
                    normalized_name="护照",
                ),
                Place(
                    id=uuid4(),
                    user_id=owner_b,
                    name="仓库",
                    user_name="仓库",
                    is_user_named=True,
                ),
            ]
        )
        db.commit()

        gateway, provider = _gateway(
            {
                "entities": [
                    {"kind": "OBJECT", "text": "护照"},
                    {"kind": "PLACE", "text": "仓库"},
                    {"kind": "PERSON", "text": "老张"},
                ]
            }
        )
        delegate = CapturingDelegate()
        capture = _capture(
            owner_a,
            evidence=_evidence(),
            metadata={
                "capture_channel": "integration-test",
                "owner_id": str(owner_b),
            },
        )

        before_people = db.scalar(
            select(func.count(Person.id)).where(Person.user_id == owner_a)
        )
        before_links = db.scalar(
            select(func.count(PersonMemoryLink.id)).where(
                PersonMemoryLink.user_id == owner_a
            )
        )
        before_relationships = db.scalar(
            select(func.count(PersonRelationship.id)).where(
                PersonRelationship.user_id == owner_a
            )
        )
        result = await _pipeline(db, gateway, delegate).run(capture)
        after_people = db.scalar(
            select(func.count(Person.id)).where(Person.user_id == owner_a)
        )
        after_links = db.scalar(
            select(func.count(PersonMemoryLink.id)).where(
                PersonMemoryLink.user_id == owner_a
            )
        )
        after_relationships = db.scalar(
            select(func.count(PersonRelationship.id)).where(
                PersonRelationship.user_id == owner_a
            )
        )

        assert result.status == MemoryPipelineStatus.STORED
        assert before_people == after_people == 0
        assert before_links == after_links == 0
        assert before_relationships == after_relationships == 0
        assert result.store_decision == StoreDecision.STORE
        assert delegate.contexts == [
            MemoryPipelineExecutionContext(
                execution_id=capture.execution_id,
                user_id=owner_a,
            )
        ]
        by_text = {
            annotation.link.candidate.text: annotation
            for annotation in result.entity_annotations
        }
        passport = by_text["护照"]
        assert passport.trust_class == "inference"
        assert passport.link.status == EntityLinkStatus.LINKED
        assert passport.link.linked_entity is not None
        assert passport.link.linked_entity.entity_id == passport_id
        assert passport.link.candidate.provenance.trust_class == "inference"
        assert passport.link.candidate.provenance.provider == "deterministic"
        assert by_text["仓库"].link.status == EntityLinkStatus.UNRESOLVED
        assert by_text["仓库"].link.reason == EntityLinkReason.NO_MATCH
        assert by_text["老张"].link.reason == EntityLinkReason.NOT_LINKABLE
        assert provider.requests[0].input_text == capture.original_text.strip()

        memory = db.scalar(select(Memory).where(Memory.id == result.memory_id))
        assert memory is not None
        assert memory.user_id == owner_a
        assert memory.source_type == SourceType.AI_INFERENCE
        assert memory.is_confirmed is False


@pytest.mark.asyncio
async def test_linked_entity_annotation_cannot_bypass_evidence_gate():
    with SessionLocal() as db:
        owner = _create_user(db, "entity-pipeline-no-evidence")
        db.add(
            ObjectItem(
                id=uuid4(),
                user_id=owner,
                name="护照",
                normalized_name="护照",
            )
        )
        db.commit()
        gateway, _ = _gateway(
            {"entities": [{"kind": "OBJECT", "text": "护照"}]}
        )

        result = await _pipeline(db, gateway, CapturingDelegate()).run(
            _capture(owner, evidence=None)
        )

        assert result.status == MemoryPipelineStatus.SKIPPED
        assert result.evidence_decision == EvidenceDecision.MISSING
        assert result.store_decision == StoreDecision.SKIP_NO_EVIDENCE
        assert result.entity_annotations[0].link.status == EntityLinkStatus.LINKED
        assert db.scalar(
            select(func.count(Memory.id)).where(Memory.user_id == owner)
        ) == 0


@pytest.mark.asyncio
async def test_entity_gateway_failure_fails_closed_at_extract_stage():
    with SessionLocal() as db:
        owner = _create_user(db, "entity-pipeline-gateway-failure")
        gateway = AIGateway(_settings(), DisabledAIProvider())

        result = await _pipeline(db, gateway, CapturingDelegate()).run(
            _capture(owner, evidence=_evidence())
        )

        assert result.status == MemoryPipelineStatus.FAILED
        assert result.error_code == "AI_PROVIDER_UNAVAILABLE"
        assert result.stages[-1].stage == MemoryPipelineStage.EXTRACT
        assert result.stages[-1].status == MemoryPipelineStageStatus.FAILED
        assert db.scalar(
            select(func.count(Memory.id)).where(Memory.user_id == owner)
        ) == 0


@pytest.mark.asyncio
async def test_entity_pipeline_replay_does_not_duplicate_memory_or_evidence():
    with SessionLocal() as db:
        owner = _create_user(db, "entity-pipeline-replay")
        gateway, _ = _gateway(
            {"entities": [{"kind": "PERSON", "text": "老张"}]}
        )
        execution_id = uuid4()
        capture = _capture(
            owner,
            execution_id=execution_id,
            evidence=_evidence(),
        )
        pipeline = _pipeline(db, gateway, CapturingDelegate())

        before_people = db.scalar(
            select(func.count(Person.id)).where(Person.user_id == owner)
        )
        before_links = db.scalar(
            select(func.count(PersonMemoryLink.id)).where(
                PersonMemoryLink.user_id == owner
            )
        )
        before_relationships = db.scalar(
            select(func.count(PersonRelationship.id)).where(
                PersonRelationship.user_id == owner
            )
        )
        first = await pipeline.run(capture)
        second = await pipeline.run(capture)
        after_people = db.scalar(
            select(func.count(Person.id)).where(Person.user_id == owner)
        )
        after_links = db.scalar(
            select(func.count(PersonMemoryLink.id)).where(
                PersonMemoryLink.user_id == owner
            )
        )
        after_relationships = db.scalar(
            select(func.count(PersonRelationship.id)).where(
                PersonRelationship.user_id == owner
            )
        )

        assert first.status == MemoryPipelineStatus.STORED
        assert before_people == after_people == 0
        assert before_links == after_links == 0
        assert before_relationships == after_relationships == 0
        assert second.status == MemoryPipelineStatus.STORED
        assert first.memory_id == second.memory_id
        assert db.scalar(
            select(func.count(Memory.id)).where(Memory.user_id == owner)
        ) == 1
        assert db.scalar(
            select(func.count(MemorySource.id))
            .join(Memory, Memory.id == MemorySource.memory_id)
            .where(Memory.user_id == owner)
        ) == 1
        assert db.scalar(
            select(func.count(ClientMutation.id)).where(
                ClientMutation.user_id == owner,
                ClientMutation.operation_type == "MEMORY_PIPELINE_STORE_V1",
                ClientMutation.client_uuid == execution_id,
            )
        ) == 1
