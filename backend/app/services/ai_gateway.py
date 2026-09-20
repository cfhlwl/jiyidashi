from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Literal, Protocol
from uuid import uuid4

import httpx

from app.core.config import Settings, get_settings

_PURPOSE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


class AIGatewayError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class AITransportError(AIGatewayError):
    pass


class AIProviderError(AIGatewayError):
    def __init__(
        self,
        code: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
    ):
        super().__init__(code, retryable=retryable)
        self.status_code = status_code


class AIMalformedResponseError(AIGatewayError):
    pass


class AIPolicyError(AIGatewayError):
    pass


# Stage 3 模型调用只能穿过本模块。这里刻意没有数据库依赖：
# Gateway 只产生 inference + provenance，不能把模型输出升级成可信 Memory/Evidence。
@dataclass(frozen=True)
class AIInferenceRequest:
    purpose: str
    system_instruction: str
    input_text: str
    max_output_tokens: int | None = None


@dataclass(frozen=True)
class AIProviderResult:
    output_text: str
    provider: str
    model: str
    provider_request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class AIUsage:
    input_tokens: int | None
    output_tokens: int | None


@dataclass(frozen=True)
class AIProvenance:
    gateway_request_id: str
    purpose: str
    provider_request_id: str | None
    provider: str
    model: str


@dataclass(frozen=True)
class AIInferenceResult:
    output_text: str
    provenance: AIProvenance
    usage: AIUsage
    trust_class: Literal["inference"] = "inference"


class AIProvider(Protocol):
    async def infer(self, request: AIInferenceRequest) -> AIProviderResult: ...


class DisabledAIProvider:
    async def infer(self, request: AIInferenceRequest) -> AIProviderResult:
        del request
        raise AIProviderError("AI_PROVIDER_UNAVAILABLE")


class DeterministicAIProvider:
    """Deterministic provider seam for gateway tests and future service tests."""

    def __init__(
        self,
        *,
        output_text: str = "deterministic inference",
        provider: str = "deterministic",
        model: str = "fixture",
    ):
        self.output_text = output_text
        self.provider = provider
        self.model = model
        self.requests: list[AIInferenceRequest] = []

    async def infer(self, request: AIInferenceRequest) -> AIProviderResult:
        self.requests.append(request)
        return AIProviderResult(
            output_text=self.output_text,
            provider=self.provider,
            model=self.model,
            provider_request_id="deterministic-request",
        )


class OpenAIResponsesProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._settings = settings
        # Transport injection is the only network test seam. Production uses httpx's
        # real transport; tests can verify Authorization/body/error mapping without I/O.
        self._transport = transport

    async def infer(self, request: AIInferenceRequest) -> AIProviderResult:
        endpoint = f"{self._settings.ai_base_url.rstrip('/')}/responses"
        body = {
            "model": self._settings.ai_model,
            "instructions": request.system_instruction,
            "input": request.input_text,
            "max_output_tokens": request.max_output_tokens,
            "store": False,
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._settings.ai_timeout_seconds,
                transport=self._transport,
            ) as client:
                # httpx timeout protects individual network phases; asyncio.timeout adds
                # an end-to-end wall-clock boundary so a provider cannot keep a request alive
                # indefinitely by making incremental progress.
                async with asyncio.timeout(self._settings.ai_timeout_seconds):
                    response = await client.post(
                        endpoint,
                        headers={
                            "Authorization": f"Bearer {self._settings.ai_api_key}",
                            "Content-Type": "application/json",
                        },
                        json=body,
                    )
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise AITransportError("AI_GATEWAY_TIMEOUT", retryable=True) from exc
        except httpx.RequestError as exc:
            raise AITransportError("AI_GATEWAY_TRANSPORT_ERROR", retryable=True) from exc

        # Provider error bodies are intentionally discarded. They may contain vendor
        # internals or prompt fragments and must not cross the trust boundary.
        if response.status_code < 200 or response.status_code >= 300:
            retryable = response.status_code == 429 or response.status_code >= 500
            raise AIProviderError(
                "AI_PROVIDER_FAILED",
                retryable=retryable,
                status_code=response.status_code,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise AIMalformedResponseError("AI_PROVIDER_INVALID_RESPONSE") from exc
        if not isinstance(payload, dict):
            raise AIMalformedResponseError("AI_PROVIDER_INVALID_RESPONSE")

        status = payload.get("status")
        if status != "completed":
            if isinstance(status, str) and status in {
                "failed",
                "incomplete",
                "cancelled",
                "queued",
                "in_progress",
            }:
                raise AIProviderError("AI_PROVIDER_INCOMPLETE")
            raise AIMalformedResponseError("AI_PROVIDER_INVALID_RESPONSE")
        if payload.get("error") is not None or payload.get("incomplete_details") is not None:
            raise AIMalformedResponseError("AI_PROVIDER_INVALID_RESPONSE")

        provider_request_id = _required_string(payload.get("id"))
        model = _required_string(payload.get("model"))
        output_text = _extract_openai_output(payload.get("output"))
        input_tokens, output_tokens = _parse_openai_usage(payload.get("usage"))
        return AIProviderResult(
            output_text=output_text,
            provider="openai",
            model=model,
            provider_request_id=provider_request_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


class AIGateway:
    def __init__(self, settings: Settings, provider: AIProvider):
        self._settings = settings
        self._provider = provider

    async def infer(self, request: AIInferenceRequest) -> AIInferenceResult:
        validated = self._validate_request(request)
        # Cancellation intentionally propagates; it must never become a synthetic AI result.
        provider_result = await self._provider.infer(validated)
        checked = _validate_provider_result(provider_result)
        return AIInferenceResult(
            output_text=checked.output_text,
            provenance=AIProvenance(
                gateway_request_id=str(uuid4()),
                purpose=validated.purpose,
                provider_request_id=checked.provider_request_id,
                provider=checked.provider,
                model=checked.model,
            ),
            usage=AIUsage(
                input_tokens=checked.input_tokens,
                output_tokens=checked.output_tokens,
            ),
        )

    def _validate_request(self, request: AIInferenceRequest) -> AIInferenceRequest:
        purpose = request.purpose.strip()
        if not _PURPOSE_PATTERN.fullmatch(purpose):
            raise AIPolicyError("AI_REQUEST_PURPOSE_INVALID")
        if not request.system_instruction.strip() or not request.input_text.strip():
            raise AIPolicyError("AI_REQUEST_EMPTY")

        input_chars = len(request.system_instruction) + len(request.input_text)
        if input_chars > self._settings.ai_max_input_chars:
            raise AIPolicyError("AI_REQUEST_TOO_LARGE")

        max_output_tokens = request.max_output_tokens
        if max_output_tokens is None:
            max_output_tokens = self._settings.ai_max_output_tokens
        if (
            not isinstance(max_output_tokens, int)
            or isinstance(max_output_tokens, bool)
            or max_output_tokens < 1
            or max_output_tokens > self._settings.ai_max_output_tokens
        ):
            raise AIPolicyError("AI_MAX_OUTPUT_TOKENS_INVALID")

        return replace(
            request,
            purpose=purpose,
            max_output_tokens=max_output_tokens,
        )


def _required_string(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AIMalformedResponseError("AI_PROVIDER_INVALID_RESPONSE")
    return value.strip()


def _optional_non_negative_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AIMalformedResponseError("AI_PROVIDER_INVALID_RESPONSE")
    return value


def _parse_openai_usage(value: object) -> tuple[int | None, int | None]:
    if value is None:
        return None, None
    if not isinstance(value, dict):
        raise AIMalformedResponseError("AI_PROVIDER_INVALID_RESPONSE")
    return (
        _optional_non_negative_int(value.get("input_tokens")),
        _optional_non_negative_int(value.get("output_tokens")),
    )


def _extract_openai_output(value: object) -> str:
    if not isinstance(value, list):
        raise AIMalformedResponseError("AI_PROVIDER_INVALID_RESPONSE")

    text_parts: list[str] = []
    refusal_seen = False
    for item in value:
        if not isinstance(item, dict):
            raise AIMalformedResponseError("AI_PROVIDER_INVALID_RESPONSE")
        if item.get("type") != "message" or item.get("role") != "assistant":
            continue
        if item.get("status") != "completed":
            raise AIMalformedResponseError("AI_PROVIDER_INVALID_RESPONSE")
        content = item.get("content")
        if not isinstance(content, list):
            raise AIMalformedResponseError("AI_PROVIDER_INVALID_RESPONSE")
        for part in content:
            if not isinstance(part, dict):
                raise AIMalformedResponseError("AI_PROVIDER_INVALID_RESPONSE")
            part_type = part.get("type")
            if part_type == "refusal":
                refusal_seen = True
                continue
            if part_type != "output_text":
                raise AIMalformedResponseError("AI_PROVIDER_INVALID_RESPONSE")
            text = part.get("text")
            if not isinstance(text, str):
                raise AIMalformedResponseError("AI_PROVIDER_INVALID_RESPONSE")
            if text.strip():
                text_parts.append(text.strip())

    # A refusal anywhere in the assistant message dominates any coexisting text. This
    # avoids exposing partial provider output from an internally inconsistent response.
    if refusal_seen:
        raise AIPolicyError("AI_PROVIDER_REFUSAL")
    if text_parts:
        return "\n".join(text_parts)
    raise AIMalformedResponseError("AI_PROVIDER_INVALID_RESPONSE")


def _validate_provider_result(result: object) -> AIProviderResult:
    if not isinstance(result, AIProviderResult):
        raise AIMalformedResponseError("AI_PROVIDER_INVALID_RESPONSE")
    output_text = _required_string(result.output_text)
    provider = _required_string(result.provider)
    model = _required_string(result.model)
    provider_request_id = result.provider_request_id
    if provider_request_id is not None:
        provider_request_id = _required_string(provider_request_id)
    input_tokens = _optional_non_negative_int(result.input_tokens)
    output_tokens = _optional_non_negative_int(result.output_tokens)
    return AIProviderResult(
        output_text=output_text,
        provider=provider,
        model=model,
        provider_request_id=provider_request_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def build_ai_gateway(
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AIGateway:
    if settings.ai_provider == "disabled":
        provider: AIProvider = DisabledAIProvider()
    elif settings.ai_provider == "openai":
        provider = OpenAIResponsesProvider(settings, transport=transport)
    else:
        # Settings rejects unknown providers; this remains as a fail-closed defense
        # for non-standard Settings objects constructed by tests/tooling.
        raise AIProviderError("AI_PROVIDER_UNAVAILABLE")
    return AIGateway(settings, provider)


@lru_cache
def get_ai_gateway() -> AIGateway:
    return build_ai_gateway(get_settings())
