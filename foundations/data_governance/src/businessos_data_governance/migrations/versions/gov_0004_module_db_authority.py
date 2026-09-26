"""Separate legacy destructive authority from the ordinary application role.

Revision ID: gov_0004
Revises: gov_0003
"""

from collections.abc import Sequence

from alembic import op

from businessos.migration_assets.governance_role import (
    assert_governance_role_safe,
    assert_ordinary_governance_write_denied,
)

revision: str = "gov_0004"
down_revision: str | Sequence[str] | None = "gov_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "platform_gov"
TENANT_EXPRESSION = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
PROTECTED = ("retention_policies", "legal_holds")
READ_ONLY = (
    "data_classifications",
    "classification_definitions",
    "classification_versions",
    "tenant_classifications",
    "tenant_classification_versions",
    "classification_overlays",
    "classification_legacy_mappings",
)


def upgrade() -> None:
    assert_governance_role_safe(op.get_bind())
    op.execute("GRANT USAGE ON SCHEMA platform_gov TO businessos_governance")
    for table in PROTECTED:
        qualified = f"{SCHEMA}.{table}"
        op.execute(
            f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON {qualified} "
            "FROM PUBLIC, businessos_app, businessos_worker"
        )
        op.execute(f"GRANT SELECT ON {qualified} TO businessos_app")
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {qualified} TO businessos_governance")
        op.execute(f"ALTER TABLE {qualified} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {qualified} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_governance_tenant ON {qualified} "
            f"TO businessos_governance USING ({TENANT_EXPRESSION}) "
            f"WITH CHECK ({TENANT_EXPRESSION})"
        )
    for table in READ_ONLY:
        op.execute(f"GRANT SELECT ON {SCHEMA}.{table} TO businessos_governance")
    # PostgreSQL requires UPDATE privilege and an UPDATE USING policy for
    # SELECT FOR SHARE. The id-only grant admits row locks; WITH CHECK (false)
    # rejects any actual update of these read-side classification rows.
    for table in (
        "tenant_classifications",
        "tenant_classification_versions",
        "classification_overlays",
    ):
        op.execute(f"GRANT UPDATE (id) ON {SCHEMA}.{table} TO businessos_governance")
        op.execute(
            f"CREATE POLICY {table}_governance_lock ON {SCHEMA}.{table} "
            f"FOR UPDATE TO businessos_governance USING ({TENANT_EXPRESSION}) "
            "WITH CHECK (false)"
        )
    for table in (
        "tenant_classifications",
        "tenant_classification_versions",
        "classification_overlays",
    ):
        op.execute(
            f"CREATE POLICY {table}_governance_tenant ON {SCHEMA}.{table} "
            f"FOR SELECT TO businessos_governance USING ({TENANT_EXPRESSION})"
        )
    op.execute(
        "CREATE POLICY classification_legacy_mappings_governance_read ON "
        "platform_gov.classification_legacy_mappings FOR SELECT TO businessos_governance "
        f"USING (tenant_id IS NULL OR {TENANT_EXPRESSION})"
    )
    assert_ordinary_governance_write_denied(op.get_bind())


def downgrade() -> None:
    raise RuntimeError(
        "gov_0004 downgrade refused: restoring ordinary direct retention/hold mutation "
        "requires reviewed operator recovery"
    )
