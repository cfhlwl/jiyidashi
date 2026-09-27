from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, aliased

from app.graph_schemas import (
    GraphEdgeKind,
    GraphEdgeMetadata,
    GraphEdgeProjection,
    GraphNeighborhood,
    GraphNodeKind,
    GraphNodeRef,
)
from app.models import (
    Memory,
    MemoryType,
    ObjectItem,
    ObjectLocation,
    ObjectLocationStatus,
    Place,
)
from app.person_memory_models import PersonMemoryLink
from app.person_models import Person
from app.person_relationship_models import PersonRelationship


class GraphProjectionError(RuntimeError):
    def __init__(self, code: str, status_code: int = 404):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class _ProjectedEdge:
    edge: GraphEdgeProjection
    authority_time: datetime


def _event_label(memory: Memory) -> str:
    if memory.title is not None and memory.title.strip():
        return memory.title.strip()
    preview = " ".join(memory.content.split())
    if len(preview) <= 80:
        return preview
    return f"{preview[:77]}..."


def _person_node(person: Person) -> GraphNodeRef:
    return GraphNodeRef(
        kind=GraphNodeKind.PERSON,
        id=person.id,
        label=person.display_name,
    )


def _place_node(place: Place) -> GraphNodeRef:
    return GraphNodeRef(
        kind=GraphNodeKind.PLACE,
        id=place.id,
        label=place.name,
    )


def _object_node(item: ObjectItem) -> GraphNodeRef:
    return GraphNodeRef(
        kind=GraphNodeKind.OBJECT,
        id=item.id,
        label=item.name,
    )


def _event_node(memory: Memory) -> GraphNodeRef:
    return GraphNodeRef(
        kind=GraphNodeKind.EVENT,
        id=memory.id,
        label=_event_label(memory),
        occurred_at=memory.occurred_at,
    )


def _load_center(
    db: Session,
    *,
    user_id: UUID,
    kind: GraphNodeKind,
    entity_id: UUID,
):
    if kind == GraphNodeKind.PERSON:
        center = db.scalar(
            select(Person)
            .where(Person.id == entity_id, Person.user_id == user_id)
            .with_for_update(read=True)
        )
    elif kind == GraphNodeKind.PLACE:
        center = db.scalar(
            select(Place)
            .where(Place.id == entity_id, Place.user_id == user_id)
            .with_for_update(read=True)
        )
    elif kind == GraphNodeKind.OBJECT:
        center = db.scalar(
            select(ObjectItem)
            .where(
                ObjectItem.id == entity_id,
                ObjectItem.user_id == user_id,
            )
            .with_for_update(read=True)
        )
    else:
        center = db.scalar(
            select(Memory)
            .where(
                Memory.id == entity_id,
                Memory.user_id == user_id,
                Memory.memory_type == MemoryType.EVENT,
                Memory.is_deleted.is_(False),
                Memory.is_confirmed.is_(True),
            )
            .with_for_update(read=True)
        )
    # V2-004 center authority is held with FOR SHARE for the lifetime of the
    # projection transaction. Writers that delete or invalidate the center use
    # FOR UPDATE, so edges and the center DTO cannot be assembled from opposite
    # sides of a committed authority transition under READ COMMITTED.
    if center is None:
        raise GraphProjectionError("GRAPH_NODE_NOT_FOUND")
    return center


