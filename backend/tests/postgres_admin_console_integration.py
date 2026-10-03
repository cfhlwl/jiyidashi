"""Real PostgreSQL ADMIN-001 authority/concurrency gate."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from threading import Barrier, Lock, Thread
from uuid import uuid4

from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError

from app.admin_models import (
    AdminAccount,
    AdminAuditEvent,
    AdminRole,
    AdminSession,
    EntitlementQuotaPolicy,
    ProviderConfiguration,
    ProviderService,
)
from app.admin_schemas import (
    AdminProviderConfigWrite,
    AdminQuotaCatalogWrite,
    AdminQuotaPlanWrite,
)
from app.core.config import Settings
from app.core.db import SessionLocal, engine
from app.maintenance.admin_bootstrap import bootstrap_super_admin
from app.services.admin_operations import write_quota_catalog
from app.services.admin_provider_service import update_provider_configuration
from app.services.admin_security import AdminOperationError, hash_admin_password

DATABASE_URL = os.environ["DATABASE_URL"]


def _alembic(*args: str) -> None:
    subprocess.run(["alembic", *args], check=True)


def _seed_super_admin() -> AdminAccount:
    with SessionLocal() as db:
        row = AdminAccount(
            email=f"admin-{uuid4()}@example.com",
            display_name="Admin Gate",
            password_hash=hash_admin_password("Admin-Gate-Password-123!"),
            role=AdminRole.SUPER_ADMIN.value,
            disabled=False,
            revision=0,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        db.expunge(row)
        return row


def _payload(*, expected_revision: int | None, storage_base: int) -> AdminQuotaCatalogWrite:
    plans = []
    for offset, plan in enumerate(("FREE", "PERSONAL", "FAMILY", "PREMIUM")):
        plans.append(
            AdminQuotaPlanWrite(
                plan_code=plan,
                expected_revision=expected_revision,
                storage_bytes=storage_base + offset,
                ai_provider_requests=100 + offset,
                ai_input_tokens=1000 + offset,
                ai_output_tokens=2000 + offset,
            )
        )
    return AdminQuotaCatalogWrite(
        plans=plans,
        confirmation="保存额度配置",
    )


def _prove_migration_roundtrip() -> None:
    _alembic("downgrade", "0027_product_analytics")
    _alembic("upgrade", "head")
    with engine.connect() as connection:
        for table in (
            "admin_accounts",
            "admin_sessions",
            "admin_audit_events",
            "entitlement_quota_policies",
            "provider_configurations",
        ):
            exists = connection.scalar(
                text("SELECT to_regclass(:name) IS NOT NULL"),
                {"name": table},
            )
            assert exists is True


def _prove_bootstrap_singleton_race() -> AdminAccount:
    email = f"bootstrap-{uuid4()}@example.com"
    os.environ["ADMIN_BOOTSTRAP_EMAIL"] = email
    os.environ["ADMIN_BOOTSTRAP_PASSWORD"] = "Bootstrap-Gate-Password-123!"
    os.environ["ADMIN_BOOTSTRAP_NAME"] = "Bootstrap Gate"

    barrier = Barrier(2)
    lock = Lock()
    results: list[bool] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            barrier.wait(timeout=15)
            created = bootstrap_super_admin()
            with lock:
                results.append(created)
        except BaseException as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)

    first = Thread(target=worker, name="admin-bootstrap-a")
    second = Thread(target=worker, name="admin-bootstrap-b")
    first.start()
    second.start()
    first.join(timeout=30)
    second.join(timeout=30)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert sorted(results) == [False, True]

    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(AdminAccount).where(
                    AdminAccount.role == AdminRole.SUPER_ADMIN.value,
                    AdminAccount.disabled.is_(False),
                )
            )
        )
        assert len(rows) == 1
        assert rows[0].email == email
        db.expunge(rows[0])
        return rows[0]


def _prove_quota_initialization_race(actor: AdminAccount) -> None:
    with SessionLocal() as db:
        db.execute(delete(ProviderConfiguration))
        db.execute(delete(EntitlementQuotaPolicy))
        db.commit()

    barrier = Barrier(2)
    lock = Lock()
    successes: list[int] = []
    stale: list[str] = []
    errors: list[BaseException] = []

    def worker(storage_base: int) -> None:
        db = SessionLocal()
        try:
            principal = db.get(AdminAccount, actor.id)
            assert principal is not None
            barrier.wait(timeout=15)
            rows = write_quota_catalog(
                db,
                actor=principal,
                payload=_payload(expected_revision=None, storage_base=storage_base),
            )
            with lock:
                successes.append(rows[0].revision)
        except AdminOperationError as exc:
            db.rollback()
            with lock:
                stale.append(exc.code)
        except BaseException as exc:  # noqa: BLE001
            db.rollback()
            with lock:
                errors.append(exc)
        finally:
            db.close()

    first = Thread(target=worker, args=(1100,), name="admin-quota-init-a")
    second = Thread(target=worker, args=(2200,), name="admin-quota-init-b")
    first.start()
    second.start()
    first.join(timeout=30)
    second.join(timeout=30)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert successes == [0]
    assert stale == ["ADMIN_STATE_STALE"]

    with SessionLocal() as db:
        rows = list(db.scalars(select(EntitlementQuotaPolicy)))
        assert len(rows) == 4
        assert {row.revision for row in rows} == {0}


def _prove_provider_first_write_race(actor: AdminAccount) -> None:
    with SessionLocal() as db:
        db.execute(delete(ProviderConfiguration))
        db.commit()

    barrier = Barrier(2)
    lock = Lock()
    successes: list[int] = []
    stale: list[str] = []
    errors: list[BaseException] = []
    settings = Settings(
        app_env="test",
        database_url=DATABASE_URL,
        provider_config_master_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    )

    def worker(model: str) -> None:
        db = SessionLocal()
        try:
            principal = db.get(AdminAccount, actor.id)
            assert principal is not None
            barrier.wait(timeout=15)
            row = update_provider_configuration(
                db,
                actor=principal,
                service=ProviderService.AI,
                payload=AdminProviderConfigWrite(
                    expected_revision=None,
                    enabled=True,
                    provider_type="openai",
                    base_url="https://api.openai.test/v1",
                    model=model,
                    timeout_seconds=20,
                    max_input_chars=2000,
                    max_output_tokens=200,
                    min_confidence=None,
                    api_key="provider-first-write-secret",
                ),
                settings=settings,
            )
            with lock:
                successes.append(row.revision)
        except AdminOperationError as exc:
            db.rollback()
            with lock:
                stale.append(exc.code)
        except BaseException as exc:  # noqa: BLE001
            db.rollback()
            with lock:
                errors.append(exc)
        finally:
            db.close()

    first = Thread(target=worker, args=("first-write-a",), name="provider-init-a")
    second = Thread(target=worker, args=("first-write-b",), name="provider-init-b")
    first.start()
    second.start()
    first.join(timeout=30)
    second.join(timeout=30)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert successes == [0]
    assert stale == ["ADMIN_STATE_STALE"]

    with SessionLocal() as db:
        rows = list(db.scalars(select(ProviderConfiguration)))
        assert len(rows) == 1
        assert rows[0].service == ProviderService.AI.value
        assert rows[0].revision == 0
        assert rows[0].credential_ciphertext
        assert "provider-first-write-secret" not in rows[0].credential_ciphertext
        db.delete(rows[0])
        db.commit()


def _prove_audit_is_database_append_only(actor: AdminAccount) -> None:
    with SessionLocal() as db:
        event = AdminAuditEvent(
            admin_actor_id=actor.id,
            admin_role_snapshot=actor.role,
            action="ADMIN_GATE_EVENT",
            target_type="SYSTEM",
            target_id="admin-gate",
            result="SUCCESS",
            metadata_json={},
        )
        db.add(event)
        db.commit()
        event_id = event.id

    with engine.begin() as connection:
        try:
            connection.execute(
                text(
                    "UPDATE admin_audit_events "
                    "SET result = 'MUTATED' WHERE id = :event_id"
                ),
                {"event_id": event_id},
            )
        except DBAPIError as exc:
            assert "ADMIN_AUDIT_APPEND_ONLY" in str(exc)
        else:
            raise AssertionError("Admin audit UPDATE must fail at PostgreSQL boundary")


def _prove_quota_revision_race(actor: AdminAccount) -> None:
    with SessionLocal() as db:
        db.execute(delete(EntitlementQuotaPolicy))
        db.commit()

    with SessionLocal() as db:
        write_quota_catalog(
            db,
            actor=db.get(AdminAccount, actor.id),
            payload=_payload(expected_revision=None, storage_base=1000),
        )

    barrier = Barrier(2)
    lock = Lock()
    successes: list[int] = []
    stale: list[str] = []
    errors: list[BaseException] = []

    def worker(storage_base: int) -> None:
        db = SessionLocal()
        try:
            principal = db.get(AdminAccount, actor.id)
            assert principal is not None
            barrier.wait(timeout=15)
            rows = write_quota_catalog(
                db,
                actor=principal,
                payload=_payload(expected_revision=0, storage_base=storage_base),
            )
            with lock:
                successes.append(rows[0].revision)
        except AdminOperationError as exc:
            db.rollback()
            with lock:
                stale.append(exc.code)
        except BaseException as exc:  # noqa: BLE001
            db.rollback()
            with lock:
                errors.append(exc)
        finally:
            db.close()

    first = Thread(target=worker, args=(2000,), name="admin-quota-a")
    second = Thread(target=worker, args=(3000,), name="admin-quota-b")
    first.start()
    second.start()
    first.join(timeout=30)
    second.join(timeout=30)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert successes == [1]
    assert stale == ["ADMIN_STATE_STALE"]

    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(EntitlementQuotaPolicy).order_by(
                    EntitlementQuotaPolicy.plan_code.asc()
                )
            )
        )
        assert len(rows) == 4
        assert {row.revision for row in rows} == {1}

        audits = list(
            db.scalars(
                select(AdminAuditEvent).where(
                    AdminAuditEvent.action == "ENTITLEMENT_QUOTA_CATALOG_UPDATE"
                )
            )
        )
        # Initial catalog write + exactly one winning concurrent update.
        assert len(audits) >= 2


def _prove_revision_snapshot_is_persisted(actor: AdminAccount) -> None:
    now = datetime.now(UTC)
    with SessionLocal() as db:
        row = AdminSession(
            admin_id=actor.id,
            token_digest="a" * 64,
            csrf_digest="b" * 64,
            admin_revision_snapshot=actor.revision,
            created_at=now,
            expires_at=now.replace(year=now.year + 1),
            last_seen_at=now,
        )
        db.add(row)
        db.commit()
        session_id = row.id

        locked_actor = db.get(AdminAccount, actor.id)
        assert locked_actor is not None
        locked_actor.revision += 1
        db.commit()

        persisted = db.get(AdminSession, session_id)
        current = db.get(AdminAccount, actor.id)
        assert persisted is not None and current is not None
        assert persisted.admin_revision_snapshot != current.revision


def _cleanup() -> None:
    with SessionLocal() as db:
        db.execute(delete(EntitlementQuotaPolicy))
        db.execute(delete(AdminSession))
        # Audit rows are intentionally append-only at DB level and cannot be cleaned
        # by application SQL. The CI database itself is disposable.
        db.execute(delete(AdminAccount))
        try:
            db.commit()
        except DBAPIError:
            db.rollback()
            # AdminAccount FK uses SET NULL for audit actors; delete can be retried
            # without mutating the audit table itself.
            db.execute(delete(AdminSession))
            db.execute(delete(AdminAccount))
            db.commit()


def main() -> None:
    assert DATABASE_URL.startswith("postgresql")
    _prove_migration_roundtrip()
    actor = _prove_bootstrap_singleton_race()
    _prove_audit_is_database_append_only(actor)
    _prove_quota_initialization_race(actor)
    _prove_quota_revision_race(actor)
    _prove_provider_first_write_race(actor)
    _prove_revision_snapshot_is_persisted(actor)
    print("PostgreSQL ADMIN-001 authority/concurrency PASS")


if __name__ == "__main__":
    main()
