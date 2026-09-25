from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import IntEnum
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.family_models import (
    FamilyArrivalReminder,
    FamilyArrivalReminderStatus,
    FamilyMembership,
)
from app.models import Place, Visit
from app.services.privacy_service import ensure_utc, pause_intervals_for_range


class ArrivalReminderValidity(IntEnum):
    MINUTES_120 = 120
    MINUTES_360 = 360
    MINUTES_720 = 720


SUPPORTED_ARRIVAL_VALIDITIES = frozenset(item.value for item in ArrivalReminderValidity)
ARRIVAL_REMINDER_LIST_LIMIT = 50


class FamilyArrivalReminderError(RuntimeError):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class FamilyArrivalReminderView:
    reminder_id: UUID
    resource_owner_user_id: UUID
    grantee_user_id: UUID
    destination_place_id: UUID
    destination_display_name: str
    status: str
    created_at: datetime
    expires_at: datetime
    arrived_at: datetime | None
    direction: str


def _reference_now(now: datetime | None) -> datetime:
    return ensure_utc(now or datetime.now(UTC))


def _lock_membership_pair(
    db: Session,
    *,
    first_user_id: UUID,
    second_user_id: UUID,
) -> dict[UUID, UUID]:
    rows = db.execute(
        select(FamilyMembership.user_id, FamilyMembership.family_id)
        .where(FamilyMembership.user_id.in_((first_user_id, second_user_id)))
        .order_by(FamilyMembership.user_id.asc())
        .with_for_update()
    ).all()
    return {row.user_id: row.family_id for row in rows}


def _expire_locked(reminder: FamilyArrivalReminder, *, now: datetime) -> None:
    if (
        reminder.status == FamilyArrivalReminderStatus.ACTIVE.value
        and ensure_utc(reminder.expires_at) <= now
    ):
        reminder.status = FamilyArrivalReminderStatus.EXPIRED.value


def _destination_name(db: Session, reminder: FamilyArrivalReminder) -> str:
    name = db.scalar(
        select(Place.name).where(
            Place.id == reminder.destination_place_id,
            Place.user_id == reminder.resource_owner_user_id,
        )
    )
    if name is None:
        raise FamilyArrivalReminderError("ARRIVAL_REMINDER_NOT_AVAILABLE", 404)
    return name[:200]


