import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

settings = get_settings()

def _standard_connect_args(database_url: str) -> dict[str, object]:
    connect_args: dict[str, object] = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return connect_args


def create_application_engine(
    database_url: str,
    *,
    pool_size: int,
    max_overflow: int,
    pool_timeout_seconds: int,
    pool_recycle_seconds: int,
    enforce_pool_bounds: bool,
) -> Engine:
    kwargs: dict[str, object] = {
        "echo": False,
        "pool_pre_ping": True,
        "connect_args": _standard_connect_args(database_url),
    }
    if enforce_pool_bounds and database_url.startswith("postgresql"):
        kwargs.update(
            {
                "pool_size": pool_size,
                "max_overflow": max_overflow,
                "pool_timeout": pool_timeout_seconds,
                "pool_recycle": pool_recycle_seconds,
            }
        )
    return create_engine(database_url, **kwargs)


def create_readiness_engine(
    database_url: str,
    *,
    connect_timeout_seconds: int,
    statement_timeout_ms: int,
) -> Engine:
    """Create a no-pool engine whose PostgreSQL I/O is bounded by the driver/server."""

    connect_args = _standard_connect_args(database_url)
    if database_url.startswith("postgresql"):
        connect_args.update(
            {
                "connect_timeout": connect_timeout_seconds,
                "options": f"-c statement_timeout={statement_timeout_ms}",
            }
        )

    return create_engine(
        database_url,
        echo=False,
        poolclass=NullPool,
        connect_args=connect_args,
    )


engine = create_application_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout_seconds=settings.db_pool_timeout_seconds,
    pool_recycle_seconds=settings.db_pool_recycle_seconds,
    enforce_pool_bounds=settings.is_production,
)

readiness_engine = create_readiness_engine(
    settings.database_url,
    connect_timeout_seconds=settings.database_readiness_connect_timeout_seconds,
    statement_timeout_ms=settings.database_readiness_statement_timeout_ms,
)


@dataclass(frozen=True)
class UserDataAdmission:
    user_id: UUID
    deletion_generation: int


class UserDataRequestStale(RuntimeError):
    """A request admitted before a destructive deletion may no longer persist data."""


USER_DATA_ADMISSION_INFO_KEY = "user_data_admission"


def _user_data_disclosure_lock_key(user_id: UUID) -> int:
    digest = hashlib.blake2b(
        user_id.bytes,
        digest_size=8,
        person=b"jiyi-disclose-v1",
    ).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


OBJECT_OWNER_CAPACITY_LOCK_SEED = 214001


def lock_object_owner_capacity(db: Session, *, user_id: UUID) -> None:
    """Serialize object inserts for one owner in production PostgreSQL."""

    if db.get_bind().dialect.name != "postgresql":
        return
    db.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            "hashtextextended(:user_id, :seed)"
            ")"
        ),
        {
            "user_id": str(user_id),
            "seed": OBJECT_OWNER_CAPACITY_LOCK_SEED,
        },
    )


def lock_user_data_destructive_handoff(db: Session, *, user_id: UUID) -> None:
    """Serialize the first destructive gate commit against provider disclosure.

    PostgreSQL transaction-scoped advisory locking is deliberately acquired before the
    canonical User FOR UPDATE. Re-acquiring the same key in one transaction is safe.
    Other database engines keep the existing User-row authority only.
    """

    if db.get_bind().dialect.name != "postgresql":
        return
    db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": _user_data_disclosure_lock_key(user_id)},
    )


