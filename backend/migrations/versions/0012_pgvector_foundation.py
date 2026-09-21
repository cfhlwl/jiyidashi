"""enable Stage 3 pgvector foundation

Revision ID: 0012_pgvector_foundation
Revises: 0011_place_naming
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_pgvector_foundation"
down_revision: str | None = "0011_place_naming"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _dialect_name() -> str:
    return op.get_bind().dialect.name


def upgrade() -> None:
    dialect = _dialect_name()
    if dialect == "sqlite":
        # [人工注释][S3-008] SQLite 继续承载非 vector 的本地/单元测试路径；
        # Foundation 不伪造 SQLite vector 类型，也不要求开发者安装另一套扩展。
        return
    if dialect != "postgresql":
        raise RuntimeError(f"PGVECTOR_DATABASE_UNSUPPORTED: {dialect}")

    try:
        # [人工注释][S3-008] extension 属于数据库级共享能力，不属于某个用户/Memory。
        # migration 只确保 capability 存在，不创建 vector 列、索引或任何用户 embedding 数据。
        op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    except sa.exc.SQLAlchemyError as exc:
        raise RuntimeError(
            "PGVECTOR_EXTENSION_ENABLE_FAILED: install/allow the PostgreSQL vector "
            "extension before upgrading"
        ) from exc


def downgrade() -> None:
    dialect = _dialect_name()
    if dialect == "sqlite":
        return
    if dialect != "postgresql":
        raise RuntimeError(f"PGVECTOR_DATABASE_UNSUPPORTED: {dialect}")

    # [人工注释][S3-008] 故意不执行 DROP EXTENSION。
    # vector 是数据库级共享 capability，可能已被同库其他 schema/服务使用；
    # Alembic 回退本应用 revision 不拥有删除共享 extension 的授权。
    return
