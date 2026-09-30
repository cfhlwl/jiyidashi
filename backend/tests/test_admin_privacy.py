from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import delete

from app.account_deletion_models import AccountDeletionOperation
from app.admin_models import AdminAccount, AdminRole
from app.auth_models import AuthRateLimitBucket
from app.core.db import SessionLocal
from app.data_deletion_models import DataDeletionOperation, DataDeletionStatus
from app.entitlement_models import PlanCode, UserEntitlement
from app.family_models import Family, FamilyMembership
from app.media_models import MediaAsset, MediaKind, MediaStatus
from app.models import Memory, User
from app.services.admin_security import hash_admin_password




def _reset_admin_login_buckets() -> None:
    with SessionLocal() as db:
        db.execute(
            delete(AuthRateLimitBucket).where(
                AuthRateLimitBucket.scope.in_(
                    ("admin_login_ip", "admin_login_account_ip")
                )
            )
        )
        db.commit()


async def _admin_login(client):
    _reset_admin_login_buckets()
    email = f"privacy-admin-{uuid4()}@example.com"
    password = "Admin-Test-Password-123!"
    with SessionLocal() as db:
        db.add(
            AdminAccount(
                email=email,
                display_name="隐私审查管理员",
                password_hash=hash_admin_password(password),
                role=AdminRole.SUPPORT_READONLY.value,
                disabled=False,
                revision=0,
            )
        )
        db.commit()
    response = await client.post(
        "/admin/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200


def _seed_private_user() -> str:
    secret = f"PRIVATE-CONTENT-{uuid4()}"
    with SessionLocal() as db:
        user = User(
            nickname="隐私边界测试用户",
            email=f"privacy-user-{uuid4()}@example.com",
        )
        db.add(user)
        db.flush()
        db.add(
            UserEntitlement(
                user_id=user.id,
                plan_code=PlanCode.LEGACY_FULL.value,
                revision=0,
                effective_at=user.created_at,
            )
        )
        db.add(
            Memory(
                user_id=user.id,
                title=f"{secret}-TITLE",
                content=f"{secret}-MEMORY-BODY",
                latitude=39.123456,
                longitude=116.654321,
            )
        )
        db.add(
            MediaAsset(
                user_id=user.id,
                client_upload_id=uuid4(),
                kind=MediaKind.IMAGE,
                status=MediaStatus.READY,
                upload_object_key=f"{secret}/private-upload-key",
                object_key=f"{secret}/private-object-key",
                content_type="image/jpeg",
                size_bytes=1234,
                storage_etag=f"{secret}-etag",
            )
        )
        family = Family(created_by_user_id=user.id)
        db.add(family)
        db.flush()
        db.add(
            FamilyMembership(
                family_id=family.id,
                user_id=user.id,
                role="OWNER",
            )
        )
        db.add(
            DataDeletionOperation(
                user_id=user.id,
                request_id=uuid4(),
                status=DataDeletionStatus.STORAGE_FAILED,
                last_error_code=f"{secret}-RAW-ERROR",
                deleted_counts={"memories": 1},
            )
        )
        db.add(
            AccountDeletionOperation(
                user_id=user.id,
                request_id=uuid4(),
                data_deletion_request_id=uuid4(),
            )
        )
        user_id = str(user.id)
        db.commit()
    return user_id, secret


async def test_admin_projections_never_expose_private_content_or_storage_capabilities(client):
    user_id, secret = _seed_private_user()
    await _admin_login(client)

    urls = [
        "/admin/api/v1/dashboard",
        "/admin/api/v1/users",
        f"/admin/api/v1/users/{user_id}",
        "/admin/api/v1/families",
        "/admin/api/v1/data-tasks/deletions",
        "/admin/api/v1/data-tasks/account-deletions",
        "/admin/api/v1/security/alerts",
        "/admin/api/v1/system/settings",
        "/admin/api/v1/system/health",
    ]
    forbidden = [
        secret,
        "PRIVATE-CONTENT",
        "39.123456",
        "116.654321",
        "private-object-key",
        "private-upload-key",
        "RAW-ERROR",
        "storage_etag",
        "object_key",
        "upload_object_key",
        "latitude",
        "longitude",
    ]

    for url in urls:
        response = await client.get(url)
        assert response.status_code == 200, (url, response.text)
        payload = json.dumps(response.json(), ensure_ascii=False)
        for value in forbidden:
            assert value not in payload, (url, value, payload)