@contextmanager
def hold_user_data_disclosure_handoff(bind: Engine, *, user_id: UUID):
    """Hold a PostgreSQL session advisory *shared* lease across provider disclosure.

    The connection runs in AUTOCOMMIT and has no active SQLAlchemy transaction while
    yielded. Therefore external provider I/O holds neither a PostgreSQL transaction nor
    a User row lock. The matching destructive xact lock can commit only before this lease
    is acquired or after it is released.
    """

    if bind.dialect.name != "postgresql":
        yield
        return

    connection = bind.connect().execution_options(isolation_level="AUTOCOMMIT")
    lock_key = _user_data_disclosure_lock_key(user_id)
    try:
        connection.execute(
            text("SELECT pg_advisory_lock_shared(:lock_key)"),
            {"lock_key": lock_key},
        )
        # End SQLAlchemy's logical autobegin wrapper. The session-level advisory lock
        # survives commit while the DBAPI connection remains open.
        connection.commit()
        if connection.in_transaction():
            connection.invalidate()
            raise RuntimeError("USER_DATA_DISCLOSURE_LOCK_TRANSACTION_ACTIVE")
        try:
            yield
        finally:
            unlocked = connection.scalar(
                text("SELECT pg_advisory_unlock_shared(:lock_key)"),
                {"lock_key": lock_key},
            )
            connection.commit()
            if unlocked is not True:
                connection.invalidate()
                raise RuntimeError("USER_DATA_DISCLOSURE_LOCK_RELEASE_FAILED")
    except Exception:
        if not connection.closed:
            connection.invalidate()
        raise
    finally:
        connection.close()


class GuardedSession(Session):
    def _enforce_user_data_admission(self) -> None:
        admission = self.info.get(USER_DATA_ADMISSION_INFO_KEY)
        if not isinstance(admission, UserDataAdmission):
            return

        # [人工注释][S1-021-FIX-001] 每一次 commit 都重新拿 User KEY SHARE，
        # 不能依赖请求入口时那把锁跨越 commit/rollback。这样删除服务的 User FOR UPDATE
        # 要么先完成并改变 generation，要么等待本次 commit 完成后再删除本次写入。
        from app.account_deletion_models import AccountDeletionOperation
        from app.data_deletion_models import DataDeletionOperation, DataDeletionStatus
        from app.models import User

        with self.no_autoflush:
            user_exists = self.scalar(
                select(User.id)
                .where(User.id == admission.user_id)
                .with_for_update(read=True, key_share=True)
            )
            current_generation = int(
                self.scalar(
                    select(func.count(DataDeletionOperation.id)).where(
                        DataDeletionOperation.user_id == admission.user_id
                    )
                )
                or 0
            )
            active_deletion = self.scalar(
                select(DataDeletionOperation.id)
                .where(
                    DataDeletionOperation.user_id == admission.user_id,
                    DataDeletionOperation.status != DataDeletionStatus.COMPLETED,
                )
                .limit(1)
            )
            active_account_deletion = self.scalar(
                select(AccountDeletionOperation.id)
                .where(AccountDeletionOperation.user_id == admission.user_id)
                .limit(1)
            )

        if (
            user_exists is None
            or current_generation != admission.deletion_generation
            or active_deletion is not None
            or active_account_deletion is not None
        ):
            # Pending ORM writes may already exist in this transaction; rollback them before
            # surfacing the stale-request error so no caller can accidentally reuse them.
            super().rollback()
            raise UserDataRequestStale("DATA_DELETION_REQUEST_STALE")

    def commit(self) -> None:
        self._enforce_user_data_admission()
        super().commit()


SessionLocal = sessionmaker(
    bind=engine,
    class_=GuardedSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def create_schema() -> None:
    # create_all 必须显式加载认证、媒体、删除状态机和幂等模型，
    # 不能依赖 router / schema 的偶然 import 顺序决定数据库是否缺表。
    from app import (  # noqa: F401
        abuse_models,
        account_deletion_models,
        admin_models,
        analytics_models,
        auth_models,
        data_deletion_models,
        embedding_models,
        entitlement_models,
        export_models,
        family_models,
        idempotency_models,
        life_event_models,
        life_stage_models,
        maintenance_job_models,
        media_models,
        memory_feedback_models,
        models,
        person_memory_models,
        person_models,
        person_relationship_models,
        security_models,
    )

    Base.metadata.create_all(bind=engine)
