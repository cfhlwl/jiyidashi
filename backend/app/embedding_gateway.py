from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import httpx

from app.core.config import Settings, get_settings


class EmbeddingGatewayError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class EmbeddingRequest:
    text: str
    model: str
    dimensions: int


@dataclass(frozen=True)
class EmbeddingProviderResult:
    vector: object
    provider: str
    model: str
    provider_request_id: str | None = None


@dataclass(frozen=True)
class EmbeddingProvenance:
    provider: str
    model: str
    provider_request_id: str | None


@dataclass(frozen=True)
class EmbeddingInference:
    vector: tuple[float, ...]
    provenance: EmbeddingProvenance


class EmbeddingProvider(Protocol):
    async def embed(self, request: EmbeddingRequest) -> EmbeddingProviderResult: ...


class DisabledEmbeddingProvider:
    async def embed(self, request: EmbeddingRequest) -> EmbeddingProviderResult:
        del request
        raise EmbeddingGatewayError("EMBEDDING_PROVIDER_UNAVAILABLE")


class DeterministicEmbeddingProvider:
    """Test provider with stable output and captured server-owned input."""

    def __init__(
        self,
        vector: object | None = None,
        *,
        provider: str = "deterministic",
        model: str | None = None,
        provider_request_id: str | None = "deterministic-request",
    ):
        self.vector = vector
        self.provider = provider
        self.model = model
        self.provider_request_id = provider_request_id
        self.requests: list[EmbeddingRequest] = []

    async def embed(self, request: EmbeddingRequest) -> EmbeddingProviderResult:
        self.requests.append(request)
        vector = self.vector
        if vector is None:
            vector = [0.001] * request.dimensions
        return EmbeddingProviderResult(
            vector=vector,
            provider=self.provider,
            model=self.model or request.model,
            provider_request_id=self.provider_request_id,
        )


class OpenAIEmbeddingProvider:
    """Server-only OpenAI embeddings adapter; credentials never leave this process."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._settings = settings
        self._transport = transport

    async def embed(self, request: EmbeddingRequest) -> EmbeddingProviderResult:
        headers = {
            "Authorization": f"Bearer {self._settings.embedding_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": request.model,
            "input": request.text,
            "dimensions": request.dimensions,
            "encoding_format": "float",
        }
        try:
            async with httpx.AsyncClient(
                base_url=f"{self._settings.embedding_base_url.rstrip('/')}/",
                headers=headers,
                transport=self._transport,
            ) as client:
                response = await client.post("embeddings", json=payload)
        except httpx.TimeoutException as exc:
            raise EmbeddingGatewayError("EMBEDDING_PROVIDER_TIMEOUT") from exc
        except httpx.RequestError as exc:
            raise EmbeddingGatewayError("EMBEDDING_PROVIDER_UNAVAILABLE") from exc

        if response.status_code >= 400:
            raise EmbeddingGatewayError("EMBEDDING_PROVIDER_FAILED")

        try:
            body = response.json()
        except ValueError as exc:
            raise EmbeddingGatewayError("EMBEDDING_PROVIDER_INVALID_RESPONSE") from exc
        if not isinstance(body, dict):
            raise EmbeddingGatewayError("EMBEDDING_PROVIDER_INVALID_RESPONSE")

        data = body.get("data")
        model = body.get("model")
        if not isinstance(data, list) or len(data) != 1 or not isinstance(model, str):
            raise EmbeddingGatewayError("EMBEDDING_PROVIDER_INVALID_RESPONSE")
        item = data[0]
        if not isinstance(item, dict) or item.get("index") not in (None, 0):
            raise EmbeddingGatewayError("EMBEDDING_PROVIDER_INVALID_RESPONSE")

        provider_request_id = response.headers.get("x-request-id")
        if provider_request_id is None:
            raw_id = body.get("id")
            provider_request_id = raw_id if isinstance(raw_id, str) else None
        return EmbeddingProviderResult(
            vector=item.get("embedding"),
            provider="openai",
            model=model,
            provider_request_id=provider_request_id,
        )


class EmbeddingGateway:
    def __init__(self, settings: Settings, provider: EmbeddingProvider):
        self._settings = settings
        self._provider = provider

    @property
    def model(self) -> str:
        return self._settings.embedding_model

    @property
    def dimensions(self) -> int:
        return self._settings.embedding_dimensions

    async def embed(self, text: str) -> EmbeddingInference:
        if not isinstance(text, str) or not text.strip():
            raise EmbeddingGatewayError("EMBEDDING_INPUT_EMPTY")
        if len(text) > self._settings.embedding_max_input_chars:
            raise EmbeddingGatewayError("EMBEDDING_INPUT_TOO_LARGE")

        request = EmbeddingRequest(
            text=text,
            model=self.model,
            dimensions=self.dimensions,
        )
        try:
            result = await asyncio.wait_for(
                self._provider.embed(request),
                timeout=self._settings.embedding_timeout_seconds,
            )
        except TimeoutError as exc:
            raise EmbeddingGatewayError("EMBEDDING_PROVIDER_TIMEOUT") from exc

        if not isinstance(result, EmbeddingProviderResult):
            raise EmbeddingGatewayError("EMBEDDING_PROVIDER_INVALID_RESPONSE")
        provider = _required_text(result.provider)
        model = _required_text(result.model)
        if model != request.model:
            raise EmbeddingGatewayError("EMBEDDING_PROVIDER_MODEL_MISMATCH")

        provider_request_id = result.provider_request_id
        if provider_request_id is not None:
            provider_request_id = _required_text(provider_request_id)
        vector = _validate_vector(result.vector, request.dimensions)
        return EmbeddingInference(
            vector=vector,
            provenance=EmbeddingProvenance(
                provider=provider,
                model=model,
                provider_request_id=provider_request_id,
            ),
        )


def _required_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EmbeddingGatewayError("EMBEDDING_PROVIDER_INVALID_RESPONSE")
    return value.strip()


def _validate_vector(value: object, dimensions: int) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != dimensions:
        raise EmbeddingGatewayError("EMBEDDING_VECTOR_DIMENSION_MISMATCH")

    normalized: list[float] = []
    for component in value:
        if isinstance(component, bool) or not isinstance(component, (int, float)):
            raise EmbeddingGatewayError("EMBEDDING_PROVIDER_INVALID_RESPONSE")
        number = float(component)
        if not math.isfinite(number):
            raise EmbeddingGatewayError("EMBEDDING_VECTOR_NON_FINITE")
        normalized.append(number)
    return tuple(normalized)


def build_embedding_gateway(
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> EmbeddingGateway:
    if settings.embedding_provider == "disabled":
        provider: EmbeddingProvider = DisabledEmbeddingProvider()
    elif settings.embedding_provider == "openai":
        provider = OpenAIEmbeddingProvider(settings, transport=transport)
    else:
        raise EmbeddingGatewayError("EMBEDDING_PROVIDER_UNAVAILABLE")
    return EmbeddingGateway(settings, provider)


@lru_cache
def get_embedding_gateway() -> EmbeddingGateway:
    return build_embedding_gateway(get_settings())
