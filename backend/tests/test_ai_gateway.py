import asyncio
import json

import httpx
import pytest

from app.core.config import Settings
from app.services.ai_gateway import (
    AIGateway,
    AIInferenceRequest,
    AIMalformedResponseError,
    AIPolicyError,
    AIProviderError,
    AIProviderResult,
    AITransportError,
    DeterministicAIProvider,
    OpenAIResponsesProvider,
    build_ai_gateway,
)


def _settings(**overrides) -> Settings:
    values = {
        "app_env": "test",
        "ai_provider": "openai",
        "ai_api_key": "test-ai-key",
        "ai_model": "test-model",
        "ai_base_url": "https://api.openai.test/v1",
        "ai_timeout_seconds": 5.0,
        "ai_max_input_chars": 1000,
        "ai_max_output_tokens": 256,
    }
    values.update(overrides)
    return Settings(**values)


def _request(**overrides) -> AIInferenceRequest:
    values = {
        "purpose": "memory.normalize",
        "system_instruction": "Return only an inference; never invent user facts.",
        "input_text": "用户输入",
        "max_output_tokens": 128,
    }
    values.update(overrides)
    return AIInferenceRequest(**values)


@pytest.mark.asyncio
async def test_gateway_returns_inference_with_provenance_and_resolved_limits():
    provider = DeterministicAIProvider(output_text="结构化推断")
    gateway = AIGateway(_settings(), provider)

    result = await gateway.infer(_request(max_output_tokens=None))

    assert result.output_text == "结构化推断"
    assert result.trust_class == "inference"
    assert result.provenance.purpose == "memory.normalize"
    assert result.provenance.provider == "deterministic"
    assert result.provenance.model == "fixture"
    assert result.provenance.provider_request_id == "deterministic-request"
    assert result.provenance.gateway_request_id
    assert provider.requests[0].max_output_tokens == 256


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("inference_request", "code"),
    [
        (_request(purpose="Bad Purpose"), "AI_REQUEST_PURPOSE_INVALID"),
        (_request(system_instruction="   "), "AI_REQUEST_EMPTY"),
        (_request(input_text=""), "AI_REQUEST_EMPTY"),
        (_request(max_output_tokens=0), "AI_MAX_OUTPUT_TOKENS_INVALID"),
        (_request(max_output_tokens=True), "AI_MAX_OUTPUT_TOKENS_INVALID"),
        (_request(max_output_tokens=257), "AI_MAX_OUTPUT_TOKENS_INVALID"),
    ],
)
async def test_gateway_policy_rejects_invalid_requests_before_provider(
    inference_request, code
):
    provider = DeterministicAIProvider()
    gateway = AIGateway(_settings(), provider)

    with pytest.raises(AIPolicyError, match=code):
        await gateway.infer(inference_request)

    assert provider.requests == []


@pytest.mark.asyncio
async def test_gateway_rejects_oversized_input_before_provider():
    provider = DeterministicAIProvider()
    gateway = AIGateway(_settings(ai_max_input_chars=10), provider)

    with pytest.raises(AIPolicyError, match="AI_REQUEST_TOO_LARGE"):
        await gateway.infer(_request(system_instruction="123456", input_text="12345"))

    assert provider.requests == []


@pytest.mark.asyncio
async def test_disabled_gateway_fails_closed():
    gateway = build_ai_gateway(_settings(ai_provider="disabled"))

    with pytest.raises(AIProviderError, match="AI_PROVIDER_UNAVAILABLE"):
        await gateway.infer(_request())


