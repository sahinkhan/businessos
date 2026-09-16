"""Create the reference data and number sequence foundation schema.

Revision ID: reference_0001
Revises: geography_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "reference_0001"
down_revision: str | Sequence[str] | None = "geography_0001"
branch_labels: str | Sequence[str] | None = ("foundation_reference_data",)
depends_on: str | Sequence[str] | None = None

SCHEMA = "platform_ref"
TABLES = ("reference_sets", "reference_values", "number_sequences")


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
        "reference_sets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owning_module", sa.String(length=100), nullable=False),
        sa.Column("is_extensible", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reference_sets"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_ref_set_tenant_code"),
        schema=SCHEMA,
    )

    op.create_table(
        "reference_values",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("set_code", sa.String(length=100), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("label_key", sa.String(length=200), nullable=False),
        sa.Column("default_label", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("external_id", sa.String(length=200), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("seed_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "properties",
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
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_from IS NULL OR "
            "effective_until >= effective_from",
            name="ck_ref_value_effective_dates",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reference_values"),
        sa.UniqueConstraint("tenant_id", "set_code", "code", name="uq_ref_value_tenant_set_code"),
        schema=SCHEMA,
    )

    op.create_table(
        "number_sequences",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("prefix", sa.String(length=30), server_default="", nullable=False),
        sa.Column("suffix", sa.String(length=30), server_default="", nullable=False),
        sa.Column("next_value", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("step", sa.Integer(), server_default="1", nullable=False),
        sa.Column("padding", sa.Integer(), server_default="6", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("next_value >= 1", name="ck_number_seq_next_value_positive"),
        sa.PrimaryKeyConstraint("id", name="pk_number_sequences"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_number_seq_tenant_code"),
        schema=SCHEMA,
    )

    for table in TABLES:
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"], schema=SCHEMA)
        _isolate(table)

    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO businessos_app")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {SCHEMA} TO businessos_app"
    )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table, schema=SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