def _sort_time(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()


def _finalize(
    center: GraphNodeRef,
    projected: list[_ProjectedEdge],
    *,
    limit: int,
    branch_truncated: bool,
) -> GraphNeighborhood:
    projected.sort(
        key=lambda item: (
            item.edge.edge_kind.value,
            -_sort_time(item.authority_time),
            item.edge.authority_ref.bytes,
        )
    )
    truncated = branch_truncated or len(projected) > limit
    selected = projected[:limit]

    # Typed identity, not bare UUID, is the dedupe key because UUID values are not
    # globally unique across Person/Place/Object/Memory tables.
    nodes_by_key: dict[tuple[GraphNodeKind, UUID], GraphNodeRef] = {}
    for item in selected:
        for node in (item.edge.source, item.edge.target):
            key = (node.kind, node.id)
            if key != (center.kind, center.id):
                nodes_by_key[key] = node

    nodes = sorted(
        nodes_by_key.values(),
        key=lambda node: (node.kind.value, node.label.casefold(), node.id.bytes),
    )
    return GraphNeighborhood(
        center=center,
        nodes=nodes,
        edges=[item.edge for item in selected],
        truncated=truncated,
    )


def _person_edges(
    db: Session,
    *,
    user_id: UUID,
    center: Person,
    limit: int,
) -> tuple[list[_ProjectedEdge], bool]:
    low_person = aliased(Person)
    high_person = aliased(Person)
    relationship_rows = db.execute(
        select(PersonRelationship, low_person, high_person)
        .join(
            low_person,
            and_(
                low_person.id == PersonRelationship.person_low_id,
                low_person.user_id == PersonRelationship.user_id,
            ),
        )
        .join(
            high_person,
            and_(
                high_person.id == PersonRelationship.person_high_id,
                high_person.user_id == PersonRelationship.user_id,
            ),
        )
        .where(
            PersonRelationship.user_id == user_id,
            or_(
                PersonRelationship.person_low_id == center.id,
                PersonRelationship.person_high_id == center.id,
            ),
        )
        .order_by(PersonRelationship.created_at.desc(), PersonRelationship.id.desc())
        .limit(limit + 1)
    ).all()

    result: list[_ProjectedEdge] = []
    center_node = _person_node(center)
    for edge, low, high in relationship_rows[: limit + 1]:
        other = high if edge.person_low_id == center.id else low
        result.append(
            _ProjectedEdge(
                edge=GraphEdgeProjection(
                    edge_kind=GraphEdgeKind.PERSON_RELATIONSHIP,
                    source=center_node,
                    target=_person_node(other),
                    authority_ref=edge.id,
                    metadata=GraphEdgeMetadata(
                        relationship_kind=edge.relationship_kind.value,
                        custom_label=edge.custom_label,
                    ),
                ),
                authority_time=edge.created_at,
            )
        )

    event_rows = db.execute(
        select(PersonMemoryLink, Memory)
        .join(
            Memory,
            and_(
                Memory.id == PersonMemoryLink.memory_id,
                Memory.user_id == PersonMemoryLink.user_id,
            ),
        )
        .where(
            PersonMemoryLink.user_id == user_id,
            PersonMemoryLink.person_id == center.id,
            Memory.memory_type == MemoryType.EVENT,
            Memory.is_deleted.is_(False),
            Memory.is_confirmed.is_(True),
        )
        .order_by(PersonMemoryLink.created_at.desc(), PersonMemoryLink.id.desc())
        .limit(limit + 1)
    ).all()
    for link, memory in event_rows[: limit + 1]:
        result.append(
            _ProjectedEdge(
                edge=GraphEdgeProjection(
                    edge_kind=GraphEdgeKind.PERSON_EVENT,
                    source=center_node,
                    target=_event_node(memory),
                    authority_ref=link.id,
                    metadata=GraphEdgeMetadata(relation_kind=link.relation_kind.value),
                ),
                authority_time=link.created_at,
            )
        )

    return result, len(relationship_rows) > limit or len(event_rows) > limit


def _place_edges(
    db: Session,
    *,
    user_id: UUID,
    center: Place,
    limit: int,
) -> tuple[list[_ProjectedEdge], bool]:
    center_node = _place_node(center)
    object_rows = db.execute(
        select(ObjectLocation, ObjectItem)
        .join(
            ObjectItem,
            and_(
                ObjectItem.id == ObjectLocation.object_id,
                ObjectItem.user_id == ObjectLocation.user_id,
            ),
        )
        .where(
            ObjectLocation.user_id == user_id,
            ObjectLocation.status == ObjectLocationStatus.CURRENT,
            ObjectLocation.place_id == center.id,
            ObjectItem.user_id == user_id,
        )
        .order_by(ObjectLocation.recorded_at.desc(), ObjectLocation.id.desc())
        .limit(limit + 1)
    ).all()

    result = [
        _ProjectedEdge(
            edge=GraphEdgeProjection(
                edge_kind=GraphEdgeKind.OBJECT_PLACE,
                source=center_node,
                target=_object_node(item),
                authority_ref=location.id,
                metadata=GraphEdgeMetadata(recorded_at=location.recorded_at),
            ),
            authority_time=location.recorded_at,
        )
        for location, item in object_rows[: limit + 1]
    ]

    event_rows = list(
        db.scalars(
            select(Memory)
            .where(
                Memory.user_id == user_id,
                Memory.memory_type == MemoryType.EVENT,
                Memory.is_deleted.is_(False),
                Memory.is_confirmed.is_(True),
                Memory.place_id == center.id,
            )
            .order_by(Memory.created_at.desc(), Memory.id.desc())
            .limit(limit + 1)
        ).all()
    )
    for memory in event_rows[: limit + 1]:
        result.append(
            _ProjectedEdge(
                edge=GraphEdgeProjection(
                    edge_kind=GraphEdgeKind.EVENT_PLACE,
                    source=center_node,
                    target=_event_node(memory),
                    authority_ref=memory.id,
                    metadata=GraphEdgeMetadata(),
                ),
                authority_time=memory.created_at,
            )
        )

    return result, len(object_rows) > limit or len(event_rows) > limit


def _object_edges(
    db: Session,
    *,
    user_id: UUID,
    center: ObjectItem,
    limit: int,
) -> tuple[list[_ProjectedEdge], bool]:
    rows = db.execute(
        select(ObjectLocation, Place)
        .join(
            Place,
            and_(
                Place.id == ObjectLocation.place_id,
                Place.user_id == ObjectLocation.user_id,
            ),
        )
        .where(
            ObjectLocation.user_id == user_id,
            ObjectLocation.object_id == center.id,
            ObjectLocation.status == ObjectLocationStatus.CURRENT,
            ObjectLocation.place_id.is_not(None),
            Place.user_id == user_id,
        )
        .order_by(ObjectLocation.recorded_at.desc(), ObjectLocation.id.desc())
        .limit(limit + 1)
    ).all()
    center_node = _object_node(center)
    projected = [
        _ProjectedEdge(
            edge=GraphEdgeProjection(
                edge_kind=GraphEdgeKind.OBJECT_PLACE,
                source=center_node,
                target=_place_node(place),
                authority_ref=location.id,
                metadata=GraphEdgeMetadata(recorded_at=location.recorded_at),
            ),
            authority_time=location.recorded_at,
        )
        for location, place in rows[: limit + 1]
    ]
    return projected, len(rows) > limit


def _event_edges(
    db: Session,
    *,
    user_id: UUID,
    center: Memory,
    limit: int,
) -> tuple[list[_ProjectedEdge], bool]:
    center_node = _event_node(center)
    person_rows = db.execute(
        select(PersonMemoryLink, Person)
        .join(
            Person,
            and_(
                Person.id == PersonMemoryLink.person_id,
                Person.user_id == PersonMemoryLink.user_id,
            ),
        )
        .where(
            PersonMemoryLink.user_id == user_id,
            PersonMemoryLink.memory_id == center.id,
            Person.user_id == user_id,
        )
        .order_by(PersonMemoryLink.created_at.desc(), PersonMemoryLink.id.desc())
        .limit(limit + 1)
    ).all()

    result = [
        _ProjectedEdge(
            edge=GraphEdgeProjection(
                edge_kind=GraphEdgeKind.PERSON_EVENT,
                source=center_node,
                target=_person_node(person),
                authority_ref=link.id,
                metadata=GraphEdgeMetadata(relation_kind=link.relation_kind.value),
            ),
            authority_time=link.created_at,
        )
        for link, person in person_rows[: limit + 1]
    ]

    place_rows: list[Place] = []
    if center.place_id is not None:
        place = db.scalar(
            select(Place).where(
                Place.id == center.place_id,
                Place.user_id == user_id,
            )
        )
        if place is not None:
            place_rows.append(place)
            result.append(
                _ProjectedEdge(
                    edge=GraphEdgeProjection(
                        edge_kind=GraphEdgeKind.EVENT_PLACE,
                        source=center_node,
                        target=_place_node(place),
                        authority_ref=center.id,
                        metadata=GraphEdgeMetadata(),
                    ),
                    authority_time=center.created_at,
                )
            )

    return result, len(person_rows) > limit or len(place_rows) > limit


def get_graph_neighborhood(
    db: Session,
    *,
    user_id: UUID,
    kind: GraphNodeKind,
    entity_id: UUID,
    limit: int,
) -> GraphNeighborhood:
    center = _load_center(
        db,
        user_id=user_id,
        kind=kind,
        entity_id=entity_id,
    )
    if kind == GraphNodeKind.PERSON:
        projected, branch_truncated = _person_edges(
            db,
            user_id=user_id,
            center=center,
            limit=limit,
        )
        center_node = _person_node(center)
    elif kind == GraphNodeKind.PLACE:
        projected, branch_truncated = _place_edges(
            db,
            user_id=user_id,
            center=center,
            limit=limit,
        )
        center_node = _place_node(center)
    elif kind == GraphNodeKind.OBJECT:
        projected, branch_truncated = _object_edges(
            db,
            user_id=user_id,
            center=center,
            limit=limit,
        )
        center_node = _object_node(center)
    else:
        projected, branch_truncated = _event_edges(
            db,
            user_id=user_id,
            center=center,
            limit=limit,
        )
        center_node = _event_node(center)

    return _finalize(
        center_node,
        projected,
        limit=limit,
        branch_truncated=branch_truncated,
    )
