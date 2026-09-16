"""Create the party and contacts foundation schema.

Revision ID: party_0001
Revises: uom_0001
"""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "party_0001"
down_revision: str | Sequence[str] | None = "uom_0001"
branch_labels: str | Sequence[str] | None = ("foundation_party",)
depends_on: str | Sequence[str] | None = None

SCHEMA = "platform_party"
TABLES = (
    "parties",
    "person_profiles",
    "organization_profiles",
    "party_relationships",
    "contact_points",
    "party_address_assignments",
    "external_identifiers",
)


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
        "parties",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("party_number", sa.String(length=50), nullable=False),
        sa.Column("party_type", sa.String(length=30), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("preferred_locale", sa.String(length=20), nullable=True),
        sa.Column("preferred_timezone", sa.String(length=50), nullable=True),
        sa.Column("preferred_currency", sa.String(length=3), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_parties"),
        sa.UniqueConstraint("tenant_id", "party_number", name="uq_party_tenant_number"),
        schema=SCHEMA,
    )

    op.create_table(
        "person_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("party_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("middle_name", sa.String(length=100), nullable=True),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=30), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("gender", sa.String(length=30), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["party_id"], [f"{SCHEMA}.parties.id"], name="fk_person_profiles_party"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_person_profiles"),
        sa.UniqueConstraint("party_id", name="uq_person_profiles_party"),
        schema=SCHEMA,
    )

    op.create_table(
        "organization_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("party_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("legal_name", sa.String(length=255), nullable=False),
        sa.Column("trade_name", sa.String(length=255), nullable=True),
        sa.Column("tax_identifier", sa.String(length=100), nullable=True),
        sa.Column("registration_number", sa.String(length=100), nullable=True),
        sa.Column("website", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["party_id"], [f"{SCHEMA}.parties.id"], name="fk_org_profiles_party"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_org_profiles"),
        sa.UniqueConstraint("party_id", name="uq_org_profiles_party"),
        schema=SCHEMA,
    )

    op.create_table(
        "party_relationships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_party_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_party_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relationship_type", sa.String(length=50), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["from_party_id"], [f"{SCHEMA}.parties.id"], name="fk_relationships_from_party"
        ),
        sa.ForeignKeyConstraint(
            ["to_party_id"], [f"{SCHEMA}.parties.id"], name="fk_relationships_to_party"
        ),
        sa.CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name="ck_relationship_dates",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_party_relationships"),
        schema=SCHEMA,
    )

    op.create_table(
        "contact_points",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("party_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_type", sa.String(length=30), nullable=False),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.Column("purpose", sa.String(length=50), server_default="primary", nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_verified", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["party_id"], [f"{SCHEMA}.parties.id"], name="fk_contact_points_party"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_contact_points"),
        schema=SCHEMA,
    )

    op.create_table(
        "party_address_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("party_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("address_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purpose", sa.String(length=50), server_default="billing", nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["party_id"], [f"{SCHEMA}.parties.id"], name="fk_address_assign_party"
        ),
        sa.ForeignKeyConstraint(
            ["address_id"], ["platform_geo.addresses.id"], name="fk_address_assign_address"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_party_address_assignments"),
        schema=SCHEMA,
    )

    op.create_table(
        "external_identifiers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("party_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("identifier_value", sa.String(length=200), nullable=False),
        sa.Column("is_sensitive", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["party_id"], [f"{SCHEMA}.parties.id"], name="fk_ext_ident_party"),
        sa.PrimaryKeyConstraint("id", name="pk_external_identifiers"),
        sa.UniqueConstraint(
            "tenant_id", "provider", "identifier_value", name="uq_party_tenant_provider_identifier"
        ),
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
