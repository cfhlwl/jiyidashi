from __future__ import annotations

import hashlib
import hmac
import math
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.abuse_models import ConcurrencyGuard, WorkPermit
from app.core.config import Settings, get_settings


class ConcurrencyRejected(RuntimeError):
    def __init__(self, code: str, *, retry_after: int):
        super().__init__(code)
        self.code = code
        self.retry_after = max(1, int(retry_after))


@dataclass(frozen=True)
class Permit:
    permit_id: UUID
    token: str
    service_class: str
    user_id: UUID | None
    expires_at: datetime


def _token_digest(token: str, settings: Settings) -> str:
    return hmac.new(
        settings.jwt_secret.encode("utf-8"),
        f"sec016:permit:{token}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _guard_row(db: Session, scope_key: str, now: datetime) -> ConcurrencyGuard:
    row = db.scalar(
        select(ConcurrencyGuard)
        .where(ConcurrencyGuard.scope_key == scope_key)
        .with_for_update()
    )
    if row is not None:
        row.updated_at = now
        return row

    db.add(ConcurrencyGuard(scope_key=scope_key, updated_at=now))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        row = db.scalar(
            select(ConcurrencyGuard)
            .where(ConcurrencyGuard.scope_key == scope_key)
            .with_for_update()
        )
        if row is None:
            raise
        row.updated_at = now
        return row
    return db.get(ConcurrencyGuard, scope_key)


def _active_count(
    db: Session,
    *,
    service_class: str,
    now: datetime,
    user_id: UUID | None = None,
) -> int:
    query = select(func.count()).select_from(WorkPermit).where(
        WorkPermit.service_class == service_class,
        WorkPermit.expires_at > now,
    )
    if user_id is not None:
        query = query.where(WorkPermit.user_id == user_id)
    return int(db.scalar(query) or 0)


def claim_permit(
    bind: Engine,
    *,
    service_class: str,
    global_limit: int,
    user_limit: int | None,
    user_id: UUID | None,
    lease_seconds: int,
    saturated_code: str,
    settings: Settings | None = None,
) -> Permit:
    cfg = settings or get_settings()
    now = datetime.now(UTC)
    global_scope = f"global:{service_class}"
    user_scope = None if user_id is None else f"user:{service_class}:{user_id}"

    with Session(bind=bind, autoflush=False, expire_on_commit=False) as db:
        # Stable lock order prevents user/global inversion across workers.
        for scope in sorted(x for x in (global_scope, user_scope) if x is not None):
            _guard_row(db, scope, now)

        # Correctness never depends on cleanup; expired rows are ignored. Delete only
        # a bounded age cohort during admission to keep the table compact.
        db.execute(
            delete(WorkPermit).where(
                WorkPermit.expires_at <= now - timedelta(seconds=max(lease_seconds, 1))
            )
        )

        global_active = _active_count(
            db,
            service_class=service_class,
            now=now,
        )
        if global_active >= global_limit:
            db.commit()
            raise ConcurrencyRejected(saturated_code, retry_after=lease_seconds)

        if user_id is not None and user_limit is not None:
            user_active = _active_count(
                db,
                service_class=service_class,
                now=now,
                user_id=user_id,
            )
            if user_active >= user_limit:
                db.commit()
                raise ConcurrencyRejected(saturated_code, retry_after=lease_seconds)

        token = secrets.token_urlsafe(32)
        row = WorkPermit(
            token_digest=_token_digest(token, cfg),
            service_class=service_class,
            user_id=user_id,
            claimed_at=now,
            expires_at=now + timedelta(seconds=lease_seconds),
        )
        db.add(row)
        db.commit()
        return Permit(
            permit_id=row.id,
            token=token,
            service_class=service_class,
            user_id=user_id,
            expires_at=row.expires_at,
        )


def release_permit(
    bind: Engine,
    *,
    permit: Permit,
    settings: Settings | None = None,
) -> bool:
    cfg = settings or get_settings()
    with Session(bind=bind, autoflush=False, expire_on_commit=False) as db:
        result = db.execute(
            delete(WorkPermit).where(
                WorkPermit.id == permit.permit_id,
                WorkPermit.token_digest == _token_digest(permit.token, cfg),
                WorkPermit.service_class == permit.service_class,
            )
        )
        db.commit()
        return bool(result.rowcount)


def provider_limits(settings: Settings, service_class: str) -> tuple[int, int]:
    if service_class == "AI":
        return settings.provider_ai_global_concurrency, settings.provider_ai_user_concurrency
    if service_class == "ASR":
        return settings.provider_asr_global_concurrency, settings.provider_asr_user_concurrency
    if service_class == "EMBEDDING":
        return (
            settings.provider_embedding_global_concurrency,
            settings.provider_embedding_user_concurrency,
        )
    raise ValueError("unknown provider service")


def claim_provider_permit(
    bind: Engine,
    *,
    service_class: str,
    user_id: UUID,
    settings: Settings | None = None,
) -> Permit:
    cfg = settings or get_settings()
    global_limit, user_limit = provider_limits(cfg, service_class)
    return claim_permit(
        bind,
        service_class=service_class,
        global_limit=global_limit,
        user_limit=user_limit,
        user_id=user_id,
        lease_seconds=cfg.provider_permit_lease_seconds,
        saturated_code="PROVIDER_CONCURRENCY_SATURATED",
        settings=cfg,
    )


def claim_argon2_permit(
    bind: Engine,
    *,
    settings: Settings | None = None,
) -> Permit:
    cfg = settings or get_settings()
    return claim_permit(
        bind,
        service_class="ARGON2",
        global_limit=cfg.argon2_global_concurrency,
        user_limit=None,
        user_id=None,
        lease_seconds=cfg.argon2_permit_lease_seconds,
        saturated_code="AUTH_PASSWORD_WORK_SATURATED",
        settings=cfg,
    )
