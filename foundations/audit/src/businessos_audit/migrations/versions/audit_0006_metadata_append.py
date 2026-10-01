"""Permit protected Metadata commands to append to the transactional Audit.

Revision ID: audit_0006
Revises: audit_0005
"""

from collections.abc import Sequence

from alembic import op

from businessos.migration_assets.metadata_role import assert_metadata_role_safe

revision: str = "audit_0006"
down_revision: str | Sequence[str] | None = "audit_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    assert_metadata_role_safe(op.get_bind())
    expression = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    op.execute("GRANT USAGE ON SCHEMA platform_audit TO businessos_metadata")
    op.execute("GRANT SELECT, INSERT ON platform_audit.audit_logs TO businessos_metadata")
    op.execute("ALTER TABLE platform_audit.audit_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE platform_audit.audit_logs FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY audit_logs_metadata_tenant ON platform_audit.audit_logs "
        f"TO businessos_metadata USING ({expression}) WITH CHECK ({expression})"
    )


def downgrade() -> None:
    op.execute("DROP POLICY audit_logs_metadata_tenant ON platform_audit.audit_logs")
    op.execute("REVOKE SELECT, INSERT ON platform_audit.audit_logs FROM businessos_metadata")
    op.execute("REVOKE USAGE ON SCHEMA platform_audit FROM businessos_metadata")
