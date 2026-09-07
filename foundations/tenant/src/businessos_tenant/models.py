"""SQLAlchemy mappings owned by the tenant foundation."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()

TENANTS = Table(
    "tenants",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False, unique=True),
    Column("slug", String(100), nullable=False, unique=True),
    Column("name", String(200), nullable=False),
    Column("status", String(30), nullable=False),
    Column("deployment_mode", String(40), nullable=False),
    Column("region", String(100), nullable=False),
    Column("residency", JSONB(), nullable=False, server_default="{}"),
    Column("configuration_defaults", JSONB(), nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("id = tenant_id", name="tenant_identity_matches_boundary"),
    schema="platform_tenant",
)

TENANT_STATUS_HISTORY = Table(
    "tenant_status_history",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("from_status", String(30)),
    Column("to_status", String(30), nullable=False),
    Column("reason", Text()),
    Column("changed_by", UUID(as_uuid=True)),
    Column("changed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="platform_tenant",
)

TENANT_ENTITLEMENTS = Table(
    "tenant_entitlements",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("capability", String(200), nullable=False),
    Column("enabled", Boolean(), nullable=False, server_default="false"),
    Column("reference", String(200)),
    Column("effective_from", DateTime(timezone=True)),
    Column("effective_until", DateTime(timezone=True)),
    UniqueConstraint("tenant_id", "capability", name="tenant_entitlement_capability"),
    CheckConstraint(
        "effective_until IS NULL OR effective_from IS NULL OR effective_until >= effective_from",
        name="tenant_entitlement_dates",
    ),
    schema="platform_tenant",
)

TENANT_QUOTAS = Table(
    "tenant_quotas",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("quota", String(200), nullable=False),
    Column("limit_value", BigInteger(), nullable=False),
    Column("unit", String(50), nullable=False),
    UniqueConstraint("tenant_id", "quota", name="tenant_quota_name"),
    CheckConstraint("limit_value >= 0", name="tenant_quota_nonnegative"),
    schema="platform_tenant",
)
