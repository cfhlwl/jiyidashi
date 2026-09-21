from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Memory, MemorySource, MemoryType, SourceType
from app.services.idempotency_service import (
    IdempotencyConflict,
    IdempotencyResourceGone,
    execute_idempotent_mutation,
)
from app.services.memory_service import get_memory_for_user

PIPELINE_VERSION = "memory-pipeline-v1"
MIN_EVIDENCE_CONFIDENCE = 0.60


class MemoryPipelineStage(StrEnum):
    CAPTURE = "CAPTURE"
    NORMALIZE = "NORMALIZE"
    EXTRACT = "EXTRACT"
    CLASSIFY = "CLASSIFY"
    EVIDENCE = "EVIDENCE"
    STORE = "STORE"


class MemoryPipelineStageStatus(StrEnum):
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class MemoryPipelineStatus(StrEnum):
    STORED = "STORED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class EvidenceDecision(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    MISSING = "MISSING"
    AI_ONLY = "AI_ONLY"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"


class StoreDecision(StrEnum):
    STORE = "STORE"
    SKIP_NO_CANDIDATE = "SKIP_NO_CANDIDATE"
    SKIP_NO_EVIDENCE = "SKIP_NO_EVIDENCE"
    FAILED = "FAILED"


@dataclass(frozen=True)
class PipelineEvidence:
    source_type: SourceType
    raw_text: str
    confidence: float
    source_id: str | None = None


@dataclass(frozen=True)
class MemoryPipelineInput:
    execution_id: UUID
    user_id: UUID
    original_text: str
    occurred_at: datetime
    evidence: PipelineEvidence | None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedMemoryInput:
    original_text: str
    normalized_text: str
    occurred_at: datetime
    metadata: dict[str, str]


@dataclass(frozen=True)
class ExtractedMemoryCandidate:
    content: str
    title: str | None = None
    confidence: float = 0.5
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ClassifiedMemoryCandidate:
    content: str
    memory_type: MemoryType
    title: str | None = None
    confidence: float = 0.5
    attributes: dict[str, str] = field(default_factory=dict)
    trust_class: Literal["inference"] = "inference"


@dataclass(frozen=True)
class MemoryPipelineStageState:
    stage: MemoryPipelineStage
    status: MemoryPipelineStageStatus
    code: str | None = None


@dataclass(frozen=True)
class MemoryPipelineResult:
    execution_id: UUID
    user_id: UUID
    status: MemoryPipelineStatus
    stages: tuple[MemoryPipelineStageState, ...]
    candidate: ClassifiedMemoryCandidate | None
    evidence_decision: EvidenceDecision | None
    store_decision: StoreDecision
    memory_id: UUID | None = None
    error_code: str | None = None
    retryable: bool = False


@dataclass(frozen=True)
class MemoryPipelineStageFailure(Exception):
    stage: MemoryPipelineStage
    code: str
    retryable: bool = False


class MemoryNormalizer(Protocol):
    async def normalize(self, capture: MemoryPipelineInput) -> NormalizedMemoryInput: ...


class MemoryExtractor(Protocol):
    async def extract(
        self,
        normalized: NormalizedMemoryInput,
    ) -> ExtractedMemoryCandidate | None: ...


class MemoryClassifier(Protocol):
    async def classify(
        self,
        extracted: ExtractedMemoryCandidate,
    ) -> ClassifiedMemoryCandidate: ...


class MemoryPipelineStore(Protocol):
    def store(
        self,
        *,
        capture: MemoryPipelineInput,
        candidate: ClassifiedMemoryCandidate,
        evidence: PipelineEvidence,
    ) -> Memory: ...


class BasicMemoryNormalizer:
    """Deterministic normalization that never mutates the original capture/evidence."""

    async def normalize(self, capture: MemoryPipelineInput) -> NormalizedMemoryInput:
        # The normalized view is disposable processing state. original_text and
        # MemorySource.raw_text remain untouched so later review can always inspect source.
        normalized = " ".join(capture.original_text.split())
        return NormalizedMemoryInput(
            original_text=capture.original_text,
            normalized_text=normalized,
            occurred_at=capture.occurred_at,
            metadata=dict(capture.metadata),
        )


