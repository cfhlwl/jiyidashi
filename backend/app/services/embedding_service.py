from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.embedding_gateway import EmbeddingGateway, EmbeddingGatewayError
from app.embedding_models import MemoryEmbedding
from app.models import Memory, MemoryType
from app.vector_support import VectorCapabilityError, inspect_vector_capability


class EmbeddingServiceError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class MemoryEmbeddingSnapshot:
    memory_id: UUID
    user_id: UUID
    memory_revision: int
    canonical_text: str
    content_fingerprint: str


@dataclass(frozen=True)
class EmbeddingRefreshResult:
    memory_id: UUID
    memory_revision: int
    content_fingerprint: str
    provider: str
    model: str
    dimensions: int
    provider_request_id: str | None
    refreshed: bool


def build_memory_embedding_text(memory: Memory) -> str:
    """Build the only text S3-009 is allowed to send to the embedding provider."""

    memory_type = (
        memory.memory_type.value
        if isinstance(memory.memory_type, MemoryType)
        else str(memory.memory_type)
    )
    parts = [f"memory_type={memory_type}"]
    title = (memory.title or "").strip()
    if title:
        parts.append(f"title={title}")
    parts.append(f"content={memory.content.strip()}")
    return "\n".join(parts)


def memory_embedding_fingerprint(canonical_text: str) -> str:
    return hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()


def _require_vector_database(db: Session) -> None:
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        raise EmbeddingServiceError("EMBEDDING_DATABASE_UNSUPPORTED")
    try:
        inspect_vector_capability(db.connection())
    except VectorCapabilityError as exc:
        raise EmbeddingServiceError(exc.args[0]) from exc


def _snapshot_memory(
    db: Session,
    *,
    user_id: UUID,
    memory_id: UUID,
) -> MemoryEmbeddingSnapshot:
    memory = db.scalar(
        select(Memory)
        .where(
            Memory.id == memory_id,
            Memory.user_id == user_id,
            Memory.is_deleted.is_(False),
        )
        .with_for_update()
    )
    if memory is None:
        raise EmbeddingServiceError("MEMORY_NOT_FOUND")

    canonical_text = build_memory_embedding_text(memory)
    return MemoryEmbeddingSnapshot(
        memory_id=memory.id,
        user_id=memory.user_id,
        memory_revision=memory.edit_revision,
        canonical_text=canonical_text,
        content_fingerprint=memory_embedding_fingerprint(canonical_text),
    )


def _load_embedding_for_update(
    db: Session,
    memory_id: UUID,
) -> MemoryEmbedding | None:
    return db.scalar(
        select(MemoryEmbedding)
        .where(MemoryEmbedding.memory_id == memory_id)
        .with_for_update()
    )


def _matches(
    row: MemoryEmbedding,
    snapshot: MemoryEmbeddingSnapshot,
    gateway: EmbeddingGateway,
) -> bool:
    return (
        row.user_id == snapshot.user_id
        and row.memory_revision == snapshot.memory_revision
        and row.content_fingerprint == snapshot.content_fingerprint
        and row.model == gateway.model
        and row.dimensions == gateway.dimensions
    )


def _result_from_row(row: MemoryEmbedding, *, refreshed: bool) -> EmbeddingRefreshResult:
    return EmbeddingRefreshResult(
        memory_id=row.memory_id,
        memory_revision=row.memory_revision,
        content_fingerprint=row.content_fingerprint,
        provider=row.provider,
        model=row.model,
        dimensions=row.dimensions,
        provider_request_id=row.provider_request_id,
        refreshed=refreshed,
    )


async def generate_or_refresh_memory_embedding(
    db: Session,
    *,
    user_id: UUID,
    memory_id: UUID,
    gateway: EmbeddingGateway,
) -> EmbeddingRefreshResult:
    """Generate one current derived vector without holding DB locks over provider I/O."""

    _require_vector_database(db)

    snapshot = _snapshot_memory(db, user_id=user_id, memory_id=memory_id)
    existing = _load_embedding_for_update(db, memory_id)
    if existing is not None and _matches(existing, snapshot, gateway):
        db.commit()
        return _result_from_row(existing, refreshed=False)

    # A mismatched row is stale by definition. Remove it before external I/O so an old
    # vector cannot remain the current searchable row while a refresh is in flight.
    if existing is not None:
        db.delete(existing)
    db.commit()

    try:
        inference = await gateway.embed(snapshot.canonical_text)
    except EmbeddingGatewayError as exc:
        raise EmbeddingServiceError(exc.code) from exc

    current = _snapshot_memory(db, user_id=user_id, memory_id=memory_id)
    if (
        current.memory_revision != snapshot.memory_revision
        or current.content_fingerprint != snapshot.content_fingerprint
    ):
        db.rollback()
        raise EmbeddingServiceError("MEMORY_CHANGED_DURING_EMBEDDING")

    # The Memory row lock serializes concurrent refresh finalization. A second worker
    # that paid provider I/O still converges on the row committed by the first worker.
    existing = _load_embedding_for_update(db, memory_id)
    if existing is not None and _matches(existing, current, gateway):
        db.commit()
        return _result_from_row(existing, refreshed=False)
    if existing is not None:
        db.delete(existing)
        db.flush()

    row = MemoryEmbedding(
        memory_id=current.memory_id,
        user_id=current.user_id,
        memory_revision=current.memory_revision,
        content_fingerprint=current.content_fingerprint,
        provider=inference.provenance.provider,
        model=inference.provenance.model,
        dimensions=gateway.dimensions,
        provider_request_id=inference.provenance.provider_request_id,
        embedding=list(inference.vector),
    )
    db.add(row)
    # GuardedSession.commit() is the final deletion-generation gate when called from an
    # admitted request. If the generation changed during provider I/O, this write rolls back.
    db.commit()
    return _result_from_row(row, refreshed=True)


def invalidate_memory_embedding(db: Session, memory_id: UUID) -> int:
    """Delete a Memory's derived row in the same trusted edit/delete transaction."""

    if db.get_bind().dialect.name != "postgresql":
        return 0
    result = db.execute(
        delete(MemoryEmbedding).where(MemoryEmbedding.memory_id == memory_id)
    )
    return int(result.rowcount or 0)


def delete_owner_memory_embeddings(db: Session, user_id: UUID) -> int:
    if db.get_bind().dialect.name != "postgresql":
        return 0
    result = db.execute(
        delete(MemoryEmbedding).where(MemoryEmbedding.user_id == user_id)
    )
    return int(result.rowcount or 0)
