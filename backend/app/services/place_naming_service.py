from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Place, PlaceNameCorrection
from app.services.idempotency_service import (
    IdempotencyConflict,
    IdempotencyResourceGone,
    execute_idempotent_mutation,
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
