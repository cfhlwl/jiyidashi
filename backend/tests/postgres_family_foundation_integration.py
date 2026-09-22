"""PostgreSQL invariants for Stage 4A Family foundation."""

from __future__ import annotations

from threading import Barrier, Thread
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.db import SessionLocal
from app.family_models import (
    Family,
    FamilyInvite,
    FamilyMembership,
    FamilyPermissionCode,
    FamilyPermissionGrant,
)
from app.models import User
from app.services.account_deletion_service import delete_current_account
from app.services.data_deletion_service import delete_all_user_data
from app.services.family_service import (
    FamilyServiceError,
    accept_invite,
    create_family,
    create_invite,
    has_family_permission,
    remove_member,
    replace_permissions,
    revoke_invite,
)


class EmptyStorage:
    def iter_object_keys(self, prefix: str):
        return iter(())

    def delete_object(self, object_key: str) -> None:
        return None


def _user(label: str):
    user_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname=f"family-pg-{label}"))
        db.commit()
    return user_id


def _assert_concurrent_family_create() -> None:
    user_id = _user("create-race")
    barrier = Barrier(2)
    successes = []
    errors = []

    def worker() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                successes.append(create_family(db, user_id=user_id))
        except FamilyServiceError as exc:
            errors.append(exc)

    threads = [Thread(target=worker), Thread(target=worker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()

    assert len(successes) == 1
    assert len(errors) == 1
    assert errors[0].code == "FAMILY_ALREADY_JOINED"
    with SessionLocal() as db:
        assert int(
            db.scalar(
                select(func.count())
                .select_from(FamilyMembership)
                .where(FamilyMembership.user_id == user_id)
            )
            or 0
        ) == 1
        assert int(db.scalar(select(func.count()).select_from(Family)) or 0) >= 1

    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, user_id))
        cleanup.commit()