def create_arrival_reminder(
    db: Session,
    *,
    resource_owner_user_id: UUID,
    grantee_user_id: UUID,
    destination_place_id: UUID,
    validity_minutes: int,
    now: datetime | None = None,
) -> FamilyArrivalReminderView:
    if resource_owner_user_id == grantee_user_id:
        raise FamilyArrivalReminderError("ARRIVAL_REMINDER_TARGET_INVALID", 409)
    if validity_minutes not in SUPPORTED_ARRIVAL_VALIDITIES:
        raise FamilyArrivalReminderError("ARRIVAL_REMINDER_VALIDITY_UNSUPPORTED", 422)

    locked = _lock_membership_pair(
        db,
        first_user_id=resource_owner_user_id,
        second_user_id=grantee_user_id,
    )
    owner_family = locked.get(resource_owner_user_id)
    grantee_family = locked.get(grantee_user_id)
    if owner_family is None or grantee_family != owner_family:
        db.rollback()
        raise FamilyArrivalReminderError("ARRIVAL_REMINDER_TARGET_INVALID", 404)

    place = db.scalar(
        select(Place)
        .where(
            Place.id == destination_place_id,
            Place.user_id == resource_owner_user_id,
        )
        .with_for_update()
    )
    if place is None:
        db.rollback()
        raise FamilyArrivalReminderError("ARRIVAL_REMINDER_DESTINATION_INVALID", 404)

    reference = _reference_now(now)
    prior = tuple(
        db.scalars(
            select(FamilyArrivalReminder)
            .where(
                FamilyArrivalReminder.family_id == owner_family,
                FamilyArrivalReminder.resource_owner_user_id == resource_owner_user_id,
                FamilyArrivalReminder.grantee_user_id == grantee_user_id,
                FamilyArrivalReminder.destination_place_id == destination_place_id,
                FamilyArrivalReminder.status == FamilyArrivalReminderStatus.ACTIVE.value,
            )
            .order_by(
                FamilyArrivalReminder.created_at.asc(),
                FamilyArrivalReminder.id.asc(),
            )
            .with_for_update()
        )
    )
    reference = _reference_now(now)
    for row in prior:
        _expire_locked(row, now=reference)
        if row.status == FamilyArrivalReminderStatus.ACTIVE.value:
            row.status = FamilyArrivalReminderStatus.CANCELLED.value
            row.cancelled_at = reference

    reminder = FamilyArrivalReminder(
        family_id=owner_family,
        resource_owner_user_id=resource_owner_user_id,
        grantee_user_id=grantee_user_id,
        destination_place_id=destination_place_id,
        status=FamilyArrivalReminderStatus.ACTIVE.value,
        created_at=reference,
        expires_at=reference + timedelta(minutes=validity_minutes),
    )
    db.add(reminder)
    db.commit()
    return FamilyArrivalReminderView(
        reminder_id=reminder.id,
        resource_owner_user_id=reminder.resource_owner_user_id,
        grantee_user_id=reminder.grantee_user_id,
        destination_place_id=reminder.destination_place_id,
        destination_display_name=place.name[:200],
        status=reminder.status,
        created_at=ensure_utc(reminder.created_at),
        expires_at=ensure_utc(reminder.expires_at),
        arrived_at=None,
        direction="OUTGOING",
    )


def list_arrival_reminders(
    db: Session,
    *,
    user_id: UUID,
    now: datetime | None = None,
) -> tuple[FamilyArrivalReminderView, ...]:
    membership = db.scalar(
        select(FamilyMembership).where(FamilyMembership.user_id == user_id)
    )
    if membership is None:
        raise FamilyArrivalReminderError("FAMILY_NOT_FOUND", 404)

    rows = tuple(
        db.scalars(
            select(FamilyArrivalReminder)
            .where(
                FamilyArrivalReminder.family_id == membership.family_id,
                or_(
                    FamilyArrivalReminder.resource_owner_user_id == user_id,
                    FamilyArrivalReminder.grantee_user_id == user_id,
                ),
            )
            .order_by(
                FamilyArrivalReminder.created_at.desc(),
                FamilyArrivalReminder.id.desc(),
            )
            .limit(ARRIVAL_REMINDER_LIST_LIMIT)
            .with_for_update()
        )
    )
    reference = _reference_now(now)
    reference = _reference_now(now)
    changed = False
    result: list[FamilyArrivalReminderView] = []
    for row in rows:
        before = row.status
        _expire_locked(row, now=reference)
        changed = changed or before != row.status
        result.append(
            FamilyArrivalReminderView(
                reminder_id=row.id,
                resource_owner_user_id=row.resource_owner_user_id,
                grantee_user_id=row.grantee_user_id,
                destination_place_id=row.destination_place_id,
                destination_display_name=_destination_name(db, row),
                status=row.status,
                created_at=ensure_utc(row.created_at),
                expires_at=ensure_utc(row.expires_at),
                arrived_at=(
                    ensure_utc(row.arrived_at) if row.arrived_at is not None else None
                ),
                direction=(
                    "OUTGOING"
                    if row.resource_owner_user_id == user_id
                    else "INCOMING"
                ),
            )
        )
    if changed:
        db.commit()
    return tuple(result)


