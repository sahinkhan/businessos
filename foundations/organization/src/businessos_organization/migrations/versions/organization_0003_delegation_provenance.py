"""Add explicit, tenant-bound delegation provenance and revocation.

Revision ID: organization_0003
Revises: organization_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "organization_0003"
down_revision: str | Sequence[str] | None = "organization_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "platform_org"


def upgrade() -> None:
    op.add_column(
        "delegated_scopes", sa.Column("authority_source_kind", sa.String(20)), schema=SCHEMA
    )
    op.add_column(
        "delegated_scopes",
        sa.Column("parent_delegation_id", postgresql.UUID(as_uuid=True)),
        schema=SCHEMA,
    )
    op.add_column(
        "delegated_scopes", sa.Column("revoked_at", sa.DateTime(timezone=True)), schema=SCHEMA
    )
    op.add_column(
        "delegated_scopes",
        sa.Column("revoked_by_principal_id", postgresql.UUID(as_uuid=True)),
        schema=SCHEMA,
    )
    op.add_column(
        "delegated_scopes", sa.Column("revoked_by_principal_type", sa.String(30)), schema=SCHEMA
    )
    op.add_column("delegated_scopes", sa.Column("revocation_reason", sa.Text()), schema=SCHEMA)
    op.add_column(
        "delegated_scopes", sa.Column("revocation_correlation_id", sa.String(200)), schema=SCHEMA
    )
    op.create_unique_constraint(
        "delegated_scope_tenant_id", "delegated_scopes", ["tenant_id", "id"], schema=SCHEMA
    )
    op.create_foreign_key(
        "delegated_scope_parent_tenant",
        "delegated_scopes",
        "delegated_scopes",
        ["tenant_id", "parent_delegation_id"],
        ["tenant_id", "id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
    )
    op.create_check_constraint(
        "delegated_scope_source",
        "delegated_scopes",
        "authority_source_kind IS NULL OR "
        "(authority_source_kind = 'direct' AND parent_delegation_id IS NULL) OR "
        "(authority_source_kind = 'delegation' AND parent_delegation_id IS NOT NULL)",
        schema=SCHEMA,
    )
    op.create_index(
        "ix_org_delegation_parent",
        "delegated_scopes",
        ["tenant_id", "parent_delegation_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_org_delegation_grantor",
        "delegated_scopes",
        ["tenant_id", "grantor_principal_type", "grantor_principal_id"],
        schema=SCHEMA,
    )
    op.execute(
        """
        CREATE FUNCTION platform_org.guard_delegation_provenance() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.authority_source_kind IS NOT NULL AND (
            NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR
            NEW.authority_source_kind IS DISTINCT FROM OLD.authority_source_kind OR
            NEW.parent_delegation_id IS DISTINCT FROM OLD.parent_delegation_id OR
            NEW.grantor_principal_id IS DISTINCT FROM OLD.grantor_principal_id OR
            NEW.grantor_principal_type IS DISTINCT FROM OLD.grantor_principal_type OR
            NEW.recipient_principal_id IS DISTINCT FROM OLD.recipient_principal_id OR
            NEW.recipient_principal_type IS DISTINCT FROM OLD.recipient_principal_type OR
            NEW.scope_type IS DISTINCT FROM OLD.scope_type OR
            NEW.scope_id IS DISTINCT FROM OLD.scope_id OR
            NEW.allowed_actions IS DISTINCT FROM OLD.allowed_actions OR
            NEW.valid_from IS DISTINCT FROM OLD.valid_from OR
            NEW.valid_until IS DISTINCT FROM OLD.valid_until
          ) THEN
            RAISE EXCEPTION 'verified delegation provenance is immutable';
          END IF;
          RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        "CREATE TRIGGER delegated_scope_provenance_immutable "
        "BEFORE UPDATE ON platform_org.delegated_scopes "
        "FOR EACH ROW EXECUTE FUNCTION platform_org.guard_delegation_provenance()"
    )
    # Deliberately do not infer provenance for old grants. NULL source means
    # legacy_unverified and is unusable until operator-reviewed reconciliation.


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM platform_org.delegated_scopes WHERE "
                "authority_source_kind IS NOT NULL OR parent_delegation_id IS NOT NULL "
                "OR revoked_at IS NOT NULL OR revoked_by_principal_id IS NOT NULL "
                "OR revoked_by_principal_type IS NOT NULL OR revocation_reason IS NOT NULL "
                "OR revocation_correlation_id IS NOT NULL LIMIT 1"
            )
        )
        .first()
        is not None
    ):
        raise RuntimeError("Provenance-bearing grants require operator-reviewed downgrade")
    op.execute("DROP TRIGGER delegated_scope_provenance_immutable ON platform_org.delegated_scopes")
    op.execute("DROP FUNCTION platform_org.guard_delegation_provenance()")
    op.drop_index("ix_org_delegation_grantor", table_name="delegated_scopes", schema=SCHEMA)
    op.drop_index("ix_org_delegation_parent", table_name="delegated_scopes", schema=SCHEMA)
    op.drop_constraint("delegated_scope_source", "delegated_scopes", schema=SCHEMA, type_="check")
    op.drop_constraint(
        "delegated_scope_parent_tenant", "delegated_scopes", schema=SCHEMA, type_="foreignkey"
    )
    op.drop_constraint(
        "delegated_scope_tenant_id", "delegated_scopes", schema=SCHEMA, type_="unique"
    )
    for column in (
        "revocation_correlation_id",
        "revocation_reason",
        "revoked_by_principal_type",
        "revoked_by_principal_id",
        "revoked_at",
        "parent_delegation_id",
        "authority_source_kind",
    ):
        op.drop_column("delegated_scopes", column, schema=SCHEMA)
