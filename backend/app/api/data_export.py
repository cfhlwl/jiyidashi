from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.media_models import MediaAsset, MediaEvidenceLink
from app.person_models import Person, PersonAlias
from app.models import (
    LocationDerivationState,
    LocationPoint,
    Memory,
    MemoryEdit,
    MemorySource,
    ObjectItem,
    ObjectLocation,
    ObjectLocationStatus,
    Place,
    PlaceNameCorrection,
    PrivacyPauseInterval,
    PrivacyState,
    Reminder,
    User,
    Visit,
)

router = APIRouter(prefix="/export", tags=["export"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]

EXPORT_FORMAT = "jiyidashi.user-export.v1"
EXPORT_MAX_ROWS_PER_SECTION = 5000


# [人工注释][S1-020] V1 导出对每个集合设置明确硬上限，避免无边界 ORM 拉取拖垮进程；
# 超限时显式 413，后续若需要超大账号导出再单独引入异步/分片作业。
def _bounded_scalars(
    db: Session,
    statement: Select[tuple[Any]],
    section: str,
) -> list[Any]:
    rows = list(db.scalars(statement.limit(EXPORT_MAX_ROWS_PER_SECTION + 1)))
    if len(rows) > EXPORT_MAX_ROWS_PER_SECTION:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"EXPORT_SECTION_TOO_LARGE:{section}",
        )
    return rows


def _memory_payload(memory: Memory) -> dict[str, Any]:
    # [人工注释][S1-020] 导出保留当前可信 Memory 的服务端字段；
    # 不接受客户端补造 confidence / confirmed。
    return {
        "id": memory.id,
        "memory_type": memory.memory_type.value,
        "title": memory.title,
        "content": memory.content,
        "occurred_at": memory.occurred_at,
        "source_type": memory.source_type.value,
        "confidence": memory.confidence,
        "place_id": memory.place_id,
        "latitude": memory.latitude,
        "longitude": memory.longitude,
        "is_confirmed": memory.is_confirmed,
        "metadata": memory.metadata_json,
        "edit_revision": memory.edit_revision,
        "edited_at": memory.edited_at,
        "created_at": memory.created_at,
        "updated_at": memory.updated_at,
    }


# [人工注释][S1-020] backing Memory 一旦被软删除，对应 ObjectLocation
# 只能保留“曾有历史记录且已失效”的审计语义；location_text/place_id/confidence/memory_id
# 都必须脱敏，防止数据导出绕过删除语义重新暴露位置事实。
def _object_location_payload(
    location: ObjectLocation,
    deleted_memory_ids: set[UUID],
) -> dict[str, Any]:
    is_redacted = (
        location.memory_id is not None and location.memory_id in deleted_memory_ids
    )
    if is_redacted:
        return {
            "id": location.id,
            "object_id": location.object_id,
            "memory_id": None,
            "location_text": None,
            "place_id": None,
            "recorded_at": location.recorded_at,
            "confidence": None,
            "status": ObjectLocationStatus.STALE.value,
            "redacted": True,
            "redaction_reason": "BACKING_MEMORY_DELETED",
        }

    return {
        "id": location.id,
        "object_id": location.object_id,
        "memory_id": location.memory_id,
        "location_text": location.location_text,
        "place_id": location.place_id,
        "recorded_at": location.recorded_at,
        "confidence": location.confidence,
        "status": location.status.value,
        "redacted": False,
        "redaction_reason": None,
    }


