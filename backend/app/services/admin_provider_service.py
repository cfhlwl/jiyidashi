from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.admin_models import (
    AdminAccount,
    AdminRole,
    ProviderConfiguration,
    ProviderRuntimeEvidence,
    ProviderService,
)
from app.admin_schemas import (
    AdminEmbeddingBackfillRead,
    AdminEmbeddingBackfillRequest,
    AdminProviderConfigListRead,
    AdminProviderConfigRead,
    AdminProviderConfigWrite,
)
from app.core.config import Settings, get_settings
from app.embedding_gateway import build_embedding_gateway
from app.embedding_models import MemoryEmbedding
from app.embedding_policy import (
    MEMORY_EMBEDDING_DIMENSIONS,
    MEMORY_EMBEDDING_MODEL,
)
from app.entitlement_models import AIUsageEvent
from app.media_models import MediaASRClaim
from app.models import Memory, MemorySource, SourceType
from app.services.admin_security import AdminOperationError, append_admin_audit
from app.services.embedding_service import (
    EmbeddingServiceError,
    generate_or_refresh_memory_embedding,
)
from app.services.provider_config_service import (
    ProviderRuntimeConfigError,
    effective_provider_credential,
    encrypt_provider_credential,
    invalidate_provider_runtime_cache,
    provider_destination_authority,
    provider_runtime_fingerprint,
    provider_snapshot,
    read_provider_rows,
    runtime_provider_settings_from_db,
    validate_provider_policy,
)
from app.vector_support import VectorCapabilityError, inspect_vector_capability

_PROVIDER_LABELS = {
    ProviderService.AI: "AI 整理服务",
    ProviderService.ASR: "语音识别",
    ProviderService.EMBEDDING: "语义记忆检索",
}
_EVIDENCE_WINDOW = timedelta(hours=24)
_STALE_AI_RESERVATION_GRACE = timedelta(minutes=5)


def _require_super_admin(actor: AdminAccount) -> None:
    if actor.role != AdminRole.SUPER_ADMIN.value:
        raise AdminOperationError("ADMIN_PERMISSION_DENIED", 403)


def _provider_error(exc: ProviderRuntimeConfigError) -> AdminOperationError:
    status = 503 if exc.code.startswith("PROVIDER_CONFIG_MASTER_KEY") else 400
    if exc.code == "PROVIDER_CREDENTIAL_DECRYPT_FAILED":
        status = 503
    return AdminOperationError(f"ADMIN_{exc.code}", status)


def _safe_host(value: str) -> str:
    parsed = urlparse(value.strip())
    return parsed.hostname or ""


def _latest(db: Session, statement) -> datetime | None:
    value = db.scalar(statement)
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _runtime_state(
    db: Session,
    *,
    service: ProviderService,
    enabled: bool,
    configured: bool,
    runtime_fingerprint: str,
    now: datetime,
) -> str:
    if not enabled:
        return "CONFIGURED_UNVERIFIED" if configured else "DISABLED"
    if not configured:
        return "WARNING"

    evidence = db.get(
        ProviderRuntimeEvidence,
        (service.value, runtime_fingerprint),
    )
    if evidence is None:
        return "ENABLED_UNVERIFIED"

    recent_since = now - _EVIDENCE_WINDOW

    success = evidence.last_success_at
    if success is not None:
        if success.tzinfo is None or success.utcoffset() is None:
            success = success.replace(tzinfo=UTC)
        else:
            success = success.astimezone(UTC)
        if success < recent_since:
            success = None

    failure = evidence.last_failure_at
    if failure is not None:
        if failure.tzinfo is None or failure.utcoffset() is None:
            failure = failure.replace(tzinfo=UTC)
        else:
            failure = failure.astimezone(UTC)
        if failure < recent_since:
            failure = None

    if failure is not None and (success is None or failure > success):
        return "WARNING"
    return "NORMAL" if success is not None else "ENABLED_UNVERIFIED"


