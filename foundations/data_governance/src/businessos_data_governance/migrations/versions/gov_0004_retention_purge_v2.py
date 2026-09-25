"""Add explicit retention V2 intervals, holds, and decision evidence.

Revision ID: gov_0004
Revises: gov_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "gov_0004"
down_revision: str | Sequence[str] | None = "gov_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "platform_gov"
TABLES = ("retention_policies_v2", "legal_holds_v2", "destructive_decisions_v2")


def preflight(connection: sa.engine.Connection) -> None:
    """Read-only and bounded: never infer retention category from classification."""
    policies = (
        connection.execute(
            sa.text("SELECT id::text FROM platform_gov.retention_policies ORDER BY id LIMIT 11")
        )
        .scalars()
        .all()
    )
    if policies:
        identifiers = ", ".join(policies[:10])
        more = " (more exist)" if len(policies) > 10 else ""
        raise RuntimeError(
            "gov_0004 preflight: legacy policies need an owner-approved category "
            f"and interval mapping before migration: {identifiers}{more}"
        )
    ambiguous = (
        connection.execute(
            sa.text(
                "SELECT id::text FROM platform_gov.legal_holds "
                "WHERE entity_id IS NOT NULL AND entity_id !~* "
                "'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' "
                "ORDER BY id LIMIT 11"
            )
        )
        .scalars()
        .all()
    )
    if ambiguous:
        identifiers = ", ".join(ambiguous[:10])
        more = " (more exist)" if len(ambiguous) > 10 else ""
        raise RuntimeError(
            "gov_0004 preflight: legacy record holds have noncanonical subject IDs; "
            f"review before migration: {identifiers}{more}"
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
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {qualified} TO businessos_app")


def upgrade() -> None:
    # No DDL occurs until every legacy row has passed deterministic inspection.
    preflight(op.get_bind())
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table(
        "retention_policies_v2",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_module_id", sa.String(150), nullable=False),
        sa.Column("resource_namespace", sa.String(200), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("retention_category", sa.String(100), nullable=False),
        sa.Column("retention_period_days", sa.Integer(), nullable=False),
        sa.Column("action_on_expiry", sa.String(20), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.CheckConstraint("retention_period_days > 0", name="ck_retention_v2_positive_days"),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from", name="ck_retention_v2_interval"
        ),
        sa.CheckConstraint(
            "action_on_expiry IN ('archive','anonymize','purge')", name="ck_retention_v2_action"
        ),
        schema=SCHEMA,
    )
    op.execute(
        "ALTER TABLE platform_gov.retention_policies_v2 ADD CONSTRAINT "
        "ex_retention_v2_effective EXCLUDE USING gist ("
        "tenant_id WITH =, owner_module_id WITH =, resource_namespace WITH =, "
        "entity_type WITH =, retention_category WITH =, "
        "tstzrange(valid_from, valid_until, '[)') WITH &&) WHERE (is_active)"
    )
    op.create_table(
        "legal_holds_v2",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_module_id", sa.String(150), nullable=False),
        sa.Column("resource_namespace", sa.String(200), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("hold_scope", sa.String(10), nullable=False),
        sa.Column("record_id", postgresql.UUID(as_uuid=True)),
        sa.Column("retention_category", sa.String(100)),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.CheckConstraint("reason <> ''", name="ck_hold_v2_reason"),
        sa.CheckConstraint(
            "(hold_scope = 'ALL' AND record_id IS NULL AND retention_category IS NULL) OR "
            "(hold_scope = 'RECORD' AND record_id IS NOT NULL)",
            name="ck_hold_v2_scope",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_legal_holds_v2_applicable",
        "legal_holds_v2",
        [
            "tenant_id",
            "owner_module_id",
            "resource_namespace",
            "entity_type",
            "record_id",
            "retention_category",
        ],
        schema=SCHEMA,
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "destructive_decisions_v2",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_module_id", sa.String(150), nullable=False),
        sa.Column("resource_namespace", sa.String(200), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("external_cleanup_status", sa.String(20), nullable=False),
        sa.CheckConstraint(
            "external_cleanup_status IN ('pending','completed','failed')",
            name="ck_destructive_v2_cleanup_status",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_destructive_decisions_v2_subject",
        "destructive_decisions_v2",
        ["tenant_id", "entity_type", "record_id"],
        schema=SCHEMA,
    )
    for table in TABLES:
        _isolate(table)
    # Legacy category-free holds explicitly mean ALL. Keep their rows and
    # original owner-free scope; V2 checks them conservatively as wildcard.
    op.add_column("legal_holds", sa.Column("hold_scope", sa.String(10)), schema=SCHEMA)
    op.execute(
        "UPDATE platform_gov.legal_holds SET hold_scope = CASE "
        "WHEN entity_id IS NULL THEN 'ALL' ELSE 'RECORD' END"
    )
    op.alter_column("legal_holds", "hold_scope", nullable=False, schema=SCHEMA)
    op.create_check_constraint(
        "ck_legacy_hold_scope",
        "legal_holds",
        "(hold_scope = 'ALL' AND entity_id IS NULL) OR "
        "(hold_scope = 'RECORD' AND entity_id IS NOT NULL)",
        schema=SCHEMA,
    )
    op.create_index(
        "ix_legacy_holds_v2_applicable",
        "legal_holds",
        ["tenant_id", "entity_type", "entity_id"],
        schema=SCHEMA,
        postgresql_where=sa.text("is_active"),
    )


def downgrade() -> None:
    raise RuntimeError(
        "gov_0004 downgrade refused: retention and legal-hold authority evidence "
        "requires reviewed operator recovery"
    )
