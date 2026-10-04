from __future__ import annotations

import asyncio
import base64
import re
from dataclasses import dataclass, replace
from time import perf_counter
from typing import Literal, Protocol
from uuid import UUID, uuid4

import httpx
from sqlalchemy.orm import Session

from app.admin_models import ProviderService
from app.core.config import Settings
from app.core.observability import emit_operational_event
from app.services.concurrency_guard import (
    ConcurrencyRejected,
    claim_provider_permit,
    release_permit,
)
from app.services.entitlement_service import (
    EntitlementError,
    finalize_ai_usage,
    reserve_ai_provider_request,
)
from app.services.provider_config_service import (
    ProviderRuntimeConfigError,
    get_runtime_provider_settings,
    provider_runtime_fingerprint,
    record_provider_runtime_evidence,
)

_PURPOSE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_POSTGRES_BIGINT_MAX = 9_223_372_036_854_775_807
_PROVIDER_REQUEST_ID_MAX_LENGTH = 255


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


class AIEntitlementError(AIGatewayError):
    def __init__(self, code: str, *, status_code: int):
        super().__init__(code, retryable=status_code >= 500)
        self.status_code = status_code


# Stage 3 模型调用只能穿过本模块。这里刻意没有数据库依赖：
# Gateway 只产生 inference + provenance，不能把模型输出升级成可信 Memory/Evidence。
@dataclass(frozen=True)
class AIInferenceRequest:
    purpose: str
    system_instruction: str
    input_text: str
    max_output_tokens: int | None = None


@dataclass(frozen=True)
class AIImageInferenceRequest:
    purpose: str
    system_instruction: str
    input_text: str
    image_bytes: bytes
    content_type: str
    detail: Literal["auto", "low", "high"] = "high"
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

    async def infer_image(self, request: AIImageInferenceRequest) -> AIProviderResult: ...


