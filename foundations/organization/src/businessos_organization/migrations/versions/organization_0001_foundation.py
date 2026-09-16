"""Create the multinational organization foundation schema.

Revision ID: organization_0001
Revises: identity_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.schema import SchemaItem

revision: str = "organization_0001"
down_revision: str | Sequence[str] | None = "identity_0001"
branch_labels: str | Sequence[str] | None = ("foundation_organization",)
depends_on: str | Sequence[str] | None = None

SCHEMA = "platform_org"
TABLES = (
    "enterprise_groups",
    "legal_entities",
    "companies",
    "org_units",
    "regions",
    "site_types",
    "operating_sites",
    "relationships",
    "financial_dimensions",
    "warehouses",
    "warehouse_locations",
    "assignments",
    "delegated_scopes",
)


def _tenant_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["tenant_id"], ["platform_tenant.tenants.tenant_id"], name=name)


def _identity_columns() -> tuple[SchemaItem, ...]:
    return (
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("effective_from", sa.Date()),
        sa.Column("effective_until", sa.Date()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_from IS NULL "
            "OR effective_until >= effective_from",
            name="effective_dates",
        ),
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
        "enterprise_groups",
        *_identity_columns(),
        _tenant_fk("fk_enterprise_groups_tenant"),
        sa.PrimaryKeyConstraint("id", name="pk_enterprise_groups"),
        sa.UniqueConstraint("tenant_id", "code", name="enterprise_group_code"),
        sa.UniqueConstraint("tenant_id", "id", name="enterprise_group_tenant_id"),
        schema=SCHEMA,
    )
    op.create_table(
        "legal_entities",
        *_identity_columns(),
        sa.Column("enterprise_group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("registration_number", sa.String(length=200)),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        _tenant_fk("fk_legal_entities_tenant"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "enterprise_group_id"],
            [f"{SCHEMA}.enterprise_groups.tenant_id", f"{SCHEMA}.enterprise_groups.id"],
            name="fk_legal_entity_group",
        ),
        sa.CheckConstraint("country_code ~ '^[A-Z]{2}$'", name="legal_entity_country"),
        sa.PrimaryKeyConstraint("id", name="pk_legal_entities"),
        sa.UniqueConstraint("tenant_id", "code", name="legal_entity_code"),
        sa.UniqueConstraint("tenant_id", "id", name="legal_entity_tenant_id"),
        schema=SCHEMA,
    )
    op.create_table(
        "companies",
        *_identity_columns(),
        sa.Column("legal_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("timezone", sa.String(length=100), nullable=False),
        _tenant_fk("fk_companies_tenant"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "legal_entity_id"],
            [f"{SCHEMA}.legal_entities.tenant_id", f"{SCHEMA}.legal_entities.id"],
            name="fk_company_legal_entity",
        ),
        sa.CheckConstraint("base_currency ~ '^[A-Z]{3}$'", name="company_currency"),
        sa.PrimaryKeyConstraint("id", name="pk_companies"),
        sa.UniqueConstraint("tenant_id", "code", name="company_code"),
        sa.UniqueConstraint("tenant_id", "id", name="company_tenant_id"),
        schema=SCHEMA,
    )
    op.create_table(
        "org_units",
        *_identity_columns(),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True)),
        sa.Column("unit_type", sa.String(length=30), nullable=False),
        _tenant_fk("fk_org_units_tenant"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "company_id"],
            [f"{SCHEMA}.companies.tenant_id", f"{SCHEMA}.companies.id"],
            name="fk_org_unit_company",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            [f"{SCHEMA}.org_units.tenant_id", f"{SCHEMA}.org_units.id"],
            name="fk_org_unit_parent",
        ),
        sa.CheckConstraint(
            "unit_type IN ('business_unit','division','department','team')",
            name="org_unit_type",
        ),
        sa.CheckConstraint("parent_id IS NULL OR parent_id <> id", name="org_unit_not_self"),
        sa.PrimaryKeyConstraint("id", name="pk_org_units"),
        sa.UniqueConstraint("tenant_id", "company_id", "code", name="org_unit_code"),
        sa.UniqueConstraint("tenant_id", "id", name="org_unit_tenant_id"),
        schema=SCHEMA,
    )
    op.create_table(
        "regions",
        *_identity_columns(),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True)),
        _tenant_fk("fk_regions_tenant"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "company_id"],
            [f"{SCHEMA}.companies.tenant_id", f"{SCHEMA}.companies.id"],
            name="fk_region_company",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            [f"{SCHEMA}.regions.tenant_id", f"{SCHEMA}.regions.id"],
            name="fk_region_parent",
        ),
        sa.CheckConstraint("parent_id IS NULL OR parent_id <> id", name="region_not_self"),
        sa.PrimaryKeyConstraint("id", name="pk_regions"),
        sa.UniqueConstraint("tenant_id", "company_id", "code", name="region_code"),
        sa.UniqueConstraint("tenant_id", "id", name="region_tenant_id"),
        schema=SCHEMA,
    )
    op.create_table(
        "site_types",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("profile_contract", sa.String(length=300)),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        _tenant_fk("fk_site_types_tenant"),
        sa.PrimaryKeyConstraint("id", name="pk_site_types"),
        sa.UniqueConstraint("tenant_id", "code", name="site_type_code"),
        sa.UniqueConstraint("tenant_id", "id", name="site_type_tenant_id"),
        schema=SCHEMA,
    )
    op.create_table(
        "operating_sites",
        *_identity_columns(),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("region_id", postgresql.UUID(as_uuid=True)),
        sa.Column("site_type_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("timezone", sa.String(length=100), nullable=False),
        _tenant_fk("fk_operating_sites_tenant"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "company_id"],
            [f"{SCHEMA}.companies.tenant_id", f"{SCHEMA}.companies.id"],
            name="fk_site_company",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "region_id"],
            [f"{SCHEMA}.regions.tenant_id", f"{SCHEMA}.regions.id"],
            name="fk_site_region",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "site_type_id"],
            [f"{SCHEMA}.site_types.tenant_id", f"{SCHEMA}.site_types.id"],
            name="fk_site_type",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_operating_sites"),
        sa.UniqueConstraint("tenant_id", "company_id", "code", name="operating_site_code"),
        sa.UniqueConstraint("tenant_id", "id", name="operating_site_tenant_id"),
        schema=SCHEMA,
    )
    op.create_table(
        "relationships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relationship_type", sa.String(length=100), nullable=False),
        sa.Column("effective_from", sa.Date()),
        sa.Column("effective_until", sa.Date()),
        _tenant_fk("fk_relationships_tenant"),
        sa.CheckConstraint("source_id <> target_id", name="relationship_not_self"),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_from IS NULL "
            "OR effective_until >= effective_from",
            name="relationship_effective_dates",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_relationships"),
        sa.UniqueConstraint(
            "tenant_id",
            "source_type",
            "source_id",
            "target_type",
            "target_id",
            "relationship_type",
            name="organization_relationship_identity",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "financial_dimensions",
        *_identity_columns(),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dimension_type", sa.String(length=40), nullable=False),
        _tenant_fk("fk_financial_dimensions_tenant"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "company_id"],
            [f"{SCHEMA}.companies.tenant_id", f"{SCHEMA}.companies.id"],
            name="fk_financial_dimension_company",
        ),
        sa.CheckConstraint(
            "dimension_type IN "
            "('cost_center','profit_center','project','channel','responsibility_center')",
            name="financial_dimension_type",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_financial_dimensions"),
        sa.UniqueConstraint(
            "tenant_id", "company_id", "dimension_type", "code", name="financial_dimension_code"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="financial_dimension_tenant_id"),
        schema=SCHEMA,
    )
    op.create_table(
        "warehouses",
        *_identity_columns(),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operating_site_id", postgresql.UUID(as_uuid=True)),
        _tenant_fk("fk_warehouses_tenant"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "company_id"],
            [f"{SCHEMA}.companies.tenant_id", f"{SCHEMA}.companies.id"],
            name="fk_warehouse_company",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "operating_site_id"],
            [f"{SCHEMA}.operating_sites.tenant_id", f"{SCHEMA}.operating_sites.id"],
            name="fk_warehouse_site",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_warehouses"),
        sa.UniqueConstraint("tenant_id", "company_id", "code", name="warehouse_code"),
        sa.UniqueConstraint("tenant_id", "id", name="warehouse_tenant_id"),
        schema=SCHEMA,
    )
    op.create_table(
        "warehouse_locations",
        *_identity_columns(),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True)),
        _tenant_fk("fk_warehouse_locations_tenant"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "warehouse_id"],
            [f"{SCHEMA}.warehouses.tenant_id", f"{SCHEMA}.warehouses.id"],
            name="fk_location_warehouse",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "parent_id"],
            [f"{SCHEMA}.warehouse_locations.tenant_id", f"{SCHEMA}.warehouse_locations.id"],
            name="fk_location_parent",
        ),
        sa.CheckConstraint("parent_id IS NULL OR parent_id <> id", name="location_not_self"),
        sa.PrimaryKeyConstraint("id", name="pk_warehouse_locations"),
        sa.UniqueConstraint("tenant_id", "warehouse_id", "code", name="warehouse_location_code"),
        sa.UniqueConstraint("tenant_id", "id", name="warehouse_location_tenant_id"),
        schema=SCHEMA,
    )
    op.create_table(
        "assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_type", sa.String(length=40), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200)),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        _tenant_fk("fk_assignments_tenant"),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from",
            name="assignment_dates",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_assignments"),
        sa.UniqueConstraint(
            "tenant_id",
            "principal_id",
            "scope_type",
            "scope_id",
            "valid_from",
            name="assignment_identity",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "delegated_scopes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("grantor_principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_type", sa.String(length=40), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("allowed_actions", postgresql.ARRAY(sa.String(length=200)), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        _tenant_fk("fk_delegated_scopes_tenant"),
        sa.CheckConstraint("valid_until > valid_from", name="delegated_scope_dates"),
        sa.CheckConstraint("cardinality(allowed_actions) > 0", name="delegated_scope_actions"),
        sa.PrimaryKeyConstraint("id", name="pk_delegated_scopes"),
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
