"""PostgreSQL migration gate for S4-008 audit authority backfill."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.family_models import (
    FamilyAccessAuditEvent,
    FamilyAuditAuthorityType,
    FamilyMembership,
    FamilyPermissionCode,
    FamilyRole,
)
from app.models import User
from app.services.family_service import create_family

DATABASE_URL = os.environ["DATABASE_URL"]


def _alembic(*args: str) -> None:
    subprocess.run(["alembic", *args], check=True)


def main() -> None:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    owner_id = uuid4()
    member_id = uuid4()
    event_id = uuid4()

    with Session(engine) as db:
        db.add_all(
            [
                User(id=owner_id, nickname="emergency-migration-owner"),
                User(id=member_id, nickname="emergency-migration-member"),
            ]
        )
        db.commit()
        family = create_family(db, user_id=owner_id)
        family_id = family.family_id
        db.add(
            FamilyMembership(
                family_id=family_id,
                user_id=member_id,
                role=FamilyRole.MEMBER.value,
            )
        )
        db.commit()

    # Recreate the exact pre-Stage-4F schema and seed a real #112-style legacy row
    # that has no authority_type column yet.
    _alembic("downgrade", "0016_family_privacy_audit")
    engine.dispose()
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO family_access_audit_events (
                    id,
                    family_id,
                    actor_user_id,
                    resource_owner_user_id,
                    permission_code,
                    resource_type,
                    action,
                    result,
                    created_at
                ) VALUES (
                    :id,
                    :family_id,
                    :actor_user_id,
                    :resource_owner_user_id,
                    :permission_code,
                    'CURRENT_LOCATION',
                    'READ_CURRENT_LOCATION',
                    'ALLOWED',
                    :created_at
                )
                """
            ),
            {
                "id": event_id,
                "family_id": family_id,
                "actor_user_id": member_id,
                "resource_owner_user_id": owner_id,
                "permission_code": FamilyPermissionCode.VIEW_CURRENT_LOCATION.value,
                "created_at": datetime.now(UTC),
            },
        )

    _alembic("upgrade", "head")
    engine.dispose()
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

    with Session(engine) as db:
        event = db.scalar(
            select(FamilyAccessAuditEvent).where(
                FamilyAccessAuditEvent.id == event_id
            )
        )
        assert event is not None
        assert event.authority_type == FamilyAuditAuthorityType.EXACT_GRANT.value
        assert event.permission_code == FamilyPermissionCode.VIEW_CURRENT_LOCATION.value
        assert event.action == "READ_CURRENT_LOCATION"

    # P1 regression: PostgreSQL CHECK must reject EXACT_GRANT + NULL permission.
    invalid_event_id = uuid4()
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(
                text(
                    """
                    INSERT INTO family_access_audit_events (
                        id,
                        family_id,
                        actor_user_id,
                        resource_owner_user_id,
                        authority_type,
                        permission_code,
                        resource_type,
                        action,
                        result,
                        created_at
                    ) VALUES (
                        :id,
                        :family_id,
                        :actor_user_id,
                        :resource_owner_user_id,
                        'EXACT_GRANT',
                        NULL,
                        'CURRENT_LOCATION',
                        'READ_CURRENT_LOCATION',
                        'ALLOWED',
                        :created_at
                    )
                    """
                ),
                {
                    "id": invalid_event_id,
                    "family_id": family_id,
                    "actor_user_id": member_id,
                    "resource_owner_user_id": owner_id,
                    "created_at": datetime.now(UTC),
                },
            )
        except IntegrityError:
            transaction.rollback()
        else:
            transaction.rollback()
            raise AssertionError(
                "EXACT_GRANT + NULL permission_code must fail PostgreSQL CHECK"
            )

    with Session(engine) as db:
        assert db.get(FamilyAccessAuditEvent, invalid_event_id) is None
        member = db.get(User, member_id)
        owner = db.get(User, owner_id)
        assert member is not None
        assert owner is not None
        db.delete(member)
        db.delete(owner)
        db.commit()

    engine.dispose()
    print("PostgreSQL Emergency audit migration/backfill gate: PASS")


if __name__ == "__main__":
    main()
