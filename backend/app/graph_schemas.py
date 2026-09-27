from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel


class GraphNodeKind(StrEnum):
    PERSON = "PERSON"
    PLACE = "PLACE"
    OBJECT = "OBJECT"
    EVENT = "EVENT"


class GraphEdgeKind(StrEnum):
    PERSON_RELATIONSHIP = "PERSON_RELATIONSHIP"
    PERSON_EVENT = "PERSON_EVENT"
    OBJECT_PLACE = "OBJECT_PLACE"
    EVENT_PLACE = "EVENT_PLACE"


class GraphNodeRef(BaseModel):
    kind: GraphNodeKind
    id: UUID
    label: str
    occurred_at: datetime | None = None


class GraphEdgeMetadata(BaseModel):
    relationship_kind: str | None = None
    custom_label: str | None = None
    relation_kind: str | None = None
    recorded_at: datetime | None = None


class GraphEdgeProjection(BaseModel):
    edge_kind: GraphEdgeKind
    source: GraphNodeRef
    target: GraphNodeRef
    authority_ref: UUID
    metadata: GraphEdgeMetadata


class GraphNeighborhood(BaseModel):
    center: GraphNodeRef
    nodes: list[GraphNodeRef]
    edges: list[GraphEdgeProjection]
    truncated: bool
