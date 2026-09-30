from __future__ import annotations

import os
from uuid import uuid4

from sqlalchemy import func, select, text

from app.admin_models import AdminAccount, AdminRole
from app.core.db import SessionLocal
from app.services.admin_security import (
    append_admin_audit,
    hash_admin_password,
    normalize_admin_email,
)

_ADMIN_BOOTSTRAP_LOCK_KEY = 0x4A4959491002


def bootstrap_super_admin() -> bool:
    email_raw = os.environ.get("ADMIN_BOOTSTRAP_EMAIL", "").strip()
    password = os.environ.get("ADMIN_BOOTSTRAP_PASSWORD", "")
    display_name = os.environ.get("ADMIN_BOOTSTRAP_NAME", "系统管理员").strip()

    if not email_raw or not password:
        raise RuntimeError(
            "ADMIN_BOOTSTRAP_EMAIL and ADMIN_BOOTSTRAP_PASSWORD are required"
        )
    if len(password) < 12 or len(password) > 128:
        raise RuntimeError("ADMIN_BOOTSTRAP_PASSWORD must be 12..128 characters")
    if not display_name or len(display_name) > 80:
        raise RuntimeError("ADMIN_BOOTSTRAP_NAME must be 1..80 characters")

    email = normalize_admin_email(email_raw)
    with SessionLocal() as db:
        # The "first SUPER_ADMIN" invariant is a logical singleton. Row locks
        # cannot protect an empty admin_accounts table, so serialize bootstrap
        # transactions before checking whether the singleton already exists.
        if db.get_bind().dialect.name == "postgresql":
            db.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": _ADMIN_BOOTSTRAP_LOCK_KEY},
            )

        active_super_count = int(
            db.scalar(
                select(func.count(AdminAccount.id)).where(
                    AdminAccount.role == AdminRole.SUPER_ADMIN.value,
                    AdminAccount.disabled.is_(False),
                )
            )
            or 0
        )
        if active_super_count > 0:
            return False

        existing = db.scalar(select(AdminAccount).where(AdminAccount.email == email))
        if existing is not None:
            raise RuntimeError(
                "bootstrap email already exists; use reviewed Admin account recovery"
            )

        row = AdminAccount(
            id=uuid4(),
            email=email,
            display_name=display_name,
            password_hash=hash_admin_password(password),
            role=AdminRole.SUPER_ADMIN.value,
            disabled=False,
            revision=0,
        )
        db.add(row)
        db.flush()
        append_admin_audit(
            db,
            actor=row,
            action="ADMIN_BOOTSTRAP",
            target_type="ADMIN_ACCOUNT",
            target_id=row.id,
            result="SUCCESS",
            metadata={"role": row.role},
        )
        db.commit()
        return True


def main() -> None:
    created = bootstrap_super_admin()
    print("admin bootstrap: created" if created else "admin bootstrap: already initialized")


if __name__ == "__main__":
    main()
