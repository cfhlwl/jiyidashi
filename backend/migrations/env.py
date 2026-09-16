from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# [人工注释][S1-006] Alembic 显式加载媒体模型，保证 media_assets 与
# media_evidence_links 进入正式 schema drift gate。
from app import auth_models, media_models, models  # noqa: F401
from app.core.config import get_settings
from app.core.db import Base

config = context.config
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# [人工注释][S1-FIX-001] Alembic 必须显式加载认证模型，保证 target_metadata 与迁移 head 一致。
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
