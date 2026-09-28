import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    connect_args=connect_args,
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
        account_deletion_models,
        auth_models,
        data_deletion_models,
        embedding_models,
        family_models,
        idempotency_models,
        media_models,
        memory_feedback_models,
        models,
        person_memory_models,
        person_models,
        person_relationship_models,
    )

    Base.metadata.create_all(bind=engine)
