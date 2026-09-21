"""Trusted Entity -> Memory Pipeline Extract-stage adapter.

The adapter composes the merged Entity Extraction + Link service with an existing
MemoryExtractor. Owner identity comes only from MemoryPipelineExecutionContext;
provider output and free-form capture metadata never choose an owner or entity ID.
Entity results remain inference-only internal annotations and do not participate in
the Pipeline Evidence decision.
"""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy.orm import Session

from app.services.ai_gateway import AIGateway, AIGatewayError
from app.services.entity_extraction_service import (
    EntityExtractionError,
    extract_and_link_entities,
)
from app.services.memory_pipeline import (
    EntityPipelineAnnotation,
    ExtractedMemoryCandidate,
    MemoryExtractor,
    MemoryPipelineExecutionContext,
    MemoryPipelineStage,
    MemoryPipelineStageFailure,
    NormalizedMemoryInput,
)


class EntityAnnotatedMemoryExtractor:
    """Decorate one MemoryExtractor with owner-scoped Entity inference annotations."""

    def __init__(
        self,
        *,
        db: Session,
        gateway: AIGateway,
        delegate: MemoryExtractor,
    ):
        self._db = db
        self._gateway = gateway
        self._delegate = delegate

    async def extract(
        self,
        normalized: NormalizedMemoryInput,
        *,
        context: MemoryPipelineExecutionContext,
    ) -> ExtractedMemoryCandidate | None:
        candidate = await self._delegate.extract(
            normalized,
            context=context,
        )
        if candidate is None:
            return None
        if not isinstance(candidate, ExtractedMemoryCandidate):
            raise MemoryPipelineStageFailure(
                MemoryPipelineStage.EXTRACT,
                "PIPELINE_EXTRACT_INVALID",
            )

        try:
            entity_result = await extract_and_link_entities(
                self._db,
                user_id=context.user_id,
                text=normalized.original_text,
                gateway=self._gateway,
            )
        except EntityExtractionError as exc:
            raise MemoryPipelineStageFailure(
                MemoryPipelineStage.EXTRACT,
                exc.code,
            ) from exc
        except AIGatewayError as exc:
            raise MemoryPipelineStageFailure(
                MemoryPipelineStage.EXTRACT,
                exc.code,
                retryable=exc.retryable,
            ) from exc

        # The trusted Entity service is the sole author of these annotations on this
        # integration path. Delegate/model-provided annotations are overwritten rather
        # than merged, preventing a downstream extractor from smuggling linked IDs.
        annotations = tuple(
            EntityPipelineAnnotation(link=link)
            for link in entity_result.links
        )
        return replace(candidate, entity_annotations=annotations)
