"""Grant the protected Governance transaction append-only Audit access.

Revision ID: audit_0004
Revises: audit_0003
"""

from collections.abc import Sequence

from alembic import op

from businessos.migration_assets.governance_role import assert_governance_role_safe

revision: str = "audit_0004"
down_revision: str | Sequence[str] | None = "audit_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    assert_governance_role_safe(op.get_bind())
    expression = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    op.execute("GRANT USAGE ON SCHEMA platform_audit TO businessos_governance")
    op.execute("GRANT SELECT, INSERT ON platform_audit.audit_logs TO businessos_governance")
    op.execute("ALTER TABLE platform_audit.audit_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE platform_audit.audit_logs FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY audit_logs_governance_tenant ON platform_audit.audit_logs "
        f"TO businessos_governance USING ({expression}) WITH CHECK ({expression})"
    )


def downgrade() -> None:
    op.execute("DROP POLICY audit_logs_governance_tenant ON platform_audit.audit_logs")
    op.execute("REVOKE SELECT, INSERT ON platform_audit.audit_logs FROM businessos_governance")
    op.execute("REVOKE USAGE ON SCHEMA platform_audit FROM businessos_governance")
