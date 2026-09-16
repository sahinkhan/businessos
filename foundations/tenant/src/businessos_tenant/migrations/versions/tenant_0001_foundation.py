"""Create the tenant-management foundation schema.

Revision ID: tenant_0001
Revises: 0005_durable_event_subscribers
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "tenant_0001"
down_revision: str | Sequence[str] | None = "0005_durable_event_subscribers"
branch_labels: str | Sequence[str] | None = ("foundation_tenant",)
depends_on: str | Sequence[str] | None = None

SCHEMA = "platform_tenant"
TENANT_TABLES = (
    "tenants",
    "tenant_status_history",
    "tenant_entitlements",
    "tenant_quotas",
)


def _enable_tenant_isolation(table: str) -> None:
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
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("deployment_mode", sa.String(length=40), nullable=False),
        sa.Column("region", sa.String(length=100), nullable=False),
        sa.Column(
            "residency",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "configuration_defaults",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("id = tenant_id", name="tenant_identity_matches_boundary"),
        sa.CheckConstraint(
            "status IN ('requested','provisioning','active','suspended','retention_hold',"
            "'terminating','deleted')",
            name="tenant_status",
        ),
        sa.CheckConstraint(
            "deployment_mode IN ('dedicated','database_per_tenant','shared_schema')",
            name="tenant_deployment_mode",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tenants"),
        sa.UniqueConstraint("tenant_id", name="uq_tenants_tenant_id"),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
        schema=SCHEMA,
    )
    op.create_table(
        "tenant_status_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_status", sa.String(length=30)),
        sa.Column("to_status", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], [f"{SCHEMA}.tenants.tenant_id"], name="fk_status_history_tenant"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tenant_status_history"),
        schema=SCHEMA,
    )
    op.create_table(
        "tenant_entitlements",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capability", sa.String(length=200), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("reference", sa.String(length=200)),
        sa.Column("effective_from", sa.DateTime(timezone=True)),
        sa.Column("effective_until", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_from IS NULL "
            "OR effective_until >= effective_from",
            name="tenant_entitlement_dates",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], [f"{SCHEMA}.tenants.tenant_id"], name="fk_entitlements_tenant"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tenant_entitlements"),
        sa.UniqueConstraint("tenant_id", "capability", name="tenant_entitlement_capability"),
        schema=SCHEMA,
    )
    op.create_table(
        "tenant_quotas",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quota", sa.String(length=200), nullable=False),
        sa.Column("limit_value", sa.BigInteger(), nullable=False),
        sa.Column("unit", sa.String(length=50), nullable=False),
        sa.CheckConstraint("limit_value >= 0", name="tenant_quota_nonnegative"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], [f"{SCHEMA}.tenants.tenant_id"], name="fk_quotas_tenant"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tenant_quotas"),
        sa.UniqueConstraint("tenant_id", "quota", name="tenant_quota_name"),
        schema=SCHEMA,
    )
    for table in TENANT_TABLES:
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"], schema=SCHEMA)
        _enable_tenant_isolation(table)
    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO businessos_app, businessos_ops")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {SCHEMA}.tenants TO businessos_app")
    op.execute(f"GRANT SELECT, INSERT ON {SCHEMA}.tenant_status_history TO businessos_app")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE ON {SCHEMA}.tenant_entitlements, "
        f"{SCHEMA}.tenant_quotas TO businessos_app"
    )
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {SCHEMA} TO businessos_ops"
    )


def downgrade() -> None:
    for table in reversed(TENANT_TABLES):
        op.drop_table(table, schema=SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
