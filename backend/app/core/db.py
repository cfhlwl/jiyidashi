from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import create_engine, func, select
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


class GuardedSession(Session):
    def _enforce_user_data_admission(self) -> None:
        admission = self.info.get(USER_DATA_ADMISSION_INFO_KEY)
        if not isinstance(admission, UserDataAdmission):
            return

        # [人工注释][S1-021-FIX-001] 每一次 commit 都重新拿 User KEY SHARE，
        # 不能依赖请求入口时那把锁跨越 commit/rollback。这样删除服务的 User FOR UPDATE
        # 要么先完成并改变 generation，要么等待本次 commit 完成后再删除本次写入。
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

        if (
            user_exists is None
            or current_generation != admission.deletion_generation
            or active_deletion is not None
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
        auth_models,
        data_deletion_models,
        idempotency_models,
        media_models,
        models,
    )

    Base.metadata.create_all(bind=engine)
