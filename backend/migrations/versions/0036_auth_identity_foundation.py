"""add canonical provider values and V1 identity cardinality guards

Revision ID: 0036_auth_identity_foundation
Revises: 0035_sec017_human_alert_delivery
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036_auth_identity_foundation"
down_revision: str | None = "0035_sec017_human_alert_delivery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # AuthProvider is native_enum=False in 0002_stage1_auth. PHONE/WECHAT are
    # therefore Python/domain values that fit the existing varchar column; no
    # artificial PostgreSQL enum operation is generated here.
    op.create_index(
        "uq_auth_identities_user_email_password",
        "auth_identities",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("provider = 'EMAIL_PASSWORD'"),
        sqlite_where=sa.text("provider = 'EMAIL_PASSWORD'"),
    )
    op.create_index(
        "uq_auth_identities_user_phone",
        "auth_identities",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("provider = 'PHONE'"),
        sqlite_where=sa.text("provider = 'PHONE'"),
    )


def downgrade() -> None:
    op.drop_index("uq_auth_identities_user_phone", table_name="auth_identities")
    op.drop_index(
        "uq_auth_identities_user_email_password",
        table_name="auth_identities",
    )
