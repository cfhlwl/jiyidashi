"""PostgreSQL race gates for S4-007 Family Photos Read V1."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Barrier, Thread
from uuid import UUID, uuid4

from app.core.db import SessionLocal
from app.family_models import FamilyMembership, FamilyPermissionCode, FamilyRole
from app.media_models import MediaAsset, MediaKind, MediaStatus
from app.models import User
from app.services.family_sensitive_read_service import (
    FamilySensitiveReadError,
    get_family_photos,
    sign_family_photo_download,
)
from app.services.family_service import create_family, remove_member, replace_permissions
from app.services.object_storage import PresignedTransfer


class _Storage:
    def __init__(self) -> None:
        self.keys: list[str] = []

    def sign_download(self, object_key: str) -> PresignedTransfer:
        self.keys.append(object_key)
        return PresignedTransfer(
            method="GET",
            url=f"https://family-photo-race.test/{object_key}?temporary=1",
            headers={},
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )


def _user(label: str) -> UUID:
    user_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname=f"family-photo-pg-{label}"))
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


def _photo(owner: UUID) -> tuple[UUID, str]:
    media_id = uuid4()
    key = f"final/{owner}/{media_id.hex}"
    with SessionLocal() as db:
        db.add(
            MediaAsset(
                id=media_id,
                user_id=owner,
                client_upload_id=uuid4(),
                kind=MediaKind.IMAGE,
                status=MediaStatus.READY,
                upload_object_key=f"staging/{owner}/{media_id.hex}",
                object_key=key,
                content_type="image/jpeg",
                size_bytes=1024,
                created_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
        )
        db.commit()
    return media_id, key


def _cleanup(*user_ids: UUID) -> None:
    with SessionLocal() as db:
        for user_id in user_ids:
            user = db.get(User, user_id)
            if user is not None:
                db.delete(user)
        db.commit()


def _assert_photos_denied(owner: UUID, member: UUID) -> None:
    with SessionLocal() as db:
        try:
            get_family_photos(
                db,
                resource_owner_user_id=owner,
                grantee_user_id=member,
            )
            raise AssertionError("post-mutation Family photo list unexpectedly allowed")
        except FamilySensitiveReadError as exc:
            assert exc.code == "FAMILY_READ_NOT_AUTHORIZED"
            assert exc.status_code == 403


def _assert_sign_denied(owner: UUID, member: UUID, media_id: UUID) -> None:
    storage = _Storage()
    with SessionLocal() as db:
        try:
            sign_family_photo_download(
                db,
                resource_owner_user_id=owner,
                grantee_user_id=member,
                media_id=media_id,
                storage=storage,
            )
            raise AssertionError("post-mutation Family photo signing unexpectedly allowed")
        except FamilySensitiveReadError as exc:
            assert exc.code == "FAMILY_READ_NOT_AUTHORIZED"
            assert exc.status_code == 403
    assert storage.keys == []


def _list_vs_revoke() -> None:
    owner, member = _family_pair("list-revoke")
    _photo(owner)

    for _ in range(6):
        _grant(owner, member, FamilyPermissionCode.VIEW_PHOTOS.value)
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
                        get_family_photos(
                            db,
                            resource_owner_user_id=owner,
                            grantee_user_id=member,
                        )
                        outcomes.append("list-allowed")
                    except FamilySensitiveReadError as exc:
                        assert exc.code == "FAMILY_READ_NOT_AUTHORIZED"
                        outcomes.append("list-denied")
            except BaseException as exc:  # noqa: BLE001
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
            except BaseException as exc:  # noqa: BLE001
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
        assert set(outcomes).issubset({"list-allowed", "list-denied", "revoked"})
        _assert_photos_denied(owner, member)

    _cleanup(member, owner)


def _list_vs_remove() -> None:
    owner, member = _family_pair("list-remove")
    _photo(owner)
    _grant(owner, member, FamilyPermissionCode.VIEW_PHOTOS.value)

    barrier = Barrier(2)
    outcomes: list[str] = []
    errors: list[BaseException] = []

    def reader() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                try:
                    get_family_photos(
                        db,
                        resource_owner_user_id=owner,
                        grantee_user_id=member,
                    )
                    outcomes.append("list-allowed")
                except FamilySensitiveReadError as exc:
                    assert exc.code == "FAMILY_READ_NOT_AUTHORIZED"
                    outcomes.append("list-denied")
        except BaseException as exc:  # noqa: BLE001
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
        except BaseException as exc:  # noqa: BLE001
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
    assert set(outcomes).issubset({"list-allowed", "list-denied", "removed"})
    _assert_photos_denied(owner, member)
    _cleanup(member, owner)


def _sign_vs_revoke() -> None:
    owner, member = _family_pair("sign-revoke")
    media_id, expected_key = _photo(owner)

    for _ in range(6):
        _grant(owner, member, FamilyPermissionCode.VIEW_PHOTOS.value)
        barrier = Barrier(2)
        outcomes: list[str] = []
        errors: list[BaseException] = []
        storage = _Storage()

        def signer(
            barrier: Barrier = barrier,
            outcomes: list[str] = outcomes,
            errors: list[BaseException] = errors,
            storage: _Storage = storage,
        ) -> None:
            try:
                barrier.wait(timeout=15)
                with SessionLocal() as db:
                    try:
                        transfer = sign_family_photo_download(
                            db,
                            resource_owner_user_id=owner,
                            grantee_user_id=member,
                            media_id=media_id,
                            storage=storage,
                        )
                        assert transfer.method == "GET"
                        outcomes.append("sign-issued")
                    except FamilySensitiveReadError as exc:
                        assert exc.code == "FAMILY_READ_NOT_AUTHORIZED"
                        outcomes.append("sign-denied")
            except BaseException as exc:  # noqa: BLE001
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
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [Thread(target=signer), Thread(target=revoker)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
            assert not thread.is_alive()
        if errors:
            raise errors[0]

        assert "revoked" in outcomes
        assert set(outcomes).issubset({"sign-issued", "sign-denied", "revoked"})
        if "sign-issued" in outcomes:
            assert storage.keys == [expected_key]
        else:
            assert storage.keys == []
        _assert_sign_denied(owner, member, media_id)

    _cleanup(member, owner)


def _sign_vs_remove() -> None:
    owner, member = _family_pair("sign-remove")
    media_id, expected_key = _photo(owner)
    _grant(owner, member, FamilyPermissionCode.VIEW_PHOTOS.value)

    barrier = Barrier(2)
    outcomes: list[str] = []
    errors: list[BaseException] = []
    storage = _Storage()

    def signer() -> None:
        try:
            barrier.wait(timeout=15)
            with SessionLocal() as db:
                try:
                    sign_family_photo_download(
                        db,
                        resource_owner_user_id=owner,
                        grantee_user_id=member,
                        media_id=media_id,
                        storage=storage,
                    )
                    outcomes.append("sign-issued")
                except FamilySensitiveReadError as exc:
                    assert exc.code == "FAMILY_READ_NOT_AUTHORIZED"
                    outcomes.append("sign-denied")
        except BaseException as exc:  # noqa: BLE001
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
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [Thread(target=signer), Thread(target=remover)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    if errors:
        raise errors[0]

    assert "removed" in outcomes
    assert set(outcomes).issubset({"sign-issued", "sign-denied", "removed"})
    if "sign-issued" in outcomes:
        assert storage.keys == [expected_key]
    else:
        assert storage.keys == []
    _assert_sign_denied(owner, member, media_id)
    _cleanup(member, owner)


def main() -> None:
    _list_vs_revoke()
    _list_vs_remove()
    _sign_vs_revoke()
    _sign_vs_remove()
    print("PostgreSQL Family Photos Read invariants PASS")


if __name__ == "__main__":
    main()
