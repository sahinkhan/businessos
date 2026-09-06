"""Create Phase 1 protected runtime schemas.

Revision ID: 0001_phase1_kernel
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_phase1_kernel"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS eventing")
    op.execute("CREATE SCHEMA IF NOT EXISTS platform_module")
    op.execute("REVOKE ALL ON SCHEMA eventing FROM PUBLIC")
    op.execute("REVOKE ALL ON SCHEMA platform_module FROM PUBLIC")

    op.create_table(
        "outbox_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=200), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.String(length=100), nullable=False),
        sa.Column("causation_id", sa.String(length=100), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_messages"),
        schema="eventing",
    )
    op.create_index(
        "ix_outbox_messages_tenant_id",
        "outbox_messages",
        ["tenant_id"],
        schema="eventing",
    )
    op.create_index(
        "ix_outbox_messages_unpublished",
        "outbox_messages",
        ["occurred_at"],
        unique=False,
        schema="eventing",
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.create_table(
        "inbox_receipts",
        sa.Column("consumer", sa.String(length=200), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("tenant_id", "consumer", "event_id", name="pk_inbox_receipts"),
        schema="eventing",
    )
    op.create_index(
        "ix_inbox_receipts_tenant_id",
        "inbox_receipts",
        ["tenant_id"],
        schema="eventing",
    )
    op.create_table(
        "module_runtime_state",
        sa.Column("module_id", sa.String(length=200), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("module_id", name="pk_module_runtime_state"),
        schema="platform_module",
    )

    tenant_expression = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    for table_name in ("outbox_messages", "inbox_receipts"):
        qualified = f"eventing.{table_name}"
        op.execute(f"ALTER TABLE {qualified} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {qualified} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table_name}_tenant_isolation ON {qualified} "
            f"TO businessos_app USING ({tenant_expression}) WITH CHECK ({tenant_expression})"
        )

    op.execute("GRANT USAGE ON SCHEMA eventing TO businessos_app, businessos_ops")
    op.execute("GRANT USAGE ON SCHEMA platform_module TO businessos_app, businessos_ops")
    op.execute("GRANT SELECT, INSERT ON eventing.outbox_messages TO businessos_app")
    op.execute("GRANT SELECT, INSERT ON eventing.inbox_receipts TO businessos_app")
    op.execute("GRANT SELECT, UPDATE ON eventing.outbox_messages TO businessos_ops")
    op.execute("GRANT SELECT, INSERT ON eventing.inbox_receipts TO businessos_ops")
    op.execute("GRANT SELECT ON platform_module.module_runtime_state TO businessos_app")
    op.execute("GRANT SELECT ON platform_module.module_runtime_state TO businessos_ops")


def downgrade() -> None:
    op.drop_table("module_runtime_state", schema="platform_module")
    op.drop_index("ix_inbox_receipts_tenant_id", table_name="inbox_receipts", schema="eventing")
    op.drop_table("inbox_receipts", schema="eventing")
    op.drop_index("ix_outbox_messages_unpublished", table_name="outbox_messages", schema="eventing")
    op.drop_index("ix_outbox_messages_tenant_id", table_name="outbox_messages", schema="eventing")
    op.drop_table("outbox_messages", schema="eventing")
    op.execute("DROP SCHEMA IF EXISTS platform_module")
    op.execute("DROP SCHEMA IF EXISTS eventing")
