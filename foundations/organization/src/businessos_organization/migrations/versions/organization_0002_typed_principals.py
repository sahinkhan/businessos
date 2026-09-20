"""Add tenant-safe typed principals and scopes to organization grants.

Revision ID: organization_0002
Revises: organization_0001, identity_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "organization_0002"
down_revision: str | Sequence[str] | None = ("organization_0001", "identity_0002")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCOPE_TABLES = (
    ("enterprise_groups", "enterprise_group"),
    ("legal_entities", "legal_entity"),
    ("companies", "company"),
    ("org_units", "org_unit"),
    ("regions", "region"),
    ("operating_sites", "operating_site"),
    ("warehouses", "warehouse"),
    ("financial_dimensions", "financial_dimension"),
)


def upgrade() -> None:
    op.add_column(
        "assignments",
        sa.Column("principal_type", sa.String(length=30), server_default="user", nullable=False),
        schema="platform_org",
    )
    op.create_check_constraint(
        "assignment_principal_type",
        "assignments",
        "principal_type IN ('user','service_account','device')",
        schema="platform_org",
    )
    op.add_column(
        "delegated_scopes",
        sa.Column(
            "recipient_principal_type",
            sa.String(length=30),
            server_default="user",
            nullable=False,
        ),
        schema="platform_org",
    )
    op.add_column(
        "delegated_scopes",
        sa.Column(
            "grantor_principal_type",
            sa.String(length=30),
            server_default="user",
            nullable=False,
        ),
        schema="platform_org",
    )
    op.create_check_constraint(
        "delegation_recipient_principal_type",
        "delegated_scopes",
        "recipient_principal_type IN ('user','service_account','device')",
        schema="platform_org",
    )
    op.create_check_constraint(
        "delegation_grantor_principal_type",
        "delegated_scopes",
        "grantor_principal_type IN ('user','service_account','device')",
        schema="platform_org",
    )
    op.execute(
        """
        CREATE FUNCTION platform_org.scope_exists(
          checked_tenant_id uuid,
          checked_scope_type text,
          checked_scope_id uuid
        ) RETURNS boolean LANGUAGE plpgsql STABLE AS $$
        BEGIN
          IF checked_scope_type = 'enterprise_group' THEN
            RETURN EXISTS (SELECT 1 FROM platform_org.enterprise_groups
              WHERE tenant_id = checked_tenant_id AND id = checked_scope_id);
          ELSIF checked_scope_type = 'legal_entity' THEN
            RETURN EXISTS (SELECT 1 FROM platform_org.legal_entities
              WHERE tenant_id = checked_tenant_id AND id = checked_scope_id);
          ELSIF checked_scope_type = 'company' THEN
            RETURN EXISTS (SELECT 1 FROM platform_org.companies
              WHERE tenant_id = checked_tenant_id AND id = checked_scope_id);
          ELSIF checked_scope_type = 'org_unit' THEN
            RETURN EXISTS (SELECT 1 FROM platform_org.org_units
              WHERE tenant_id = checked_tenant_id AND id = checked_scope_id);
          ELSIF checked_scope_type = 'region' THEN
            RETURN EXISTS (SELECT 1 FROM platform_org.regions
              WHERE tenant_id = checked_tenant_id AND id = checked_scope_id);
          ELSIF checked_scope_type = 'operating_site' THEN
            RETURN EXISTS (SELECT 1 FROM platform_org.operating_sites
              WHERE tenant_id = checked_tenant_id AND id = checked_scope_id);
          ELSIF checked_scope_type = 'warehouse' THEN
            RETURN EXISTS (SELECT 1 FROM platform_org.warehouses
              WHERE tenant_id = checked_tenant_id AND id = checked_scope_id);
          ELSIF checked_scope_type = 'financial_dimension' THEN
            RETURN EXISTS (SELECT 1 FROM platform_org.financial_dimensions
              WHERE tenant_id = checked_tenant_id AND id = checked_scope_id);
          END IF;
          RETURN false;
        END $$
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM platform_org.assignments AS assignment
            WHERE NOT platform_identity.principal_exists(
              assignment.tenant_id, assignment.principal_type, assignment.principal_id
            ) OR NOT platform_org.scope_exists(
              assignment.tenant_id, assignment.scope_type, assignment.scope_id
            )
          ) THEN
            RAISE EXCEPTION 'existing assignments contain invalid tenant references'
              USING ERRCODE = '23503';
          END IF;
          IF EXISTS (
            SELECT 1 FROM platform_org.delegated_scopes AS delegation
            WHERE NOT platform_identity.principal_exists(
              delegation.tenant_id,
              delegation.recipient_principal_type,
              delegation.recipient_principal_id
            ) OR NOT platform_identity.principal_exists(
              delegation.tenant_id,
              delegation.grantor_principal_type,
              delegation.grantor_principal_id
            ) OR NOT platform_org.scope_exists(
              delegation.tenant_id, delegation.scope_type, delegation.scope_id
            )
          ) THEN
            RAISE EXCEPTION 'existing delegations contain invalid tenant references'
              USING ERRCODE = '23503';
          END IF;
        END $$
        """
    )
    op.drop_constraint("assignment_identity", "assignments", schema="platform_org", type_="unique")
    op.execute(
        """
        WITH ranked AS (
          SELECT id, row_number() OVER (
            PARTITION BY tenant_id, principal_type, principal_id, scope_type, scope_id, valid_from
            ORDER BY created_at, id
          ) AS position
          FROM platform_org.assignments
        )
        DELETE FROM platform_org.assignments AS assignment
        USING ranked
        WHERE assignment.id = ranked.id AND ranked.position > 1
        """
    )
    op.create_unique_constraint(
        "assignment_identity",
        "assignments",
        ("tenant_id", "principal_type", "principal_id", "scope_type", "scope_id", "valid_from"),
        schema="platform_org",
        postgresql_nulls_not_distinct=True,
    )
    op.execute(
        """
        CREATE FUNCTION platform_org.validate_grant_references()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT platform_org.scope_exists(NEW.tenant_id, NEW.scope_type, NEW.scope_id) THEN
            RAISE EXCEPTION 'tenant organization scope does not exist' USING ERRCODE = '23503';
          END IF;
          IF TG_TABLE_NAME = 'assignments' THEN
            IF NOT platform_identity.principal_exists(
              NEW.tenant_id, NEW.principal_type, NEW.principal_id
            ) THEN
              RAISE EXCEPTION 'tenant assignment principal does not exist'
                USING ERRCODE = '23503';
            END IF;
          ELSE
            IF NOT platform_identity.principal_exists(
              NEW.tenant_id, NEW.recipient_principal_type, NEW.recipient_principal_id
            ) OR NOT platform_identity.principal_exists(
              NEW.tenant_id, NEW.grantor_principal_type, NEW.grantor_principal_id
            ) THEN
              RAISE EXCEPTION 'tenant delegation principal does not exist'
                USING ERRCODE = '23503';
            END IF;
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION platform_org.protect_scope_references()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          scope_kind text := TG_ARGV[0];
        BEGIN
          IF EXISTS (
            SELECT 1 FROM platform_org.assignments
            WHERE tenant_id = OLD.tenant_id AND scope_type = scope_kind AND scope_id = OLD.id
          ) OR EXISTS (
            SELECT 1 FROM platform_org.delegated_scopes
            WHERE tenant_id = OLD.tenant_id AND scope_type = scope_kind AND scope_id = OLD.id
          ) THEN
            RAISE EXCEPTION 'organization scope is referenced by grants'
              USING ERRCODE = '23001';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION platform_org.protect_principal_grants()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          principal_kind text := TG_ARGV[0];
        BEGIN
          IF EXISTS (
            SELECT 1 FROM platform_org.assignments
            WHERE tenant_id = OLD.tenant_id AND principal_type = principal_kind
              AND principal_id = OLD.id
          ) OR EXISTS (
            SELECT 1 FROM platform_org.delegated_scopes
            WHERE tenant_id = OLD.tenant_id AND (
              (recipient_principal_type = principal_kind AND recipient_principal_id = OLD.id) OR
              (grantor_principal_type = principal_kind AND grantor_principal_id = OLD.id)
            )
          ) THEN
            RAISE EXCEPTION 'principal is referenced by organization grants'
              USING ERRCODE = '23001';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER assignments_validate_references
        BEFORE INSERT OR UPDATE OF tenant_id, principal_type, principal_id, scope_type, scope_id
        ON platform_org.assignments
        FOR EACH ROW EXECUTE FUNCTION platform_org.validate_grant_references()
        """
    )
    op.execute(
        """
        CREATE TRIGGER delegated_scopes_validate_references
        BEFORE INSERT OR UPDATE OF tenant_id, recipient_principal_type,
          recipient_principal_id, grantor_principal_type, grantor_principal_id,
          scope_type, scope_id
        ON platform_org.delegated_scopes
        FOR EACH ROW EXECUTE FUNCTION platform_org.validate_grant_references()
        """
    )
    for table, scope_type in _SCOPE_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_protect_grant_references "
            f"BEFORE DELETE OR UPDATE OF tenant_id, id ON platform_org.{table} "
            "FOR EACH ROW EXECUTE FUNCTION "
            f"platform_org.protect_scope_references('{scope_type}')"
        )
    for table, principal_type in (
        ("users", "user"),
        ("service_accounts", "service_account"),
        ("devices", "device"),
    ):
        op.execute(
            f"CREATE TRIGGER {table}_protect_organization_grants "
            f"BEFORE DELETE OR UPDATE OF tenant_id, id ON platform_identity.{table} "
            "FOR EACH ROW EXECUTE FUNCTION "
            f"platform_org.protect_principal_grants('{principal_type}')"
        )


def downgrade() -> None:
    for table in ("users", "service_accounts", "devices"):
        op.execute(
            f"DROP TRIGGER IF EXISTS {table}_protect_organization_grants "
            f"ON platform_identity.{table}"
        )
    for table, _scope_type in _SCOPE_TABLES:
        op.execute(
            f"DROP TRIGGER IF EXISTS {table}_protect_grant_references ON platform_org.{table}"
        )
    op.execute(
        "DROP TRIGGER IF EXISTS delegated_scopes_validate_references "
        "ON platform_org.delegated_scopes"
    )
    op.execute("DROP TRIGGER IF EXISTS assignments_validate_references ON platform_org.assignments")
    op.execute("DROP FUNCTION IF EXISTS platform_org.protect_principal_grants()")
    op.execute("DROP FUNCTION IF EXISTS platform_org.protect_scope_references()")
    op.execute("DROP FUNCTION IF EXISTS platform_org.validate_grant_references()")
    op.execute("DROP FUNCTION IF EXISTS platform_org.scope_exists(uuid, text, uuid)")
    op.drop_constraint("assignment_identity", "assignments", schema="platform_org", type_="unique")
    op.execute(
        """
        WITH ranked AS (
          SELECT id, row_number() OVER (
            PARTITION BY tenant_id, principal_id, scope_type, scope_id, valid_from
            ORDER BY created_at, id
          ) AS position
          FROM platform_org.assignments
        )
        DELETE FROM platform_org.assignments AS assignment
        USING ranked
        WHERE assignment.id = ranked.id AND ranked.position > 1
        """
    )
    op.create_unique_constraint(
        "assignment_identity",
        "assignments",
        ("tenant_id", "principal_id", "scope_type", "scope_id", "valid_from"),
        schema="platform_org",
    )
    op.drop_constraint(
        "delegation_grantor_principal_type",
        "delegated_scopes",
        schema="platform_org",
        type_="check",
    )
    op.drop_constraint(
        "delegation_recipient_principal_type",
        "delegated_scopes",
        schema="platform_org",
        type_="check",
    )
    op.drop_column("delegated_scopes", "grantor_principal_type", schema="platform_org")
    op.drop_column("delegated_scopes", "recipient_principal_type", schema="platform_org")
    op.drop_constraint(
        "assignment_principal_type", "assignments", schema="platform_org", type_="check"
    )
    op.drop_column("assignments", "principal_type", schema="platform_org")
