"""PostgreSQL race gates for S4-015 Family Privacy Audit V1."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Barrier, Thread
from uuid import UUID, uuid4

from sqlalchemy import delete, select

from app.core.db import SessionLocal
from app.family_models import (
    FamilyAccessAuditEvent,
    FamilyAuditAction,
    FamilyAuditResult,
    FamilyMembership,
    FamilyPermissionCode,
    FamilyRole,
)
from app.media_models import MediaAsset, MediaKind, MediaStatus
from app.models import LocationPoint, User
from app.services.family_sensitive_read_service import (
    FamilySensitiveReadError,
    get_family_current_location,
    sign_family_photo_download,
)
from app.services.family_service import create_family, remove_member, replace_permissions
from app.services.object_storage import PresignedTransfer


class _Storage:
    def sign_download(self, object_key: str) -> PresignedTransfer:
        return PresignedTransfer(
            method="GET",
            url=f"https://family-audit-race.test/{object_key}?temporary=1",
            headers={},
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )


def _user(label: str) -> UUID:
    user_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname=f"family-audit-{label}"))
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


def _point(owner: UUID) -> None:
    with SessionLocal() as db:
        db.add(
            LocationPoint(
                user_id=owner,
                client_uuid=f"audit-race-{uuid4().hex}",
                latitude=31.2304,
                longitude=121.4737,
                accuracy=6.0,
                speed=0.0,
                recorded_at=datetime.now(UTC),
            )
        )
        db.commit()


def _photo(owner: UUID) -> UUID:
    media_id = uuid4()
    with SessionLocal() as db:
        db.add(
            MediaAsset(
                id=media_id,
                user_id=owner,
                client_upload_id=uuid4(),
                kind=MediaKind.IMAGE,
                status=MediaStatus.READY,
                upload_object_key=f"staging/{owner}/{media_id.hex}",
                object_key=f"final/{owner}/{media_id.hex}",
                content_type="image/jpeg",
                size_bytes=1024,
                original_filename="private.jpg",
                storage_etag="private-etag",
                created_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
        )
        db.commit()
    return media_id


def _clear_audit(owner: UUID) -> None:
    with SessionLocal() as db:
        db.execute(
            delete(FamilyAccessAuditEvent).where(
                FamilyAccessAuditEvent.resource_owner_user_id == owner
            )
        )
        db.commit()


def _allowed_count(owner: UUID, action: FamilyAuditAction) -> int:
    with SessionLocal() as db:
        return len(
            db.scalars(
                select(FamilyAccessAuditEvent.id).where(
                    FamilyAccessAuditEvent.resource_owner_user_id == owner,
                    FamilyAccessAuditEvent.action == action.value,
                    FamilyAccessAuditEvent.result == FamilyAuditResult.ALLOWED.value,
                )
            ).all()
        )


def _cleanup(*user_ids: UUID) -> None:
    with SessionLocal() as db:
        for user_id in user_ids:
            user = db.get(User, user_id)
            if user is not None:
                db.delete(user)
        db.commit()


def _race_location_revoke() -> None:
    owner, member = _family_pair("location-revoke")
    _point(owner)
    for _ in range(4):
        _grant(owner, member, FamilyPermissionCode.VIEW_CURRENT_LOCATION.value)
        _clear_audit(owner)
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
                        get_family_current_location(
                            db,
                            resource_owner_user_id=owner,
                            grantee_user_id=member,
                        )
                        outcome.append("allowed")
                    except FamilySensitiveReadError as exc:
                        assert exc.code == "FAMILY_READ_NOT_AUTHORIZED"
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
                    replace_permissions(
                        db,
                        resource_owner_user_id=owner,
                        grantee_user_id=member,
                        permission_codes=[],
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

        count = _allowed_count(owner, FamilyAuditAction.READ_CURRENT_LOCATION)
        assert count == (1 if outcome == ["allowed"] else 0)

    _cleanup(member, owner)


def _race_location_remove() -> None:
    owner, member = _family_pair("location-remove")
    _grant(owner, member, FamilyPermissionCode.VIEW_CURRENT_LOCATION.value)
    _point(owner)
    _clear_audit(owner)
    barrier = Barrier(2)
    outcome: list[str] = []
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
                    outcome.append("allowed")
                except FamilySensitiveReadError as exc:
                    assert exc.code == "FAMILY_READ_NOT_AUTHORIZED"
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

    assert _allowed_count(owner, FamilyAuditAction.READ_CURRENT_LOCATION) == (
        1 if outcome == ["allowed"] else 0
    )
    _cleanup(member, owner)


def _race_photo_revoke() -> None:
    owner, member = _family_pair("photo-revoke")
    media_id = _photo(owner)
    for _ in range(4):
        _grant(owner, member, FamilyPermissionCode.VIEW_PHOTOS.value)
        _clear_audit(owner)
        barrier = Barrier(2)
        outcome: list[str] = []
        errors: list[BaseException] = []

        def signer(
            barrier: Barrier = barrier,
            outcome: list[str] = outcome,
            errors: list[BaseException] = errors,
        ) -> None:
            try:
                barrier.wait(timeout=15)
                with SessionLocal() as db:
                    try:
                        sign_family_photo_download(
                            db,
                            resource_owner_user_id=owner,
                            grantee_user_id=member,
                            media_id=media_id,
                            storage=_Storage(),
                        )
                        outcome.append("allowed")
                    except FamilySensitiveReadError as exc:
                        assert exc.code == "FAMILY_READ_NOT_AUTHORIZED"
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
                    replace_permissions(
                        db,
                        resource_owner_user_id=owner,
                        grantee_user_id=member,
                        permission_codes=[],
                    )
            except BaseException as exc:
                errors.append(exc)

        threads = [Thread(target=signer), Thread(target=revoker)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
            assert not thread.is_alive()
        if errors:
            raise errors[0]

        assert _allowed_count(owner, FamilyAuditAction.DOWNLOAD_PHOTO) == (
            1 if outcome == ["allowed"] else 0
        )

    _cleanup(member, owner)


def _race_photo_remove() -> None:
    owner, member = _family_pair("photo-remove")
    media_id = _photo(owner)
    _grant(owner, member, FamilyPermissionCode.VIEW_PHOTOS.value)
    _clear_audit(owner)
    barrier = Barrier(2)
    outcome: list[str] = []
    errors: list[BaseException] = []

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
                        storage=_Storage(),
                    )
                    outcome.append("allowed")
                except FamilySensitiveReadError as exc:
                    assert exc.code == "FAMILY_READ_NOT_AUTHORIZED"
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

    threads = [Thread(target=signer), Thread(target=remover)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    if errors:
        raise errors[0]

    assert _allowed_count(owner, FamilyAuditAction.DOWNLOAD_PHOTO) == (
        1 if outcome == ["allowed"] else 0
    )
    _cleanup(member, owner)


if __name__ == "__main__":
    _race_location_revoke()
    _race_location_remove()
    _race_photo_revoke()
    _race_photo_remove()
    print("PostgreSQL Family Privacy Audit race gate: PASS")
