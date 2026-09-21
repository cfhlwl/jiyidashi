from __future__ import annotations

import asyncio
import json
import math

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.embedding_gateway import (
    DeterministicEmbeddingProvider,
    EmbeddingGateway,
    EmbeddingGatewayError,
    EmbeddingProviderResult,
    EmbeddingRequest,
    build_embedding_gateway,
)
from app.embedding_policy import MEMORY_EMBEDDING_DIMENSIONS, MEMORY_EMBEDDING_MODEL


def _settings(**overrides) -> Settings:
    values = {
        "app_env": "test",
        "embedding_provider": "disabled",
        "embedding_model": MEMORY_EMBEDDING_MODEL,
        "embedding_dimensions": MEMORY_EMBEDDING_DIMENSIONS,
        "embedding_timeout_seconds": 1.0,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.asyncio
async def test_deterministic_gateway_enforces_model_dimension_and_finite_vector():
    provider = DeterministicEmbeddingProvider()
    gateway = EmbeddingGateway(_settings(), provider)

    result = await gateway.embed("memory_type=NOTE\ncontent=passport in drawer")

    assert len(result.vector) == MEMORY_EMBEDDING_DIMENSIONS
    assert result.provenance.provider == "deterministic"
    assert result.provenance.model == MEMORY_EMBEDDING_MODEL
    assert provider.requests == [
        EmbeddingRequest(
            text="memory_type=NOTE\ncontent=passport in drawer",
            model=MEMORY_EMBEDDING_MODEL,
            dimensions=MEMORY_EMBEDDING_DIMENSIONS,
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("vector", "expected"),
    [
        ([0.1], "EMBEDDING_VECTOR_DIMENSION_MISMATCH"),
        (
            [0.1] * (MEMORY_EMBEDDING_DIMENSIONS + 1),
            "EMBEDDING_VECTOR_DIMENSION_MISMATCH",
        ),
        (
            [0.1] * (MEMORY_EMBEDDING_DIMENSIONS - 1) + [float("nan")],
            "EMBEDDING_VECTOR_NON_FINITE",
        ),
        (
            [0.1] * (MEMORY_EMBEDDING_DIMENSIONS - 1) + [float("inf")],
            "EMBEDDING_VECTOR_NON_FINITE",
        ),
        (
            [0.1] * (MEMORY_EMBEDDING_DIMENSIONS - 1) + [True],
            "EMBEDDING_PROVIDER_INVALID_RESPONSE",
        ),
    ],
)
async def test_embedding_vector_validation_fails_closed(vector, expected):
    gateway = EmbeddingGateway(
        _settings(),
        DeterministicEmbeddingProvider(vector=vector),
    )

    with pytest.raises(EmbeddingGatewayError) as caught:
        await gateway.embed("memory_type=NOTE\ncontent=test")
    assert caught.value.code == expected


class _WrongModelProvider:
    async def embed(self, request: EmbeddingRequest) -> EmbeddingProviderResult:
        return EmbeddingProviderResult(
            vector=[0.01] * request.dimensions,
            provider="fixture",
            model="wrong-model",
        )


class _SlowProvider:
    async def embed(self, request: EmbeddingRequest) -> EmbeddingProviderResult:
        await asyncio.sleep(2)
        return EmbeddingProviderResult(
            vector=[0.01] * request.dimensions,
            provider="fixture",
            model=request.model,
        )


@pytest.mark.asyncio
async def test_model_mismatch_and_timeout_fail_closed():
    with pytest.raises(EmbeddingGatewayError) as wrong_model:
        await EmbeddingGateway(_settings(), _WrongModelProvider()).embed("safe text")
    assert wrong_model.value.code == "EMBEDDING_PROVIDER_MODEL_MISMATCH"

    with pytest.raises(EmbeddingGatewayError) as timeout:
        await EmbeddingGateway(_settings(), _SlowProvider()).embed("safe text")
    assert timeout.value.code == "EMBEDDING_PROVIDER_TIMEOUT"


@pytest.mark.asyncio
async def test_openai_adapter_sends_only_server_embedding_contract():
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            headers={"x-request-id": "req-embedding-test"},
            json={
                "object": "list",
                "model": MEMORY_EMBEDDING_MODEL,
                "data": [
                    {
                        "object": "embedding",
                        "index": 0,
                        "embedding": [0.002] * MEMORY_EMBEDDING_DIMENSIONS,
                    }
                ],
            },
        )

    settings = _settings(
        embedding_provider="openai",
        embedding_api_key="server-only-key",
    )
    gateway = build_embedding_gateway(
        settings,
        transport=httpx.MockTransport(handler),
    )
    result = await gateway.embed("memory_type=NOTE\ntitle=t\ncontent=c")

    assert seen["authorization"] == "Bearer server-only-key"
    assert seen["body"] == {
        "model": MEMORY_EMBEDDING_MODEL,
        "input": "memory_type=NOTE\ntitle=t\ncontent=c",
        "dimensions": MEMORY_EMBEDDING_DIMENSIONS,
        "encoding_format": "float",
    }
    assert result.provenance.provider_request_id == "req-embedding-test"
    assert all(math.isfinite(value) for value in result.vector)


def test_embedding_configuration_policy_is_explicit_and_fail_closed():
    with pytest.raises(ValidationError):
        _settings(embedding_model="other-model")
    with pytest.raises(ValidationError):
        _settings(embedding_dimensions=3072)
    with pytest.raises(ValidationError):
        _settings(embedding_provider="openai", embedding_api_key="")
