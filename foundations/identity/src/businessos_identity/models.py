"""SQLAlchemy mappings owned by the identity foundation."""

from sqlalchemy import (
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

metadata = MetaData()

USERS = Table(
    "users",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("email", String(320), nullable=False),
    Column("display_name", String(200), nullable=False),
    Column("active", Boolean(), nullable=False, server_default="true"),
    Column("is_break_glass", Boolean(), nullable=False, server_default="false"),
    Column("credential_secret_reference", Text()),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "email", name="identity_user_email"),
    UniqueConstraint("tenant_id", "id", name="identity_user_tenant_id"),
    schema="platform_identity",
)

EXTERNAL_IDENTITIES = Table(
    "external_identities",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("issuer", String(500), nullable=False),
    Column("subject", String(500), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "issuer", "subject", name="external_identity_subject"),
    schema="platform_identity",
)

MEMBERSHIPS = Table(
    "memberships",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("principal_id", UUID(as_uuid=True), nullable=False),
    Column("principal_type", String(30), nullable=False),
    Column("status", String(30), nullable=False, server_default="active"),
    Column("valid_from", DateTime(timezone=True)),
    Column("valid_until", DateTime(timezone=True)),
    Column("scopes", JSONB(), nullable=False, server_default="[]"),
    Column("granted_by", UUID(as_uuid=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "principal_type", "principal_id", name="membership_principal"),
    CheckConstraint(
        "valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from",
        name="membership_dates",
    ),
    schema="platform_identity",
)

SERVICE_ACCOUNTS = Table(
    "service_accounts",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("name", String(200), nullable=False),
    Column("credential_secret_reference", Text(), nullable=False),
    Column("active", Boolean(), nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "name", name="service_account_name"),
    UniqueConstraint("tenant_id", "id", name="service_account_tenant_id"),
    schema="platform_identity",
)

DEVICES = Table(
    "devices",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("principal_id", UUID(as_uuid=True), nullable=False),
    Column("name", String(200), nullable=False),
    Column("device_type", String(100), nullable=False),
    Column("credential_secret_reference", Text(), nullable=False),
    Column("active", Boolean(), nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "name", name="device_name"),
    schema="platform_identity",
)

AUTHENTICATION_SESSIONS = Table(
    "authentication_sessions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("principal_id", UUID(as_uuid=True), nullable=False),
    Column("authentication_strength", String(100), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    schema="platform_identity",
)

OIDC_PROVIDERS = Table(
    "oidc_providers",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("issuer", String(500), nullable=False),
    Column("audience", String(500), nullable=False),
    Column("jwks_uri", String(1000), nullable=False),
    Column("algorithms", ARRAY(String(20)), nullable=False),
    Column("active", Boolean(), nullable=False, server_default="true"),
    UniqueConstraint("tenant_id", "issuer", "audience", name="oidc_provider_identity"),
    schema="platform_identity",
)

MFA_POLICIES = Table(
    "mfa_policies",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", UUID(as_uuid=True), nullable=False),
    Column("minimum_strength", String(100), nullable=False),
    Column("required_methods", ARRAY(String(100)), nullable=False),
    Column("configuration", JSONB(), nullable=False, server_default="{}"),
    UniqueConstraint("tenant_id", name="mfa_policy_tenant"),
    schema="platform_identity",
)
