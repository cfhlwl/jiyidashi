from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TypeVar
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.abuse_models import ConcurrencyGuard, WorkPermit
from app.core.config import Settings, get_settings
from app.security_models import SecuritySignalCode
from app.services.security_alerting import SecurityScope, record_security_signal


_BlockingResult = TypeVar("_BlockingResult")


async def run_blocking_worker(
    func: Callable[..., _BlockingResult],
    /,
    *args,
    **kwargs,
) -> _BlockingResult:
    """Keep an already-started thread alive under its caller's authority.

    Cancelling an await of ``asyncio.to_thread`` does not stop the underlying
    worker thread.  Shield the explicit task and, once caller cancellation is
    observed, drain the worker to physical completion before re-propagating the
    cancellation.  This lets an enclosing permit/lease context keep renewing
    until the protected storage/decode work has actually stopped.
    """
    worker = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))
    cancelled: asyncio.CancelledError | None = None

    while True:
        try:
            result = await asyncio.shield(worker)
        except asyncio.CancelledError as exc:
            if cancelled is None:
                cancelled = exc
            if worker.done():
                # Retrieve the terminal state so a worker exception cannot be
                # reported as an unobserved Task exception. Caller cancellation
                # remains the externally visible outcome.
                try:
                    worker.result()
                except BaseException:
                    pass
                raise cancelled
            # A Task can receive cancellation more than once. Keep draining the
            # shielded worker until the physical thread is no longer running.
            continue
        except BaseException:
            if cancelled is not None:
                raise cancelled
            raise

        if cancelled is not None:
            raise cancelled
        return result


class PermitLeaseLost(RuntimeError):
    def __init__(self, code: str = "CONCURRENCY_PERMIT_LEASE_LOST"):
        super().__init__(code)
        self.code = code


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
        settings.jwt_secret.encode(),
        f"sec016:permit:{token}".encode(),
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

    try:
        with db.begin_nested():
            db.add(ConcurrencyGuard(scope_key=scope_key, updated_at=now))
            db.flush()
    except IntegrityError:
        # SAVEPOINT rollback preserves any guard rows already locked in the outer
        # transaction while a concurrent first creator wins this scope.
        pass
    row = db.scalar(
        select(ConcurrencyGuard)
        .where(ConcurrencyGuard.scope_key == scope_key)
        .with_for_update()
    )
    if row is None:
        raise RuntimeError("CONCURRENCY_GUARD_CREATE_FAILED")
    row.updated_at = now
    return row


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
        stale_ids = list(
            db.scalars(
                select(WorkPermit.id)
                .where(
                    WorkPermit.expires_at
                    <= now - timedelta(seconds=max(lease_seconds, 1))
                )
                .order_by(WorkPermit.expires_at.asc())
                .limit(100)
            )
        )
        if stale_ids:
            db.execute(delete(WorkPermit).where(WorkPermit.id.in_(stale_ids)))

        global_active = _active_count(
            db,
            service_class=service_class,
            now=now,
        )
        if global_active >= global_limit:
            db.commit()
            _record_saturation(
                bind,
                service_class=service_class,
                user_id=user_id,
            )
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
                _record_saturation(
                    bind,
                    service_class=service_class,
                    user_id=user_id,
                )
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


def renew_permit(
    bind: Engine,
    *,
    permit: Permit,
    lease_seconds: int,
    settings: Settings | None = None,
) -> Permit | None:
    cfg = settings or get_settings()
    global_scope = f"global:{permit.service_class}"
    user_scope = (
        None
        if permit.user_id is None
        else f"user:{permit.service_class}:{permit.user_id}"
    )

    with Session(bind=bind, autoflush=False, expire_on_commit=False) as db:
        # Renewal and admission serialize on the exact same guard rows, in the
        # exact same stable order. The lease clock is sampled only after these
        # locks are acquired so waiting behind another authority cannot revive
        # a permit that expired while blocked.
        lock_started_at = datetime.now(UTC)
        for scope in sorted(
            x for x in (global_scope, user_scope) if x is not None
        ):
            _guard_row(db, scope, lock_started_at)

        now = datetime.now(UTC)
        new_expires_at = now + timedelta(seconds=lease_seconds)
        result = db.execute(
            update(WorkPermit)
            .where(
                WorkPermit.id == permit.permit_id,
                WorkPermit.token_digest == _token_digest(permit.token, cfg),
                WorkPermit.service_class == permit.service_class,
                WorkPermit.expires_at > now,
            )
            .values(expires_at=new_expires_at)
        )
        db.commit()
        if not result.rowcount:
            return None

    return Permit(
        permit_id=permit.permit_id,
        token=permit.token,
        service_class=permit.service_class,
        user_id=permit.user_id,
        expires_at=new_expires_at,
    )


