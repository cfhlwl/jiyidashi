from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session

from app.account_deletion_models import AccountDeletionOperation
from app.core.config import Settings, get_settings
from app.core.db import SessionLocal
from app.data_deletion_models import DataDeletionOperation, DataDeletionStatus
from app.export_models import UserExportJob, UserExportStatus
from app.life_event_models import LifeEvent, LifeEventMemoryLink
from app.life_stage_models import LifeStage, LifeStageEventLink
from app.media_models import MediaAsset, MediaEvidenceLink
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
from app.person_memory_models import PersonMemoryLink
from app.person_models import Person, PersonAlias
from app.person_relationship_models import PersonRelationship
from app.services.object_storage import ObjectStorage, ObjectStorageError

EXPORT_FORMAT = "jiyidashi.user-export.v1"
EXPORT_CONTENT_TYPE = "application/json"
EXPORT_TEMP_PREFIX = "jiyidashi-export-"


class ExportExecutionError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class ExportSuperseded(ExportExecutionError):
    def __init__(self):
        super().__init__("EXPORT_AUTHORITY_LOST", retryable=False)


@dataclass(frozen=True)
class GeneratedExport:
    path: str
    size_bytes: int
    sha256: str


class _BoundedWriter:
    def __init__(self, handle, *, max_bytes: int):
        self._handle = handle
        self._max_bytes = max_bytes
        self.size_bytes = 0
        self._digest = hashlib.sha256()

    @property
    def sha256(self) -> str:
        return self._digest.hexdigest()

    def write(self, value: str | bytes) -> None:
        data = value.encode("utf-8") if isinstance(value, str) else value
        next_size = self.size_bytes + len(data)
        if next_size > self._max_bytes:
            raise ExportExecutionError("EXPORT_ARTIFACT_TOO_LARGE", retryable=False)
        self._handle.write(data)
        self._digest.update(data)
        self.size_bytes = next_size

    def json(self, value: Any) -> None:
        self.write(
            json.dumps(
                jsonable_encoder(value),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=False,
            )
        )


def export_object_prefix(owner_user_id: UUID, job_id: UUID | None = None) -> str:
    root = get_settings().storage_object_prefix.strip("/") or "media"
    base = f"{root}/_exports/{owner_user_id}/"
    return base if job_id is None else f"{base}{job_id}/"


def export_attempt_object_key(
    *,
    owner_user_id: UUID,
    job_id: UUID,
    revision: int,
    attempt_token: UUID,
) -> str:
    return (
        export_object_prefix(owner_user_id, job_id)
        + f"r{revision}-{attempt_token}.json"
    )


def _serialize_memory(memory: Memory) -> dict[str, Any]:
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


def _iter_keyset(
    db: Session,
    statement: Select,
    *,
    first_column,
    id_column,
    batch_size: int,
    authority_check: Callable[[], None],
) -> Iterator[Any]:
    last_first = None
    last_id = None
    while True:
        authority_check()
        page = statement
        if last_id is not None:
            page = page.where(
                or_(
                    first_column > last_first,
                    and_(first_column == last_first, id_column > last_id),
                )
            )
        rows = list(
            db.scalars(
                page.order_by(first_column, id_column).limit(batch_size)
            )
        )
        if not rows:
            return
        for row in rows:
            yield row
        tail = rows[-1]
        last_first = getattr(tail, first_column.key)
        last_id = getattr(tail, id_column.key)
        if len(rows) < batch_size:
            return


def _write_array(
    writer: _BoundedWriter,
    rows: Iterator[Any],
    serializer: Callable[[Any], Any],
) -> None:
    writer.write("[")
    first = True
    for row in rows:
        if not first:
            writer.write(",")
        writer.json(serializer(row))
        first = False
    writer.write("]")


def _deleted_backing_memory(db: Session, owner_user_id: UUID, memory_id: UUID) -> bool:
    return bool(
        db.scalar(
            select(Memory.is_deleted).where(
                Memory.id == memory_id,
                Memory.user_id == owner_user_id,
            )
        )
    )


