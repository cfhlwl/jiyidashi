from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core.db import SessionLocal
from app.embedding_gateway import DeterministicEmbeddingProvider, EmbeddingGateway
from app.embedding_policy import MEMORY_EMBEDDING_DIMENSIONS, MEMORY_EMBEDDING_MODEL
from app.main import app
from app.models import Memory, MemoryType
from app.services.embedding_service import (
    EmbeddingServiceError,
    build_memory_embedding_text,
    generate_or_refresh_memory_embedding,
    memory_embedding_fingerprint,
)


def _gateway(provider: DeterministicEmbeddingProvider) -> EmbeddingGateway:
    settings = Settings(
        app_env="test",
        embedding_provider="disabled",
        embedding_model=MEMORY_EMBEDDING_MODEL,
        embedding_dimensions=MEMORY_EMBEDDING_DIMENSIONS,
    )
    return EmbeddingGateway(settings, provider)


def test_canonical_memory_text_is_deterministic_and_excludes_untrusted_surfaces():
    memory = Memory(
        user_id=uuid4(),
        memory_type=MemoryType.NOTE,
        title="  护照位置  ",
        content="  护照放在书房抽屉  ",
        metadata_json={
            "secret_metadata": "must-not-enter-provider",
            "object_key": "private/storage/key",
        },
        latitude=1.23,
        longitude=4.56,
    )

    canonical = build_memory_embedding_text(memory)

    assert canonical == (
        "memory_type=NOTE\n"
        "title=护照位置\n"
        "content=护照放在书房抽屉"
    )
    assert "secret_metadata" not in canonical
    assert "private/storage/key" not in canonical
    assert "1.23" not in canonical
    assert memory_embedding_fingerprint(canonical) == memory_embedding_fingerprint(
        build_memory_embedding_text(memory)
    )


@pytest.mark.asyncio
async def test_sqlite_embedding_persistence_fails_before_provider_io():
    provider = DeterministicEmbeddingProvider()
    gateway = _gateway(provider)
    with SessionLocal() as db:
        with pytest.raises(EmbeddingServiceError) as caught:
            await generate_or_refresh_memory_embedding(
                db,
                user_id=uuid4(),
                memory_id=uuid4(),
                gateway=gateway,
            )
    assert caught.value.code == "EMBEDDING_DATABASE_UNSUPPORTED"
    assert provider.requests == []


def test_s3_009_adds_no_public_embedding_or_semantic_search_api():
    public_paths = {
        path
        for route in app.routes
        if isinstance((path := getattr(route, "path", None)), str)
    }
    assert all("embedding" not in path for path in public_paths)
    assert all("semantic" not in path for path in public_paths)
