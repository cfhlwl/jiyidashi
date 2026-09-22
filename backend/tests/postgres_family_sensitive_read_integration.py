"""PostgreSQL invariants for Stage 4B Family sensitive reads."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Barrier, Thread
from uuid import UUID, uuid4

from app.core.db import SessionLocal
from app.family_models import (
    FamilyMembership,
    FamilyPermissionCode,
    FamilyRole,
)
from app.models import LocationPoint, Place, PrivacyState, User, Visit
from app.services.family_sensitive_read_service import (
    FamilySensitiveReadError,
    get_family_current_location,
    get_family_today_footprint,
)
from app.services.family_service import create_family, remove_member, replace_permissions
from app.services.privacy_service import (
    lock_location_derivation_state,
    pause_recording,
    resume_recording,
)
from app.services.time_service import local_today, user_day_bounds_utc


def _user(label: str, *, timezone: str = "Asia/Shanghai") -> UUID:
    user_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname=f"family-read-pg-{label}", timezone=timezone))
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


def _grant(owner: UUID, member: UUID, *codes: str) -> None:
    with SessionLocal() as db:
        replace_permissions(
            db,
            resource_owner_user_id=owner,
            grantee_user_id=member,
            permission_codes=list(codes),
        )


def _point(user_id: UUID, *, latitude: float = 31.2304) -> None:
    with SessionLocal() as db:
        db.add(
            LocationPoint(
                user_id=user_id,
                client_uuid=f"pg-{uuid4()}",
                latitude=latitude,
                longitude=121.4737,
                accuracy=8.0,
                speed=0.2,
                recorded_at=datetime.now(UTC),
            )
        )
        db.commit()


def _cleanup(*user_ids: UUID) -> None:
    with SessionLocal() as db:
        for user_id in user_ids:
            user = db.get(User, user_id)
            if user is not None:
                db.delete(user)
        db.commit()


def _assert_denied(
    *,
    owner: UUID,
    grantee: UUID,
    current: bool,
) -> None:
    with SessionLocal() as db:
        try:
            if current:
                get_family_current_location(
                    db,
                    resource_owner_user_id=owner,
                    grantee_user_id=grantee,
                )
            else:
                get_family_today_footprint(
                    db,
                    resource_owner_user_id=owner,
                    grantee_user_id=grantee,
                )
            raise AssertionError("family sensitive read unexpectedly authorized")
        except FamilySensitiveReadError as exc:
            assert exc.code == "FAMILY_READ_NOT_AUTHORIZED"
            assert exc.status_code == 403


def _assert_exact_grant_and_cross_family_isolation() -> None:
    owner, member = _family_pair("exact")
    foreign_owner = _user("foreign-owner")
    create_family_session = SessionLocal()
    try:
        create_family(create_family_session, user_id=foreign_owner)
    finally:
        create_family_session.close()

    _point(owner)

    _assert_denied(owner=owner, grantee=member, current=True)
    _assert_denied(owner=owner, grantee=member, current=False)

    _grant(owner, member, FamilyPermissionCode.VIEW_CURRENT_LOCATION.value)
    with SessionLocal() as db:
        result = get_family_current_location(
            db,
            resource_owner_user_id=owner,
            grantee_user_id=member,
        )
        assert result.resource_owner_user_id == owner

    # A current-location grant never authorizes footprint.
    _assert_denied(owner=owner, grantee=member, current=False)

    _grant(owner, member, FamilyPermissionCode.VIEW_FOOTPRINT.value)
    _assert_denied(owner=owner, grantee=member, current=True)
    with SessionLocal() as db:
        footprint = get_family_today_footprint(
            db,
            resource_owner_user_id=owner,
            grantee_user_id=member,
        )
        assert footprint.visits == []

    # OWNER role alone is not a sensitive-read bypass.
    _assert_denied(owner=member, grantee=owner, current=True)

    # A user in another Family gets the same non-enumerating denial.
    _assert_denied(owner=owner, grantee=foreign_owner, current=True)

    _cleanup(member, owner, foreign_owner)


def _assert_owner_privacy_pause_blocks_current_location() -> None:
    owner, member = _family_pair("privacy")
    _grant(owner, member, FamilyPermissionCode.VIEW_CURRENT_LOCATION.value)
    _point(owner)

    now = datetime.now(UTC)
    with SessionLocal() as db:
        db.add(
            PrivacyState(
                user_id=owner,
                recording_paused_since=now - timedelta(minutes=1),
                recording_paused_until=now + timedelta(minutes=10),
            )
        )
        db.commit()

    with SessionLocal() as db:
        try:
            get_family_current_location(
                db,
                resource_owner_user_id=owner,
                grantee_user_id=member,
                now=now,
            )
            raise AssertionError("active owner Privacy Pause leaked current location")
        except FamilySensitiveReadError as exc:
            assert exc.code == "CURRENT_LOCATION_UNAVAILABLE"
            assert exc.status_code == 404

    _cleanup(member, owner)


def _assert_owner_local_day_footprint_semantics() -> None:
    owner, member = _family_pair("footprint")
    _grant(owner, member, FamilyPermissionCode.VIEW_FOOTPRINT.value)

    with SessionLocal() as db:
        owner_row = db.get(User, owner)
        member_row = db.get(User, member)
        assert owner_row is not None and member_row is not None
        owner_row.timezone = "Asia/Shanghai"
        member_row.timezone = "America/New_York"
        db.commit()

        day = local_today(db, owner)
        start_utc, _ = user_day_bounds_utc(db, owner, day)
        place = Place(
            user_id=owner,
            name="PG Owner Place",
            cluster_key=f"pg-{uuid4().hex[:8]}",
        )
        db.add(place)
        db.flush()
        db.add(
            Visit(
                user_id=owner,
                place_id=place.id,
                arrived_at=start_utc - timedelta(hours=1),
                left_at=start_utc + timedelta(minutes=30),
                confidence=0.9,
                source="PG_TEST",
            )
        )
        db.commit()

    with SessionLocal() as db:
        result = get_family_today_footprint(
            db,
            resource_owner_user_id=owner,
            grantee_user_id=member,
        )
        assert result.timezone == "Asia/Shanghai"
        assert result.day == day
        assert len(result.visits) == 1
        assert result.visits[0].place_name == "PG Owner Place"

    _cleanup(member, owner)


def _assert_read_vs_permission_revoke_serializes() -> None:
    owner, member = _family_pair("revoke")
    _point(owner)

    for _ in range(6):
        _grant(owner, member, FamilyPermissionCode.VIEW_CURRENT_LOCATION.value)
        barrier = Barrier(2)
        outcomes: list[str] = []
        errors: list[BaseException] = []

        def reader(
            barrier: Barrier = barrier,
            outcomes: list[str] = outcomes,
            errors: list[BaseException] = errors,
        ) -> None:
            try:
                barrier.wait(timeout=15)
                with SessionLocal() as db:
                    try:
                        get_family_current_location(
                            db,
                            resource_owner_user_id=owner,
                            grantee_user_id=member,
                        )
                        outcomes.append("read-allowed")
                    except FamilySensitiveReadError as exc:
                        assert exc.code == "FAMILY_READ_NOT_AUTHORIZED"
                        outcomes.append("read-denied")
            except BaseException as exc:  # noqa: BLE001 - thread reports gate failure
                errors.append(exc)

        def revoker(
            barrier: Barrier = barrier,
            outcomes: list[str] = outcomes,
            errors: list[BaseException] = errors,
        ) -> None:
            try:
                barrier.wait(timeout=15)
                with SessionLocal() as db:
                    replace_permissions(
                        db,
                        resource_owner_user_id=owner,
                        grantee_user_id=member,
                        permission_codes=[],
                    )
                    outcomes.append("revoked")
            except BaseException as exc:  # noqa: BLE001 - thread reports gate failure
                errors.append(exc)

        threads = [Thread(target=reader), Thread(target=revoker)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
            assert not thread.is_alive()
        if errors:
            raise errors[0]

        assert "revoked" in outcomes
        assert set(outcomes).issubset({"read-allowed", "read-denied", "revoked"})
        _assert_denied(owner=owner, grantee=member, current=True)

    _cleanup(member, owner)


def _assert_read_vs_member_removal_serializes() -> None:
    owner, member = _family_pair("remove")
    _grant(owner, member, FamilyPermissionCode.VIEW_CURRENT_LOCATION.value)
    _point(owner)

    barrier = Barrier(2)
    outcomes: list[str] = []
    errors: list[BaseException] = []

    def reader() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                try:
                    get_family_current_location(
                        db,
                        resource_owner_user_id=owner,
                        grantee_user_id=member,
                    )
                    outcomes.append("read-allowed")
                except FamilySensitiveReadError as exc:
                    assert exc.code == "FAMILY_READ_NOT_AUTHORIZED"
                    outcomes.append("read-denied")
        except BaseException as exc:  # noqa: BLE001 - thread reports gate failure
            errors.append(exc)

    def remover() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                remove_member(
                    db,
                    actor_user_id=owner,
                    target_user_id=member,
                )
                outcomes.append("removed")
        except BaseException as exc:  # noqa: BLE001 - thread reports gate failure
            errors.append(exc)

    threads = [Thread(target=reader), Thread(target=remover)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    if errors:
        raise errors[0]

    assert "removed" in outcomes
    assert set(outcomes).issubset({"read-allowed", "read-denied", "removed"})
    _assert_denied(owner=owner, grantee=member, current=True)

    _cleanup(member, owner)



def _assert_current_read_vs_privacy_pause_serializes() -> None:
    owner, member = _family_pair("privacy-race")
    _grant(owner, member, FamilyPermissionCode.VIEW_CURRENT_LOCATION.value)
    _point(owner)

    # Persist the same owner serialization row used by location derivation and
    # pause/resume so every round races on the exact production lock boundary.
    with SessionLocal() as db:
        lock_location_derivation_state(db, owner)
        db.commit()

    for _ in range(6):
        with SessionLocal() as db:
            resume_recording(db, owner, resumed_at=datetime.now(UTC))
            db.commit()

        barrier = Barrier(2)
        outcomes: list[str] = []
        errors: list[BaseException] = []

        def reader(
            barrier: Barrier = barrier,
            outcomes: list[str] = outcomes,
            errors: list[BaseException] = errors,
        ) -> None:
            try:
                barrier.wait(timeout=15)
                with SessionLocal() as db:
                    try:
                        get_family_current_location(
                            db,
                            resource_owner_user_id=owner,
                            grantee_user_id=member,
                        )
                        outcomes.append("read-allowed")
                    except FamilySensitiveReadError as exc:
                        assert exc.code == "CURRENT_LOCATION_UNAVAILABLE"
                        outcomes.append("read-unavailable")
            except BaseException as exc:  # noqa: BLE001 - thread reports gate failure
                errors.append(exc)

        def pauser(
            barrier: Barrier = barrier,
            outcomes: list[str] = outcomes,
            errors: list[BaseException] = errors,
        ) -> None:
            try:
                barrier.wait(timeout=15)
                now = datetime.now(UTC)
                with SessionLocal() as db:
                    pause_recording(
                        db,
                        owner,
                        started_at=now,
                        ended_at=now + timedelta(minutes=10),
                    )
                    db.commit()
                    outcomes.append("pause-committed")
            except BaseException as exc:  # noqa: BLE001 - thread reports gate failure
                errors.append(exc)

        threads = [Thread(target=reader), Thread(target=pauser)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
            assert not thread.is_alive()
        if errors:
            raise errors[0]

        assert "pause-committed" in outcomes
        assert set(outcomes).issubset(
            {"read-allowed", "read-unavailable", "pause-committed"}
        )

        # Once the owner pause commit is visible, every new Family read must fail closed.
        with SessionLocal() as db:
            try:
                get_family_current_location(
                    db,
                    resource_owner_user_id=owner,
                    grantee_user_id=member,
                )
                raise AssertionError("post-pause Family current-location unexpectedly allowed")
            except FamilySensitiveReadError as exc:
                assert exc.code == "CURRENT_LOCATION_UNAVAILABLE"
                assert exc.status_code == 404

    _cleanup(member, owner)

def main() -> None:
    _assert_exact_grant_and_cross_family_isolation()
    _assert_owner_privacy_pause_blocks_current_location()
    _assert_owner_local_day_footprint_semantics()
    _assert_read_vs_permission_revoke_serializes()
    _assert_read_vs_member_removal_serializes()
    _assert_current_read_vs_privacy_pause_serializes()
    print("PostgreSQL Family Sensitive Read invariants PASS")


if __name__ == "__main__":
    main()
