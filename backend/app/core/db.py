from collections.abc import Iterator

from sqlalchemy import create_engine
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

SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def create_schema() -> None:
    # create_all 必须显式加载认证、媒体和幂等模型，
    # 不能依赖 router / schema 的偶然 import 顺序决定数据库是否缺表。
    from app import auth_models, idempotency_models, media_models, models  # noqa: F401

    Base.metadata.create_all(bind=engine)