class SQLAlchemyMemoryPipelineStore:
    """Persistence boundary for inferred candidates.

    Stored pipeline candidates remain AI_INFERENCE + unconfirmed even when they carry
    valid original Evidence. Existing query gates therefore cannot silently promote them
    to answerable facts. ClientMutation provides replay/concurrency idempotency.
    """

    def __init__(self, db: Session):
        self._db = db

    def store(
        self,
        *,
        capture: MemoryPipelineInput,
        candidate: ClassifiedMemoryCandidate,
        evidence: PipelineEvidence,
    ) -> Memory:
        validated_capture = _validate_capture(capture)
        validated_candidate = _validate_classified(candidate)
        try:
            validated_evidence = _validate_evidence(evidence)
        except MemoryPipelineStageFailure as exc:
            raise MemoryPipelineStageFailure(
                MemoryPipelineStage.STORE,
                "PIPELINE_STORE_EVIDENCE_INVALID",
            ) from exc
        if (
            validated_evidence.source_type == SourceType.AI_INFERENCE
            or validated_evidence.confidence < MIN_EVIDENCE_CONFIDENCE
        ):
            # Store is a trust boundary too. Future callers cannot bypass the orchestrator
            # and persist AI-only or sub-threshold Evidence directly.
            raise MemoryPipelineStageFailure(
                MemoryPipelineStage.STORE,
                "PIPELINE_STORE_EVIDENCE_REJECTED",
            )

        capture = validated_capture
        candidate = validated_candidate
        evidence = validated_evidence
        occurred_at = _require_aware_utc(capture.occurred_at)
        fingerprint_payload = {
            "pipeline_version": PIPELINE_VERSION,
            "user_id": str(capture.user_id),
            "original_text": capture.original_text,
            "occurred_at": occurred_at.isoformat(),
            "metadata": dict(sorted(capture.metadata.items())),
            "candidate": {
                "content": candidate.content,
                "memory_type": candidate.memory_type.value,
                "title": candidate.title,
                "confidence": candidate.confidence,
                "attributes": dict(sorted(candidate.attributes.items())),
                "trust_class": candidate.trust_class,
            },
            "evidence": {
                "source_type": evidence.source_type.value,
                "source_id": evidence.source_id,
                "raw_text": evidence.raw_text,
                "confidence": evidence.confidence,
            },
        }

        def create_resource(db: Session) -> Memory:
            # The Memory row represents an AI-derived candidate, never a confirmed fact.
            # Original Evidence is attached as a separate MemorySource so provenance is
            # retained without pretending the user authored the normalized/extracted text.
            memory = Memory(
                user_id=capture.user_id,
                memory_type=candidate.memory_type,
                title=candidate.title,
                content=candidate.content,
                occurred_at=occurred_at,
                source_type=SourceType.AI_INFERENCE,
                confidence=min(candidate.confidence, 0.5),
                is_confirmed=False,
                metadata_json={
                    **capture.metadata,
                    "memory_pipeline": {
                        "version": PIPELINE_VERSION,
                        "execution_id": str(capture.execution_id),
                        "trust_class": "inference",
                        "candidate_attributes": dict(candidate.attributes),
                    },
                },
            )
            db.add(memory)
            db.flush()
            db.add(
                MemorySource(
                    memory_id=memory.id,
                    source_type=evidence.source_type,
                    source_id=evidence.source_id,
                    raw_text=evidence.raw_text,
                    confidence=evidence.confidence,
                )
            )
            return memory

        try:
            return execute_idempotent_mutation(
                self._db,
                user_id=capture.user_id,
                operation_type="MEMORY_PIPELINE_STORE_V1",
                client_uuid=capture.execution_id,
                fingerprint_payload=fingerprint_payload,
                resource_type="MEMORY",
                create_resource=create_resource,
                resource_id=lambda memory: memory.id,
                load_resource=lambda db, resource_id: get_memory_for_user(
                    db,
                    capture.user_id,
                    resource_id,
                ),
            )
        except IdempotencyConflict as exc:
            raise MemoryPipelineStageFailure(
                MemoryPipelineStage.STORE,
                "PIPELINE_REPLAY_CONFLICT",
            ) from exc
        except IdempotencyResourceGone as exc:
            raise MemoryPipelineStageFailure(
                MemoryPipelineStage.STORE,
                "PIPELINE_REPLAY_RESOURCE_GONE",
            ) from exc


