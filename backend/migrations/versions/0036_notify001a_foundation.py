"""add server notification foundation

Revision ID: 0036_notify001a_foundation
Revises: 0035_sec017_human_alert_delivery
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036_notify001a_foundation"
down_revision: str | None = "0035_sec017_human_alert_delivery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_JOB_TYPES = (
    "DATA_DELETE",
    "ACCOUNT_DELETE",
    "MEDIA_PENDING_CLEANUP",
    "SECURITY_ALERT_DELIVERY",
    "ANALYTICS_RETENTION",
    "LOCATION_RETENTION",
    "EXPORT",
)
_NEW_JOB_TYPES = (
    *_OLD_JOB_TYPES,
    "NOTIFICATION_FANOUT",
    "NOTIFICATION_DELIVERY",
)


def _job_type_check(values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"job_type IN ({quoted})"


def upgrade() -> None:
    with op.batch_alter_table("devices", recreate="auto") as batch:
        batch.add_column(
            sa.Column("push_provider", sa.String(length=32), nullable=True)
        )
        batch.add_column(
            sa.Column("push_token_digest", sa.String(length=64), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "push_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column(
                "push_token_updated_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "push_invalidated_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column("app_version", sa.String(length=64), nullable=True)
        )
        batch.add_column(
            sa.Column("os_version", sa.String(length=64), nullable=True)
        )
        batch.alter_column("push_enabled", server_default=None)

    # Legacy Device.push_token had no reviewed provider/platform provenance. It must
    # never become active merely because the new server-side delivery stack exists.
    op.execute(
        sa.text(
            """
            UPDATE devices
            SET push_token = NULL,
                push_provider = NULL,
                push_token_digest = NULL,
                push_enabled = false,
                push_token_updated_at = NULL,
                push_invalidated_at = CURRENT_TIMESTAMP
            WHERE push_token IS NOT NULL
            """
        )
    )
    op.create_index(
        "uq_devices_active_push_binding",
        "devices",
        ["push_provider", "push_token_digest"],
        unique=True,
        postgresql_where=sa.text(
            "push_enabled = true AND push_token_digest IS NOT NULL"
        ),
        sqlite_where=sa.text(
            "push_enabled = 1 AND push_token_digest IS NOT NULL"
        ),
    )

    op.create_table(
        "notification_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("route_intent", sa.String(length=32), nullable=False),
        sa.Column("route_resource_id", sa.Uuid(), nullable=True),
        sa.Column("payload_version", sa.Integer(), nullable=False),
        sa.Column("safe_payload_json", sa.JSON(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "category IN ('REMINDER','ADMIN','SYSTEM','APP_UPDATE',"
            "'EXPORT_COMPLETE','FAMILY')",
            name="ck_notification_messages_category",
        ),
        sa.CheckConstraint(
            "source_type IN ('REMINDER','ADMIN','SYSTEM','APP_UPDATE',"
            "'EXPORT_COMPLETE','FAMILY')",
            name="ck_notification_messages_source_type",
        ),
        sa.CheckConstraint(
            "route_intent IN ('HOME','REMINDER','MEMORY','APP_UPDATE','FAMILY','EXPORT')",
            name="ck_notification_messages_route",
        ),
        sa.CheckConstraint(
            "payload_version >= 1 AND payload_version <= 100",
            name="ck_notification_messages_payload_version",
        ),
    )
    op.create_index(
        "ix_notification_messages_source",
        "notification_messages",
        ["source_type", "source_id"],
        unique=False,
    )

    op.create_table(
        "notification_campaigns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("target_platform", sa.String(length=16), nullable=False),
        sa.Column("audience_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("send_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("audience_cutoff_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fanout_cursor_device_id", sa.Uuid(), nullable=True),
        sa.Column("fanout_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_admin_id", sa.Uuid(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["notification_messages.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_admin_id"],
            ["admin_accounts.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "target_platform IN ('ALL','IOS','ANDROID')",
            name="ck_notification_campaigns_platform",
        ),
        sa.CheckConstraint(
            "audience_type IN ('ALL_ELIGIBLE_DEVICES','USER_IDS','DEVICE_IDS')",
            name="ck_notification_campaigns_audience",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT','SCHEDULED','FANOUT','DELIVERING',"
            "'COMPLETED','CANCELLED')",
            name="ck_notification_campaigns_status",
        ),
        sa.CheckConstraint(
            "revision >= 0",
            name="ck_notification_campaigns_revision",
        ),
    )
    op.create_index(
        "ix_notification_campaigns_message_id",
        "notification_campaigns",
        ["message_id"],
        unique=False,
    )
    op.create_index(
        "ix_notification_campaigns_created_by_admin_id",
        "notification_campaigns",
        ["created_by_admin_id"],
        unique=False,
    )
    op.create_index(
        "ix_notification_campaigns_due",
        "notification_campaigns",
        ["status", "send_at", "created_at"],
        unique=False,
    )

    op.create_table(
        "notification_campaign_targets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["notification_campaigns.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "(user_id IS NOT NULL AND device_id IS NULL) OR "
            "(user_id IS NULL AND device_id IS NOT NULL)",
            name="ck_notification_campaign_targets_exactly_one",
        ),
        sa.UniqueConstraint(
            "campaign_id",
            "user_id",
            name="uq_notification_campaign_targets_user",
        ),
        sa.UniqueConstraint(
            "campaign_id",
            "device_id",
            name="uq_notification_campaign_targets_device",
        ),
    )
    op.create_index(
        "ix_notification_campaign_targets_campaign",
        "notification_campaign_targets",
        ["campaign_id", "id"],
        unique=False,
    )
    op.create_index(
        "ix_notification_campaign_targets_user_id",
        "notification_campaign_targets",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_notification_campaign_targets_device_id",
        "notification_campaign_targets",
        ["device_id"],
        unique=False,
    )

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("platform_snapshot", sa.String(length=16), nullable=False),
        sa.Column("provider_snapshot", sa.String(length=32), nullable=False),
        sa.Column("token_digest_snapshot", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("attempt_token", sa.Uuid(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["notification_campaigns.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["notification_messages.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "campaign_id",
            "device_id",
            name="uq_notification_deliveries_campaign_device",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','RUNNING','ACCEPTED','RETRY_WAIT',"
            "'TERMINAL_FAILURE','CANCELLED','EXPIRED')",
            name="ck_notification_deliveries_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_notification_deliveries_attempt_count",
        ),
        sa.CheckConstraint(
            "revision >= 0",
            name="ck_notification_deliveries_revision",
        ),
    )
    op.create_index(
        "ix_notification_deliveries_campaign_id",
        "notification_deliveries",
        ["campaign_id"],
        unique=False,
    )
    op.create_index(
        "ix_notification_deliveries_device_id",
        "notification_deliveries",
        ["device_id"],
        unique=False,
    )
    op.create_index(
        "ix_notification_deliveries_owner_user_id",
        "notification_deliveries",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_notification_deliveries_campaign_status",
        "notification_deliveries",
        ["campaign_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_notification_deliveries_owner_created",
        "notification_deliveries",
        ["owner_user_id", "created_at"],
        unique=False,
    )

    with op.batch_alter_table("maintenance_jobs", recreate="auto") as batch:
        batch.drop_constraint("ck_maintenance_jobs_known_type", type_="check")
        batch.create_check_constraint(
            "ck_maintenance_jobs_known_type",
            _job_type_check(_NEW_JOB_TYPES),
        )


def downgrade() -> None:
    with op.batch_alter_table("maintenance_jobs", recreate="auto") as batch:
        batch.drop_constraint("ck_maintenance_jobs_known_type", type_="check")
        batch.create_check_constraint(
            "ck_maintenance_jobs_known_type",
            _job_type_check(_OLD_JOB_TYPES),
        )

    op.drop_index(
        "ix_notification_deliveries_owner_created",
        table_name="notification_deliveries",
    )
    op.drop_index(
        "ix_notification_deliveries_campaign_status",
        table_name="notification_deliveries",
    )
    op.drop_index(
        "ix_notification_deliveries_owner_user_id",
        table_name="notification_deliveries",
    )
    op.drop_index(
        "ix_notification_deliveries_device_id",
        table_name="notification_deliveries",
    )
    op.drop_index(
        "ix_notification_deliveries_campaign_id",
        table_name="notification_deliveries",
    )
    op.drop_table("notification_deliveries")

    op.drop_index(
        "ix_notification_campaign_targets_device_id",
        table_name="notification_campaign_targets",
    )
    op.drop_index(
        "ix_notification_campaign_targets_user_id",
        table_name="notification_campaign_targets",
    )
    op.drop_index(
        "ix_notification_campaign_targets_campaign",
        table_name="notification_campaign_targets",
    )
    op.drop_table("notification_campaign_targets")

    op.drop_index(
        "ix_notification_campaigns_due",
        table_name="notification_campaigns",
    )
    op.drop_index(
        "ix_notification_campaigns_created_by_admin_id",
        table_name="notification_campaigns",
    )
    op.drop_index(
        "ix_notification_campaigns_message_id",
        table_name="notification_campaigns",
    )
    op.drop_table("notification_campaigns")

    op.drop_index(
        "ix_notification_messages_source",
        table_name="notification_messages",
    )
    op.drop_table("notification_messages")

    op.drop_index("uq_devices_active_push_binding", table_name="devices")
    with op.batch_alter_table("devices", recreate="auto") as batch:
        batch.drop_column("os_version")
        batch.drop_column("app_version")
        batch.drop_column("push_invalidated_at")
        batch.drop_column("push_token_updated_at")
        batch.drop_column("push_enabled")
        batch.drop_column("push_token_digest")
        batch.drop_column("push_provider")