def _serialize_object_location(
    db: Session,
    owner_user_id: UUID,
    item: ObjectLocation,
) -> dict[str, Any]:
    redacted = (
        item.memory_id is not None
        and _deleted_backing_memory(db, owner_user_id, item.memory_id)
    )
    if redacted:
        return {
            "id": item.id,
            "object_id": item.object_id,
            "memory_id": None,
            "location_text": None,
            "place_id": None,
            "recorded_at": item.recorded_at,
            "confidence": None,
            "status": ObjectLocationStatus.STALE.value,
            "redacted": True,
            "redaction_reason": "BACKING_MEMORY_DELETED",
        }
    return {
        "id": item.id,
        "object_id": item.object_id,
        "memory_id": item.memory_id,
        "location_text": item.location_text,
        "place_id": item.place_id,
        "recorded_at": item.recorded_at,
        "confidence": item.confidence,
        "status": item.status.value,
        "redacted": False,
        "redaction_reason": None,
    }


def _write_people(
    writer: _BoundedWriter,
    db: Session,
    *,
    owner_user_id: UUID,
    batch_size: int,
    authority_check: Callable[[], None],
) -> None:
    writer.write("[")
    first_person = True
    people = _iter_keyset(
        db,
        select(Person).where(Person.user_id == owner_user_id),
        first_column=Person.created_at,
        id_column=Person.id,
        batch_size=batch_size,
        authority_check=authority_check,
    )
    for person in people:
        if not first_person:
            writer.write(",")
        writer.write("{")
        fields = [
            ("id", person.id),
            ("display_name", person.display_name),
            ("relationship_label", person.relationship_label),
            ("note", person.note),
        ]
        for index, (name, value) in enumerate(fields):
            if index:
                writer.write(",")
            writer.json(name)
            writer.write(":")
            writer.json(value)
        writer.write(',"aliases":')
        aliases = _iter_keyset(
            db,
            select(PersonAlias).where(
                PersonAlias.user_id == owner_user_id,
                PersonAlias.person_id == person.id,
            ),
            first_column=PersonAlias.normalized_alias,
            id_column=PersonAlias.id,
            batch_size=batch_size,
            authority_check=authority_check,
        )
        _write_array(writer, aliases, lambda alias: alias.alias)
        for name, value in (
            ("revision", person.revision),
            ("created_at", person.created_at),
            ("updated_at", person.updated_at),
        ):
            writer.write(",")
            writer.json(name)
            writer.write(":")
            writer.json(value)
        writer.write("}")
        first_person = False
    writer.write("]")


def _ensure_export_owner_active(db: Session, owner_user_id: UUID) -> None:
    if db.get(User, owner_user_id) is None:
        raise ExportSuperseded()
    active_data_delete = db.scalar(
        select(DataDeletionOperation.id)
        .where(
            DataDeletionOperation.user_id == owner_user_id,
            DataDeletionOperation.status != DataDeletionStatus.COMPLETED,
        )
        .limit(1)
    )
    active_account_delete = db.scalar(
        select(AccountDeletionOperation.id)
        .where(AccountDeletionOperation.user_id == owner_user_id)
        .limit(1)
    )
    if active_data_delete is not None or active_account_delete is not None:
        raise ExportSuperseded()