def read_provider_configurations(
    db: Session,
    *,
    settings: Settings | None = None,
) -> AdminProviderConfigListRead:
    cfg = settings or get_settings()
    rows = read_provider_rows(db)
    try:
        runtime_settings = runtime_provider_settings_from_db(db, settings=cfg)
    except ProviderRuntimeConfigError as exc:
        raise _provider_error(exc) from exc
    observed = datetime.now(UTC)
    services: list[AdminProviderConfigRead] = []
    for service in ProviderService:
        row = rows.get(service)
        try:
            snapshot = provider_snapshot(row, service=service, settings=cfg)
        except ProviderRuntimeConfigError as exc:
            raise _provider_error(exc) from exc
        services.append(
            AdminProviderConfigRead(
                service=service,
                label=_PROVIDER_LABELS[service],
                state=_runtime_state(
                    db,
                    service=service,
                    enabled=snapshot.enabled,
                    configured=snapshot.credential_configured and bool(snapshot.model.strip()),
                    runtime_fingerprint=provider_runtime_fingerprint(
                        runtime_settings,
                        service,
                    ),
                    now=observed,
                ),
                enabled=snapshot.enabled,
                provider_type=snapshot.provider_type,
                base_url=snapshot.base_url,
                endpoint_host=_safe_host(snapshot.base_url),
                model=snapshot.model,
                timeout_seconds=snapshot.timeout_seconds,
                max_input_chars=snapshot.max_input_chars,
                max_output_tokens=snapshot.max_output_tokens,
                min_confidence=snapshot.min_confidence,
                configured=snapshot.credential_configured,
                revision=snapshot.revision,
                updated_at=snapshot.updated_at,
                source=snapshot.source,
                dimensions=(
                    MEMORY_EMBEDDING_DIMENSIONS
                    if service == ProviderService.EMBEDDING
                    else None
                ),
            )
        )
    return AdminProviderConfigListRead(services=services)


