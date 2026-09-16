"""Create the units of measure foundation schema.

Revision ID: uom_0001
Revises: reference_0001
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "uom_0001"
down_revision: str | Sequence[str] | None = "reference_0001"
branch_labels: str | Sequence[str] | None = ("foundation_uom",)
depends_on: str | Sequence[str] | None = None

SCHEMA = "platform_uom"
TABLES = ("measurement_categories", "units_of_measure")


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
        "measurement_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("base_unit_code", sa.String(length=50), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_measurement_categories"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_meas_cat_tenant_code"),
        schema=SCHEMA,
    )

    op.create_table(
        "units_of_measure",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_code", sa.String(length=100), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("is_base_unit", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "conversion_ratio",
            sa.Numeric(precision=20, scale=8),
            server_default="1.0",
            nullable=False,
        ),
        sa.Column(
            "conversion_offset",
            sa.Numeric(precision=20, scale=8),
            server_default="0.0",
            nullable=False,
        ),
        sa.Column("precision", sa.Integer(), server_default="2", nullable=False),
        sa.Column("rounding_mode", sa.String(length=50), server_default="ROUND_HALF_UP", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("conversion_ratio > 0", name="ck_uom_conversion_ratio_positive"),
        sa.CheckConstraint("precision >= 0", name="ck_uom_precision_nonnegative"),
        sa.PrimaryKeyConstraint("id", name="pk_units_of_measure"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_uom_tenant_code"),
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
