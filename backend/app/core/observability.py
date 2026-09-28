from __future__ import annotations

import json
import logging
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

_OBSERVABILITY_LOGGER_NAME = "jiyidashi.observability"
_OBSERVABILITY_HANDLER_MARKER = "_jiyidashi_observability_sink"
_request_id_var: ContextVar[str | None] = ContextVar(
    "jiyidashi_request_id",
    default=None,
)


class CheckedStreamHandler(logging.StreamHandler):
    """Stream handler with an explicit write/flush acknowledgement path."""

    def emit_checked(self, record: logging.LogRecord) -> bool:
        try:
            msg = self.format(record)
            stream = self.stream
            self.acquire()
            try:
                stream.write(msg + self.terminator)
                self.flush()
            finally:
                self.release()
            return True
        except Exception:
            return False


def configure_observability_log_level(level: str) -> None:
    """Install one explicit raw-message production sink and set its level."""

    logger = logging.getLogger(_OBSERVABILITY_LOGGER_NAME)
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(numeric_level)
    logger.propagate = False

    handler = next(
        (
            item
            for item in logger.handlers
            if getattr(item, _OBSERVABILITY_HANDLER_MARKER, False)
        ),
        None,
    )
    if handler is not None and not isinstance(handler, CheckedStreamHandler):
        logger.removeHandler(handler)
        handler = None
    if handler is None:
        handler = CheckedStreamHandler()
        setattr(handler, _OBSERVABILITY_HANDLER_MARKER, True)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    handler.setLevel(numeric_level)


def normalize_request_id(value: str | None) -> str:
    if value:
        try:
            return str(UUID(value))
        except (TypeError, ValueError, AttributeError):
            pass
    return str(uuid4())


def set_request_id(request_id: str) -> Token[str | None]:
    return _request_id_var.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    _request_id_var.reset(token)


def current_request_id() -> str | None:
    return _request_id_var.get()


def _build_operational_payload(
    *,
    event: str,
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"],
    request_id: str | None,
    optional_fields: dict[str, object | None],
) -> dict[str, object]:
    payload: dict[str, object] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "level": level,
        "event": event,
        "request_id": request_id if request_id is not None else current_request_id(),
    }
    for key, value in optional_fields.items():
        if value is not None:
            payload[key] = value
    return payload


def _operational_optional_fields(
    *,
    method: str | None = None,
    route: str | None = None,
    status_code: int | None = None,
    latency_ms: float | None = None,
    purpose: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    gateway_request_id: str | None = None,
    provider_request_id: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    retryable: bool | None = None,
    error_code: str | None = None,
    operation: str | None = None,
    operation_request_id: str | None = None,
    operation_status: str | None = None,
    completed: bool | None = None,
    dependency: str | None = None,
    ready: bool | None = None,
    alert_id: str | None = None,
    rule_code: str | None = None,
    severity: str | None = None,
    signal_count: int | None = None,
    window_seconds: int | None = None,
    correlation_id: str | None = None,
    delivery_status: str | None = None,
) -> dict[str, object | None]:
    return {
        "method": method,
        "route": route,
        "status_code": status_code,
        "latency_ms": None if latency_ms is None else round(float(latency_ms), 3),
        "purpose": purpose,
        "provider": provider,
        "model": model,
        "gateway_request_id": gateway_request_id,
        "provider_request_id": provider_request_id,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "retryable": retryable,
        "error_code": error_code,
        "operation": operation,
        "operation_request_id": operation_request_id,
        "operation_status": operation_status,
        "completed": completed,
        "dependency": dependency,
        "ready": ready,
        "alert_id": alert_id,
        "rule_code": rule_code,
        "severity": severity,
        "signal_count": signal_count,
        "window_seconds": window_seconds,
        "correlation_id": correlation_id,
        "delivery_status": delivery_status,
    }


def emit_operational_event(
    *,
    event: str,
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO",
    request_id: str | None = None,
    method: str | None = None,
    route: str | None = None,
    status_code: int | None = None,
    latency_ms: float | None = None,
    purpose: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    gateway_request_id: str | None = None,
    provider_request_id: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    retryable: bool | None = None,
    error_code: str | None = None,
    operation: str | None = None,
    operation_request_id: str | None = None,
    operation_status: str | None = None,
    completed: bool | None = None,
    dependency: str | None = None,
    ready: bool | None = None,
    alert_id: str | None = None,
    rule_code: str | None = None,
    severity: str | None = None,
    signal_count: int | None = None,
    window_seconds: int | None = None,
    correlation_id: str | None = None,
    delivery_status: str | None = None,
) -> bool:
    """Emit one fail-safe JSON event using only explicitly whitelisted fields."""

    try:
        payload = _build_operational_payload(
            event=event,
            level=level,
            request_id=request_id,
            optional_fields=_operational_optional_fields(
                method=method,
                route=route,
                status_code=status_code,
                latency_ms=latency_ms,
                purpose=purpose,
                provider=provider,
                model=model,
                gateway_request_id=gateway_request_id,
                provider_request_id=provider_request_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                retryable=retryable,
                error_code=error_code,
                operation=operation,
                operation_request_id=operation_request_id,
                operation_status=operation_status,
                completed=completed,
                dependency=dependency,
                ready=ready,
                alert_id=alert_id,
                rule_code=rule_code,
                severity=severity,
                signal_count=signal_count,
                window_seconds=window_seconds,
                correlation_id=correlation_id,
                delivery_status=delivery_status,
            ),
        )
        logger = logging.getLogger(_OBSERVABILITY_LOGGER_NAME)
        log_method = {
            "DEBUG": logger.debug,
            "INFO": logger.info,
            "WARNING": logger.warning,
            "ERROR": logger.error,
        }[level]
        log_method(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
        return True
    except Exception:
        # Telemetry must never alter business success/failure semantics.
        return False


def emit_security_alert_event_checked(
    *,
    level: Literal["WARNING", "ERROR"],
    alert_id: str,
    rule_code: str,
    severity: str,
    signal_count: int,
    window_seconds: int,
    correlation_id: str,
    delivery_status: str,
) -> bool:
    """Write one security alert only when the production stream write+flush succeeds."""

    try:
        payload = _build_operational_payload(
            event="security.alert.triggered",
            level=level,
            request_id=None,
            optional_fields=_operational_optional_fields(
                alert_id=alert_id,
                rule_code=rule_code,
                severity=severity,
                signal_count=signal_count,
                window_seconds=window_seconds,
                correlation_id=correlation_id,
                delivery_status=delivery_status,
            ),
        )
        logger = logging.getLogger(_OBSERVABILITY_LOGGER_NAME)
        handler = next(
            (
                item
                for item in logger.handlers
                if getattr(item, _OBSERVABILITY_HANDLER_MARKER, False)
                and isinstance(item, CheckedStreamHandler)
            ),
            None,
        )
        if handler is None:
            return False
        numeric_level = getattr(logging, level)
        if numeric_level < logger.getEffectiveLevel() or numeric_level < handler.level:
            return False
        record = logging.LogRecord(
            name=_OBSERVABILITY_LOGGER_NAME,
            level=numeric_level,
            pathname=__file__,
            lineno=0,
            msg=json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            args=(),
            exc_info=None,
        )
        return handler.emit_checked(record)
    except Exception:
        return False

