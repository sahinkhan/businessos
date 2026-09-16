"""Create the geography foundation schema.

Revision ID: geography_0001
Revises: organization_0001
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "geography_0001"
down_revision: str | Sequence[str] | None = "organization_0001"
branch_labels: str | Sequence[str] | None = ("foundation_geography",)
depends_on: str | Sequence[str] | None = None

SCHEMA = "platform_geo"
TABLES = ("countries", "subdivisions", "cities", "addresses")


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
        "countries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=2), nullable=False),
        sa.Column("alpha3_code", sa.String(length=3), nullable=False),
        sa.Column("numeric_code", sa.String(length=3), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=True),
        sa.Column("phone_prefix", sa.String(length=10), nullable=True),
        sa.Column(
            "address_format",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_countries"),
        sa.UniqueConstraint("code", name="uq_countries_code"),
        sa.UniqueConstraint("alpha3_code", name="uq_countries_alpha3_code"),
        schema=SCHEMA,
    )

    op.create_table(
        "subdivisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("code", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["country_code"], [f"{SCHEMA}.countries.code"], name="fk_subdivisions_country"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_subdivisions"),
        sa.UniqueConstraint("country_code", "code", name="uq_subdivisions_country_code"),
        schema=SCHEMA,
    )

    op.create_table(
        "cities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("subdivision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("postal_code_pattern", sa.String(length=50), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["country_code"], [f"{SCHEMA}.countries.code"], name="fk_cities_country"
        ),
        sa.ForeignKeyConstraint(
            ["subdivision_id"], [f"{SCHEMA}.subdivisions.id"], name="fk_cities_subdivision"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cities"),
        schema=SCHEMA,
    )

    op.create_table(
        "addresses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("subdivision_code", sa.String(length=10), nullable=True),
        sa.Column("city", sa.String(length=200), nullable=False),
        sa.Column("postal_code", sa.String(length=30), nullable=True),
        sa.Column("street_line1", sa.String(length=300), nullable=False),
        sa.Column("street_line2", sa.String(length=300), nullable=True),
        sa.Column("formatted_address", sa.Text(), nullable=False),
        sa.Column("coordinates", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "metadata",
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
        sa.ForeignKeyConstraint(
            ["country_code"], [f"{SCHEMA}.countries.code"], name="fk_addresses_country"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_addresses"),
        schema=SCHEMA,
    )

    op.create_index("ix_addresses_tenant_id", "addresses", ["tenant_id"], schema=SCHEMA)
    _isolate("addresses")

    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO businessos_app")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {SCHEMA} TO businessos_app"
    )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table, schema=SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