class MemoryPipeline:
    """Trusted Stage 3 orchestration foundation.

    Extract/classify adapters are injected and may be deterministic or AI-backed. Any
    future AI-backed adapter must depend on AIGateway rather than a model vendor client.
    This orchestrator never fabricates fallback facts when a stage fails.
    """

    def __init__(
        self,
        *,
        normalizer: MemoryNormalizer,
        extractor: MemoryExtractor,
        classifier: MemoryClassifier,
        store: MemoryPipelineStore,
        min_evidence_confidence: float = MIN_EVIDENCE_CONFIDENCE,
    ):
        if not math.isfinite(min_evidence_confidence) or not (
            MIN_EVIDENCE_CONFIDENCE <= min_evidence_confidence <= 1.0
        ):
            # The pipeline may tighten the existing Evidence gate, never weaken it.
            raise ValueError(
                "min_evidence_confidence must be finite and within "
                f"[{MIN_EVIDENCE_CONFIDENCE}, 1]"
            )
        self._normalizer = normalizer
        self._extractor = extractor
        self._classifier = classifier
        self._store = store
        self._min_evidence_confidence = min_evidence_confidence

    async def run(self, capture: MemoryPipelineInput) -> MemoryPipelineResult:
        states: list[MemoryPipelineStageState] = []
        try:
            validated_capture = _validate_capture(capture)
            states.append(_completed(MemoryPipelineStage.CAPTURE))

            normalized = _validate_normalized(
                await self._normalizer.normalize(validated_capture)
            )
            states.append(_completed(MemoryPipelineStage.NORMALIZE))

            extracted = await self._extractor.extract(normalized)
            if extracted is None:
                states.append(_completed(MemoryPipelineStage.EXTRACT))
                states.extend(
                    (
                        _skipped(MemoryPipelineStage.CLASSIFY, "NO_CANDIDATE"),
                        _skipped(MemoryPipelineStage.EVIDENCE, "NO_CANDIDATE"),
                        _skipped(MemoryPipelineStage.STORE, "NO_CANDIDATE"),
                    )
                )
                return MemoryPipelineResult(
                    execution_id=capture.execution_id,
                    user_id=capture.user_id,
                    status=MemoryPipelineStatus.SKIPPED,
                    stages=tuple(states),
                    candidate=None,
                    evidence_decision=None,
                    store_decision=StoreDecision.SKIP_NO_CANDIDATE,
                )

            extracted = _validate_extracted(extracted)
            states.append(_completed(MemoryPipelineStage.EXTRACT))

            candidate = _validate_classified(await self._classifier.classify(extracted))
            states.append(_completed(MemoryPipelineStage.CLASSIFY))

            evidence_decision = self._decide_evidence(validated_capture.evidence)
            states.append(_completed(MemoryPipelineStage.EVIDENCE, evidence_decision.value))
            if evidence_decision != EvidenceDecision.ELIGIBLE:
                states.append(
                    _skipped(
                        MemoryPipelineStage.STORE,
                        f"EVIDENCE_{evidence_decision.value}",
                    )
                )
                return MemoryPipelineResult(
                    execution_id=capture.execution_id,
                    user_id=capture.user_id,
                    status=MemoryPipelineStatus.SKIPPED,
                    stages=tuple(states),
                    candidate=candidate,
                    evidence_decision=evidence_decision,
                    store_decision=StoreDecision.SKIP_NO_EVIDENCE,
                )

            evidence = validated_capture.evidence
            if evidence is None:
                raise AssertionError("eligible Evidence decision requires Evidence")

            memory = self._store.store(
                capture=validated_capture,
                candidate=candidate,
                evidence=evidence,
            )
            states.append(_completed(MemoryPipelineStage.STORE))
            return MemoryPipelineResult(
                execution_id=capture.execution_id,
                user_id=capture.user_id,
                status=MemoryPipelineStatus.STORED,
                stages=tuple(states),
                candidate=candidate,
                evidence_decision=evidence_decision,
                store_decision=StoreDecision.STORE,
                memory_id=memory.id,
            )
        except MemoryPipelineStageFailure as exc:
            if not states or states[-1].stage != exc.stage:
                states.append(
                    MemoryPipelineStageState(
                        stage=exc.stage,
                        status=MemoryPipelineStageStatus.FAILED,
                        code=exc.code,
                    )
                )
            return MemoryPipelineResult(
                execution_id=capture.execution_id,
                user_id=capture.user_id,
                status=MemoryPipelineStatus.FAILED,
                stages=tuple(states),
                candidate=None,
                evidence_decision=None,
                store_decision=StoreDecision.FAILED,
                error_code=exc.code,
                retryable=exc.retryable,
            )

    def _decide_evidence(self, evidence: PipelineEvidence | None) -> EvidenceDecision:
        if evidence is None:
            return EvidenceDecision.MISSING
        _validate_evidence(evidence)
        if evidence.source_type == SourceType.AI_INFERENCE:
            return EvidenceDecision.AI_ONLY
        if evidence.confidence < self._min_evidence_confidence:
            return EvidenceDecision.LOW_CONFIDENCE
        return EvidenceDecision.ELIGIBLE


