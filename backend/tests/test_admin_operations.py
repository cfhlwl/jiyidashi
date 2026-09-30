from __future__ import annotations

from uuid import uuid4

from sqlalchemy import delete, select

from app.admin_models import (
    AdminAccount,
    AdminAuditEvent,
    AdminRole,
    EntitlementQuotaPolicy,
)
from app.auth_models import AuthRateLimitBucket
from app.core.db import SessionLocal
from app.models import User
from app.services.admin_security import hash_admin_password
from app.services.entitlement_service import create_legacy_full_entitlement


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


def _create_admin(*, role: AdminRole) -> tuple[str, str]:
    _reset_admin_login_buckets()
    email = f"admin-{uuid4()}@example.com"
    password = "Admin-Test-Password-123!"
    with SessionLocal() as db:
        db.add(
            AdminAccount(
                email=email,
                display_name="测试管理员",
                password_hash=hash_admin_password(password),
                role=role.value,
                disabled=False,
                revision=0,
            )
        )
        db.commit()
    return email, password


async def _login(client, *, role: AdminRole):
    email, password = _create_admin(role=role)
    response = await client.post(
        "/admin/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    csrf = client.cookies.get("jiyi_admin_csrf")
    assert csrf
    return email, {"X-CSRF-Token": csrf}


def _quota_payload(*, expected_revision=None, storage=1000):
    return {
        "plans": [
            {
                "plan_code": plan,
                "expected_revision": expected_revision,
                "storage_bytes": storage + index,
                "ai_provider_requests": 100 + index,
                "ai_input_tokens": 1000 + index,
                "ai_output_tokens": 2000 + index,
            }
            for index, plan in enumerate(["FREE", "PERSONAL", "FAMILY", "PREMIUM"])
        ],
        "confirmation": "保存额度配置",
    }


async def test_support_and_operator_cannot_mutate_privileged_settings(client):
    for role in (AdminRole.SUPPORT_READONLY, AdminRole.OPERATOR):
        client.cookies.clear()
        _, headers = await _login(client, role=role)
        response = await client.put(
            "/admin/api/v1/settings/quota-catalog",
            headers=headers,
            json=_quota_payload(),
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "ADMIN_PERMISSION_DENIED"


async def test_quota_catalog_initializes_atomically_and_rejects_stale_revision(client):
    client.cookies.clear()
    _, headers = await _login(client, role=AdminRole.SUPER_ADMIN)

    # Clean any rows left by a prior test; production has no delete API for this table.
    with SessionLocal() as db:
        for row in db.scalars(select(EntitlementQuotaPolicy)):
            db.delete(row)
        db.commit()

    created = await client.put(
        "/admin/api/v1/settings/quota-catalog",
        headers=headers,
        json=_quota_payload(),
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["initialized"] is True
    assert len(body["plans"]) == 4
    assert {item["revision"] for item in body["plans"]} == {0}

    stale = await client.put(
        "/admin/api/v1/settings/quota-catalog",
        headers=headers,
        json=_quota_payload(expected_revision=99, storage=5000),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == "ADMIN_STATE_STALE"

    updated = await client.put(
        "/admin/api/v1/settings/quota-catalog",
        headers=headers,
        json=_quota_payload(expected_revision=0, storage=5000),
    )
    assert updated.status_code == 200
    assert {item["revision"] for item in updated.json()["plans"]} == {1}

    with SessionLocal() as db:
        audit = db.scalar(
            select(AdminAuditEvent)
            .where(AdminAuditEvent.action == "ENTITLEMENT_QUOTA_CATALOG_UPDATE")
            .order_by(AdminAuditEvent.created_at.desc())
            .limit(1)
        )
        assert audit is not None
        assert "before" in audit.metadata_json
        assert "after" in audit.metadata_json


async def test_entitlement_adjustment_requires_catalog_and_stale_revision(client):
    client.cookies.clear()
    _, headers = await _login(client, role=AdminRole.SUPER_ADMIN)

    with SessionLocal() as db:
        for row in db.scalars(select(EntitlementQuotaPolicy)):
            db.delete(row)
        user = User(nickname="Admin target")
        db.add(user)
        db.flush()
        create_legacy_full_entitlement(db, user_id=user.id)
        user_id = user.id
        db.commit()

    denied = await client.put(
        f"/admin/api/v1/users/{user_id}/entitlement",
        headers=headers,
        json={
            "expected_revision": 0,
            "plan_code": "PERSONAL",
            "confirmation": "调整会员方案",
        },
    )
    assert denied.status_code == 409
    assert denied.json()["detail"] == "ADMIN_QUOTA_POLICY_NOT_INITIALIZED"

    initialized = await client.put(
        "/admin/api/v1/settings/quota-catalog",
        headers=headers,
        json=_quota_payload(),
    )
    assert initialized.status_code == 200

    changed = await client.put(
        f"/admin/api/v1/users/{user_id}/entitlement",
        headers=headers,
        json={
            "expected_revision": 0,
            "plan_code": "PERSONAL",
            "confirmation": "调整会员方案",
        },
    )
    assert changed.status_code == 200

    stale = await client.put(
        f"/admin/api/v1/users/{user_id}/entitlement",
        headers=headers,
        json={
            "expected_revision": 0,
            "plan_code": "FREE",
            "confirmation": "调整会员方案",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == "ADMIN_STATE_STALE"


async def test_admin_role_change_revokes_target_sessions_and_forbids_self_role_change(client):
    client.cookies.clear()
    actor_email, headers = await _login(client, role=AdminRole.SUPER_ADMIN)

    create = await client.post(
        "/admin/api/v1/admins",
        headers=headers,
        json={
            "email": f"support-{uuid4()}@example.com",
            "display_name": "支持同事",
            "password": "Support-Test-Password-123!",
            "role": "SUPPORT_READONLY",
            "confirmation": "创建管理员",
        },
    )
    assert create.status_code == 201, create.text
    target = create.json()

    updated = await client.patch(
        f"/admin/api/v1/admins/{target['id']}",
        headers=headers,
        json={
            "expected_revision": target["revision"],
            "role": "OPERATOR",
            "confirmation": "确认管理员变更",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["role"] == "OPERATOR"
    assert updated.json()["revision"] == target["revision"] + 1

    with SessionLocal() as db:
        actor = db.scalar(select(AdminAccount).where(AdminAccount.email == actor_email))
        assert actor is not None
        actor_id = actor.id
        actor_revision = actor.revision

    self_change = await client.patch(
        f"/admin/api/v1/admins/{actor_id}",
        headers=headers,
        json={
            "expected_revision": actor_revision,
            "disabled": True,
            "confirmation": "确认管理员变更",
        },
    )
    assert self_change.status_code == 409
    assert self_change.json()["detail"] == "ADMIN_SELF_ROLE_CHANGE_DENIED"