def generate_export_file(
    *,
    owner_user_id: UUID,
    authority_check: Callable[[], None],
    settings: Settings | None = None,
) -> GeneratedExport:
    cfg = settings or get_settings()
    fd, path = tempfile.mkstemp(prefix=EXPORT_TEMP_PREFIX, suffix=".json")
    os.close(fd)

    try:
        with open(path, "wb", buffering=0) as handle:
            writer = _BoundedWriter(
                handle,
                max_bytes=cfg.export_artifact_max_bytes,
            )
            with SessionLocal() as db:
                if db.get_bind().dialect.name == "postgresql":
                    db.connection(
                        execution_options={"isolation_level": "REPEATABLE READ"}
                    )
                _ensure_export_owner_active(db, owner_user_id)
                user = db.get(User, owner_user_id)
                if user is None:
                    raise ExportSuperseded()
                generated_at = datetime.now(UTC)
                batch = cfg.export_batch_size

                writer.write("{")
                writer.json("format")
                writer.write(":")
                writer.json(EXPORT_FORMAT)
                writer.write(",")
                writer.json("generated_at")
                writer.write(":")
                writer.json(generated_at)
                writer.write(",")
                writer.json("profile")
                writer.write(":")
                writer.json(
                    {
                        "id": user.id,
                        "nickname": user.nickname,
                        "phone": user.phone,
                        "email": user.email,
                        "timezone": user.timezone,
                        "locale": user.locale,
                        "elder_mode_enabled": user.elder_mode_enabled,
                        "created_at": user.created_at,
                        "updated_at": user.updated_at,
                    }
                )

                writer.write(',"memories":')
                _write_array(
                    writer,
                    _iter_keyset(
                        db,
                        select(Memory).where(
                            Memory.user_id == owner_user_id,
                            Memory.is_deleted.is_(False),
                        ),
                        first_column=Memory.occurred_at,
                        id_column=Memory.id,
                        batch_size=batch,
                        authority_check=authority_check,
                    ),
                    _serialize_memory,
                )

                writer.write(',"memory_sources":')
                _write_array(
                    writer,
                    _iter_keyset(
                        db,
                        select(MemorySource)
                        .join(Memory, MemorySource.memory_id == Memory.id)
                        .where(
                            Memory.user_id == owner_user_id,
                            Memory.is_deleted.is_(False),
                        ),
                        first_column=MemorySource.created_at,
                        id_column=MemorySource.id,
                        batch_size=batch,
                        authority_check=authority_check,
                    ),
                    lambda item: {
                        "id": item.id,
                        "memory_id": item.memory_id,
                        "source_type": item.source_type.value,
                        "source_id": item.source_id,
                        "raw_text": item.raw_text,
                        "confidence": item.confidence,
                        "created_at": item.created_at,
                    },
                )

                writer.write(',"memory_edits":')
                _write_array(
                    writer,
                    _iter_keyset(
                        db,
                        select(MemoryEdit)
                        .join(Memory, MemoryEdit.memory_id == Memory.id)
                        .where(
                            Memory.user_id == owner_user_id,
                            Memory.is_deleted.is_(False),
                        ),
                        first_column=MemoryEdit.created_at,
                        id_column=MemoryEdit.id,
                        batch_size=batch,
                        authority_check=authority_check,
                    ),
                    lambda item: {
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
                    },
                )

                writer.write(',"people":')
                _write_people(
                    writer,
                    db,
                    owner_user_id=owner_user_id,
                    batch_size=batch,
                    authority_check=authority_check,
                )

                writer.write(',"person_relationships":')
                _write_array(
                    writer,
                    _iter_keyset(
                        db,
                        select(PersonRelationship).where(
                            PersonRelationship.user_id == owner_user_id
                        ),
                        first_column=PersonRelationship.created_at,
                        id_column=PersonRelationship.id,
                        batch_size=batch,
                        authority_check=authority_check,
                    ),
                    lambda edge: {
                        "id": edge.id,
                        "person_a_id": edge.person_low_id,
                        "person_b_id": edge.person_high_id,
                        "relationship_kind": edge.relationship_kind.value,
                        "custom_label": edge.custom_label,
                        "note": edge.note,
                        "revision": edge.revision,
                        "created_at": edge.created_at,
                        "updated_at": edge.updated_at,
                    },
                )

                writer.write(',"person_memory_links":')
                _write_array(
                    writer,
                    _iter_keyset(
                        db,
                        select(PersonMemoryLink)
                        .join(
                            Memory,
                            and_(
                                Memory.id == PersonMemoryLink.memory_id,
                                Memory.user_id == PersonMemoryLink.user_id,
                            ),
                        )
                        .join(
                            Person,
                            and_(
                                Person.id == PersonMemoryLink.person_id,
                                Person.user_id == PersonMemoryLink.user_id,
                            ),
                        )
                        .where(
                            PersonMemoryLink.user_id == owner_user_id,
                            Memory.is_deleted.is_(False),
                        ),
                        first_column=PersonMemoryLink.created_at,
                        id_column=PersonMemoryLink.id,
                        batch_size=batch,
                        authority_check=authority_check,
                    ),
                    lambda link: {
                        "id": link.id,
                        "person_id": link.person_id,
                        "memory_id": link.memory_id,
                        "relation_kind": link.relation_kind.value,
                        "revision": link.revision,
                        "created_at": link.created_at,
                        "updated_at": link.updated_at,
                    },
                )

                writer.write(',"life_events":')
                _write_array(
                    writer,
                    _iter_keyset(
                        db,
                        select(LifeEvent).where(LifeEvent.user_id == owner_user_id),
                        first_column=LifeEvent.started_at,
                        id_column=LifeEvent.id,
                        batch_size=batch,
                        authority_check=authority_check,
                    ),
                    lambda event: {
                        "id": event.id,
                        "event_kind": event.event_kind.value,
                        "title": event.title,
                        "custom_label": event.custom_label,
                        "note": event.note,
                        "started_at": event.started_at,
                        "ended_at": event.ended_at,
                        "place_id": event.place_id,
                        "revision": event.revision,
                        "created_at": event.created_at,
                        "updated_at": event.updated_at,
                    },
                )

                writer.write(',"life_event_memory_links":')
                _write_array(
                    writer,
                    _iter_keyset(
                        db,
                        select(LifeEventMemoryLink)
                        .join(
                            Memory,
                            and_(
                                Memory.id == LifeEventMemoryLink.memory_id,
                                Memory.user_id == LifeEventMemoryLink.user_id,
                            ),
                        )
                        .where(
                            LifeEventMemoryLink.user_id == owner_user_id,
                            Memory.is_deleted.is_(False),
                            Memory.is_confirmed.is_(True),
                        ),
                        first_column=LifeEventMemoryLink.created_at,
                        id_column=LifeEventMemoryLink.id,
                        batch_size=batch,
                        authority_check=authority_check,
                    ),
                    lambda link: {
                        "id": link.id,
                        "life_event_id": link.life_event_id,
                        "memory_id": link.memory_id,
                        "created_at": link.created_at,
                    },
                )

                writer.write(',"life_stages":')
                _write_array(
                    writer,
                    _iter_keyset(
                        db,
                        select(LifeStage).where(LifeStage.user_id == owner_user_id),
                        first_column=LifeStage.started_at,
                        id_column=LifeStage.id,
                        batch_size=batch,
                        authority_check=authority_check,
                    ),
                    lambda stage: {
                        "id": stage.id,
                        "stage_kind": stage.stage_kind.value,
                        "title": stage.title,
                        "custom_label": stage.custom_label,
                        "note": stage.note,
                        "started_at": stage.started_at,
                        "ended_at": stage.ended_at,
                        "revision": stage.revision,
                        "created_at": stage.created_at,
                        "updated_at": stage.updated_at,
                    },
                )

                writer.write(',"life_stage_event_links":')
                _write_array(
                    writer,
                    _iter_keyset(
                        db,
                        select(LifeStageEventLink)
                        .join(
                            LifeEvent,
                            and_(
                                LifeEvent.id == LifeStageEventLink.life_event_id,
                                LifeEvent.user_id == LifeStageEventLink.user_id,
                            ),
                        )
                        .where(LifeStageEventLink.user_id == owner_user_id),
                        first_column=LifeStageEventLink.created_at,
                        id_column=LifeStageEventLink.id,
                        batch_size=batch,
                        authority_check=authority_check,
                    ),
                    lambda link: {
                        "id": link.id,
                        "life_stage_id": link.life_stage_id,
                        "life_event_id": link.life_event_id,
                        "created_at": link.created_at,
                    },
                )

                writer.write(',"objects":')
                _write_array(
                    writer,
                    _iter_keyset(
                        db,
                        select(ObjectItem).where(ObjectItem.user_id == owner_user_id),
                        first_column=ObjectItem.created_at,
                        id_column=ObjectItem.id,
                        batch_size=batch,
                        authority_check=authority_check,
                    ),
                    lambda item: {
                        "id": item.id,
                        "name": item.name,
                        "category": item.category,
                        "description": item.description,
                        "created_at": item.created_at,
                    },
                )

                writer.write(',"object_locations":')
                _write_array(
                    writer,
                    _iter_keyset(
                        db,
                        select(ObjectLocation).where(
                            ObjectLocation.user_id == owner_user_id
                        ),
                        first_column=ObjectLocation.recorded_at,
                        id_column=ObjectLocation.id,
                        batch_size=batch,
                        authority_check=authority_check,
                    ),
                    lambda item: _serialize_object_location(
                        db,
                        owner_user_id,
                        item,
                    ),
                )

                writer.write(',"location":{"points":')
                _write_array(
                    writer,
                    _iter_keyset(
                        db,
                        select(LocationPoint).where(
                            LocationPoint.user_id == owner_user_id
                        ),
                        first_column=LocationPoint.recorded_at,
                        id_column=LocationPoint.id,
                        batch_size=batch,
                        authority_check=authority_check,
                    ),
                    lambda item: {
                        "id": item.id,
                        "client_uuid": item.client_uuid,
                        "device_id": item.device_id,
                        "latitude": item.latitude,
                        "longitude": item.longitude,
                        "accuracy": item.accuracy,
                        "speed": item.speed,
                        "recorded_at": item.recorded_at,
                    },
                )
                writer.write(',"visits":')
                _write_array(
                    writer,
                    _iter_keyset(
                        db,
                        select(Visit).where(Visit.user_id == owner_user_id),
                        first_column=Visit.arrived_at,
                        id_column=Visit.id,
                        batch_size=batch,
                        authority_check=authority_check,
                    ),
                    lambda item: {
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
                    },
                )
                writer.write(',"places":')
                _write_array(
                    writer,
                    _iter_keyset(
                        db,
                        select(Place).where(Place.user_id == owner_user_id),
                        first_column=Place.created_at,
                        id_column=Place.id,
                        batch_size=batch,
                        authority_check=authority_check,
                    ),
                    lambda item: {
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
                    },
                )
                writer.write(',"place_name_corrections":')
                _write_array(
                    writer,
                    _iter_keyset(
                        db,
                        select(PlaceNameCorrection).where(
                            PlaceNameCorrection.user_id == owner_user_id
                        ),
                        first_column=PlaceNameCorrection.created_at,
                        id_column=PlaceNameCorrection.id,
                        batch_size=batch,
                        authority_check=authority_check,
                    ),
                    lambda item: {
                        "id": item.id,
                        "place_id": item.place_id,
                        "client_uuid": item.client_uuid,
                        "revision": item.revision,
                        "previous_user_name": item.previous_user_name,
                        "new_user_name": item.new_user_name,
                        "created_at": item.created_at,
                    },
                )
                derivation = db.get(LocationDerivationState, owner_user_id)
                writer.write(',"finalized_through":')
                writer.json(
                    None if derivation is None else derivation.finalized_through
                )
                writer.write("}")

                writer.write(',"reminders":')
                _write_array(
                    writer,
                    _iter_keyset(
                        db,
                        select(Reminder).where(Reminder.user_id == owner_user_id),
                        first_column=Reminder.created_at,
                        id_column=Reminder.id,
                        batch_size=batch,
                        authority_check=authority_check,
                    ),
                    lambda item: {
                        "id": item.id,
                        "memory_id": item.memory_id,
                        "title": item.title,
                        "content": item.content,
                        "remind_at": item.remind_at,
                        "status": item.status.value,
                        "created_at": item.created_at,
                    },
                )

                privacy = db.get(PrivacyState, owner_user_id)
                writer.write(',"privacy":{"state":')
                writer.json(
                    None
                    if privacy is None
                    else {
                        "recording_paused_since": privacy.recording_paused_since,
                        "recording_paused_until": privacy.recording_paused_until,
                        "updated_at": privacy.updated_at,
                    }
                )
                writer.write(',"pause_intervals":')
                _write_array(
                    writer,
                    _iter_keyset(
                        db,
                        select(PrivacyPauseInterval).where(
                            PrivacyPauseInterval.user_id == owner_user_id
                        ),
                        first_column=PrivacyPauseInterval.started_at,
                        id_column=PrivacyPauseInterval.id,
                        batch_size=batch,
                        authority_check=authority_check,
                    ),
                    lambda item: {
                        "id": item.id,
                        "started_at": item.started_at,
                        "ended_at": item.ended_at,
                        "created_at": item.created_at,
                    },
                )
                writer.write("}")

                writer.write(',"media":{"assets":')
                _write_array(
                    writer,
                    _iter_keyset(
                        db,
                        select(MediaAsset).where(
                            MediaAsset.user_id == owner_user_id
                        ),
                        first_column=MediaAsset.created_at,
                        id_column=MediaAsset.id,
                        batch_size=batch,
                        authority_check=authority_check,
                    ),
                    lambda item: {
                        "id": item.id,
                        "client_upload_id": item.client_upload_id,
                        "kind": item.kind.value,
                        "status": item.status.value,
                        "content_type": item.content_type,
                        "size_bytes": item.size_bytes,
                        "original_filename": item.original_filename,
                        "created_at": item.created_at,
                        "completed_at": item.completed_at,
                    },
                )
                writer.write(',"evidence_links":')
                _write_array(
                    writer,
                    _iter_keyset(
                        db,
                        select(MediaEvidenceLink)
                        .join(MediaAsset, MediaEvidenceLink.media_id == MediaAsset.id)
                        .join(
                            MemorySource,
                            MediaEvidenceLink.memory_source_id == MemorySource.id,
                        )
                        .join(Memory, MemorySource.memory_id == Memory.id)
                        .where(
                            MediaAsset.user_id == owner_user_id,
                            Memory.user_id == owner_user_id,
                            Memory.is_deleted.is_(False),
                        ),
                        first_column=MediaEvidenceLink.created_at,
                        id_column=MediaEvidenceLink.id,
                        batch_size=batch,
                        authority_check=authority_check,
                    ),
                    lambda item: {
                        "id": item.id,
                        "media_id": item.media_id,
                        "memory_source_id": item.memory_source_id,
                        "created_at": item.created_at,
                    },
                )
                writer.write("}}")
                authority_check()
                db.rollback()

            return GeneratedExport(
                path=path,
                size_bytes=writer.size_bytes,
                sha256=writer.sha256,
            )
    except BaseException:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        raise


