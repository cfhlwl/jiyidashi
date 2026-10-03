from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.db import SessionLocal
from app.core.observability import emit_operational_event
from app.models import Place, PlaceNameCorrection
from app.services.idempotency_service import (
    IdempotencyConflict,
    IdempotencyResourceGone,
    execute_idempotent_mutation,
)
from app.services.place_resolver import (
    PlaceResolver,
    PlaceResolverError,
    get_place_resolver,
)

UNNAMED_PLACE = "未命名地点"
PLACE_NAME_CORRECTION_OPERATION = "PLACE_NAME_CORRECTION"


@dataclass(frozen=True)
class PlaceNamingError(RuntimeError):
    code: str
    status_code: int


def _normalize_name(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 200:
        raise PlaceNamingError("PLACE_NAME_INVALID", 422)
    return normalized


def _get_place(
    db: Session,
    *,
    user_id: UUID,
    place_id: UUID,
    for_update: bool = False,
) -> Place | None:
    statement = select(Place).where(
        Place.id == place_id,
        Place.user_id == user_id,
    )
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def _sync_display_name(place: Place) -> None:
    # [人工注释][S2-009][S2-010] 这是唯一展示 precedence：
    # 用户纠正永远压过自动候选；撤销用户纠正时才回退 automatic / UNNAMED。
    if place.user_name is not None:
        place.name = place.user_name
        place.is_user_named = True
    elif place.automatic_name is not None:
        place.name = place.automatic_name
        place.is_user_named = False
    else:
        place.name = UNNAMED_PLACE
        place.is_user_named = False


def apply_automatic_place_label_candidate(
    db: Session,
    *,
    user_id: UUID,
    place_id: UUID,
    label: str,
    source: str,
    now: datetime | None = None,
) -> Place:
    """Apply one trusted server-side label candidate without changing Place evidence."""

    normalized_label = _normalize_name(label)
    normalized_source = source.strip()
    if not normalized_source or len(normalized_source) > 64:
        raise PlaceNamingError("PLACE_AUTOMATIC_NAME_SOURCE_INVALID", 422)

    place = _get_place(db, user_id=user_id, place_id=place_id, for_update=True)
    if place is None:
        raise PlaceNamingError("PLACE_NOT_FOUND", 404)

    if (
        place.automatic_name == normalized_label
        and place.automatic_name_source == normalized_source
    ):
        return place

    # [人工注释][S2-009] 自动命名只是 label candidate 元数据，不是 Memory/Evidence。
    # 即使候选变化，也不能写 Visit/cluster/provenance，更不能覆盖 user_name。
    place.automatic_name = normalized_label
    place.automatic_name_source = normalized_source
    place.name_revision += 1
    place.name_updated_at = now or datetime.now(UTC)
    _sync_display_name(place)
    db.flush()
    return place


def correct_place_name(
    db: Session,
    *,
    user_id: UUID,
    place_id: UUID,
    client_uuid: UUID,
    name: str | None,
    now: datetime | None = None,
) -> Place:
    normalized_name = None if name is None else _normalize_name(name)
    effective_now = now or datetime.now(UTC)

    def create_resource(session: Session) -> Place:
        place = _get_place(
            session,
            user_id=user_id,
            place_id=place_id,
            for_update=True,
        )
        if place is None:
            raise PlaceNamingError("PLACE_NOT_FOUND", 404)

        previous = place.user_name
        if previous == normalized_name:
            # 同一个业务值用新的 client_uuid 再提交也不制造虚假 revision/history；
            # ClientMutation 仍记录该请求键，后续网络重放会稳定收敛。
            return place

        place.user_name = normalized_name
        place.name_revision += 1
        place.name_updated_at = effective_now
        _sync_display_name(place)
        session.add(
            PlaceNameCorrection(
                user_id=user_id,
                place_id=place.id,
                client_uuid=client_uuid,
                revision=place.name_revision,
                previous_user_name=previous,
                new_user_name=normalized_name,
                created_at=effective_now,
            )
        )
        session.flush()
        return place

    try:
        return execute_idempotent_mutation(
            db,
            user_id=user_id,
            operation_type=PLACE_NAME_CORRECTION_OPERATION,
            client_uuid=client_uuid,
            fingerprint_payload={
                "place_id": str(place_id),
                "name": normalized_name,
            },
            resource_type="PLACE",
            create_resource=create_resource,
            resource_id=lambda place: place.id,
            load_resource=lambda session, resource_id: _get_place(
                session,
                user_id=user_id,
                place_id=resource_id,
            ),
        )
    except IdempotencyConflict as exc:
        raise PlaceNamingError("PLACE_NAME_CORRECTION_CONFLICT", 409) from exc
    except IdempotencyResourceGone as exc:
        raise PlaceNamingError("PLACE_NAME_CORRECTION_TARGET_GONE", 409) from exc



@dataclass(frozen=True)
class PlaceNameBackfillResult:
    attempted: int
    resolved: int
    provider_failures: int


def backfill_automatic_place_names_for_user(
    user_id: UUID,
    *,
    resolver: PlaceResolver | None = None,
    settings: Settings | None = None,
) -> PlaceNameBackfillResult:
    """Resolve a bounded owner-scoped batch without holding DB locks across provider I/O."""

    effective_settings = settings or get_settings()
    if resolver is None and effective_settings.place_resolver_provider == "disabled":
        return PlaceNameBackfillResult(attempted=0, resolved=0, provider_failures=0)
    effective_resolver = resolver or get_place_resolver()

    # Read only immutable identifiers/coordinates, then end this DB transaction before
    # external provider I/O. This keeps AMap latency outside location ingestion and DB locks.
    with SessionLocal() as db:
        rows = list(
            db.execute(
                select(Place.id, Place.latitude, Place.longitude)
                .where(
                    Place.user_id == user_id,
                    Place.user_name.is_(None),
                    Place.automatic_name.is_(None),
                    Place.latitude.is_not(None),
                    Place.longitude.is_not(None),
                )
                .order_by(Place.created_at, Place.id)
                .limit(effective_settings.place_naming_backfill_batch_size)
            )
        )
        db.rollback()

    resolved = 0
    failures = 0
    for place_id, latitude, longitude in rows:
        if latitude is None or longitude is None:
            continue
        try:
            candidate = effective_resolver.resolve(
                latitude=float(latitude),
                longitude=float(longitude),
            )
        except PlaceResolverError as exc:
            failures += 1
            emit_operational_event(
                event="place.naming.provider_failed",
                level="WARNING",
                provider=effective_settings.place_resolver_provider,
                error_code=exc.code,
            )
            continue
        except Exception:
            # Background enrichment must never become an availability dependency for
            # location ingestion. Unexpected provider adapter failures stay bounded here.
            failures += 1
            emit_operational_event(
                event="place.naming.provider_failed",
                level="ERROR",
                provider=effective_settings.place_resolver_provider,
                error_code="PLACE_RESOLVER_UNEXPECTED_FAILURE",
            )
            continue

        if candidate is None:
            continue

        try:
            with SessionLocal() as db:
                place = apply_automatic_place_label_candidate(
                    db,
                    user_id=user_id,
                    place_id=place_id,
                    label=candidate.label,
                    source=candidate.source,
                )
                if candidate.address is not None:
                    place.address = candidate.address
                if candidate.category is not None:
                    place.category = candidate.category[:80]
                db.commit()
                resolved += 1
        except PlaceNamingError:
            # Place may have been deleted by a concurrent location rebuild. That is a
            # normal stale enrichment result and must not recreate or cross owners.
            continue

    result = PlaceNameBackfillResult(
        attempted=len(rows),
        resolved=resolved,
        provider_failures=failures,
    )
    emit_operational_event(
        event="place.naming.backfill_completed",
        level="INFO",
        provider=effective_settings.place_resolver_provider,
        operation="PLACE_NAMING_BACKFILL",
        operation_status=(
            "COMPLETED_WITH_PROVIDER_FAILURES"
            if result.provider_failures
            else "COMPLETED"
        ),
        signal_count=result.resolved,
    )
    return result


def run_place_naming_background(user_id: UUID) -> None:
    """Best-effort BackgroundTasks entrypoint; never propagates into location upload."""

    try:
        backfill_automatic_place_names_for_user(user_id)
    except Exception:
        emit_operational_event(
            event="place.naming.background_failed",
            level="ERROR",
            error_code="PLACE_NAMING_BACKGROUND_FAILED",
        )