def cancel_arrival_reminder(
    db: Session,
    *,
    actor_user_id: UUID,
    reminder_id: UUID,
    now: datetime | None = None,
) -> None:
    probe = db.scalar(
        select(FamilyArrivalReminder).where(FamilyArrivalReminder.id == reminder_id)
    )
    if probe is None or probe.resource_owner_user_id != actor_user_id:
        db.rollback()
        raise FamilyArrivalReminderError("ARRIVAL_REMINDER_NOT_AVAILABLE", 404)

    locked = _lock_membership_pair(
        db,
        first_user_id=probe.resource_owner_user_id,
        second_user_id=probe.grantee_user_id,
    )
    if (
        locked.get(probe.resource_owner_user_id) != probe.family_id
        or locked.get(probe.grantee_user_id) != probe.family_id
    ):
        db.rollback()
        raise FamilyArrivalReminderError("ARRIVAL_REMINDER_NOT_AVAILABLE", 404)

    reminder = db.scalar(
        select(FamilyArrivalReminder)
        .where(
            FamilyArrivalReminder.id == reminder_id,
            FamilyArrivalReminder.resource_owner_user_id == actor_user_id,
        )
        .with_for_update()
    )
    if reminder is None:
        db.rollback()
        raise FamilyArrivalReminderError("ARRIVAL_REMINDER_NOT_AVAILABLE", 404)

    reference = _reference_now(now)
    _expire_locked(reminder, now=reference)
    if reminder.status == FamilyArrivalReminderStatus.ACTIVE.value:
        reminder.status = FamilyArrivalReminderStatus.CANCELLED.value
        reminder.cancelled_at = reference
    db.commit()


def derive_arrival_for_finalized_visit(
    db: Session,
    *,
    visit: Visit,
    now: datetime | None = None,
) -> int:
    if visit.finalized_at is None:
        return 0

    arrived_at = ensure_utc(visit.arrived_at)
    source_start = ensure_utc(visit.source_started_at or visit.arrived_at)
    source_end = ensure_utc(visit.source_ended_at or visit.left_at or visit.arrived_at)
    intervals = pause_intervals_for_range(
        db,
        visit.user_id,
        start=source_start,
        end=source_end,
    )
    if any(
        start <= source_end and (end is None or end >= source_start)
        for start, end in intervals
    ):
        return 0

    reminder_ids = tuple(
        db.scalars(
            select(FamilyArrivalReminder.id)
            .where(
                FamilyArrivalReminder.resource_owner_user_id == visit.user_id,
                FamilyArrivalReminder.destination_place_id == visit.place_id,
                FamilyArrivalReminder.status == FamilyArrivalReminderStatus.ACTIVE.value,
            )
            .order_by(FamilyArrivalReminder.id.asc())
        )
    )
    transitioned = 0
    for reminder_id in reminder_ids:
        probe = db.scalar(
            select(FamilyArrivalReminder).where(
                FamilyArrivalReminder.id == reminder_id
            )
        )
        if probe is None:
            continue
        locked = _lock_membership_pair(
            db,
            first_user_id=probe.resource_owner_user_id,
            second_user_id=probe.grantee_user_id,
        )
        if (
            locked.get(probe.resource_owner_user_id) != probe.family_id
            or locked.get(probe.grantee_user_id) != probe.family_id
        ):
            continue
        reminder = db.scalar(
            select(FamilyArrivalReminder)
            .where(
                FamilyArrivalReminder.id == reminder_id,
                FamilyArrivalReminder.resource_owner_user_id == visit.user_id,
                FamilyArrivalReminder.destination_place_id == visit.place_id,
            )
            .with_for_update()
        )
        if reminder is None:
            continue
        lock_reference = _reference_now(now)
        _expire_locked(reminder, now=lock_reference)
        if reminder.status != FamilyArrivalReminderStatus.ACTIVE.value:
            continue
        if arrived_at < ensure_utc(reminder.created_at):
            continue
        transition_reference = _reference_now(now)
        _expire_locked(reminder, now=transition_reference)
        if reminder.status != FamilyArrivalReminderStatus.ACTIVE.value:
            continue
        reminder.status = FamilyArrivalReminderStatus.ARRIVED.value
        reminder.arrived_at = arrived_at
        transitioned += 1
    return transitioned
