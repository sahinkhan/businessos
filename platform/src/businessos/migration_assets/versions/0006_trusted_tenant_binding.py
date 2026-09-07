"""Bind RLS tenant identity to an independently authenticated login role.

Revision ID: 0006_trusted_tenant_binding
Revises: 0005_durable_event_subscribers
"""

from alembic import op

revision = "0006_trusted_tenant_binding"
down_revision = "0005_durable_event_subscribers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA platform_security AUTHORIZATION businessos_migrator")
    op.execute("REVOKE ALL ON SCHEMA platform_security FROM PUBLIC")
    op.execute(
        "CREATE TABLE platform_security.tenant_database_roles ("
        "role_name NAME PRIMARY KEY, tenant_id UUID NOT NULL)"
    )
    op.execute(
        "CREATE FUNCTION platform_security.current_tenant_id() RETURNS UUID "
        "LANGUAGE SQL STABLE SECURITY DEFINER "
        "SET search_path = pg_catalog, platform_security "
        "AS 'SELECT tenant_id FROM platform_security.tenant_database_roles "
        "WHERE role_name = session_user'"
    )
    op.execute("REVOKE ALL ON FUNCTION platform_security.current_tenant_id() FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA platform_security TO businessos_app")
    op.execute("GRANT EXECUTE ON FUNCTION platform_security.current_tenant_id() TO businessos_app")
    for table in ("outbox_messages", "inbox_receipts"):
        op.execute(
            f"ALTER POLICY {table}_tenant_isolation ON eventing.{table} "
            "USING (tenant_id = platform_security.current_tenant_id()) "
            "WITH CHECK (tenant_id = platform_security.current_tenant_id())"
        )


def downgrade() -> None:
    # Offline maintenance rollback only; downgrading restores uncertified legacy RLS.
    for table in ("outbox_messages", "inbox_receipts"):
        op.execute(
            f"ALTER POLICY {table}_tenant_isolation ON eventing.{table} "
            "USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)"
        )
    op.execute("DROP FUNCTION platform_security.current_tenant_id()")
    op.execute("DROP TABLE platform_security.tenant_database_roles")
    op.execute("DROP SCHEMA platform_security")
