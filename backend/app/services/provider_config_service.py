from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import monotonic
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin_models import ProviderConfiguration, ProviderService
from app.core.config import Settings, get_settings
from app.core.db import SessionLocal
from app.embedding_policy import (
    MEMORY_EMBEDDING_DIMENSIONS,
    MEMORY_EMBEDDING_MAX_INPUT_CHARS,
    MEMORY_EMBEDDING_MODEL,
)


class ProviderRuntimeConfigError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ProviderConfigSnapshot:
    service: ProviderService
    enabled: bool
    provider_type: str
    base_url: str
    model: str
    timeout_seconds: float
    max_input_chars: int | None
    max_output_tokens: int | None
    min_confidence: float | None
    credential_configured: bool
    revision: int | None
    updated_at: object | None
    source: str


_cache_lock = Lock()
_cache_deadline = 0.0
_cache_settings: Settings | None = None
_cache_generation = 0


def _fernet(settings: Settings) -> Fernet:
    raw = settings.provider_config_master_key.strip()
    if not raw:
        raise ProviderRuntimeConfigError("PROVIDER_CONFIG_MASTER_KEY_UNAVAILABLE")
    try:
        return Fernet(raw.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise ProviderRuntimeConfigError("PROVIDER_CONFIG_MASTER_KEY_INVALID") from exc


def encrypt_provider_credential(value: str, *, settings: Settings | None = None) -> str:
    secret = value.strip()
    if not secret:
        raise ProviderRuntimeConfigError("PROVIDER_CREDENTIAL_INVALID")
    cfg = settings or get_settings()
    return _fernet(cfg).encrypt(secret.encode("utf-8")).decode("ascii")


def decrypt_provider_credential(
    ciphertext: str,
    *,
    settings: Settings | None = None,
) -> str:
    cfg = settings or get_settings()
    try:
        value = _fernet(cfg).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
        raise ProviderRuntimeConfigError("PROVIDER_CREDENTIAL_DECRYPT_FAILED") from exc
    if not value.strip():
        raise ProviderRuntimeConfigError("PROVIDER_CREDENTIAL_DECRYPT_FAILED")
    return value


def _bootstrap_secret(settings: Settings, service: ProviderService) -> str:
    if service == ProviderService.AI:
        return settings.ai_api_key
    if service == ProviderService.ASR:
        return settings.asr_api_key
    return settings.embedding_api_key


def effective_provider_credential(
    row: ProviderConfiguration | None,
    *,
    service: ProviderService,
    settings: Settings | None = None,
) -> str:
    cfg = settings or get_settings()
    if row is None or not row.credential_override:
        return _bootstrap_secret(cfg, service).strip()
    if not row.credential_ciphertext:
        return ""
    return decrypt_provider_credential(row.credential_ciphertext, settings=cfg)


def _bootstrap_snapshot(
    settings: Settings,
    service: ProviderService,
) -> ProviderConfigSnapshot:
    if service == ProviderService.AI:
        provider = settings.ai_provider
        return ProviderConfigSnapshot(
            service=service,
            enabled=provider != "disabled",
            provider_type=provider if provider != "disabled" else "openai",
            base_url=settings.ai_base_url,
            model=settings.ai_model,
            timeout_seconds=settings.ai_timeout_seconds,
            max_input_chars=settings.ai_max_input_chars,
            max_output_tokens=settings.ai_max_output_tokens,
            min_confidence=None,
            credential_configured=bool(settings.ai_api_key.strip()),
            revision=None,
            updated_at=None,
            source="BOOTSTRAP",
        )
    if service == ProviderService.ASR:
        provider = settings.asr_provider
        return ProviderConfigSnapshot(
            service=service,
            enabled=provider != "disabled",
            provider_type=provider if provider != "disabled" else "openai",
            base_url=settings.asr_base_url,
            model=settings.asr_model,
            timeout_seconds=settings.asr_timeout_seconds,
            max_input_chars=None,
            max_output_tokens=None,
            min_confidence=settings.asr_min_confidence,
            credential_configured=bool(settings.asr_api_key.strip()),
            revision=None,
            updated_at=None,
            source="BOOTSTRAP",
        )
    provider = settings.embedding_provider
    return ProviderConfigSnapshot(
        service=service,
        enabled=provider != "disabled",
        provider_type=provider if provider != "disabled" else "openai",
        base_url=settings.embedding_base_url,
        model=settings.embedding_model,
        timeout_seconds=settings.embedding_timeout_seconds,
        max_input_chars=settings.embedding_max_input_chars,
        max_output_tokens=None,
        min_confidence=None,
        credential_configured=bool(settings.embedding_api_key.strip()),
        revision=None,
        updated_at=None,
        source="BOOTSTRAP",
    )


def provider_snapshot(
    row: ProviderConfiguration | None,
    *,
    service: ProviderService,
    settings: Settings | None = None,
) -> ProviderConfigSnapshot:
    cfg = settings or get_settings()
    if row is None:
        return _bootstrap_snapshot(cfg, service)
    credential = effective_provider_credential(row, service=service, settings=cfg)
    return ProviderConfigSnapshot(
        service=service,
        enabled=row.enabled,
        provider_type=row.provider_type,
        base_url=row.base_url,
        model=row.model,
        timeout_seconds=float(row.timeout_seconds),
        max_input_chars=row.max_input_chars,
        max_output_tokens=row.max_output_tokens,
        min_confidence=row.min_confidence,
        credential_configured=bool(credential),
        revision=row.revision,
        updated_at=row.updated_at,
        source="DATABASE",
    )


def read_provider_rows(db: Session) -> dict[ProviderService, ProviderConfiguration]:
    rows = list(db.scalars(select(ProviderConfiguration)))
    result: dict[ProviderService, ProviderConfiguration] = {}
    for row in rows:
        try:
            service = ProviderService(row.service)
        except ValueError as exc:
            raise ProviderRuntimeConfigError("PROVIDER_CONFIG_INVALID") from exc
        result[service] = row
    return result


def _validate_url(value: str, *, production: bool) -> str:
    raw = value.strip()
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        raise ProviderRuntimeConfigError("PROVIDER_BASE_URL_INVALID")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ProviderRuntimeConfigError("PROVIDER_BASE_URL_INVALID")
    if production and parsed.scheme.lower() != "https":
        raise ProviderRuntimeConfigError("PROVIDER_BASE_URL_HTTPS_REQUIRED")
    return raw.rstrip("/")


def _settings_with_rows(
    rows: dict[ProviderService, ProviderConfiguration],
    *,
    settings: Settings,
) -> Settings:
    updates: dict[str, object] = {}
    for service in ProviderService:
        row = rows.get(service)
        if row is None:
            continue
        credential = effective_provider_credential(
            row,
            service=service,
            settings=settings,
        )
        base_url = _validate_url(row.base_url, production=settings.is_production)
        provider = row.provider_type if row.enabled else "disabled"
        if service == ProviderService.AI:
            updates.update(
                ai_provider=provider,
                ai_base_url=base_url,
                ai_api_key=credential,
                ai_model=row.model,
                ai_timeout_seconds=row.timeout_seconds,
                ai_max_input_chars=row.max_input_chars,
                ai_max_output_tokens=row.max_output_tokens,
            )
        elif service == ProviderService.ASR:
            updates.update(
                asr_provider=provider,
                asr_base_url=base_url,
                asr_api_key=credential,
                asr_model=row.model,
                asr_timeout_seconds=row.timeout_seconds,
                asr_min_confidence=row.min_confidence,
            )
        else:
            updates.update(
                embedding_provider=provider,
                embedding_base_url=base_url,
                embedding_api_key=credential,
                embedding_model=row.model,
                embedding_dimensions=MEMORY_EMBEDDING_DIMENSIONS,
                embedding_timeout_seconds=row.timeout_seconds,
                embedding_max_input_chars=row.max_input_chars,
            )

    payload = settings.model_dump()
    payload.update(updates)
    try:
        return Settings.model_validate(payload)
    except ValueError as exc:
        raise ProviderRuntimeConfigError("PROVIDER_CONFIG_INVALID") from exc


def runtime_provider_settings_from_db(
    db: Session,
    *,
    settings: Settings | None = None,
) -> Settings:
    cfg = settings or get_settings()
    return _settings_with_rows(read_provider_rows(db), settings=cfg)


def invalidate_provider_runtime_cache() -> None:
    global _cache_deadline, _cache_generation, _cache_settings
    with _cache_lock:
        _cache_generation += 1
        _cache_deadline = 0.0
        _cache_settings = None


def get_runtime_provider_settings() -> Settings:
    global _cache_deadline, _cache_settings
    base = get_settings()

    while True:
        now = monotonic()
        with _cache_lock:
            if _cache_settings is not None and now < _cache_deadline:
                return _cache_settings
            generation = _cache_generation

        try:
            with SessionLocal() as db:
                resolved = runtime_provider_settings_from_db(db, settings=base)
        except ProviderRuntimeConfigError:
            raise
        except Exception as exc:
            raise ProviderRuntimeConfigError("PROVIDER_CONFIG_UNAVAILABLE") from exc

        with _cache_lock:
            # A same-process Admin save can invalidate while this DB read is in flight.
            # Never let that pre-invalidation snapshot repopulate the cache afterwards.
            if generation != _cache_generation:
                continue
            _cache_settings = resolved
            _cache_deadline = monotonic() + base.provider_config_cache_ttl_seconds
            return resolved


def validate_provider_policy(
    *,
    service: ProviderService,
    enabled: bool,
    provider_type: str,
    base_url: str,
    model: str,
    timeout_seconds: float,
    max_input_chars: int | None,
    max_output_tokens: int | None,
    min_confidence: float | None,
    credential_configured: bool,
    settings: Settings | None = None,
) -> None:
    cfg = settings or get_settings()
    if provider_type != "openai":
        raise ProviderRuntimeConfigError("PROVIDER_TYPE_UNSUPPORTED")
    _validate_url(base_url, production=cfg.is_production)
    if not (1.0 <= float(timeout_seconds) <= 120.0):
        raise ProviderRuntimeConfigError("PROVIDER_TIMEOUT_INVALID")
    if service == ProviderService.AI:
        if not model.strip():
            raise ProviderRuntimeConfigError("PROVIDER_MODEL_REQUIRED")
        if max_input_chars is None or not (1 <= max_input_chars <= 1_000_000):
            raise ProviderRuntimeConfigError("PROVIDER_INPUT_LIMIT_INVALID")
        if max_output_tokens is None or not (1 <= max_output_tokens <= 65536):
            raise ProviderRuntimeConfigError("PROVIDER_OUTPUT_LIMIT_INVALID")
        if min_confidence is not None:
            raise ProviderRuntimeConfigError("PROVIDER_CONFIG_INVALID")
    elif service == ProviderService.ASR:
        if not model.strip():
            raise ProviderRuntimeConfigError("PROVIDER_MODEL_REQUIRED")
        if min_confidence is None or not (0.0 <= min_confidence <= 1.0):
            raise ProviderRuntimeConfigError("PROVIDER_CONFIDENCE_INVALID")
        if max_input_chars is not None or max_output_tokens is not None:
            raise ProviderRuntimeConfigError("PROVIDER_CONFIG_INVALID")
    else:
        if model != MEMORY_EMBEDDING_MODEL:
            raise ProviderRuntimeConfigError("EMBEDDING_MODEL_POLICY_LOCKED")
        if max_input_chars != MEMORY_EMBEDDING_MAX_INPUT_CHARS:
            raise ProviderRuntimeConfigError("EMBEDDING_INPUT_POLICY_LOCKED")
        if max_output_tokens is not None or min_confidence is not None:
            raise ProviderRuntimeConfigError("PROVIDER_CONFIG_INVALID")
    if enabled and not credential_configured:
        raise ProviderRuntimeConfigError("PROVIDER_CREDENTIAL_REQUIRED")
