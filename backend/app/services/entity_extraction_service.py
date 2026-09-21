"""Candidate-only Entity Extraction + Link service.

The model is allowed to propose literal entity spans only. The linker never accepts
provider-supplied IDs, never creates entities, and reads only the authenticated
owner's existing Object/Place inventory. Ambiguity therefore fails closed.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.entity_models import (
    EntityCandidate,
    EntityExtractionLinkResult,
    EntityExtractionResult,
    EntityInferenceProvenance,
    EntityKind,
    EntityLinkReason,
    EntityLinkResult,
    EntityLinkStatus,
    LinkedEntityReference,
)
from app.models import ObjectItem, Place
from app.services.ai_gateway import AIGateway, AIInferenceRequest, AIInferenceResult

_ENTITY_EXTRACTION_PURPOSE = "entity.extract"
_MAX_CANDIDATES = 20
_SYSTEM_INSTRUCTION = """Extract candidate entities from the user's text.
Return JSON only with exactly this shape:
{"entities":[{"kind":"OBJECT|PLACE|PERSON|TIME|EVENT","text":"exact source span"}]}
Rules:
- text must be copied verbatim from the input; do not rewrite or infer hidden facts.
- do not return IDs, confidence, links, user identity, or any other fields.
- return at most 20 candidates.
- return {"entities":[]} when nothing is supported.
Candidates are inference only and are never trusted facts."""


class EntityExtractionError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class _UntrustedEntityCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: EntityKind
    text: str = Field(min_length=1, max_length=200)


class _UntrustedEntityEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entities: list[_UntrustedEntityCandidate] = Field(max_length=_MAX_CANDIDATES)


def normalize_entity_text(value: str) -> str:
    """Use the same conservative lower/whitespace normalization as Object creation."""

    return " ".join(value.strip().lower().split())


def _candidate_provenance(inference: AIInferenceResult) -> EntityInferenceProvenance:
    provenance = inference.provenance
    return EntityInferenceProvenance(
        gateway_request_id=provenance.gateway_request_id,
        purpose=provenance.purpose,
        provider_request_id=provenance.provider_request_id,
        provider=provenance.provider,
        model=provenance.model,
        trust_class=inference.trust_class,
    )


def _parse_untrusted_candidates(
    *,
    source_text: str,
    inference: AIInferenceResult,
) -> EntityExtractionResult:
    try:
        decoded: Any = json.loads(inference.output_text)
        envelope = _UntrustedEntityEnvelope.model_validate(decoded)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise EntityExtractionError("ENTITY_EXTRACTION_INVALID_RESPONSE") from exc

    provenance = _candidate_provenance(inference)
    candidates: list[EntityCandidate] = []
    for raw in envelope.entities:
        # Literal-span enforcement is the last boundary between generative output and
        # extraction. A provider cannot silently normalize, paraphrase or hallucinate
        # a candidate that the user never supplied.
        if raw.text != raw.text.strip() or raw.text not in source_text:
            raise EntityExtractionError("ENTITY_EXTRACTION_NON_LITERAL_CANDIDATE")
        normalized = normalize_entity_text(raw.text)
        if not normalized:
            raise EntityExtractionError("ENTITY_EXTRACTION_INVALID_RESPONSE")
        candidates.append(
            EntityCandidate(
                kind=raw.kind,
                text=raw.text,
                normalized_text=normalized,
                provenance=provenance,
            )
        )
    return EntityExtractionResult(candidates=candidates)


async def extract_entity_candidates(
    *,
    text: str,
    gateway: AIGateway,
) -> EntityExtractionResult:
    source_text = text.strip()
    if not source_text:
        raise EntityExtractionError("ENTITY_EXTRACTION_EMPTY_INPUT")

    inference = await gateway.infer(
        AIInferenceRequest(
            purpose=_ENTITY_EXTRACTION_PURPOSE,
            system_instruction=_SYSTEM_INSTRUCTION,
            input_text=source_text,
            max_output_tokens=None,
        )
    )
    return _parse_untrusted_candidates(
        source_text=source_text,
        inference=inference,
    )


def _normalized_inventory_matches(
    candidate: EntityCandidate,
    inventory: Iterable[ObjectItem | Place],
) -> list[ObjectItem | Place]:
    matches: list[ObjectItem | Place] = []
    for item in inventory:
        # Object.normalized_name is authoritative for its creation-time uniqueness,
        # while Place currently has only a display name. Re-normalizing both names
        # here keeps comparison deterministic without introducing fuzzy/AI linking.
        source_name = item.normalized_name if isinstance(item, ObjectItem) else item.name
        if normalize_entity_text(source_name) == candidate.normalized_text:
            matches.append(item)
    return matches


def _resolve_candidate(
    candidate: EntityCandidate,
    *,
    inventory: Iterable[ObjectItem | Place],
) -> EntityLinkResult:
    matches = _normalized_inventory_matches(candidate, inventory)
    if not matches:
        return EntityLinkResult(
            candidate=candidate,
            status=EntityLinkStatus.UNRESOLVED,
            reason=EntityLinkReason.NO_MATCH,
        )
    if len(matches) != 1:
        # Duplicate Place display names are valid today. The linker must not select
        # one by row order, recency or model preference because none proves identity.
        return EntityLinkResult(
            candidate=candidate,
            status=EntityLinkStatus.UNRESOLVED,
            reason=EntityLinkReason.AMBIGUOUS,
        )

    match = matches[0]
    reason = (
        EntityLinkReason.EXACT_MATCH
        if match.name == candidate.text
        else EntityLinkReason.NORMALIZED_MATCH
    )
    kind = EntityKind.OBJECT if isinstance(match, ObjectItem) else EntityKind.PLACE
    return EntityLinkResult(
        candidate=candidate,
        status=EntityLinkStatus.LINKED,
        reason=reason,
        linked_entity=LinkedEntityReference(
            kind=kind,
            entity_id=match.id,
            canonical_name=match.name,
        ),
    )


def link_entity_candidates(
    db: Session,
    *,
    user_id: UUID,
    candidates: list[EntityCandidate],
) -> list[EntityLinkResult]:
    # Owner filtering happens in SQL before any name comparison. Provider output has
    # no ID field at all, so it cannot force the linker to dereference another user's
    # Object/Place even if it somehow knows such an ID.
    # This service is read-only even when composed inside a larger transaction.
    # Suppress SQLAlchemy autoflush so a lookup cannot accidentally persist unrelated
    # caller mutations before the caller's own trust/validation gates have completed.
    with db.no_autoflush:
        objects = list(
            db.scalars(
                select(ObjectItem).where(ObjectItem.user_id == user_id)
            ).all()
        )
        places = list(
            db.scalars(
                select(Place).where(Place.user_id == user_id)
            ).all()
        )

    links: list[EntityLinkResult] = []
    for candidate in candidates:
        if candidate.kind == EntityKind.OBJECT:
            links.append(_resolve_candidate(candidate, inventory=objects))
        elif candidate.kind == EntityKind.PLACE:
            links.append(_resolve_candidate(candidate, inventory=places))
        else:
            # Person has no trusted persistence model in this stage; TIME/EVENT are
            # extraction metadata only. Keeping them unresolved prevents accidental
            # fact/entity creation through a generic linker.
            links.append(
                EntityLinkResult(
                    candidate=candidate,
                    status=EntityLinkStatus.UNRESOLVED,
                    reason=EntityLinkReason.NOT_LINKABLE,
                )
            )
    return links


async def extract_and_link_entities(
    db: Session,
    *,
    user_id: UUID,
    text: str,
    gateway: AIGateway,
) -> EntityExtractionLinkResult:
    extraction = await extract_entity_candidates(text=text, gateway=gateway)
    links = link_entity_candidates(
        db,
        user_id=user_id,
        candidates=extraction.candidates,
    )
    return EntityExtractionLinkResult(
        extraction=extraction,
        links=links,
    )
