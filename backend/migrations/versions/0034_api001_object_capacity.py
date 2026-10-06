"""hard-bound per-owner object cardinality

Revision ID: 0034_api001_object_capacity
Revises: 0033_api001_export_jobs
Create Date: 2026-10-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0034_api001_object_capacity"
down_revision: str | None = "0033_api001_export_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OBJECTS_MAX_PER_OWNER = 500
OBJECT_OWNER_CAPACITY_LOCK_SEED = 214001


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Existing production data must already satisfy the business hard bound before
    # the invariant is installed. Do not silently truncate or delete owner data.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM objects
                GROUP BY user_id
                HAVING COUNT(*) > {OBJECTS_MAX_PER_OWNER}
            ) THEN
                RAISE EXCEPTION 'OBJECT_OWNER_CAPACITY_EXISTING_DATA_EXCEEDED'
                    USING ERRCODE = '23514';
            END IF;
        END
        $$;
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION enforce_object_owner_capacity()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtextextended(NEW.user_id::text, {OBJECT_OWNER_CAPACITY_LOCK_SEED})
            );

            IF (
                SELECT COUNT(*)
                FROM objects
                WHERE user_id = NEW.user_id
            ) >= {OBJECTS_MAX_PER_OWNER} THEN
                RAISE EXCEPTION 'OBJECT_OWNER_CAPACITY_EXCEEDED'
                    USING ERRCODE = '23514';
            END IF;

            RETURN NEW;
        END
        $$;
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_objects_owner_capacity
        BEFORE INSERT ON objects
        FOR EACH ROW
        EXECUTE FUNCTION enforce_object_owner_capacity();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP TRIGGER IF EXISTS trg_objects_owner_capacity ON objects")
    op.execute("DROP FUNCTION IF EXISTS enforce_object_owner_capacity()")