def _completed(
    stage: MemoryPipelineStage,
    code: str | None = None,
) -> MemoryPipelineStageState:
    return MemoryPipelineStageState(
        stage=stage,
        status=MemoryPipelineStageStatus.COMPLETED,
        code=code,
    )


def _skipped(stage: MemoryPipelineStage, code: str) -> MemoryPipelineStageState:
    return MemoryPipelineStageState(
        stage=stage,
        status=MemoryPipelineStageStatus.SKIPPED,
        code=code,
    )


def _require_text(value: object, *, code: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise MemoryPipelineStageFailure(MemoryPipelineStage.CAPTURE, code)
    normalized = value.strip()
    if not normalized or len(normalized) > max_length:
        raise MemoryPipelineStageFailure(MemoryPipelineStage.CAPTURE, code)
    return value


def _require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise MemoryPipelineStageFailure(
            MemoryPipelineStage.CAPTURE,
            "PIPELINE_CAPTURE_TIME_INVALID",
        )
    return value.astimezone(UTC)


def _validate_string_map(
    value: object,
    *,
    stage: MemoryPipelineStage,
    code: str,
) -> dict[str, str]:
    if not isinstance(value, dict):
        raise MemoryPipelineStageFailure(stage, code)
    validated: dict[str, str] = {}
    for key, item in value.items():
        if (
            not isinstance(key, str)
            or not key
            or len(key) > 100
            or not isinstance(item, str)
            or len(item) > 2000
        ):
            raise MemoryPipelineStageFailure(stage, code)
        validated[key] = item
    return validated


def _validate_confidence(
    value: object,
    *,
    stage: MemoryPipelineStage,
    code: str,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (float, int))
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise MemoryPipelineStageFailure(stage, code)
    return float(value)


def _validate_capture(capture: MemoryPipelineInput) -> MemoryPipelineInput:
    if not isinstance(capture, MemoryPipelineInput):
        raise MemoryPipelineStageFailure(
            MemoryPipelineStage.CAPTURE,
            "PIPELINE_CAPTURE_INVALID",
        )
    original_text = _require_text(
        capture.original_text,
        code="PIPELINE_CAPTURE_INVALID",
        max_length=20000,
    )
    occurred_at = _require_aware_utc(capture.occurred_at)
    metadata = _validate_string_map(
        capture.metadata,
        stage=MemoryPipelineStage.CAPTURE,
        code="PIPELINE_CAPTURE_INVALID",
    )
    return MemoryPipelineInput(
        execution_id=capture.execution_id,
        user_id=capture.user_id,
        original_text=original_text,
        occurred_at=occurred_at,
        evidence=capture.evidence,
        metadata=metadata,
    )


def _validate_evidence(evidence: PipelineEvidence) -> PipelineEvidence:
    if not isinstance(evidence, PipelineEvidence):
        raise MemoryPipelineStageFailure(
            MemoryPipelineStage.EVIDENCE,
            "PIPELINE_EVIDENCE_INVALID",
        )
    if not isinstance(evidence.source_type, SourceType):
        raise MemoryPipelineStageFailure(
            MemoryPipelineStage.EVIDENCE,
            "PIPELINE_EVIDENCE_INVALID",
        )
    raw_text = evidence.raw_text.strip()
    if not raw_text or len(raw_text) > 20000:
        raise MemoryPipelineStageFailure(
            MemoryPipelineStage.EVIDENCE,
            "PIPELINE_EVIDENCE_INVALID",
        )
    confidence = _validate_confidence(
        evidence.confidence,
        stage=MemoryPipelineStage.EVIDENCE,
        code="PIPELINE_EVIDENCE_INVALID",
    )
    if evidence.source_id is not None and (
        not isinstance(evidence.source_id, str)
        or not evidence.source_id.strip()
        or len(evidence.source_id) > 255
    ):
        raise MemoryPipelineStageFailure(
            MemoryPipelineStage.EVIDENCE,
            "PIPELINE_EVIDENCE_INVALID",
        )
    return PipelineEvidence(
        source_type=evidence.source_type,
        source_id=evidence.source_id,
        raw_text=evidence.raw_text,
        confidence=confidence,
    )


def _validate_normalized(value: object) -> NormalizedMemoryInput:
    if not isinstance(value, NormalizedMemoryInput):
        raise MemoryPipelineStageFailure(
            MemoryPipelineStage.NORMALIZE,
            "PIPELINE_NORMALIZE_INVALID",
        )
    if not value.original_text.strip() or not value.normalized_text.strip():
        raise MemoryPipelineStageFailure(
            MemoryPipelineStage.NORMALIZE,
            "PIPELINE_NORMALIZE_INVALID",
        )
    if len(value.original_text) > 20000 or len(value.normalized_text) > 20000:
        raise MemoryPipelineStageFailure(
            MemoryPipelineStage.NORMALIZE,
            "PIPELINE_NORMALIZE_INVALID",
        )
    _require_aware_utc(value.occurred_at)
    _validate_string_map(
        value.metadata,
        stage=MemoryPipelineStage.NORMALIZE,
        code="PIPELINE_NORMALIZE_INVALID",
    )
    return value


def _validate_extracted(value: object) -> ExtractedMemoryCandidate:
    if not isinstance(value, ExtractedMemoryCandidate):
        raise MemoryPipelineStageFailure(
            MemoryPipelineStage.EXTRACT,
            "PIPELINE_EXTRACT_INVALID",
        )
    if not value.content.strip() or len(value.content) > 20000:
        raise MemoryPipelineStageFailure(
            MemoryPipelineStage.EXTRACT,
            "PIPELINE_EXTRACT_INVALID",
        )
    if value.title is not None and len(value.title) > 240:
        raise MemoryPipelineStageFailure(
            MemoryPipelineStage.EXTRACT,
            "PIPELINE_EXTRACT_INVALID",
        )
    _validate_confidence(
        value.confidence,
        stage=MemoryPipelineStage.EXTRACT,
        code="PIPELINE_EXTRACT_INVALID",
    )
    _validate_string_map(
        value.attributes,
        stage=MemoryPipelineStage.EXTRACT,
        code="PIPELINE_EXTRACT_INVALID",
    )
    return value


def _validate_classified(value: object) -> ClassifiedMemoryCandidate:
    if not isinstance(value, ClassifiedMemoryCandidate):
        raise MemoryPipelineStageFailure(
            MemoryPipelineStage.CLASSIFY,
            "PIPELINE_CLASSIFY_INVALID",
        )
    if value.trust_class != "inference":
        # Stage adapters cannot promote their own output to a trusted fact.
        raise MemoryPipelineStageFailure(
            MemoryPipelineStage.CLASSIFY,
            "PIPELINE_TRUST_ESCALATION_REJECTED",
        )
    if not isinstance(value.memory_type, MemoryType):
        raise MemoryPipelineStageFailure(
            MemoryPipelineStage.CLASSIFY,
            "PIPELINE_CLASSIFY_INVALID",
        )
    if not value.content.strip() or len(value.content) > 20000:
        raise MemoryPipelineStageFailure(
            MemoryPipelineStage.CLASSIFY,
            "PIPELINE_CLASSIFY_INVALID",
        )
    if value.title is not None and len(value.title) > 240:
        raise MemoryPipelineStageFailure(
            MemoryPipelineStage.CLASSIFY,
            "PIPELINE_CLASSIFY_INVALID",
        )
    _validate_confidence(
        value.confidence,
        stage=MemoryPipelineStage.CLASSIFY,
        code="PIPELINE_CLASSIFY_INVALID",
    )
    _validate_string_map(
        value.attributes,
        stage=MemoryPipelineStage.CLASSIFY,
        code="PIPELINE_CLASSIFY_INVALID",
    )
    return value
