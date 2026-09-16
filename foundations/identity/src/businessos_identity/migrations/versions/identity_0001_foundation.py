"""Create the identity and membership foundation schema.

Revision ID: identity_0001
Revises: tenant_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "identity_0001"
down_revision: str | Sequence[str] | None = "tenant_0001"
branch_labels: str | Sequence[str] | None = ("foundation_identity",)
depends_on: str | Sequence[str] | None = None

SCHEMA = "platform_identity"
TABLES = (
    "users",
    "external_identities",
    "memberships",
    "service_accounts",
    "devices",
    "authentication_sessions",
    "oidc_providers",
    "mfa_policies",
)


def _tenant_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["tenant_id"], ["platform_tenant.tenants.tenant_id"], name=name)


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
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_break_glass", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("credential_secret_reference", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        _tenant_fk("fk_users_tenant"),
        sa.CheckConstraint(
            "NOT is_break_glass OR credential_secret_reference IS NOT NULL",
            name="break_glass_secret_reference",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_identity_users"),
        sa.UniqueConstraint("tenant_id", "email", name="identity_user_email"),
        sa.UniqueConstraint("tenant_id", "id", name="identity_user_tenant_id"),
        schema=SCHEMA,
    )
    op.create_table(
        "external_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issuer", sa.String(length=500), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        _tenant_fk("fk_external_identities_tenant"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            [f"{SCHEMA}.users.tenant_id", f"{SCHEMA}.users.id"],
            name="fk_external_identity_user",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_external_identities"),
        sa.UniqueConstraint("tenant_id", "issuer", "subject", name="external_identity_subject"),
        schema=SCHEMA,
    )
    op.create_table(
        "memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("principal_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), server_default="active", nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column(
            "scopes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        _tenant_fk("fk_memberships_tenant"),
        sa.CheckConstraint(
            "principal_type IN ('user','service_account','device')",
            name="membership_principal_type",
        ),
        sa.CheckConstraint("status IN ('active','suspended','revoked')", name="membership_status"),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from",
            name="membership_dates",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_memberships"),
        sa.UniqueConstraint(
            "tenant_id", "principal_type", "principal_id", name="membership_principal"
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "service_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("credential_secret_reference", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        _tenant_fk("fk_service_accounts_tenant"),
        sa.PrimaryKeyConstraint("id", name="pk_service_accounts"),
        sa.UniqueConstraint("tenant_id", "name", name="service_account_name"),
        sa.UniqueConstraint("tenant_id", "id", name="service_account_tenant_id"),
        schema=SCHEMA,
    )
    op.create_table(
        "devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("device_type", sa.String(length=100), nullable=False),
        sa.Column("credential_secret_reference", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        _tenant_fk("fk_devices_tenant"),
        sa.PrimaryKeyConstraint("id", name="pk_devices"),
        sa.UniqueConstraint("tenant_id", "name", name="device_name"),
        schema=SCHEMA,
    )
    op.create_table(
        "authentication_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("authentication_strength", sa.String(length=100), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        _tenant_fk("fk_sessions_tenant"),
        sa.CheckConstraint("expires_at > started_at", name="session_expiry"),
        sa.PrimaryKeyConstraint("id", name="pk_authentication_sessions"),
        schema=SCHEMA,
    )
    op.create_table(
        "oidc_providers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issuer", sa.String(length=500), nullable=False),
        sa.Column("audience", sa.String(length=500), nullable=False),
        sa.Column("jwks_uri", sa.String(length=1000), nullable=False),
        sa.Column("algorithms", postgresql.ARRAY(sa.String(length=20)), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        _tenant_fk("fk_oidc_providers_tenant"),
        sa.CheckConstraint(
            "issuer LIKE 'https://%' AND jwks_uri LIKE 'https://%'",
            name="oidc_https_only",
        ),
        sa.CheckConstraint("cardinality(algorithms) > 0", name="oidc_algorithms_nonempty"),
        sa.PrimaryKeyConstraint("id", name="pk_oidc_providers"),
        sa.UniqueConstraint("tenant_id", "issuer", "audience", name="oidc_provider_identity"),
        schema=SCHEMA,
    )
    op.create_table(
        "mfa_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("minimum_strength", sa.String(length=100), nullable=False),
        sa.Column("required_methods", postgresql.ARRAY(sa.String(length=100)), nullable=False),
        sa.Column(
            "configuration",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        _tenant_fk("fk_mfa_policies_tenant"),
        sa.PrimaryKeyConstraint("id", name="pk_mfa_policies"),
        sa.UniqueConstraint("tenant_id", name="mfa_policy_tenant"),
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
