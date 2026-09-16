"""Harden Phase 4 authorization scope and record policy storage.

Revision ID: policy_0002
Revises: policy_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "policy_0002"
down_revision: str | Sequence[str] | None = "policy_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "platform_policy"


def upgrade() -> None:
    op.create_unique_constraint("uq_roles_tenant_id", "roles", ["tenant_id", "id"], schema=SCHEMA)
    for table in (
        "role_permissions",
        "subject_role_assignments",
        "field_policies",
        "approval_limits",
        "delegations",
    ):
        op.create_foreign_key(
            f"fk_{table}_tenant_role",
            table,
            "roles",
            ["tenant_id", "role_id"],
            ["tenant_id", "id"],
            source_schema=SCHEMA,
            referent_schema=SCHEMA,
            ondelete="CASCADE",
        )
    op.create_foreign_key(
        "fk_roles_tenant_parent",
        "roles",
        "roles",
        ["tenant_id", "parent_role_id"],
        ["tenant_id", "id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_permissions_no_global_wildcard", "permissions", "code <> '*'", schema=SCHEMA
    )
    op.create_check_constraint(
        "ck_subject_role_scope",
        "subject_role_assignments",
        "(scope_type = 'tenant' AND scope_id IS NULL) OR "
        "(scope_type IN ('company', 'legal_entity', 'operating_site', 'business_unit') "
        "AND scope_id IS NOT NULL)",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_subject_role_window",
        "subject_role_assignments",
        "valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_delegation_window", "delegations", "valid_to > valid_from", schema=SCHEMA
    )
    op.create_check_constraint(
        "ck_delegation_distinct_subjects",
        "delegations",
        "delegator_id <> delegatee_id",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_delegation_scope",
        "delegations",
        "(scope_type = 'tenant' AND scope_id IS NULL) OR "
        "(scope_type IN ('company', 'legal_entity', 'operating_site', 'business_unit') "
        "AND scope_id IS NOT NULL)",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_approval_authority_target",
        "approval_limits",
        "role_id IS NOT NULL OR subject_id IS NOT NULL",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_approval_window",
        "approval_limits",
        "valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from",
        schema=SCHEMA,
    )

    op.create_table(
        "support_access_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("support_principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("valid_to > valid_from", name="ck_support_access_window"),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )

    op.create_table(
        "record_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("access_scope", sa.String(length=30), nullable=False),
        sa.Column("condition_expression", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "access_scope IN ('all', 'owned', 'organization', 'deny')",
            name="ck_record_policy_access_scope",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "role_id"],
            [f"{SCHEMA}.roles.tenant_id", f"{SCHEMA}.roles.id"],
            name="fk_record_policies_tenant_role",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    expression = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    for table in ("support_access_grants", "record_policies"):
        op.execute(f"ALTER TABLE {SCHEMA}.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {SCHEMA}.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {SCHEMA}.{table} "
            f"TO businessos_app USING ({expression}) WITH CHECK ({expression})"
        )
        op.execute(
            f"CREATE POLICY {table}_migration_access ON {SCHEMA}.{table} "
            "TO businessos_migrator USING (true) WITH CHECK (true)"
        )
    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO businessos_app")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {SCHEMA} TO businessos_app"
    )


def downgrade() -> None:
    op.execute(
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {SCHEMA} "
        "FROM businessos_app"
    )
    op.execute(f"REVOKE USAGE ON SCHEMA {SCHEMA} FROM businessos_app")
    op.drop_table("record_policies", schema=SCHEMA)
    op.drop_table("support_access_grants", schema=SCHEMA)
    for name, table in (
        ("ck_approval_window", "approval_limits"),
        ("ck_approval_authority_target", "approval_limits"),
        ("ck_delegation_scope", "delegations"),
        ("ck_delegation_distinct_subjects", "delegations"),
        ("ck_delegation_window", "delegations"),
        ("ck_subject_role_window", "subject_role_assignments"),
        ("ck_subject_role_scope", "subject_role_assignments"),
        ("ck_permissions_no_global_wildcard", "permissions"),
    ):
        op.drop_constraint(name, table, schema=SCHEMA, type_="check")
    op.drop_constraint("fk_roles_tenant_parent", "roles", schema=SCHEMA, type_="foreignkey")
    for table in reversed(
        (
            "role_permissions",
            "subject_role_assignments",
            "field_policies",
            "approval_limits",
            "delegations",
        )
    ):
        op.drop_constraint(f"fk_{table}_tenant_role", table, schema=SCHEMA, type_="foreignkey")
    op.drop_constraint("uq_roles_tenant_id", "roles", schema=SCHEMA, type_="unique")