def update_provider_configuration(
    db: Session,
    *,
    actor: AdminAccount,
    service: ProviderService,
    payload: AdminProviderConfigWrite,
    settings: Settings | None = None,
) -> ProviderConfiguration:
    _require_super_admin(actor)
    cfg = settings or get_settings()
    row = db.scalar(
        select(ProviderConfiguration)
        .where(ProviderConfiguration.service == service.value)
        .with_for_update()
    )
    if row is None:
        if payload.expected_revision is not None:
            raise AdminOperationError("ADMIN_STATE_STALE", 409)
    elif payload.expected_revision is None or row.revision != payload.expected_revision:
        raise AdminOperationError("ADMIN_STATE_STALE", 409)

    try:
        current_snapshot = provider_snapshot(
            row,
            service=service,
            settings=cfg,
        )
        current_secret = effective_provider_credential(
            row,
            service=service,
            settings=cfg,
        )
    except ProviderRuntimeConfigError as exc:
        raise _provider_error(exc) from exc

    credential_override = False if row is None else row.credential_override
    credential_ciphertext = None if row is None else row.credential_ciphertext
    credential_changed = False
    effective_secret = current_secret

    if payload.api_key is not None:
        try:
            credential_ciphertext = encrypt_provider_credential(
                payload.api_key,
                settings=cfg,
            )
        except ProviderRuntimeConfigError as exc:
            raise _provider_error(exc) from exc
        credential_override = True
        credential_changed = True
        effective_secret = payload.api_key.strip()
    elif payload.clear_api_key:
        credential_override = True
        credential_ciphertext = None
        credential_changed = True
        effective_secret = ""

    if (
        current_secret
        and payload.api_key is None
        and not payload.clear_api_key
    ):
        try:
            current_destination = provider_destination_authority(
                current_snapshot.provider_type,
                current_snapshot.base_url,
            )
            requested_destination = provider_destination_authority(
                payload.provider_type,
                payload.base_url,
            )
        except ProviderRuntimeConfigError as exc:
            raise _provider_error(exc) from exc
        if current_destination != requested_destination:
            raise AdminOperationError(
                "ADMIN_PROVIDER_CREDENTIAL_DESTINATION_CHANGED",
                409,
            )

    try:
        validate_provider_policy(
            service=service,
            enabled=payload.enabled,
            provider_type=payload.provider_type,
            base_url=payload.base_url,
            model=payload.model,
            timeout_seconds=payload.timeout_seconds,
            max_input_chars=payload.max_input_chars,
            max_output_tokens=payload.max_output_tokens,
            min_confidence=payload.min_confidence,
            credential_configured=bool(effective_secret),
            settings=cfg,
        )
    except ProviderRuntimeConfigError as exc:
        raise _provider_error(exc) from exc

    previous_revision = None if row is None else row.revision
    now = datetime.now(UTC)
    if row is None:
        row = ProviderConfiguration(
            service=service.value,
            enabled=payload.enabled,
            provider_type=payload.provider_type,
            base_url=payload.base_url.strip().rstrip("/"),
            model=payload.model.strip(),
            timeout_seconds=payload.timeout_seconds,
            max_input_chars=payload.max_input_chars,
            max_output_tokens=payload.max_output_tokens,
            min_confidence=payload.min_confidence,
            credential_override=credential_override,
            credential_ciphertext=credential_ciphertext,
            revision=0,
            updated_by_admin_id=actor.id,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.enabled = payload.enabled
        row.provider_type = payload.provider_type
        row.base_url = payload.base_url.strip().rstrip("/")
        row.model = payload.model.strip()
        row.timeout_seconds = payload.timeout_seconds
        row.max_input_chars = payload.max_input_chars
        row.max_output_tokens = payload.max_output_tokens
        row.min_confidence = payload.min_confidence
        row.credential_override = credential_override
        row.credential_ciphertext = credential_ciphertext
        row.revision += 1
        row.updated_by_admin_id = actor.id
        row.updated_at = now

    try:
        db.flush()
    except IntegrityError as exc:
        # A first-write race has no row to lock. The service primary key is the final
        # identity fence; map only a confirmed concurrent winner to stale state.
        db.rollback()
        winner = db.get(ProviderConfiguration, service.value)
        if winner is not None:
            raise AdminOperationError("ADMIN_STATE_STALE", 409) from exc
        raise AdminOperationError("ADMIN_PROVIDER_CONFIG_UNAVAILABLE", 503) from exc
    append_admin_audit(
        db,
        actor=actor,
        action="PROVIDER_CONFIG_UPDATE",
        target_type="PROVIDER_SERVICE",
        target_id=service.value,
        result="SUCCESS",
        metadata={
            "service": service.value,
            "previous_revision": previous_revision,
            "new_revision": row.revision,
            "enabled": row.enabled,
            "provider": row.provider_type,
            "model": row.model,
            "endpoint_host": _safe_host(row.base_url),
            "credential_changed": credential_changed,
        },
    )
    db.commit()
    db.refresh(row)
    invalidate_provider_runtime_cache()
    return row


def _vector_capable(db: Session) -> bool:
    if db.get_bind().dialect.name != "postgresql":
        return False
    try:
        inspect_vector_capability(db.connection())
    except VectorCapabilityError:
        return False
    return True


def _remaining_embedding_query():
    return (
        select(Memory.id, Memory.user_id)
        .outerjoin(MemoryEmbedding, MemoryEmbedding.memory_id == Memory.id)
        .where(
            Memory.is_deleted.is_(False),
            or_(
                MemoryEmbedding.memory_id.is_(None),
                MemoryEmbedding.memory_revision != Memory.edit_revision,
                MemoryEmbedding.model != MEMORY_EMBEDDING_MODEL,
                MemoryEmbedding.dimensions != MEMORY_EMBEDDING_DIMENSIONS,
            ),
        )
    )


def embedding_backfill_status(db: Session) -> AdminEmbeddingBackfillRead:
    eligible = int(
        db.scalar(select(func.count(Memory.id)).where(Memory.is_deleted.is_(False))) or 0
    )
    vector_rows = int(db.scalar(select(func.count(MemoryEmbedding.memory_id))) or 0)
    remaining = int(
        db.scalar(select(func.count()).select_from(_remaining_embedding_query().subquery()))
        or 0
    )
    return AdminEmbeddingBackfillRead(
        vector_database_capable=_vector_capable(db),
        policy_model=MEMORY_EMBEDDING_MODEL,
        policy_dimensions=MEMORY_EMBEDDING_DIMENSIONS,
        eligible_memories=eligible,
        vector_rows=vector_rows,
        remaining_memories=remaining,
    )


async def run_embedding_backfill_batch(
    db: Session,
    *,
    actor: AdminAccount,
    payload: AdminEmbeddingBackfillRequest,
    settings: Settings | None = None,
    gateway_override=None,
) -> AdminEmbeddingBackfillRead:
    _require_super_admin(actor)
    row = db.scalar(
        select(ProviderConfiguration)
        .where(ProviderConfiguration.service == ProviderService.EMBEDDING.value)
        .with_for_update()
    )
    if row is None:
        if payload.expected_provider_revision is not None:
            raise AdminOperationError("ADMIN_STATE_STALE", 409)
    elif (
        payload.expected_provider_revision is None
        or row.revision != payload.expected_provider_revision
    ):
        raise AdminOperationError("ADMIN_STATE_STALE", 409)

    try:
        runtime_settings = runtime_provider_settings_from_db(db, settings=settings)
    except ProviderRuntimeConfigError as exc:
        raise _provider_error(exc) from exc
    if runtime_settings.embedding_provider == "disabled":
        raise AdminOperationError("ADMIN_EMBEDDING_NOT_ENABLED", 409)
    if not _vector_capable(db):
        raise AdminOperationError("ADMIN_EMBEDDING_DATABASE_UNAVAILABLE", 409)

    candidates = list(
        db.execute(
            _remaining_embedding_query()
            .order_by(Memory.created_at.asc(), Memory.id.asc())
            .limit(payload.batch_size)
        )
    )
    actor_id = actor.id
    db.commit()

    gateway = gateway_override or build_embedding_gateway(runtime_settings)
    provider_revision = None if row is None else row.revision
    processed = 0
    refreshed = 0
    failed = 0
    last_error: str | None = None
    for memory_id, user_id in candidates:
        # ADMIN-002: an explicit disable/rotate/update must fence the next paid call in
        # an already-running bounded batch. Re-check committed authority before each item;
        # never continue silently on the gateway/config snapshot captured before I/O.
        current_provider = db.scalar(
            select(ProviderConfiguration)
            .where(
                ProviderConfiguration.service
                == ProviderService.EMBEDDING.value
            )
            .execution_options(populate_existing=True)
        )
        if provider_revision is None:
            if current_provider is not None:
                last_error = "PROVIDER_REVISION_CHANGED"
                break
        elif (
            current_provider is None
            or current_provider.revision != provider_revision
            or not current_provider.enabled
        ):
            last_error = "PROVIDER_REVISION_CHANGED"
            break
        db.rollback()

        processed += 1
        try:
            result = await generate_or_refresh_memory_embedding(
                db,
                user_id=user_id,
                memory_id=memory_id,
                gateway=gateway,
            )
            if result.refreshed:
                refreshed += 1
        except EmbeddingServiceError as exc:
            db.rollback()
            failed += 1
            last_error = exc.code
            break

    current_actor = db.get(AdminAccount, actor_id)
    if current_actor is None:
        raise AdminOperationError("ADMIN_SESSION_STALE", 401)
    append_admin_audit(
        db,
        actor=current_actor,
        action="EMBEDDING_BACKFILL_BATCH",
        target_type="PROVIDER_SERVICE",
        target_id=ProviderService.EMBEDDING.value,
        result="SUCCESS" if failed == 0 and last_error is None else "PARTIAL",
        metadata={
            "batch_size": payload.batch_size,
            "processed": processed,
            "refreshed": refreshed,
            "failed": failed,
            "error_code": last_error,
            "provider_revision": provider_revision,
        },
    )
    db.commit()

    status = embedding_backfill_status(db)
    return status.model_copy(
        update={
            "batch_size": payload.batch_size,
            "processed": processed,
            "refreshed": refreshed,
            "failed": failed,
            "last_error": last_error,
        }
    )