@router.get("/data")
def export_current_user_data(user_id: CurrentUser, db: DbSession) -> JSONResponse:
    # [人工注释][S1-020] user_id 只来自已验证 Bearer token；接口不接受任意 owner 参数，
    # 所有集合都再次按 owner 过滤，防止导出成为跨账号数据旁路。
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="USER_NOT_FOUND")

    memories = _bounded_scalars(
        db,
        select(Memory)
        .where(Memory.user_id == user_id, Memory.is_deleted.is_(False))
        .order_by(Memory.occurred_at, Memory.id),
        "memories",
    )
    memory_sources = _bounded_scalars(
        db,
        select(MemorySource)
        .join(Memory, MemorySource.memory_id == Memory.id)
        .where(Memory.user_id == user_id, Memory.is_deleted.is_(False))
        .order_by(MemorySource.created_at, MemorySource.id),
        "memory_sources",
    )
    memory_edits = _bounded_scalars(
        db,
        select(MemoryEdit)
        .join(Memory, MemoryEdit.memory_id == Memory.id)
        .where(Memory.user_id == user_id, Memory.is_deleted.is_(False))
        .order_by(MemoryEdit.created_at, MemoryEdit.id),
        "memory_edits",
    )
    persons = _bounded_scalars(
        db,
        select(Person)
        .where(Person.user_id == user_id)
        .order_by(Person.created_at, Person.id),
        "persons",
    )
    person_aliases = _bounded_scalars(
        db,
        select(PersonAlias)
        .where(PersonAlias.user_id == user_id)
        .order_by(PersonAlias.person_id, PersonAlias.normalized_alias, PersonAlias.id),
        "person_aliases",
    )
    aliases_by_person: dict[UUID, list[PersonAlias]] = {person.id: [] for person in persons}
    for alias in person_aliases:
        aliases_by_person.setdefault(alias.person_id, []).append(alias)

    objects = _bounded_scalars(
        db,
        select(ObjectItem)
        .where(ObjectItem.user_id == user_id)
        .order_by(ObjectItem.created_at, ObjectItem.id),
        "objects",
    )
    object_locations = _bounded_scalars(
        db,
        select(ObjectLocation)
        .where(ObjectLocation.user_id == user_id)
        .order_by(ObjectLocation.recorded_at, ObjectLocation.id),
        "object_locations",
    )
    # [人工注释][S1-020] 只针对本次已边界化的 ObjectLocation backing Memory
    # 做一次 owner-scoped 查询；被删除 Memory 的 UUID 不会直接进入导出，
    # 只用于决定该历史位置是否必须脱敏。
    location_memory_ids = {
        item.memory_id for item in object_locations if item.memory_id is not None
    }
    deleted_location_memory_ids: set[UUID] = set()
    if location_memory_ids:
        deleted_location_memory_ids = set(
            db.scalars(
                select(Memory.id).where(
                    Memory.user_id == user_id,
                    Memory.id.in_(location_memory_ids),
                    Memory.is_deleted.is_(True),
                )
            ).all()
        )
    location_points = _bounded_scalars(
        db,
        select(LocationPoint)
        .where(LocationPoint.user_id == user_id)
        .order_by(LocationPoint.recorded_at, LocationPoint.id),
        "location_points",
    )
    visits = _bounded_scalars(
        db,
        select(Visit)
        .where(Visit.user_id == user_id)
        .order_by(Visit.arrived_at, Visit.id),
        "visits",
    )
    places = _bounded_scalars(
        db,
        select(Place)
        .where(Place.user_id == user_id)
        .order_by(Place.created_at, Place.id),
        "places",
    )
    place_name_corrections = _bounded_scalars(
        db,
        select(PlaceNameCorrection)
        .where(PlaceNameCorrection.user_id == user_id)
        .order_by(PlaceNameCorrection.created_at, PlaceNameCorrection.id),
        "place_name_corrections",
    )
    location_derivation_state = db.get(LocationDerivationState, user_id)

    reminders = _bounded_scalars(
        db,
        select(Reminder)
        .where(Reminder.user_id == user_id)
        .order_by(Reminder.created_at, Reminder.id),
        "reminders",
    )
    pause_intervals = _bounded_scalars(
        db,
        select(PrivacyPauseInterval)
        .where(PrivacyPauseInterval.user_id == user_id)
        .order_by(PrivacyPauseInterval.started_at, PrivacyPauseInterval.id),
        "privacy_pause_intervals",
    )
    media_assets = _bounded_scalars(
        db,
        select(MediaAsset)
        .where(MediaAsset.user_id == user_id)
        .order_by(MediaAsset.created_at, MediaAsset.id),
        "media_assets",
    )
    media_links = _bounded_scalars(
        db,
        select(MediaEvidenceLink)
        .join(MediaAsset, MediaEvidenceLink.media_id == MediaAsset.id)
        .join(MemorySource, MediaEvidenceLink.memory_source_id == MemorySource.id)
        .join(Memory, MemorySource.memory_id == Memory.id)
        .where(
            MediaAsset.user_id == user_id,
            Memory.user_id == user_id,
            Memory.is_deleted.is_(False),
        )
        .order_by(MediaEvidenceLink.created_at, MediaEvidenceLink.id),
        "media_evidence_links",
    )
    privacy_state = db.get(PrivacyState, user_id)
    generated_at = datetime.now(UTC)

    # [人工注释][S1-020] 已删除 Memory / Evidence 不重新暴露；其 backing ObjectLocation
    # 仅保留脱敏后的失效历史；媒体只输出业务元数据，明确不序列化 upload/object key、
    # storage_etag、签名 URL 或凭证。
    payload: dict[str, Any] = {
        "format": EXPORT_FORMAT,
        "generated_at": generated_at,
        "profile": {
            "id": user.id,
            "nickname": user.nickname,
            "phone": user.phone,
            "email": user.email,
            "timezone": user.timezone,
            "locale": user.locale,
            "elder_mode_enabled": user.elder_mode_enabled,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
        },
        "memories": [_memory_payload(item) for item in memories],
        "memory_sources": [
            {
                "id": item.id,
                "memory_id": item.memory_id,
                "source_type": item.source_type.value,
                "source_id": item.source_id,
                "raw_text": item.raw_text,
                "confidence": item.confidence,
                "created_at": item.created_at,
            }
            for item in memory_sources
        ],
        "memory_edits": [
            {
                "id": item.id,
                "memory_id": item.memory_id,
                "revision": item.revision,
                "previous_title": item.previous_title,
                "previous_content": item.previous_content,
                "new_title": item.new_title,
                "new_content": item.new_content,
                "changed_title": item.changed_title,
                "changed_content": item.changed_content,
                "memory_source_id": item.memory_source_id,
                "created_at": item.created_at,
            }
            for item in memory_edits
        ],
        "people": [
            {
                "id": person.id,
                "display_name": person.display_name,
                "relationship_label": person.relationship_label,
                "note": person.note,
                "aliases": [
                    {
                        "id": alias.id,
                        "alias": alias.alias,
                        "created_at": alias.created_at,
                    }
                    for alias in aliases_by_person.get(person.id, [])
                ],
                "revision": person.revision,
                "created_at": person.created_at,
                "updated_at": person.updated_at,
            }
            for person in persons
        ],
        "objects": [
            {
                "id": item.id,
                "name": item.name,
                "category": item.category,
                "description": item.description,
                "created_at": item.created_at,
            }
            for item in objects
        ],
        "object_locations": [
            _object_location_payload(item, deleted_location_memory_ids)
            for item in object_locations
        ],
        # [人工注释][S2-006~S2-014] 导出同时保留 retention 内 raw evidence
        # 与长期 Visit/Place 派生事实；内部 cluster_key 不暴露为客户端稳定协议。
        "location": {
            "points": [
                {
                    "id": item.id,
                    "client_uuid": item.client_uuid,
                    "device_id": item.device_id,
                    "latitude": item.latitude,
                    "longitude": item.longitude,
                    "accuracy": item.accuracy,
                    "speed": item.speed,
                    "recorded_at": item.recorded_at,
                }
                for item in location_points
            ],
            "visits": [
                {
                    "id": item.id,
                    "place_id": item.place_id,
                    "arrived_at": item.arrived_at,
                    "left_at": item.left_at,
                    "duration_seconds": item.duration_seconds,
                    "confidence": item.confidence,
                    "source": item.source,
                    "centroid_latitude": item.centroid_latitude,
                    "centroid_longitude": item.centroid_longitude,
                    "source_point_count": item.source_point_count,
                    "source_started_at": item.source_started_at,
                    "source_ended_at": item.source_ended_at,
                    "source_fingerprint": item.source_fingerprint,
                    "algorithm_version": item.algorithm_version,
                    "finalized_at": item.finalized_at,
                }
                for item in visits
            ],
            "places": [
                {
                    "id": item.id,
                    "name": item.name,
                    "automatic_name": item.automatic_name,
                    "automatic_name_source": item.automatic_name_source,
                    "user_name": item.user_name,
                    "name_source": item.name_source,
                    "name_revision": item.name_revision,
                    "name_updated_at": item.name_updated_at,
                    "latitude": item.latitude,
                    "longitude": item.longitude,
                    "address": item.address,
                    "category": item.category,
                    "first_visited_at": item.first_visited_at,
                    "last_visited_at": item.last_visited_at,
                    "visit_count": item.visit_count,
                    "is_user_named": item.is_user_named,
                }
                for item in places
            ],
            # [人工注释][S2-010] 用户纠正历史本身也是 user-owned data；
            # 导出它才能解释当前 user_name 如何演变，同时不复制 Visit/GPS provenance。
            "place_name_corrections": [
                {
                    "id": item.id,
                    "place_id": item.place_id,
                    "client_uuid": item.client_uuid,
                    "revision": item.revision,
                    "previous_user_name": item.previous_user_name,
                    "new_user_name": item.new_user_name,
                    "created_at": item.created_at,
                }
                for item in place_name_corrections
            ],
            "finalized_through": (
                None
                if location_derivation_state is None
                else location_derivation_state.finalized_through
            ),
        },
        "reminders": [
            {
                "id": item.id,
                "memory_id": item.memory_id,
                "title": item.title,
                "content": item.content,
                "remind_at": item.remind_at,
                "status": item.status.value,
                "created_at": item.created_at,
            }
            for item in reminders
        ],
        "privacy": {
            "state": None
            if privacy_state is None
            else {
                "recording_paused_since": privacy_state.recording_paused_since,
                "recording_paused_until": privacy_state.recording_paused_until,
                "updated_at": privacy_state.updated_at,
            },
            "pause_intervals": [
                {
                    "id": item.id,
                    "started_at": item.started_at,
                    "ended_at": item.ended_at,
                    "created_at": item.created_at,
                }
                for item in pause_intervals
            ],
        },
        "media": {
            "assets": [
                {
                    "id": item.id,
                    "client_upload_id": item.client_upload_id,
                    "kind": item.kind.value,
                    "status": item.status.value,
                    "content_type": item.content_type,
                    "size_bytes": item.size_bytes,
                    "original_filename": item.original_filename,
                    "created_at": item.created_at,
                    "completed_at": item.completed_at,
                }
                for item in media_assets
            ],
            "evidence_links": [
                {
                    "id": item.id,
                    "media_id": item.media_id,
                    "memory_source_id": item.memory_source_id,
                    "created_at": item.created_at,
                }
                for item in media_links
            ],
        },
    }
    filename = generated_at.strftime("jiyidashi-export-v1-%Y%m%dT%H%M%SZ.json")
    return JSONResponse(
        content=jsonable_encoder(payload),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