class PermitHeartbeat:
    def __init__(
        self,
        bind: Engine,
        *,
        permit: Permit,
        lease_seconds: int,
        settings: Settings | None = None,
    ):
        self._bind = bind
        self._permit = permit
        self._lease_seconds = lease_seconds
        self._settings = settings or get_settings()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._failure: BaseException | None = None

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("PERMIT_HEARTBEAT_ALREADY_STARTED")
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        interval = max(1.0, self._lease_seconds / 4)
        while True:
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
                return
            except TimeoutError:
                pass
            try:
                renewed = await asyncio.to_thread(
                    renew_permit,
                    self._bind,
                    permit=self._permit,
                    lease_seconds=self._lease_seconds,
                    settings=self._settings,
                )
            except BaseException as exc:  # fail closed; surfaced by ensure_healthy/stop
                self._failure = exc
                return
            if renewed is None:
                self._failure = PermitLeaseLost()
                return
            self._permit = renewed

    def ensure_healthy(self) -> None:
        if self._failure is None:
            return
        if isinstance(self._failure, PermitLeaseLost):
            raise self._failure
        raise PermitLeaseLost() from self._failure

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
        self.ensure_healthy()


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


@asynccontextmanager
async def maintain_permit_lease(
    bind: Engine,
    *,
    permit: Permit,
    lease_seconds: int,
    settings: Settings | None = None,
):
    cfg = settings or get_settings()
    heartbeat = PermitHeartbeat(
        bind,
        permit=permit,
        lease_seconds=lease_seconds,
        settings=cfg,
    )
    heartbeat.start()
    try:
        yield heartbeat
    finally:
        failure: BaseException | None = None
        try:
            await heartbeat.stop()
        except BaseException as exc:  # surfaced after release attempt
            failure = exc
        try:
            released = await asyncio.to_thread(
                release_permit,
                bind,
                permit=permit,
                settings=cfg,
            )
        except BaseException as exc:
            if failure is None:
                failure = exc
            released = False
        if failure is not None or not released:
            raise PermitLeaseLost() from failure


def _record_saturation(
    bind: Engine,
    *,
    service_class: str,
    user_id: UUID | None,
) -> None:
    if service_class == "ARGON2":
        signal_code = SecuritySignalCode.ARGON2_CONCURRENCY_SATURATED
        scope = SecurityScope.ARGON2
    else:
        signal_code = SecuritySignalCode.PROVIDER_CONCURRENCY_SATURATED
        scope = {
            "AI": SecurityScope.PROVIDER_AI,
            "ASR": SecurityScope.PROVIDER_ASR,
            "EMBEDDING": SecurityScope.PROVIDER_EMBEDDING,
        }.get(service_class)
        if scope is None:
            return
    record_security_signal(
        bind,
        signal_code=signal_code,
        correlation_kind="sec016_concurrency",
        correlation_value=f"{service_class}:{user_id or 'global'}",
        scope=scope,
    )


def provider_limits(settings: Settings, service_class: str) -> tuple[int, int]:
    if service_class == "AI":
        return (
            settings.provider_ai_global_concurrency,
            settings.provider_ai_user_concurrency,
        )
    if service_class == "ASR":
        return (
            settings.provider_asr_global_concurrency,
            settings.provider_asr_user_concurrency,
        )
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


def claim_image_preprocess_permit(
    bind: Engine,
    *,
    user_id: UUID,
    settings: Settings | None = None,
) -> Permit:
    cfg = settings or get_settings()
    return claim_permit(
        bind,
        service_class="AI_IMAGE_PREPROCESS",
        global_limit=cfg.ai_image_preprocess_global_concurrency,
        user_limit=cfg.ai_image_preprocess_user_concurrency,
        user_id=user_id,
        lease_seconds=cfg.ai_image_preprocess_permit_lease_seconds,
        saturated_code="AI_IMAGE_PREPROCESS_SATURATED",
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
