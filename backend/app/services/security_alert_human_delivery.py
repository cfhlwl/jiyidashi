from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.parse import urlparse

import httpx

from app.core.config import Settings, get_settings

FEISHU_PROVIDER = "feishu"
DISABLED_PROVIDER = "disabled"
MAX_PROVIDER_RESPONSE_BYTES = 64 * 1024
MAX_RETRY_AFTER_SECONDS = 900
_FEISHU_PERMANENT_CODES = {19001, 19021, 19022, 19024}


@dataclass(frozen=True)
class SecurityAlertHumanMessage:
    alert_id: str
    severity: str
    rule_code: str
    scope: str
    signal_count: int
    window_seconds: int
    created_at: datetime
    correlation_digest: str


@dataclass(frozen=True)
class HumanDeliveryResult:
    delivered: bool
    retryable: bool
    error_code: str | None = None
    retry_after_seconds: int | None = None


class SecurityAlertHumanDeliveryAdapter(Protocol):
    provider_name: str

    def deliver(self, message: SecurityAlertHumanMessage) -> HumanDeliveryResult: ...


def feishu_signature(*, timestamp: int, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}".encode()
    digest = hmac.new(string_to_sign, digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def validate_feishu_webhook_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False
    if parsed.scheme.lower() != "https":
        return False
    if parsed.hostname != "open.feishu.cn":
        return False
    if parsed.port not in (None, 443):
        return False
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return False
    prefix = "/open-apis/bot/v2/hook/"
    token = parsed.path[len(prefix) :] if parsed.path.startswith(prefix) else ""
    return bool(token) and "/" not in token


def _retry_after_seconds(response: httpx.Response) -> int | None:
    raw = response.headers.get("Retry-After", "").strip()
    if not raw:
        return None
    try:
        seconds = int(raw)
    except ValueError:
        try:
            target = parsedate_to_datetime(raw)
            if target.tzinfo is None or target.utcoffset() is None:
                target = target.replace(tzinfo=UTC)
            seconds = int((target.astimezone(UTC) - datetime.now(UTC)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None
    if seconds <= 0:
        return None
    return min(seconds, MAX_RETRY_AFTER_SECONDS)


def _safe_text(message: SecurityAlertHumanMessage) -> str:
    created_at = message.created_at
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        created_at = created_at.replace(tzinfo=UTC)
    else:
        created_at = created_at.astimezone(UTC)
    return "\n".join(
        (
            "迹忆安全告警",
            f"alert_id: {message.alert_id}",
            f"severity: {message.severity}",
            f"rule_code: {message.rule_code}",
            f"scope: {message.scope}",
            f"signal_count: {message.signal_count}",
            f"window_seconds: {message.window_seconds}",
            f"created_at: {created_at.isoformat()}",
            f"correlation_digest: {message.correlation_digest}",
            "operator_instruction: 请在 Admin Security Center 中按 alert_id 调查。",
        )
    )


class DisabledHumanDeliveryAdapter:
    provider_name = DISABLED_PROVIDER

    def deliver(self, message: SecurityAlertHumanMessage) -> HumanDeliveryResult:
        del message
        return HumanDeliveryResult(
            delivered=False,
            retryable=False,
            error_code="SECURITY_ALERT_HUMAN_PROVIDER_DISABLED",
        )


class FeishuWebhookAdapter:
    provider_name = FEISHU_PROVIDER

    def __init__(
        self,
        *,
        webhook_url: str,
        secret: str,
        timeout_seconds: float,
        client: httpx.Client | None = None,
    ):
        self._webhook_url = webhook_url.strip()
        self._secret = secret
        self._timeout_seconds = timeout_seconds
        self._client = client

    def deliver(self, message: SecurityAlertHumanMessage) -> HumanDeliveryResult:
        if not validate_feishu_webhook_url(self._webhook_url):
            return HumanDeliveryResult(
                delivered=False,
                retryable=False,
                error_code="FEISHU_CONFIG_URL_INVALID",
            )
        if not self._secret.strip():
            return HumanDeliveryResult(
                delivered=False,
                retryable=False,
                error_code="FEISHU_CONFIG_SECRET_MISSING",
            )

        timestamp = int(time.time())
        payload = {
            "timestamp": timestamp,
            "sign": feishu_signature(timestamp=timestamp, secret=self._secret),
            "msg_type": "text",
            "content": {"text": _safe_text(message)},
        }

        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=self._timeout_seconds)
        try:
            try:
                response = client.post(self._webhook_url, json=payload)
            except httpx.TimeoutException:
                return HumanDeliveryResult(
                    delivered=False,
                    retryable=True,
                    error_code="FEISHU_TIMEOUT",
                )
            except httpx.NetworkError:
                return HumanDeliveryResult(
                    delivered=False,
                    retryable=True,
                    error_code="FEISHU_NETWORK_ERROR",
                )
            except httpx.HTTPError:
                return HumanDeliveryResult(
                    delivered=False,
                    retryable=True,
                    error_code="FEISHU_HTTP_ERROR",
                )
            except Exception:
                return HumanDeliveryResult(
                    delivered=False,
                    retryable=True,
                    error_code="FEISHU_TRANSPORT_FAILURE",
                )

            retry_after = _retry_after_seconds(response)
            if response.status_code in {408, 429} or response.status_code >= 500:
                return HumanDeliveryResult(
                    delivered=False,
                    retryable=True,
                    error_code=f"FEISHU_HTTP_{response.status_code}",
                    retry_after_seconds=retry_after,
                )
            if not 200 <= response.status_code < 300:
                return HumanDeliveryResult(
                    delivered=False,
                    retryable=False,
                    error_code="FEISHU_HTTP_PERMANENT_REJECTION",
                )

            raw = response.content
            if len(raw) > MAX_PROVIDER_RESPONSE_BYTES:
                return HumanDeliveryResult(
                    delivered=False,
                    retryable=True,
                    error_code="FEISHU_RESPONSE_TOO_LARGE",
                )
            try:
                body = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                return HumanDeliveryResult(
                    delivered=False,
                    retryable=True,
                    error_code="FEISHU_RESPONSE_INVALID",
                )
            if not isinstance(body, dict):
                return HumanDeliveryResult(
                    delivered=False,
                    retryable=True,
                    error_code="FEISHU_RESPONSE_INVALID",
                )

            code = body.get("code")
            legacy_code = body.get("StatusCode")
            if code == 0 or legacy_code == 0:
                return HumanDeliveryResult(delivered=True, retryable=False)

            provider_code = code if isinstance(code, int) else legacy_code
            if isinstance(provider_code, int) and provider_code in _FEISHU_PERMANENT_CODES:
                return HumanDeliveryResult(
                    delivered=False,
                    retryable=False,
                    error_code=f"FEISHU_PROVIDER_{provider_code}",
                )
            return HumanDeliveryResult(
                delivered=False,
                retryable=True,
                error_code="FEISHU_PROVIDER_UNKNOWN",
                retry_after_seconds=retry_after,
            )
        finally:
            if owns_client:
                client.close()


def get_security_alert_human_adapter(
    settings: Settings | None = None,
) -> SecurityAlertHumanDeliveryAdapter:
    cfg = settings or get_settings()
    provider = cfg.security_alert_human_provider.strip().lower()
    if provider == FEISHU_PROVIDER:
        return FeishuWebhookAdapter(
            webhook_url=cfg.security_alert_feishu_webhook_url,
            secret=cfg.security_alert_feishu_secret,
            timeout_seconds=cfg.security_alert_delivery_timeout_seconds,
        )
    return DisabledHumanDeliveryAdapter()
