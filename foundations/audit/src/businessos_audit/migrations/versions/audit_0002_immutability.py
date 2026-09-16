"""Make audit evidence append-only and version its integrity chain.

Revision ID: audit_0002
Revises: audit_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "audit_0002"
down_revision: str | Sequence[str] | None = "audit_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "platform_audit"
TABLE = "audit_logs"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column("trace_id", sa.String(length=100), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column("previous_checksum", sa.String(length=64), server_default="", nullable=False),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column("integrity_version", sa.String(length=10), server_default="1", nullable=False),
        schema=SCHEMA,
    )
    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.reject_audit_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'audit evidence is append-only';
        END;
        $$
        """
    )
    op.execute(
        f"CREATE TRIGGER audit_logs_append_only BEFORE UPDATE OR DELETE ON {SCHEMA}.{TABLE} "
        f"FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.reject_audit_mutation()"
    )
    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO businessos_app")
    op.execute(f"GRANT SELECT, INSERT ON TABLE {SCHEMA}.{TABLE} TO businessos_app")


def downgrade() -> None:
    op.execute(f"REVOKE SELECT, INSERT ON TABLE {SCHEMA}.{TABLE} FROM businessos_app")
    op.execute(f"REVOKE USAGE ON SCHEMA {SCHEMA} FROM businessos_app")
    op.execute(f"DROP TRIGGER audit_logs_append_only ON {SCHEMA}.{TABLE}")
    op.execute(f"DROP FUNCTION {SCHEMA}.reject_audit_mutation()")
    op.drop_column(TABLE, "integrity_version", schema=SCHEMA)
    op.drop_column(TABLE, "previous_checksum", schema=SCHEMA)
    op.drop_column(TABLE, "trace_id", schema=SCHEMA)
