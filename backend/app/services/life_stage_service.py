from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.life_event_models import LifeEvent
from app.life_stage_models import LifeStage, LifeStageEventLink, LifeStageKind
from app.life_stage_schemas import (
    LifeStageCreate,
    LifeStageEventEvidenceRead,
    LifeStagePatch,
    LifeStageRead,
)


class LifeStageError(RuntimeError):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _same_datetime(left: datetime | None, right: datetime | None) -> bool:
    if left is None or right is None:
        return left is right
    return _as_utc(left) == _as_utc(right)


def _load_stage(
    db: Session,
    *,
    user_id: UUID,
    life_stage_id: UUID,
    for_update: bool,
) -> LifeStage:
    statement = select(LifeStage).where(
        LifeStage.id == life_stage_id,
        LifeStage.user_id == user_id,
    )
    if for_update:
        statement = statement.with_for_update()
    stage = db.scalar(statement)
    if stage is None:
        raise LifeStageError("LIFE_STAGE_NOT_FOUND", 404)
    return stage


def _load_event(
    db: Session,
    *,
    user_id: UUID,
    life_event_id: UUID,
    for_update: bool,
) -> LifeEvent:
    statement = select(LifeEvent).where(
        LifeEvent.id == life_event_id,
        LifeEvent.user_id == user_id,
    )
    if for_update:
        statement = statement.with_for_update()
    event = db.scalar(statement)
    if event is None:
        raise LifeStageError("LIFE_EVENT_NOT_FOUND", 404)
    return event


def _load_link(
    db: Session,
    *,
    user_id: UUID,
    life_stage_id: UUID,
    life_event_id: UUID,
    for_update: bool,
) -> LifeStageEventLink:
    statement = select(LifeStageEventLink).where(
        LifeStageEventLink.user_id == user_id,
        LifeStageEventLink.life_stage_id == life_stage_id,
        LifeStageEventLink.life_event_id == life_event_id,
    )
    if for_update:
        statement = statement.with_for_update()
    link = db.scalar(statement)
    if link is None:
        raise LifeStageError("LIFE_STAGE_EVENT_LINK_NOT_FOUND", 404)
    return link


def _validate_final_state(
    *,
    stage_kind: LifeStageKind,
    custom_label: str | None,
    started_at: datetime,
    ended_at: datetime | None,
) -> None:
    if stage_kind == LifeStageKind.OTHER:
        if custom_label is None:
            raise LifeStageError("LIFE_STAGE_CUSTOM_LABEL_REQUIRED", 422)
    elif custom_label is not None:
        raise LifeStageError("LIFE_STAGE_CUSTOM_LABEL_ONLY_FOR_OTHER", 422)

    if ended_at is not None and _as_utc(ended_at) < _as_utc(started_at):
        raise LifeStageError("LIFE_STAGE_TIME_RANGE_INVALID", 422)


def life_stage_read(stage: LifeStage) -> LifeStageRead:
    return LifeStageRead(
        id=stage.id,
        stage_kind=stage.stage_kind,
        title=stage.title,
        custom_label=stage.custom_label,
        note=stage.note,
        started_at=stage.started_at,
        ended_at=stage.ended_at,
        revision=stage.revision,
        created_at=stage.created_at,
        updated_at=stage.updated_at,
    )


def create_life_stage(
    db: Session,
    *,
    user_id: UUID,
    payload: LifeStageCreate,
) -> LifeStage:
    # V2-006 intentionally does not query other LifeStage rows. Overlap,
    # same-kind overlap and multiple open-ended stages are explicit user authority.
    stage = LifeStage(
        user_id=user_id,
        stage_kind=payload.stage_kind,
        title=payload.title,
        custom_label=payload.custom_label,
        note=payload.note,
        started_at=payload.started_at,
        ended_at=payload.ended_at,
        revision=0,
    )
    db.add(stage)
    db.commit()
    db.refresh(stage)
    return stage


def list_life_stages(
    db: Session,
    *,
    user_id: UUID,
    limit: int,
) -> list[LifeStage]:
    return list(
        db.scalars(
            select(LifeStage)
            .where(LifeStage.user_id == user_id)
            .order_by(LifeStage.started_at.desc(), LifeStage.id.desc())
            .limit(limit)
        )
    )


def get_life_stage(
    db: Session,
    *,
    user_id: UUID,
    life_stage_id: UUID,
) -> LifeStage:
    return _load_stage(
        db,
        user_id=user_id,
        life_stage_id=life_stage_id,
        for_update=False,
    )


