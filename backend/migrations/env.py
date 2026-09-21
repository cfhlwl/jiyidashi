from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Alembic 显式加载认证、媒体、删除状态机与客户端幂等模型，
# 保证这些表全部进入正式 schema drift gate。
from app import (  # noqa: F401
    account_deletion_models,
    auth_models,
    data_deletion_models,
    embedding_models,
    idempotency_models,
    media_models,
    models,
)
from app.core.config import get_settings
from app.core.db import Base

config = context.config
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# [人工注释][S1-FIX-001] Alembic 必须显式加载认证模型，
# 保证 target_metadata 与迁移 head 一致。
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
