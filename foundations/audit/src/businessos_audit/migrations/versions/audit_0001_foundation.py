"""Create the audit and immutable evidence foundation schema.

Revision ID: audit_0001
Revises: policy_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "audit_0001"
down_revision: str | Sequence[str] | None = "policy_0001"
branch_labels: str | Sequence[str] | None = ("foundation_audit",)
depends_on: str | Sequence[str] | None = None

SCHEMA = "platform_audit"
TABLES = ("audit_logs",)


def _isolate(table: str) -> None:
    qualified = f"{SCHEMA}.{table}"
    expression = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(f"ALTER TABLE {qualified} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {qualified} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {qualified} TO businessos_app "
        f"USING ({expression}) WITH CHECK ({expression})"
    )
    op.execute(
        f"CREATE POLICY {table}_migration_access ON {qualified} TO businessos_migrator "
        "USING (true) WITH CHECK (true)"
    )


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.execute(f"REVOKE ALL ON SCHEMA {SCHEMA} FROM PUBLIC")

    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("actor_type", sa.String(length=50), nullable=False, server_default="user"),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=False),
        sa.Column("resource_id", sa.String(length=255), nullable=True),
        sa.Column("scope_type", sa.String(length=50), nullable=True),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("before_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("correlation_id", sa.String(length=100), nullable=True),
        sa.Column("client_ip", sa.String(length=50), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("decision_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="success"),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )

    op.create_index(
        "ix_audit_tenant_occurred",
        "audit_logs",
        ["tenant_id", "occurred_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_audit_tenant_resource",
        "audit_logs",
        ["tenant_id", "resource_type", "resource_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_audit_tenant_correlation",
        "audit_logs",
        ["tenant_id", "correlation_id"],
        schema=SCHEMA,
    )

    for table in TABLES:
        _isolate(table)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table, schema=SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