def begin_export_attempt(
    *,
    job_id: UUID,
    owner_user_id: UUID,
) -> int | None:
    with SessionLocal() as db:
        job = db.scalar(
            select(UserExportJob)
            .where(
                UserExportJob.id == job_id,
                UserExportJob.owner_user_id == owner_user_id,
            )
            .with_for_update()
        )
        if job is None:
            db.rollback()
            return None
        if job.status in {
            UserExportStatus.COMPLETED.value,
            UserExportStatus.CANCELLED.value,
            UserExportStatus.EXPIRED.value,
        }:
            db.rollback()
            return None
        _ensure_export_owner_active(db, owner_user_id)
        job.status = UserExportStatus.RUNNING.value
        job.started_at = job.started_at or datetime.now(UTC)
        job.error_code = None
        job.revision += 1
        revision = job.revision
        db.commit()
        return revision


def publish_export_artifact(
    *,
    job_id: UUID,
    owner_user_id: UUID,
    revision: int,
    object_key: str,
    size_bytes: int,
    sha256: str,
    settings: Settings | None = None,
) -> bool:
    cfg = settings or get_settings()
    with SessionLocal() as db:
        job = db.scalar(
            select(UserExportJob)
            .where(
                UserExportJob.id == job_id,
                UserExportJob.owner_user_id == owner_user_id,
            )
            .with_for_update()
        )
        if (
            job is None
            or job.status != UserExportStatus.RUNNING.value
            or job.revision != revision
        ):
            db.rollback()
            return False
        _ensure_export_owner_active(db, owner_user_id)
        now = datetime.now(UTC)
        job.status = UserExportStatus.COMPLETED.value
        job.artifact_object_key = object_key
        job.artifact_size_bytes = size_bytes
        job.artifact_sha256 = sha256
        job.completed_at = now
        job.expires_at = now + timedelta(hours=cfg.export_artifact_ttl_hours)
        job.error_code = None
        job.revision += 1
        db.commit()
        return True