def _assert_same_invite_has_at_most_one_winner() -> None:
    owner = _user("invite-owner")
    first = _user("invite-first")
    second = _user("invite-second")
    with SessionLocal() as db:
        create_family(db, user_id=owner)
        invite = create_invite(db, user_id=owner)

    barrier = Barrier(2)
    winners = []
    errors = []

    def worker(user_id) -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                winners.append(
                    accept_invite(db, user_id=user_id, token=invite.token)
                )
        except FamilyServiceError as exc:
            errors.append(exc)

    threads = [Thread(target=worker, args=(first,)), Thread(target=worker, args=(second,))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()

    assert len(winners) == 1
    assert len(errors) == 1
    assert errors[0].code == "FAMILY_INVITE_NOT_ACTIVE"
    with SessionLocal() as db:
        row = db.get(FamilyInvite, invite.invite_id)
        assert row is not None
        assert row.accepted_by_user_id in {first, second}
        loser = second if row.accepted_by_user_id == first else first
        assert db.scalar(
            select(FamilyMembership.id).where(FamilyMembership.user_id == loser)
        ) is None

    with SessionLocal() as cleanup:
        for user_id in (first, second, owner):
            user = cleanup.get(User, user_id)
            if user is not None:
                cleanup.delete(user)
        cleanup.commit()


def _assert_accept_vs_revoke_serializes() -> None:
    owner = _user("revoke-owner")
    member = _user("revoke-member")
    with SessionLocal() as db:
        create_family(db, user_id=owner)
        invite = create_invite(db, user_id=owner)

    barrier = Barrier(2)
    accepted = []
    revoked = []
    errors = []

    def accepter() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                accept_invite(db, user_id=member, token=invite.token)
                accepted.append(True)
        except FamilyServiceError as exc:
            errors.append(exc)

    def revoker() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                revoke_invite(db, user_id=owner, invite_id=invite.invite_id)
                revoked.append(True)
        except FamilyServiceError as exc:
            errors.append(exc)

    threads = [Thread(target=accepter), Thread(target=revoker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()

    assert len(accepted) + len(revoked) == 1
    assert len(errors) == 1
    assert errors[0].code in {"FAMILY_INVITE_NOT_ACTIVE"}
    with SessionLocal() as db:
        row = db.get(FamilyInvite, invite.invite_id)
        assert row is not None
        assert (row.accepted_at is None) != (row.revoked_at is None)

    with SessionLocal() as cleanup:
        for user_id in (member, owner):
            user = cleanup.get(User, user_id)
            if user is not None:
                cleanup.delete(user)
        cleanup.commit()


def _assert_permission_default_deny_and_removal_cleanup() -> None:
    owner = _user("permission-owner")
    member = _user("permission-member")
    with SessionLocal() as db:
        family = create_family(db, user_id=owner)
        db.add(
            FamilyMembership(
                family_id=family.family_id,
                user_id=member,
                role="MEMBER",
            )
        )
        db.commit()
        assert not has_family_permission(
            db,
            resource_owner_user_id=owner,
            grantee_user_id=member,
            permission_code=FamilyPermissionCode.VIEW_MEMORY,
        )
        replace_permissions(
            db,
            resource_owner_user_id=owner,
            grantee_user_id=member,
            permission_codes=[FamilyPermissionCode.VIEW_MEMORY.value],
        )
        assert has_family_permission(
            db,
            resource_owner_user_id=owner,
            grantee_user_id=member,
            permission_code=FamilyPermissionCode.VIEW_MEMORY,
        )
        remove_member(db, actor_user_id=owner, target_user_id=member)
        assert not has_family_permission(
            db,
            resource_owner_user_id=owner,
            grantee_user_id=member,
            permission_code=FamilyPermissionCode.VIEW_MEMORY,
        )
        assert db.scalar(
            select(FamilyPermissionGrant.id).where(
                FamilyPermissionGrant.grantee_user_id == member
            )
        ) is None

    with SessionLocal() as cleanup:
        for user_id in (member, owner):
            user = cleanup.get(User, user_id)
            if user is not None:
                cleanup.delete(user)
        cleanup.commit()


def _assert_cross_family_isolation() -> None:
    owner_a = _user("cross-owner-a")
    owner_b = _user("cross-owner-b")
    member_b = _user("cross-member-b")
    with SessionLocal() as db:
        create_family(db, user_id=owner_a)
        family_b = create_family(db, user_id=owner_b)
        db.add(
            FamilyMembership(
                family_id=family_b.family_id,
                user_id=member_b,
                role="MEMBER",
            )
        )
        db.commit()
        try:
            replace_permissions(
                db,
                resource_owner_user_id=owner_a,
                grantee_user_id=member_b,
                permission_codes=[FamilyPermissionCode.VIEW_FOOTPRINT.value],
            )
            raise AssertionError("cross-family grant succeeded")
        except FamilyServiceError as exc:
            assert exc.code == "FAMILY_MEMBER_NOT_FOUND"
            db.rollback()

    with SessionLocal() as cleanup:
        for user_id in (member_b, owner_b, owner_a):
            user = cleanup.get(User, user_id)
            if user is not None:
                cleanup.delete(user)
        cleanup.commit()


def _assert_account_delete_family_lifecycle() -> None:
    owner = _user("delete-owner")
    member = _user("delete-member")
    with SessionLocal() as db:
        family = create_family(db, user_id=owner)
        db.add(
            FamilyMembership(
                family_id=family.family_id,
                user_id=member,
                role="MEMBER",
            )
        )
        db.commit()
        replace_permissions(
            db,
            resource_owner_user_id=owner,
            grantee_user_id=member,
            permission_codes=[FamilyPermissionCode.VIEW_MEMORY.value],
        )

    with SessionLocal() as deleting_member:
        result = delete_current_account(
            deleting_member,
            user_id=member,
            request_id=uuid4(),
            storage=EmptyStorage(),
            local_cleanup_ready=True,
        )
        assert result.completed is True

    with SessionLocal() as verify:
        assert verify.get(User, member) is None
        assert verify.get(Family, family.family_id) is not None
        assert verify.scalar(
            select(FamilyPermissionGrant.id).where(
                FamilyPermissionGrant.family_id == family.family_id
            )
        ) is None

    with SessionLocal() as deleting_owner:
        result = delete_current_account(
            deleting_owner,
            user_id=owner,
            request_id=uuid4(),
            storage=EmptyStorage(),
            local_cleanup_ready=True,
        )
        assert result.completed is True

    with SessionLocal() as verify:
        assert verify.get(User, owner) is None
        assert verify.get(Family, family.family_id) is None



def _assert_database_rejects_second_owner() -> None:
    owner = _user("single-owner")
    second = _user("second-owner")
    with SessionLocal() as db:
        family = create_family(db, user_id=owner)
        db.add(
            FamilyMembership(
                family_id=family.family_id,
                user_id=second,
                role="OWNER",
            )
        )
        try:
            db.commit()
            raise AssertionError("database accepted a second OWNER")
        except IntegrityError:
            db.rollback()

        owner_count = int(
            db.scalar(
                select(func.count())
                .select_from(FamilyMembership)
                .where(
                    FamilyMembership.family_id == family.family_id,
                    FamilyMembership.role == "OWNER",
                )
            )
            or 0
        )
        assert owner_count == 1
        assert db.scalar(
            select(FamilyMembership.id).where(FamilyMembership.user_id == second)
        ) is None

    with SessionLocal() as cleanup:
        for user_id in (second, owner):
            user = cleanup.get(User, user_id)
            if user is not None:
                cleanup.delete(user)
        cleanup.commit()


def _assert_cross_family_invite_idor_fails_closed() -> None:
    owner_a = _user("invite-idor-a")
    owner_b = _user("invite-idor-b")
    with SessionLocal() as db:
        create_family(db, user_id=owner_a)
        create_family(db, user_id=owner_b)
        invite = create_invite(db, user_id=owner_a)

        try:
            revoke_invite(
                db,
                user_id=owner_b,
                invite_id=invite.invite_id,
            )
            raise AssertionError("cross-family owner revoked another Family invite")
        except FamilyServiceError as exc:
            assert exc.code == "FAMILY_INVITE_NOT_FOUND"
            assert exc.status_code == 404
            db.rollback()

        row = db.get(FamilyInvite, invite.invite_id)
        assert row is not None
        assert row.revoked_at is None
        assert row.accepted_at is None
        revoke_invite(db, user_id=owner_a, invite_id=invite.invite_id)

    with SessionLocal() as cleanup:
        for user_id in (owner_b, owner_a):
            user = cleanup.get(User, user_id)
            if user is not None:
                cleanup.delete(user)
        cleanup.commit()


def _assert_grant_vs_member_remove_converges() -> None:
    owner = _user("grant-remove-owner")
    member = _user("grant-remove-member")
    with SessionLocal() as db:
        family = create_family(db, user_id=owner)
        db.add(
            FamilyMembership(
                family_id=family.family_id,
                user_id=member,
                role="MEMBER",
            )
        )
        db.commit()

    barrier = Barrier(2)
    outcomes: list[str] = []
    errors: list[BaseException] = []

    def grant_worker() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                replace_permissions(
                    db,
                    resource_owner_user_id=owner,
                    grantee_user_id=member,
                    permission_codes=[FamilyPermissionCode.VIEW_MEMORY.value],
                )
                outcomes.append("grant")
        except FamilyServiceError as exc:
            assert exc.code == "FAMILY_MEMBER_NOT_FOUND"
            outcomes.append("grant-denied")
        except BaseException as exc:  # noqa: BLE001 - thread reports test failures
            errors.append(exc)

    def remove_worker() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                remove_member(
                    db,
                    actor_user_id=owner,
                    target_user_id=member,
                )
                outcomes.append("remove")
        except BaseException as exc:  # noqa: BLE001 - thread reports test failures
            errors.append(exc)

    threads = [Thread(target=grant_worker), Thread(target=remove_worker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    if errors:
        raise errors[0]

    assert "remove" in outcomes
    assert set(outcomes).issubset({"remove", "grant", "grant-denied"})
    with SessionLocal() as verify:
        assert verify.scalar(
            select(FamilyMembership.id).where(FamilyMembership.user_id == member)
        ) is None
        assert verify.scalar(
            select(FamilyPermissionGrant.id).where(
                FamilyPermissionGrant.grantee_user_id == member
            )
        ) is None
        assert not has_family_permission(
            verify,
            resource_owner_user_id=owner,
            grantee_user_id=member,
            permission_code=FamilyPermissionCode.VIEW_MEMORY,
        )

    with SessionLocal() as cleanup:
        for user_id in (member, owner):
            user = cleanup.get(User, user_id)
            if user is not None:
                cleanup.delete(user)
        cleanup.commit()


def _assert_direct_data_delete_family_lifecycle() -> None:
    member_owner = _user("data-member-owner")
    member = _user("data-member")
    with SessionLocal() as db:
        family = create_family(db, user_id=member_owner)
        db.add(
            FamilyMembership(
                family_id=family.family_id,
                user_id=member,
                role="MEMBER",
            )
        )
        db.commit()
        replace_permissions(
            db,
            resource_owner_user_id=member_owner,
            grantee_user_id=member,
            permission_codes=[FamilyPermissionCode.VIEW_MEMORY.value],
        )
        member_family_id = family.family_id

    with SessionLocal() as deleting:
        result = delete_all_user_data(
            deleting,
            user_id=member,
            request_id=uuid4(),
            storage=EmptyStorage(),
        )
        assert result.completed is True

    with SessionLocal() as verify:
        # Data Delete preserves account identity but removes MEMBER relationship data.
        assert verify.get(User, member) is not None
        assert verify.get(User, member_owner) is not None
        assert verify.get(Family, member_family_id) is not None
        assert verify.scalar(
            select(FamilyMembership.id).where(FamilyMembership.user_id == member)
        ) is None
        assert verify.scalar(
            select(FamilyPermissionGrant.id).where(
                FamilyPermissionGrant.grantee_user_id == member
            )
        ) is None
        owner_membership = verify.scalar(
            select(FamilyMembership).where(
                FamilyMembership.user_id == member_owner
            )
        )
        assert owner_membership is not None
        assert owner_membership.role == "OWNER"

    with SessionLocal() as cleanup:
        for user_id in (member, member_owner):
            user = cleanup.get(User, user_id)
            if user is not None:
                cleanup.delete(user)
        cleanup.commit()

    owner = _user("data-owner")
    surviving_member = _user("data-owner-member")
    with SessionLocal() as db:
        family = create_family(db, user_id=owner)
        db.add(
            FamilyMembership(
                family_id=family.family_id,
                user_id=surviving_member,
                role="MEMBER",
            )
        )
        db.commit()
        replace_permissions(
            db,
            resource_owner_user_id=owner,
            grantee_user_id=surviving_member,
            permission_codes=[FamilyPermissionCode.VIEW_FOOTPRINT.value],
        )
        dissolved_family_id = family.family_id

    with SessionLocal() as deleting:
        result = delete_all_user_data(
            deleting,
            user_id=owner,
            request_id=uuid4(),
            storage=EmptyStorage(),
        )
        assert result.completed is True

    with SessionLocal() as verify:
        # OWNER Data Delete preserves accounts but dissolves the Family authorization graph.
        assert verify.get(User, owner) is not None
        assert verify.get(User, surviving_member) is not None
        assert verify.get(Family, dissolved_family_id) is None
        assert verify.scalar(
            select(FamilyMembership.id).where(
                FamilyMembership.family_id == dissolved_family_id
            )
        ) is None
        assert verify.scalar(
            select(FamilyPermissionGrant.id).where(
                FamilyPermissionGrant.family_id == dissolved_family_id
            )
        ) is None

    with SessionLocal() as cleanup:
        for user_id in (surviving_member, owner):
            user = cleanup.get(User, user_id)
            if user is not None:
                cleanup.delete(user)
        cleanup.commit()


def _assert_reverse_grant_vs_owner_remove_converges() -> None:
    owner = _user("reverse-remove-owner")
    member = _user("reverse-remove-member")
    with SessionLocal() as db:
        family = create_family(db, user_id=owner)
        db.add(
            FamilyMembership(
                family_id=family.family_id,
                user_id=member,
                role="MEMBER",
            )
        )
        db.commit()

    barrier = Barrier(2)
    outcomes: list[str] = []
    errors: list[BaseException] = []

    def member_grants_owner() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                replace_permissions(
                    db,
                    resource_owner_user_id=member,
                    grantee_user_id=owner,
                    permission_codes=[FamilyPermissionCode.VIEW_MEMORY.value],
                )
                outcomes.append("grant")
        except FamilyServiceError as exc:
            # Removal may win first; a removed resource owner is no longer in a Family.
            assert exc.code == "FAMILY_NOT_FOUND"
            outcomes.append("grant-denied")
        except BaseException as exc:  # noqa: BLE001 - thread reports test failures
            errors.append(exc)

    def owner_removes_member() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                remove_member(
                    db,
                    actor_user_id=owner,
                    target_user_id=member,
                )
                outcomes.append("remove")
        except BaseException as exc:  # noqa: BLE001 - thread reports test failures
            errors.append(exc)

    threads = [
        Thread(target=member_grants_owner),
        Thread(target=owner_removes_member),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    if errors:
        raise errors[0]

    assert "remove" in outcomes
    assert set(outcomes).issubset({"remove", "grant", "grant-denied"})
    with SessionLocal() as verify:
        assert verify.scalar(
            select(FamilyMembership.id).where(FamilyMembership.user_id == member)
        ) is None
        assert verify.scalar(
            select(FamilyPermissionGrant.id).where(
                FamilyPermissionGrant.resource_owner_user_id == member
            )
        ) is None
        assert not has_family_permission(
            verify,
            resource_owner_user_id=member,
            grantee_user_id=owner,
            permission_code=FamilyPermissionCode.VIEW_MEMORY,
        )

    with SessionLocal() as cleanup:
        for user_id in (member, owner):
            user = cleanup.get(User, user_id)
            if user is not None:
                cleanup.delete(user)
        cleanup.commit()


def _assert_reciprocal_grants_do_not_deadlock() -> None:
    owner = _user("reciprocal-owner")
    member = _user("reciprocal-member")
    with SessionLocal() as db:
        family = create_family(db, user_id=owner)
        db.add(
            FamilyMembership(
                family_id=family.family_id,
                user_id=member,
                role="MEMBER",
            )
        )
        db.commit()

    # Run several real PostgreSQL races so the old opposite lock order would have
    # repeated opportunities to deadlock (A->B versus B->A).
    for round_index in range(8):
        barrier = Barrier(2)
        errors: list[BaseException] = []

        def owner_grants_member(
            barrier: Barrier = barrier,
            errors: list[BaseException] = errors,
        ) -> None:
            try:
                barrier.wait(timeout=15)
                with SessionLocal() as db:
                    replace_permissions(
                        db,
                        resource_owner_user_id=owner,
                        grantee_user_id=member,
                        permission_codes=[FamilyPermissionCode.VIEW_MEMORY.value],
                    )
            except BaseException as exc:  # noqa: BLE001 - thread reports test failures
                errors.append(exc)

        def member_grants_owner(
            barrier: Barrier = barrier,
            errors: list[BaseException] = errors,
        ) -> None:
            try:
                barrier.wait(timeout=15)
                with SessionLocal() as db:
                    replace_permissions(
                        db,
                        resource_owner_user_id=member,
                        grantee_user_id=owner,
                        permission_codes=[FamilyPermissionCode.VIEW_FOOTPRINT.value],
                    )
            except BaseException as exc:  # noqa: BLE001 - thread reports test failures
                errors.append(exc)

        threads = [
            Thread(
                target=owner_grants_member,
                name=f"reciprocal-owner-{round_index}",
            ),
            Thread(
                target=member_grants_owner,
                name=f"reciprocal-member-{round_index}",
            ),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
            assert not thread.is_alive()
        if errors:
            raise errors[0]

    with SessionLocal() as verify:
        assert has_family_permission(
            verify,
            resource_owner_user_id=owner,
            grantee_user_id=member,
            permission_code=FamilyPermissionCode.VIEW_MEMORY,
        )
        assert has_family_permission(
            verify,
            resource_owner_user_id=member,
            grantee_user_id=owner,
            permission_code=FamilyPermissionCode.VIEW_FOOTPRINT,
        )

    with SessionLocal() as cleanup:
        for user_id in (member, owner):
            user = cleanup.get(User, user_id)
            if user is not None:
                cleanup.delete(user)
        cleanup.commit()

def main() -> None:
    _assert_concurrent_family_create()
    _assert_database_rejects_second_owner()
    _assert_same_invite_has_at_most_one_winner()
    _assert_accept_vs_revoke_serializes()
    _assert_cross_family_invite_idor_fails_closed()
    _assert_permission_default_deny_and_removal_cleanup()
    _assert_grant_vs_member_remove_converges()
    _assert_reverse_grant_vs_owner_remove_converges()
    _assert_reciprocal_grants_do_not_deadlock()
    _assert_cross_family_isolation()
    _assert_direct_data_delete_family_lifecycle()
    _assert_account_delete_family_lifecycle()
    print("PostgreSQL Family Foundation invariants PASS")


if __name__ == "__main__":
    main()