@pytest.mark.asyncio
async def test_openai_responses_adapter_sends_server_only_request_and_parses_provenance():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://api.openai.test/v1/responses"
        assert request.headers["authorization"] == "Bearer test-ai-key"
        body = json.loads(request.content)
        assert body == {
            "model": "test-model",
            "instructions": "Return only an inference; never invent user facts.",
            "input": "用户输入",
            "max_output_tokens": 128,
            "store": False,
        }
        return httpx.Response(
            200,
            json={
                "id": "resp_test_123",
                "model": "test-model-2026-09",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": "第一段"},
                            {"type": "output_text", "text": "第二段"},
                        ],
                    }
                ],
                "usage": {"input_tokens": 21, "output_tokens": 8},
            },
            request=request,
        )

    provider = OpenAIResponsesProvider(
        _settings(),
        transport=httpx.MockTransport(handler),
    )
    result = await provider.infer(_request())

    assert result.output_text == "第一段\n第二段"
    assert result.provider == "openai"
    assert result.model == "test-model-2026-09"
    assert result.provider_request_id == "resp_test_123"
    assert result.input_tokens == 21
    assert result.output_tokens == 8


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 401, 403, 429, 500, 503])
async def test_openai_responses_adapter_maps_provider_http_failures(status_code):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={"error": {"message": "must not be exposed"}},
            request=request,
        )

    provider = OpenAIResponsesProvider(
        _settings(),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(AIProviderError) as exc_info:
        await provider.infer(_request())

    assert exc_info.value.code == "AI_PROVIDER_FAILED"
    assert exc_info.value.status_code == status_code
    assert exc_info.value.retryable is (status_code == 429 or status_code >= 500)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"id": "resp", "model": "m", "status": "completed", "output": "bad"},
        {
            "id": "resp",
            "model": "m",
            "status": "completed",
            "output": [{"type": "message", "role": "assistant", "content": []}],
        },
        {
            "id": "resp",
            "model": "m",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "ok"}],
                }
            ],
            "usage": {"input_tokens": -1},
        },
    ],
)
async def test_openai_responses_adapter_rejects_malformed_200(payload):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    provider = OpenAIResponsesProvider(
        _settings(),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(
        AIMalformedResponseError,
        match="AI_PROVIDER_INVALID_RESPONSE",
    ):
        await provider.infer(_request())


@pytest.mark.asyncio
async def test_openai_responses_adapter_maps_refusal_to_policy_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp_refusal",
                "model": "test-model",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "refusal", "refusal": "declined"}],
                    }
                ],
            },
            request=request,
        )

    provider = OpenAIResponsesProvider(
        _settings(),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(AIPolicyError, match="AI_PROVIDER_REFUSAL"):
        await provider.infer(_request())


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", "incomplete"])
async def test_openai_responses_adapter_fails_closed_on_non_completed_status(status):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"id": "resp", "model": "m", "status": status, "output": []},
            request=request,
        )

    provider = OpenAIResponsesProvider(
        _settings(),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(AIProviderError, match="AI_PROVIDER_INCOMPLETE"):
        await provider.infer(_request())


@pytest.mark.asyncio
async def test_openai_responses_adapter_maps_timeout_and_transport_errors():
    async def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    timeout_provider = OpenAIResponsesProvider(
        _settings(),
        transport=httpx.MockTransport(timeout_handler),
    )
    with pytest.raises(AITransportError) as timeout:
        await timeout_provider.infer(_request())
    assert timeout.value.code == "AI_GATEWAY_TIMEOUT"
    assert timeout.value.retryable is True

    async def connect_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    connect_provider = OpenAIResponsesProvider(
        _settings(),
        transport=httpx.MockTransport(connect_handler),
    )
    with pytest.raises(AITransportError) as transport:
        await connect_provider.infer(_request())
    assert transport.value.code == "AI_GATEWAY_TRANSPORT_ERROR"
    assert transport.value.retryable is True


@pytest.mark.asyncio
async def test_gateway_enforces_end_to_end_wall_clock_timeout():
    async def slow_handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(2)
        return httpx.Response(200, json={}, request=request)

    provider = OpenAIResponsesProvider(
        _settings(ai_timeout_seconds=1.0),
        transport=httpx.MockTransport(slow_handler),
    )
    with pytest.raises(AITransportError) as timeout:
        await provider.infer(_request())

    assert timeout.value.code == "AI_GATEWAY_TIMEOUT"
    assert timeout.value.retryable is True


@pytest.mark.asyncio
async def test_openai_responses_adapter_refusal_dominates_mixed_output():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp_mixed",
                "model": "test-model",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": "partial text"},
                            {"type": "refusal", "refusal": "declined"},
                        ],
                    }
                ],
            },
            request=request,
        )

    provider = OpenAIResponsesProvider(
        _settings(),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(AIPolicyError, match="AI_PROVIDER_REFUSAL"):
        await provider.infer(_request())


@pytest.mark.asyncio
async def test_openai_responses_adapter_rejects_incomplete_output_message():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp_bad_message",
                "model": "test-model",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "status": "incomplete",
                        "content": [{"type": "output_text", "text": "partial"}],
                    }
                ],
            },
            request=request,
        )

    provider = OpenAIResponsesProvider(
        _settings(),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(
        AIMalformedResponseError,
        match="AI_PROVIDER_INVALID_RESPONSE",
    ):
        await provider.infer(_request())


@pytest.mark.asyncio
async def test_gateway_does_not_swallow_caller_cancellation():
    started = asyncio.Event()

    class BlockingProvider:
        async def infer(self, request: AIInferenceRequest) -> AIProviderResult:
            del request
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    gateway = AIGateway(_settings(), BlockingProvider())
    task = asyncio.create_task(gateway.infer(_request()))
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_gateway_revalidates_provider_result_before_exposing_inference():
    class MalformedProvider:
        async def infer(self, request: AIInferenceRequest) -> AIProviderResult:
            del request
            return AIProviderResult(
                output_text="",
                provider="provider",
                model="model",
            )

    gateway = AIGateway(_settings(), MalformedProvider())
    with pytest.raises(
        AIMalformedResponseError,
        match="AI_PROVIDER_INVALID_RESPONSE",
    ):
        await gateway.infer(_request())


def test_ai_provider_configuration_is_fail_closed():
    with pytest.raises(ValueError, match="AI_PROVIDER must be disabled or openai"):
        _settings(ai_provider="unknown")

    with pytest.raises(ValueError, match="AI_API_KEY and AI_MODEL"):
        _settings(ai_api_key="")

    with pytest.raises(ValueError, match="AI_BASE_URL must be an absolute URL"):
        _settings(ai_base_url="not-a-url")

    with pytest.raises(ValueError, match="AI_BASE_URL must use HTTPS in production"):
        Settings(
            app_env="production",
            jwt_secret="x" * 32,
            enable_dev_auth=False,
            ai_provider="openai",
            ai_api_key="secret",
            ai_model="model",
            ai_base_url="http://provider.test/v1",
        )
