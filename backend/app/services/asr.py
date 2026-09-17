from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import httpx

from app.core.config import Settings, get_settings


# [人工注释][S1-007] ASR provider 是纯服务端可替换边界。客户端不接触模型密钥，
# 也不能提交 transcript/confidence；provider 返回值必须包含可验证置信信息才允许进入 Memory。
@dataclass(frozen=True)
class ASRResult:
    text: str
    confidence: float
    provider: str
    model: str


class ASRProviderError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ASRProvider(Protocol):
    def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str,
        filename: str | None,
    ) -> ASRResult: ...


class DisabledASRProvider:
    def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str,
        filename: str | None,
    ) -> ASRResult:
        del audio, content_type, filename
        raise ASRProviderError("ASR_PROVIDER_UNAVAILABLE")


def confidence_from_logprobs(entries: object) -> float:
    # [人工注释][S1-007] OpenAI transcription logprob 是服务端 provider 返回的 token
    # 概率证据；用几何平均聚合为 0..1 质量门禁，不接收客户端自报 confidence。
    if not isinstance(entries, list) or not entries:
        raise ASRProviderError("ASR_CONFIDENCE_MISSING")

    values: list[float] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        value = entry.get("logprob")
        if isinstance(value, int | float) and math.isfinite(float(value)):
            values.append(float(value))
    if not values:
        raise ASRProviderError("ASR_CONFIDENCE_MISSING")

    probability = math.exp(sum(values) / len(values))
    return max(0.0, min(1.0, probability))


class OpenAIASRProvider:
    def __init__(self, settings: Settings):
        self._settings = settings

    def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str,
        filename: str | None,
    ) -> ASRResult:
        # [人工注释][S1-007] 文件转写只由后端向 provider 发起；include[]=logprobs
        # 用于低置信 fail-closed。上游错误正文不向客户端透传，避免泄露供应商内部信息。
        endpoint = f"{self._settings.asr_base_url.rstrip('/')}/audio/transcriptions"
        try:
            with httpx.Client(timeout=self._settings.asr_timeout_seconds) as client:
                response = client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {self._settings.asr_api_key}"},
                    data={
                        "model": self._settings.asr_model,
                        "response_format": "json",
                        "include[]": "logprobs",
                    },
                    files={
                        "file": (
                            filename or "voice.mp3",
                            audio,
                            content_type,
                        )
                    },
                )
        except httpx.TimeoutException as exc:
            raise ASRProviderError("ASR_TIMEOUT") from exc
        except httpx.RequestError as exc:
            raise ASRProviderError("ASR_PROVIDER_UNAVAILABLE") from exc

        if response.status_code < 200 or response.status_code >= 300:
            raise ASRProviderError("ASR_PROVIDER_FAILED")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ASRProviderError("ASR_PROVIDER_INVALID_RESPONSE") from exc
        if not isinstance(payload, dict):
            raise ASRProviderError("ASR_PROVIDER_INVALID_RESPONSE")

        text = str(payload.get("text") or "").strip()
        if not text:
            raise ASRProviderError("ASR_EMPTY_RESULT")
        confidence = confidence_from_logprobs(payload.get("logprobs"))
        return ASRResult(
            text=text,
            confidence=confidence,
            provider="openai",
            model=self._settings.asr_model,
        )


@lru_cache
def get_asr_provider() -> ASRProvider:
    settings = get_settings()
    if settings.asr_provider == "disabled":
        return DisabledASRProvider()
    if settings.asr_provider == "openai":
        return OpenAIASRProvider(settings)
    raise ASRProviderError("ASR_PROVIDER_UNAVAILABLE")
