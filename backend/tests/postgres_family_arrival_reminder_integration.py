"""PostgreSQL race gates for S4-009 Arrival-Home Reminder V1."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Barrier, Thread
from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.db import SessionLocal
from app.family_models import (
    FamilyArrivalReminder,
    FamilyArrivalReminderStatus,
    FamilyMembership,
    FamilyRole,
)
from app.models import Place, User, Visit
from app.services.family_arrival_reminder_service import (
    cancel_arrival_reminder,
    create_arrival_reminder,
    derive_arrival_for_finalized_visit,
    list_arrival_reminders,
)
from app.services.family_service import create_family, remove_member


def _user(label: str) -> UUID:
    user_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname=f"arrival-{label}"))
        db.commit()
    return user_id


def _family_pair(label: str) -> tuple[UUID, UUID]:
    owner = _user(f"{label}-owner")
    member = _user(f"{label}-member")
    with SessionLocal() as db:
        family = create_family(db, user_id=owner)
        db.add(
            FamilyMembership(
                family_id=family.family_id,
                user_id=member,
                role=FamilyRole.MEMBER.value,
            )
        )
        db.commit()
    return owner, member


def _place(owner: UUID) -> UUID:
    place_id = uuid4()
    with SessionLocal() as db:
        db.add(
            Place(
                id=place_id,
                user_id=owner,
                name="家",
                user_name="家",
                name_revision=1,
                is_user_named=True,
            )
        )
        db.commit()
    return place_id


def _create(owner: UUID, member: UUID, place_id: UUID, minutes: int = 120) -> UUID:
    with SessionLocal() as db:
        return create_arrival_reminder(
            db,
            resource_owner_user_id=owner,
            grantee_user_id=member,
            destination_place_id=place_id,
            validity_minutes=minutes,
        ).reminder_id


def _visit(owner: UUID, place_id: UUID, arrived_at: datetime) -> UUID:
    visit_id = uuid4()
    with SessionLocal() as db:
        db.add(
            Visit(
                id=visit_id,
                user_id=owner,
                place_id=place_id,
                arrived_at=arrived_at,
                left_at=arrived_at + timedelta(minutes=12),
                duration_seconds=720,
                confidence=0.9,
                source="LOCATION_CLUSTER",
                derivation_key=uuid4().hex,
                source_started_at=arrived_at,
                source_ended_at=arrived_at + timedelta(minutes=12),
                source_point_count=4,
                source_fingerprint=uuid4().hex,
                algorithm_version="visit-seq-v1",
                finalized_at=arrived_at + timedelta(minutes=20),
            )
        )
        db.commit()
    return visit_id


def _derive(visit_id: UUID, *, now: datetime | None = None) -> int:
    with SessionLocal() as db:
        visit = db.get(Visit, visit_id)
        assert visit is not None
        count = derive_arrival_for_finalized_visit(db, visit=visit, now=now)
        db.commit()
        return count


def _cleanup(*user_ids: UUID) -> None:
    with SessionLocal() as db:
        for user_id in user_ids:
            user = db.get(User, user_id)
            if user is not None:
                db.delete(user)
        db.commit()


def _race_derive_cancel() -> None:
    owner, member = _family_pair("derive-cancel")
    place_id = _place(owner)
    reminder_id = _create(owner, member, place_id)
    visit_id = _visit(owner, place_id, datetime.now(UTC) - timedelta(minutes=1))
    barrier = Barrier(2)
    errors: list[BaseException] = []

    def derive() -> None:
        try:
            barrier.wait(timeout=15)
            _derive(visit_id)
        except BaseException as exc:
            errors.append(exc)

    def cancel() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                cancel_arrival_reminder(
                    db,
                    actor_user_id=owner,
                    reminder_id=reminder_id,
                )
        except BaseException as exc:
            errors.append(exc)

    threads = [Thread(target=derive), Thread(target=cancel)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    if errors:
        raise errors[0]

    with SessionLocal() as db:
        row = db.get(FamilyArrivalReminder, reminder_id)
        assert row is not None
        assert row.status in {
            FamilyArrivalReminderStatus.ARRIVED.value,
            FamilyArrivalReminderStatus.CANCELLED.value,
        }
        assert not (row.arrived_at is not None and row.cancelled_at is not None)
    _cleanup(member, owner)


def _race_derive_remove() -> None:
    owner, member = _family_pair("derive-remove")
    place_id = _place(owner)
    _create(owner, member, place_id)
    visit_id = _visit(owner, place_id, datetime.now(UTC) - timedelta(minutes=1))
    barrier = Barrier(2)
    errors: list[BaseException] = []

    def derive() -> None:
        try:
            barrier.wait(timeout=15)
            _derive(visit_id)
        except BaseException as exc:
            errors.append(exc)

    def remove() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                remove_member(db, actor_user_id=owner, target_user_id=member)
        except BaseException as exc:
            errors.append(exc)

    threads = [Thread(target=derive), Thread(target=remove)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    if errors:
        raise errors[0]

    with SessionLocal() as db:
        assert db.scalar(
            select(FamilyArrivalReminder.id).where(
                FamilyArrivalReminder.grantee_user_id == member
            )
        ) is None
    _cleanup(member, owner)


def _race_derive_expiry() -> None:
    owner, member = _family_pair("derive-expiry")
    place_id = _place(owner)
    reminder_id = _create(owner, member, place_id)
    visit_id = _visit(owner, place_id, datetime.now(UTC) - timedelta(minutes=1))

    with SessionLocal() as db:
        row = db.get(FamilyArrivalReminder, reminder_id)
        assert row is not None
        boundary = datetime.now(UTC)
        row.created_at = boundary - timedelta(minutes=120)
        row.expires_at = boundary
        db.commit()

    assert _derive(visit_id, now=boundary) == 0
    with SessionLocal() as db:
        rows = list_arrival_reminders(db, user_id=member, now=boundary)
        assert rows[0].status == FamilyArrivalReminderStatus.EXPIRED.value
        row = db.get(FamilyArrivalReminder, reminder_id)
        assert row is not None
        assert row.arrived_at is None
    _cleanup(member, owner)


def _race_same_tuple_create() -> None:
    owner, member = _family_pair("same-tuple")
    place_id = _place(owner)
    barrier = Barrier(2)
    errors: list[BaseException] = []

    def creator(minutes: int) -> None:
        try:
            barrier.wait(timeout=15)
            _create(owner, member, place_id, minutes)
        except BaseException as exc:
            errors.append(exc)

    threads = [
        Thread(target=creator, args=(120,)),
        Thread(target=creator, args=(720,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    if errors:
        raise errors[0]

    with SessionLocal() as db:
        rows = db.scalars(
            select(FamilyArrivalReminder).where(
                FamilyArrivalReminder.resource_owner_user_id == owner,
                FamilyArrivalReminder.grantee_user_id == member,
                FamilyArrivalReminder.destination_place_id == place_id,
            )
        ).all()
        active = [
            row
            for row in rows
            if row.status == FamilyArrivalReminderStatus.ACTIVE.value
        ]
        assert len(rows) == 2
        assert len(active) == 1
    _cleanup(member, owner)


def _duplicate_derivation() -> None:
    owner, member = _family_pair("duplicate")
    place_id = _place(owner)
    reminder_id = _create(owner, member, place_id)
    visit_id = _visit(owner, place_id, datetime.now(UTC) - timedelta(minutes=1))

    assert _derive(visit_id) == 1
    assert _derive(visit_id) == 0
    with SessionLocal() as db:
        row = db.get(FamilyArrivalReminder, reminder_id)
        assert row is not None
        assert row.status == FamilyArrivalReminderStatus.ARRIVED.value
        arrived_at = row.arrived_at
    assert arrived_at is not None
    assert _derive(visit_id) == 0
    with SessionLocal() as db:
        row = db.get(FamilyArrivalReminder, reminder_id)
        assert row is not None
        assert row.arrived_at == arrived_at
    _cleanup(member, owner)


if __name__ == "__main__":
    _race_derive_cancel()
    _race_derive_remove()
    _race_derive_expiry()
    _race_same_tuple_create()
    _duplicate_derivation()
    print("PostgreSQL Arrival-Home Reminder race gate: PASS")
