from math import log

import httpx
import pytest

from app.core.config import Settings
from app.services.asr import ASRProviderError, OpenAIASRProvider


def _settings() -> Settings:
    return Settings(
        app_env="test",
        asr_provider="openai",
        asr_api_key="test-asr-key",
        asr_model="gpt-4o-mini-transcribe",
        asr_base_url="https://api.openai.test/v1",
    )


def _provider(handler) -> OpenAIASRProvider:
    return OpenAIASRProvider(_settings(), transport=httpx.MockTransport(handler))


def test_openai_asr_adapter_builds_expected_multipart_and_parses_logprobs():
    # [人工注释][S1-PR18-FIX-003][S1-007] 不调用真实 OpenAI；MockTransport 直接验证
    # 生产 adapter 的 Authorization、multipart 字段、文件 MIME 与 logprobs 解析契约。
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://api.openai.test/v1/audio/transcriptions"
        assert request.headers["authorization"] == "Bearer test-asr-key"
        assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
        body = request.read()
        assert b'name="model"' in body
        assert b"gpt-4o-mini-transcribe" in body
        assert b'name="response_format"' in body
        assert b"json" in body
        assert b'name="include[]"' in body
        assert b"logprobs" in body
        assert b'name="file"; filename="voice.mp3"' in body
        assert b"Content-Type: audio/mpeg" in body
        assert b"ID3fixture-audio" in body
        return httpx.Response(
            200,
            json={
                "text": "明天下午复查",
                "logprobs": [
                    {"token": "明天", "logprob": log(0.90)},
                    {"token": "复查", "logprob": log(0.81)},
                ],
            },
        )

    result = _provider(handler).transcribe(
        b"ID3fixture-audio",
        content_type="audio/mpeg",
        filename="voice.mp3",
    )
    assert result.text == "明天下午复查"
    assert result.confidence == pytest.approx((0.90 * 0.81) ** 0.5)
    assert result.provider == "openai"
    assert result.model == "gpt-4o-mini-transcribe"


@pytest.mark.parametrize("status_code", [400, 401, 429, 500, 503])
def test_openai_asr_adapter_maps_http_failures(status_code: int):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": "not exposed"}, request=request)

    with pytest.raises(ASRProviderError, match="ASR_PROVIDER_FAILED"):
        _provider(handler).transcribe(
            b"ID3audio",
            content_type="audio/mpeg",
            filename="voice.mp3",
        )


def test_openai_asr_adapter_rejects_non_json_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json", request=request)

    with pytest.raises(ASRProviderError, match="ASR_PROVIDER_INVALID_RESPONSE"):
        _provider(handler).transcribe(
            b"ID3audio",
            content_type="audio/mpeg",
            filename="voice.mp3",
        )


def test_openai_asr_adapter_rejects_missing_logprobs():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"text": "有文字"}, request=request)

    with pytest.raises(ASRProviderError, match="ASR_CONFIDENCE_MISSING"):
        _provider(handler).transcribe(
            b"ID3audio",
            content_type="audio/mpeg",
            filename="voice.mp3",
        )


def test_openai_asr_adapter_rejects_empty_text():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"text": "   ", "logprobs": [{"token": "x", "logprob": -0.1}]},
            request=request,
        )

    with pytest.raises(ASRProviderError, match="ASR_EMPTY_RESULT"):
        _provider(handler).transcribe(
            b"ID3audio",
            content_type="audio/mpeg",
            filename="voice.mp3",
        )


def test_openai_asr_adapter_maps_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("provider timeout", request=request)

    with pytest.raises(ASRProviderError, match="ASR_TIMEOUT"):
        _provider(handler).transcribe(
            b"ID3audio",
            content_type="audio/mpeg",
            filename="voice.mp3",
        )


def test_openai_asr_adapter_maps_request_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("provider unavailable", request=request)

    with pytest.raises(ASRProviderError, match="ASR_PROVIDER_UNAVAILABLE"):
        _provider(handler).transcribe(
            b"ID3audio",
            content_type="audio/mpeg",
            filename="voice.mp3",
        )