def mark_export_attempt_failed(
    *,
    job_id: UUID,
    owner_user_id: UUID,
    revision: int,
    error_code: str,
    terminal: bool,
) -> None:
    with SessionLocal() as db:
        job = db.scalar(
            select(UserExportJob)
            .where(
                UserExportJob.id == job_id,
                UserExportJob.owner_user_id == owner_user_id,
            )
            .with_for_update()
        )
        if (
            job is None
            or job.status != UserExportStatus.RUNNING.value
            or job.revision != revision
        ):
            db.rollback()
            return
        job.status = (
            UserExportStatus.FAILED.value
            if terminal
            else UserExportStatus.PENDING.value
        )
        job.error_code = error_code[:80]
        job.revision += 1
        db.commit()


def cleanup_export_artifact(
    *,
    job_id: UUID,
    owner_user_id: UUID,
    storage: ObjectStorage,
    authority_check: Callable[[], None],
) -> None:
    with SessionLocal() as db:
        job = db.scalar(
            select(UserExportJob)
            .where(
                UserExportJob.id == job_id,
                UserExportJob.owner_user_id == owner_user_id,
            )
            .with_for_update()
        )
        if job is None:
            db.rollback()
            return
        now = datetime.now(UTC)
        if (
            job.status == UserExportStatus.COMPLETED.value
            and job.expires_at is not None
            and job.expires_at > now
        ):
            db.rollback()
            raise ExportExecutionError("EXPORT_ARTIFACT_NOT_EXPIRED", retryable=True)
        published_key = job.artifact_object_key
        revision = job.revision
        db.rollback()

    prefix = export_object_prefix(owner_user_id, job_id)
    authority_check()
    for key in storage.iter_object_keys(prefix):
        authority_check()
        storage.delete_object(key)

    with SessionLocal() as db:
        job = db.scalar(
            select(UserExportJob)
            .where(
                UserExportJob.id == job_id,
                UserExportJob.owner_user_id == owner_user_id,
            )
            .with_for_update()
        )
        if job is None:
            db.rollback()
            return
        if job.revision != revision:
            db.rollback()
            raise ExportSuperseded()
        if published_key is not None and job.artifact_object_key != published_key:
            db.rollback()
            raise ExportSuperseded()
        job.status = UserExportStatus.EXPIRED.value
        job.artifact_object_key = None
        job.artifact_size_bytes = None
        job.artifact_sha256 = None
        job.error_code = None
        job.revision += 1
        db.commit()


def remove_temp_file(path: str | None) -> None:
    if not path:
        return
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def cleanup_stale_local_exports(*, older_than_seconds: int = 24 * 60 * 60) -> int:
    root = Path(tempfile.gettempdir())
    cutoff = datetime.now(UTC).timestamp() - older_than_seconds
    removed = 0
    for candidate in root.glob(f"{EXPORT_TEMP_PREFIX}*.json"):
        try:
            if candidate.stat().st_mtime < cutoff:
                candidate.unlink()
                removed += 1
        except FileNotFoundError:
            continue
    return removed
