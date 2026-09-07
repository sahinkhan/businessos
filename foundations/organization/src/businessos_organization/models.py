"""SQLAlchemy mappings owned by the organization foundation."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.sql.schema import SchemaItem

metadata = MetaData()


def _identity_columns() -> tuple[SchemaItem, ...]:
    return (
        Column("id", UUID(as_uuid=True), primary_key=True),
        Column("tenant_id", UUID(as_uuid=True), nullable=False),
        Column("code", String(100), nullable=False),
        Column("name", String(200), nullable=False),
        Column("active", Boolean(), nullable=False, server_default="true"),
        Column("effective_from", Date()),
        Column("effective_until", Date()),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    )


ENTERPRISE_GROUPS = Table(
    "enterprise_groups",
    metadata,
    *_identity_columns(),
    UniqueConstraint("tenant_id", "code", name="enterprise_group_code"),
    UniqueConstraint("tenant_id", "id", name="enterprise_group_tenant_id"),
    schema="platform_org",
)

LEGAL_ENTITIES = Table(
    "legal_entities",
    metadata,
    *_identity_columns(),
    Column("enterprise_group_id", UUID(as_uuid=True), nullable=False),
    Column("registration_number", String(200)),
    Column("country_code", String(2), nullable=False),
    UniqueConstraint("tenant_id", "code", name="legal_entity_code"),
    UniqueConstraint("tenant_id", "id", name="legal_entity_tenant_id"),
    schema="platform_org",
)

COMPANIES = Table(
    "companies",
    metadata,
    *_identity_columns(),
    Column("legal_entity_id", UUID(as_uuid=True), nullable=False),
    Column("base_currency", String(3), nullable=False),
    Column("timezone", String(100), nullable=False),
    UniqueConstraint("tenant_id", "code", name="company_code"),
    UniqueConstraint("tenant_id", "id", name="company_tenant_id"),
    schema="platform_org",
)

ORG_UNITS = Table(
    "org_units",
    metadata,
    *_identity_columns(),
    Column("company_id", UUID(as_uuid=True), nullable=False),
    Column("parent_id", UUID(as_uuid=True)),
    Column("unit_type", String(30), nullable=False),
    UniqueConstraint("tenant_id", "company_id", "code", name="org_unit_code"),
    UniqueConstraint("tenant_id", "id", name="org_unit_tenant_id"),
    schema="platform_org",
)

REGIONS = Table(
    "regions",
    metadata,
    *_identity_columns(),
    Column("company_id", UUID(as_uuid=True), nullable=False),
    Column("parent_id", UUID(as_uuid=True)),
    UniqueConstraint("tenant_id", "company_id", "code", name="region_code"),
    UniqueConstraint("tenant_id", "id", name="region_tenant_id"),
    schema="platform_org",
)

SITE_TYPES = Table(
    "site_types",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("code", String(100), nullable=False),
    Column("name", String(200), nullable=False),
    Column("profile_contract", String(300)),
    Column("active", Boolean(), nullable=False, server_default="true"),
    UniqueConstraint("tenant_id", "code", name="site_type_code"),
    UniqueConstraint("tenant_id", "id", name="site_type_tenant_id"),
    schema="platform_org",
)

OPERATING_SITES = Table(
    "operating_sites",
    metadata,
    *_identity_columns(),
    Column("company_id", UUID(as_uuid=True), nullable=False),
    Column("region_id", UUID(as_uuid=True)),
    Column("site_type_id", UUID(as_uuid=True), nullable=False),
    Column("timezone", String(100), nullable=False),
    UniqueConstraint("tenant_id", "company_id", "code", name="operating_site_code"),
    UniqueConstraint("tenant_id", "id", name="operating_site_tenant_id"),
    schema="platform_org",
)

RELATIONSHIPS = Table(
    "relationships",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("source_type", String(30), nullable=False),
    Column("source_id", UUID(as_uuid=True), nullable=False),
    Column("target_type", String(30), nullable=False),
    Column("target_id", UUID(as_uuid=True), nullable=False),
    Column("relationship_type", String(100), nullable=False),
    Column("effective_from", Date()),
    Column("effective_until", Date()),
    UniqueConstraint(
        "tenant_id",
        "source_type",
        "source_id",
        "target_type",
        "target_id",
        "relationship_type",
        name="organization_relationship_identity",
    ),
    schema="platform_org",
)

FINANCIAL_DIMENSIONS = Table(
    "financial_dimensions",
    metadata,
    *_identity_columns(),
    Column("company_id", UUID(as_uuid=True), nullable=False),
    Column("dimension_type", String(40), nullable=False),
    UniqueConstraint(
        "tenant_id", "company_id", "dimension_type", "code", name="financial_dimension_code"
    ),
    UniqueConstraint("tenant_id", "id", name="financial_dimension_tenant_id"),
    schema="platform_org",
)

WAREHOUSES = Table(
    "warehouses",
    metadata,
    *_identity_columns(),
    Column("company_id", UUID(as_uuid=True), nullable=False),
    Column("operating_site_id", UUID(as_uuid=True)),
    UniqueConstraint("tenant_id", "company_id", "code", name="warehouse_code"),
    UniqueConstraint("tenant_id", "id", name="warehouse_tenant_id"),
    schema="platform_org",
)

WAREHOUSE_LOCATIONS = Table(
    "warehouse_locations",
    metadata,
    *_identity_columns(),
    Column("warehouse_id", UUID(as_uuid=True), nullable=False),
    Column("parent_id", UUID(as_uuid=True)),
    UniqueConstraint("tenant_id", "warehouse_id", "code", name="warehouse_location_code"),
    UniqueConstraint("tenant_id", "id", name="warehouse_location_tenant_id"),
    schema="platform_org",
)

ASSIGNMENTS = Table(
    "assignments",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("principal_id", UUID(as_uuid=True), nullable=False),
    Column("scope_type", String(40), nullable=False),
    Column("scope_id", UUID(as_uuid=True), nullable=False),
    Column("title", String(200)),
    Column("valid_from", DateTime(timezone=True)),
    Column("valid_until", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint(
        "tenant_id",
        "principal_id",
        "scope_type",
        "scope_id",
        "valid_from",
        name="assignment_identity",
    ),
    schema="platform_org",
)

DELEGATED_SCOPES = Table(
    "delegated_scopes",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("grantor_principal_id", UUID(as_uuid=True), nullable=False),
    Column("recipient_principal_id", UUID(as_uuid=True), nullable=False),
    Column("scope_type", String(40), nullable=False),
    Column("scope_id", UUID(as_uuid=True), nullable=False),
    Column("allowed_actions", ARRAY(String(200)), nullable=False),
    Column("valid_from", DateTime(timezone=True), nullable=False),
    Column("valid_until", DateTime(timezone=True), nullable=False),
    Column("reason", Text(), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("valid_until > valid_from", name="delegated_scope_dates"),
    schema="platform_org",
)