def patch_life_stage(
    db: Session,
    *,
    user_id: UUID,
    life_stage_id: UUID,
    payload: LifeStagePatch,
) -> LifeStage:
    stage = _load_stage(
        db,
        user_id=user_id,
        life_stage_id=life_stage_id,
        for_update=True,
    )
    if stage.revision != payload.expected_revision:
        db.rollback()
        raise LifeStageError("LIFE_STAGE_REVISION_CONFLICT", 409)

    fields = payload.model_fields_set
    final_kind = payload.stage_kind if "stage_kind" in fields else stage.stage_kind
    final_title = payload.title if "title" in fields else stage.title
    final_note = payload.note if "note" in fields else stage.note
    final_started_at = (
        payload.started_at if "started_at" in fields else stage.started_at
    )
    final_ended_at = payload.ended_at if "ended_at" in fields else stage.ended_at

    if "custom_label" in fields:
        final_custom_label = payload.custom_label
    elif final_kind != LifeStageKind.OTHER and stage.stage_kind == LifeStageKind.OTHER:
        final_custom_label = None
    else:
        final_custom_label = stage.custom_label

    assert final_kind is not None
    assert final_title is not None
    assert final_started_at is not None
    _validate_final_state(
        stage_kind=final_kind,
        custom_label=final_custom_label,
        started_at=final_started_at,
        ended_at=final_ended_at,
    )

    changed = (
        final_kind != stage.stage_kind
        or final_title != stage.title
        or final_custom_label != stage.custom_label
        or final_note != stage.note
        or not _same_datetime(final_started_at, stage.started_at)
        or not _same_datetime(final_ended_at, stage.ended_at)
    )
    if not changed:
        db.commit()
        return stage

    stage.stage_kind = final_kind
    stage.title = final_title
    stage.custom_label = final_custom_label
    stage.note = final_note
    stage.started_at = final_started_at
    stage.ended_at = final_ended_at
    stage.revision += 1
    stage.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(stage)
    return stage


def delete_life_stage(
    db: Session,
    *,
    user_id: UUID,
    life_stage_id: UUID,
) -> None:
    stage = _load_stage(
        db,
        user_id=user_id,
        life_stage_id=life_stage_id,
        for_update=True,
    )
    db.execute(
        delete(LifeStageEventLink).where(
            LifeStageEventLink.user_id == user_id,
            LifeStageEventLink.life_stage_id == life_stage_id,
        )
    )
    db.delete(stage)
    db.commit()


def _event_evidence_read(
    link: LifeStageEventLink,
    event: LifeEvent,
) -> LifeStageEventEvidenceRead:
    return LifeStageEventEvidenceRead(
        link_id=link.id,
        life_event_id=event.id,
        event_kind=event.event_kind,
        title=event.title,
        custom_label=event.custom_label,
        note=event.note,
        started_at=event.started_at,
        ended_at=event.ended_at,
        place_id=event.place_id,
        created_at=link.created_at,
    )


def create_life_stage_event_link(
    db: Session,
    *,
    user_id: UUID,
    life_stage_id: UUID,
    life_event_id: UUID,
) -> LifeStageEventEvidenceRead:
    # Canonical mixed-authority lock order is LifeEvent -> LifeStage -> Link.
    # This serializes evidence creation against LifeEvent DELETE without adding
    # any temporal-overlap inference.
    event = _load_event(
        db,
        user_id=user_id,
        life_event_id=life_event_id,
        for_update=True,
    )
    _load_stage(
        db,
        user_id=user_id,
        life_stage_id=life_stage_id,
        for_update=True,
    )

    existing = db.scalar(
        select(LifeStageEventLink)
        .where(
            LifeStageEventLink.user_id == user_id,
            LifeStageEventLink.life_stage_id == life_stage_id,
            LifeStageEventLink.life_event_id == life_event_id,
        )
        .with_for_update()
    )
    if existing is not None:
        db.commit()
        return _event_evidence_read(existing, event)

    link = LifeStageEventLink(
        user_id=user_id,
        life_stage_id=life_stage_id,
        life_event_id=life_event_id,
    )
    db.add(link)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        current = db.scalar(
            select(LifeStageEventLink).where(
                LifeStageEventLink.user_id == user_id,
                LifeStageEventLink.life_stage_id == life_stage_id,
                LifeStageEventLink.life_event_id == life_event_id,
            )
        )
        if current is not None:
            current_event = _load_event(
                db,
                user_id=user_id,
                life_event_id=life_event_id,
                for_update=False,
            )
            return _event_evidence_read(current, current_event)
        raise LifeStageError("LIFE_STAGE_EVENT_LINK_CONFLICT", 409) from exc
    db.refresh(link)
    return _event_evidence_read(link, event)


def list_life_stage_events(
    db: Session,
    *,
    user_id: UUID,
    life_stage_id: UUID,
    limit: int,
) -> list[LifeStageEventEvidenceRead]:
    _load_stage(
        db,
        user_id=user_id,
        life_stage_id=life_stage_id,
        for_update=False,
    )
    rows = db.execute(
        select(LifeStageEventLink, LifeEvent)
        .join(
            LifeEvent,
            (LifeEvent.id == LifeStageEventLink.life_event_id)
            & (LifeEvent.user_id == LifeStageEventLink.user_id),
        )
        .where(
            LifeStageEventLink.user_id == user_id,
            LifeStageEventLink.life_stage_id == life_stage_id,
        )
        .order_by(
            LifeEvent.started_at.desc(),
            LifeEvent.id.desc(),
            LifeStageEventLink.id.desc(),
        )
        .limit(limit)
    ).all()
    return [_event_evidence_read(link, event) for link, event in rows]


def delete_life_stage_event_link(
    db: Session,
    *,
    user_id: UUID,
    life_stage_id: UUID,
    life_event_id: UUID,
) -> None:
    _load_event(
        db,
        user_id=user_id,
        life_event_id=life_event_id,
        for_update=True,
    )
    _load_stage(
        db,
        user_id=user_id,
        life_stage_id=life_stage_id,
        for_update=True,
    )
    link = _load_link(
        db,
        user_id=user_id,
        life_stage_id=life_stage_id,
        life_event_id=life_event_id,
        for_update=True,
    )
    db.delete(link)
    db.commit()