class DisabledAIProvider:
    async def infer(self, request: AIInferenceRequest) -> AIProviderResult:
        del request
        raise AIProviderError("AI_PROVIDER_UNAVAILABLE")

    async def infer_image(self, request: AIImageInferenceRequest) -> AIProviderResult:
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
        self.image_requests: list[AIImageInferenceRequest] = []

    async def infer(self, request: AIInferenceRequest) -> AIProviderResult:
        self.requests.append(request)
        return AIProviderResult(
            output_text=self.output_text,
            provider=self.provider,
            model=self.model,
            provider_request_id="deterministic-request",
        )

    async def infer_image(self, request: AIImageInferenceRequest) -> AIProviderResult:
        self.image_requests.append(request)
        return AIProviderResult(
            output_text=self.output_text,
            provider=self.provider,
            model=self.model,
            provider_request_id="deterministic-image-request",
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

    async def infer_image(self, request: AIImageInferenceRequest) -> AIProviderResult:
        # [人工注释][S3-006] 图片字节只在服务端 Gateway 内编码并发送给 provider。
        # feature/API 层没有 vendor URL/key；store=false 防止 provider 侧持久化请求内容。
        encoded = base64.b64encode(request.image_bytes).decode("ascii")
        endpoint = f"{self._settings.ai_base_url.rstrip('/')}/responses"
        body = {
            "model": self._settings.ai_model,
            "instructions": request.system_instruction,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": request.input_text},
                        {
                            "type": "input_image",
                            "image_url": (
                                f"data:{request.content_type};base64,{encoded}"
                            ),
                            "detail": request.detail,
                        },
                    ],
                }
            ],
            "max_output_tokens": request.max_output_tokens,
            "store": False,
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._settings.ai_timeout_seconds,
                transport=self._transport,
            ) as client:
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
        self._config_fingerprint = provider_runtime_fingerprint(
            settings,
            ProviderService.AI,
        )

    async def infer(
        self,
        request: AIInferenceRequest,
        *,
        db: Session,
        actor_user_id: UUID,
    ) -> AIInferenceResult:
        gateway_request_uuid = uuid4()
        gateway_request_id = str(gateway_request_uuid)
        started = perf_counter()
        validated: AIInferenceRequest | None = None
        provider_started = False
        provider_completed = False
        try:
            validated = self._validate_request(request)
            try:
                reserve_ai_provider_request(
                    db.get_bind(),
                    user_id=actor_user_id,
                    gateway_request_id=gateway_request_uuid,
                    purpose=validated.purpose,
                    settings=self._settings,
                )
            except EntitlementError as exc:
                raise AIEntitlementError(
                    exc.code,
                    status_code=exc.status_code,
                ) from exc

            # Reservation is committed before provider I/O. SEC-016 then claims a
            # cross-worker permit in its own short transaction; no DB lock is held while
            # awaiting the paid provider.
            try:
                permit = claim_provider_permit(
                    db.get_bind(),
                    service_class="AI",
                    user_id=actor_user_id,
                    settings=self._settings,
                )
            except ConcurrencyRejected as exc:
                raise AIEntitlementError(exc.code, status_code=429) from exc
            provider_started = True
            try:
                provider_result = await self._provider.infer(validated)
            finally:
                release_permit(
                    db.get_bind(),
                    permit=permit,
                    settings=self._settings,
                )
            checked = _validate_provider_result(provider_result)
            provider_completed = True
            record_provider_runtime_evidence(
                db.get_bind(),
                service=ProviderService.AI,
                config_fingerprint=self._config_fingerprint,
                succeeded=True,
            )
            try:
                finalize_ai_usage(
                    db.get_bind(),
                    user_id=actor_user_id,
                    gateway_request_id=gateway_request_uuid,
                    provider_request_id=checked.provider_request_id,
                    input_tokens=checked.input_tokens,
                    output_tokens=checked.output_tokens,
                )
            except EntitlementError as exc:
                raise AIEntitlementError(
                    exc.code,
                    status_code=exc.status_code,
                ) from exc
        except AIGatewayError as exc:
            if provider_started and not provider_completed:
                record_provider_runtime_evidence(
                    db.get_bind(),
                    service=ProviderService.AI,
                    config_fingerprint=self._config_fingerprint,
                    succeeded=False,
                )
            emit_operational_event(
                event="ai.inference.failed",
                level="WARNING",
                gateway_request_id=gateway_request_id,
                purpose=None if validated is None else validated.purpose,
                provider=self._settings.ai_provider,
                model=self._settings.ai_model or None,
                latency_ms=(perf_counter() - started) * 1000,
                error_code=exc.code,
                retryable=exc.retryable,
            )
            raise

        emit_operational_event(
            event="ai.inference.completed",
            gateway_request_id=gateway_request_id,
            purpose=validated.purpose,
            provider=checked.provider,
            model=checked.model,
            provider_request_id=checked.provider_request_id,
            latency_ms=(perf_counter() - started) * 1000,
            input_tokens=checked.input_tokens,
            output_tokens=checked.output_tokens,
        )
        return AIInferenceResult(
            output_text=checked.output_text,
            provenance=AIProvenance(
                gateway_request_id=gateway_request_id,
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

    async def infer_image(
        self,
        request: AIImageInferenceRequest,
        *,
        db: Session,
        actor_user_id: UUID,
    ) -> AIInferenceResult:
        gateway_request_uuid = uuid4()
        gateway_request_id = str(gateway_request_uuid)
        started = perf_counter()
        validated: AIImageInferenceRequest | None = None
        provider_started = False
        provider_completed = False
        try:
            validated = self._validate_image_request(request)
            try:
                reserve_ai_provider_request(
                    db.get_bind(),
                    user_id=actor_user_id,
                    gateway_request_id=gateway_request_uuid,
                    purpose=validated.purpose,
                    settings=self._settings,
                )
            except EntitlementError as exc:
                raise AIEntitlementError(
                    exc.code,
                    status_code=exc.status_code,
                ) from exc

            # The Gateway owns the wall-clock bound even for future image adapters that
            # do not implement their own HTTP timeout. Reservation is already durable.
            try:
                permit = claim_provider_permit(
                    db.get_bind(),
                    service_class="AI",
                    user_id=actor_user_id,
                    settings=self._settings,
                )
            except ConcurrencyRejected as exc:
                raise AIEntitlementError(exc.code, status_code=429) from exc
            try:
                async with asyncio.timeout(self._settings.ai_timeout_seconds):
                    provider_started = True
                    provider_result = await self._provider.infer_image(validated)
            except TimeoutError as exc:
                raise AITransportError("AI_GATEWAY_TIMEOUT", retryable=True) from exc
            finally:
                release_permit(
                    db.get_bind(),
                    permit=permit,
                    settings=self._settings,
                )
            checked = _validate_provider_result(provider_result)
            provider_completed = True
            record_provider_runtime_evidence(
                db.get_bind(),
                service=ProviderService.AI,
                config_fingerprint=self._config_fingerprint,
                succeeded=True,
            )
            try:
                finalize_ai_usage(
                    db.get_bind(),
                    user_id=actor_user_id,
                    gateway_request_id=gateway_request_uuid,
                    provider_request_id=checked.provider_request_id,
                    input_tokens=checked.input_tokens,
                    output_tokens=checked.output_tokens,
                )
            except EntitlementError as exc:
                raise AIEntitlementError(
                    exc.code,
                    status_code=exc.status_code,
                ) from exc
        except AIGatewayError as exc:
            if provider_started and not provider_completed:
                record_provider_runtime_evidence(
                    db.get_bind(),
                    service=ProviderService.AI,
                    config_fingerprint=self._config_fingerprint,
                    succeeded=False,
                )
            emit_operational_event(
                event="ai.inference.failed",
                level="WARNING",
                gateway_request_id=gateway_request_id,
                purpose=None if validated is None else validated.purpose,
                provider=self._settings.ai_provider,
                model=self._settings.ai_model or None,
                latency_ms=(perf_counter() - started) * 1000,
                error_code=exc.code,
                retryable=exc.retryable,
            )
            raise

        emit_operational_event(
            event="ai.inference.completed",
            gateway_request_id=gateway_request_id,
            purpose=validated.purpose,
            provider=checked.provider,
            model=checked.model,
            provider_request_id=checked.provider_request_id,
            latency_ms=(perf_counter() - started) * 1000,
            input_tokens=checked.input_tokens,
            output_tokens=checked.output_tokens,
        )
        return AIInferenceResult(
            output_text=checked.output_text,
            provenance=AIProvenance(
                gateway_request_id=gateway_request_id,
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

    def _validate_image_request(
        self,
        request: AIImageInferenceRequest,
    ) -> AIImageInferenceRequest:
        purpose = request.purpose.strip()
        if not _PURPOSE_PATTERN.fullmatch(purpose):
            raise AIPolicyError("AI_REQUEST_PURPOSE_INVALID")
        if not request.system_instruction.strip() or not request.input_text.strip():
            raise AIPolicyError("AI_REQUEST_EMPTY")

        input_chars = len(request.system_instruction) + len(request.input_text)
        if input_chars > self._settings.ai_max_input_chars:
            raise AIPolicyError("AI_REQUEST_TOO_LARGE")

        if not isinstance(request.image_bytes, bytes) or not request.image_bytes:
            raise AIPolicyError("AI_IMAGE_EMPTY")
        if len(request.image_bytes) > self._settings.media_max_image_bytes:
            raise AIPolicyError("AI_IMAGE_TOO_LARGE")

        content_type = request.content_type.split(";", 1)[0].strip().lower()
        if content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise AIPolicyError("AI_IMAGE_TYPE_UNSUPPORTED")
        if request.detail not in {"auto", "low", "high"}:
            raise AIPolicyError("AI_IMAGE_DETAIL_INVALID")

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
            content_type=content_type,
            max_output_tokens=max_output_tokens,
        )


def _required_string(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AIMalformedResponseError("AI_PROVIDER_INVALID_RESPONSE")
    return value.strip()


def _optional_non_negative_int(value: object) -> int | None:
    if value is None:
        return None
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or value > _POSTGRES_BIGINT_MAX
    ):
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
        if len(provider_request_id) > _PROVIDER_REQUEST_ID_MAX_LENGTH:
            raise AIMalformedResponseError("AI_PROVIDER_INVALID_RESPONSE")
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


def get_ai_gateway() -> AIGateway:
    try:
        settings = get_runtime_provider_settings()
    except ProviderRuntimeConfigError as exc:
        raise AIProviderError("AI_PROVIDER_UNAVAILABLE") from exc
    return build_ai_gateway(settings)
