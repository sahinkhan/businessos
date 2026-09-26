"""Permit protected Governance commands to append to the transactional outbox.

Revision ID: 0006_governance_outbox
Revises: 0005_durable_event_subscribers
"""

from collections.abc import Sequence

from alembic import op

from businessos.migration_assets.governance_role import assert_governance_role_safe

revision: str = "0006_governance_outbox"
down_revision: str | Sequence[str] | None = "0005_durable_event_subscribers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    assert_governance_role_safe(op.get_bind())
    expression = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    op.execute("GRANT USAGE ON SCHEMA eventing TO businessos_governance")
    op.execute("GRANT SELECT, INSERT ON eventing.outbox_messages TO businessos_governance")
    op.execute("ALTER TABLE eventing.outbox_messages ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE eventing.outbox_messages FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY outbox_messages_governance_tenant ON eventing.outbox_messages "
        f"TO businessos_governance USING ({expression}) WITH CHECK ({expression})"
    )


def downgrade() -> None:
    op.execute("DROP POLICY outbox_messages_governance_tenant ON eventing.outbox_messages")
    op.execute("REVOKE SELECT, INSERT ON eventing.outbox_messages FROM businessos_governance")
    op.execute("REVOKE USAGE ON SCHEMA eventing FROM businessos_governance")
