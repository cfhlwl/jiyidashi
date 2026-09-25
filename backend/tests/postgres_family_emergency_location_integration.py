"""PostgreSQL race gates for S4-008 Emergency Location Sharing V1."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Barrier, Thread
from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.db import SessionLocal
from app.family_models import (
    FamilyEmergencyLocationShare,
    FamilyMembership,
    FamilyRole,
)
from app.models import LocationPoint, User
from app.services.family_emergency_location_service import (
    FamilyEmergencyShareError,
    create_emergency_location_share,
    get_emergency_shared_location,
    revoke_emergency_location_share,
)
from app.services.family_service import create_family, remove_member
from app.services.privacy_service import pause_recording


def _user(label: str) -> UUID:
    user_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname=f"emergency-{label}"))
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


def _fresh_point(owner: UUID) -> None:
    with SessionLocal() as db:
        db.add(
            LocationPoint(
                user_id=owner,
                client_uuid=f"emergency-race-{uuid4().hex}",
                latitude=31.2304,
                longitude=121.4737,
                accuracy=5.0,
                speed=0.0,
                recorded_at=datetime.now(UTC),
            )
        )
        db.commit()


def _share(owner: UUID, member: UUID) -> UUID:
    with SessionLocal() as db:
        return create_emergency_location_share(
            db,
            resource_owner_user_id=owner,
            grantee_user_id=member,
            duration_minutes=30,
        ).share_id


def _cleanup(*user_ids: UUID) -> None:
    with SessionLocal() as db:
        for user_id in user_ids:
            user = db.get(User, user_id)
            if user is not None:
                db.delete(user)
        db.commit()


def _race_read_revoke() -> None:
    owner, member = _family_pair("read-revoke")
    _fresh_point(owner)

    for _ in range(4):
        share_id = _share(owner, member)
        barrier = Barrier(2)
        outcome: list[str] = []
        errors: list[BaseException] = []

        def reader(
            barrier: Barrier = barrier,
            outcome: list[str] = outcome,
            errors: list[BaseException] = errors,
        ) -> None:
            try:
                barrier.wait(timeout=15)
                with SessionLocal() as db:
                    try:
                        get_emergency_shared_location(
                            db,
                            share_id=share_id,
                            grantee_user_id=member,
                        )
                        outcome.append("allowed")
                    except FamilyEmergencyShareError as exc:
                        assert exc.code == "EMERGENCY_SHARE_NOT_AVAILABLE"
                        outcome.append("denied")
            except BaseException as exc:
                errors.append(exc)

        def revoker(
            barrier: Barrier = barrier,
            errors: list[BaseException] = errors,
        ) -> None:
            try:
                barrier.wait(timeout=15)
                with SessionLocal() as db:
                    revoke_emergency_location_share(
                        db,
                        actor_user_id=owner,
                        share_id=share_id,
                    )
            except BaseException as exc:
                errors.append(exc)

        threads = [Thread(target=reader), Thread(target=revoker)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
            assert not thread.is_alive()
        if errors:
            raise errors[0]
        assert outcome in (["allowed"], ["denied"])

    _cleanup(member, owner)


def _race_read_remove() -> None:
    owner, member = _family_pair("read-remove")
    _fresh_point(owner)
    share_id = _share(owner, member)
    barrier = Barrier(2)
    outcome: list[str] = []
    errors: list[BaseException] = []

    def reader() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                try:
                    get_emergency_shared_location(
                        db,
                        share_id=share_id,
                        grantee_user_id=member,
                    )
                    outcome.append("allowed")
                except FamilyEmergencyShareError as exc:
                    assert exc.code == "EMERGENCY_SHARE_NOT_AVAILABLE"
                    outcome.append("denied")
        except BaseException as exc:
            errors.append(exc)

    def remover() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                remove_member(db, actor_user_id=owner, target_user_id=member)
        except BaseException as exc:
            errors.append(exc)

    threads = [Thread(target=reader), Thread(target=remover)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    if errors:
        raise errors[0]
    assert outcome in (["allowed"], ["denied"])

    with SessionLocal() as db:
        assert db.get(FamilyEmergencyLocationShare, share_id) is None
    _cleanup(member, owner)


def _race_read_pause() -> None:
    owner, member = _family_pair("read-pause")
    _fresh_point(owner)
    share_id = _share(owner, member)
    barrier = Barrier(2)
    outcome: list[str] = []
    errors: list[BaseException] = []

    def reader() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                try:
                    get_emergency_shared_location(
                        db,
                        share_id=share_id,
                        grantee_user_id=member,
                    )
                    outcome.append("allowed")
                except FamilyEmergencyShareError as exc:
                    assert exc.code == "CURRENT_LOCATION_UNAVAILABLE"
                    outcome.append("paused")
        except BaseException as exc:
            errors.append(exc)

    def pauser() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                now = datetime.now(UTC)
                pause_recording(
                    db,
                    owner,
                    started_at=now,
                    ended_at=now + timedelta(minutes=15),
                )
                db.commit()
        except BaseException as exc:
            errors.append(exc)

    threads = [Thread(target=reader), Thread(target=pauser)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    if errors:
        raise errors[0]
    assert outcome in (["allowed"], ["paused"])
    _cleanup(member, owner)


def _race_same_pair_create() -> None:
    owner, member = _family_pair("same-pair-create")
    barrier = Barrier(2)
    created: list[UUID] = []
    errors: list[BaseException] = []

    def creator(duration: int) -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                view = create_emergency_location_share(
                    db,
                    resource_owner_user_id=owner,
                    grantee_user_id=member,
                    duration_minutes=duration,
                )
                created.append(view.share_id)
        except BaseException as exc:
            errors.append(exc)

    threads = [
        Thread(target=creator, args=(30,)),
        Thread(target=creator, args=(180,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    if errors:
        raise errors[0]
    assert len(created) == 2

    with SessionLocal() as db:
        rows = db.scalars(
            select(FamilyEmergencyLocationShare).where(
                FamilyEmergencyLocationShare.resource_owner_user_id == owner,
                FamilyEmergencyLocationShare.grantee_user_id == member,
            )
        ).all()
        active = [
            row
            for row in rows
            if row.revoked_at is None and row.expires_at > datetime.now(UTC)
        ]
        assert len(active) == 1

    _cleanup(member, owner)


if __name__ == "__main__":
    _race_read_revoke()
    _race_read_remove()
    _race_read_pause()
    _race_same_pair_create()
    print("PostgreSQL Emergency Location Sharing race gate: PASS")
