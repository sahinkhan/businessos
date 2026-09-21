"""Persist ordered lifecycle work independently of broker delivery order.

Revision ID: tenant_0002
Revises: tenant_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "tenant_0002"
down_revision: str | Sequence[str] | None = "tenant_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("lifecycle_version", sa.BigInteger(), server_default="0", nullable=False),
        schema="platform_tenant",
    )
    op.create_table(
        "tenant_lifecycle_operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lifecycle_version", sa.BigInteger(), nullable=False),
        sa.Column("operation", sa.String(20), nullable=False),
        sa.Column("state", sa.String(20), server_default="pending", nullable=False),
        sa.Column("depends_on", postgresql.UUID(as_uuid=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["platform_tenant.tenants.tenant_id"],
            name="fk_tenant_lifecycle_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "depends_on"],
            [
                "platform_tenant.tenant_lifecycle_operations.tenant_id",
                "platform_tenant.tenant_lifecycle_operations.id",
            ],
            name="fk_tenant_lifecycle_dependency",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="tenant_lifecycle_operation_identity"),
        sa.UniqueConstraint(
            "tenant_id", "lifecycle_version", name="tenant_lifecycle_operation_version"
        ),
        sa.CheckConstraint(
            "operation IN ('export','delete','restore')", name="tenant_lifecycle_kind"
        ),
        sa.CheckConstraint(
            "state IN ('pending','completed','skipped')", name="tenant_lifecycle_state"
        ),
        schema="platform_tenant",
    )
    table = "platform_tenant.tenant_lifecycle_operations"
    op.create_index(
        "ix_tenant_lifecycle_operations_tenant_id",
        "tenant_lifecycle_operations",
        ["tenant_id"],
        schema="platform_tenant",
    )
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    expression = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"CREATE POLICY tenant_lifecycle_operations_tenant_isolation ON {table} "
        f"TO businessos_app USING ({expression}) WITH CHECK ({expression})"
    )
    op.execute(
        f"CREATE POLICY tenant_lifecycle_operations_migration_access ON {table} "
        "TO businessos_migrator USING (true) WITH CHECK (true)"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO businessos_app")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO businessos_ops")


def downgrade() -> None:
    op.drop_table("tenant_lifecycle_operations", schema="platform_tenant")
    op.drop_column("tenants", "lifecycle_version", schema="platform_tenant")
