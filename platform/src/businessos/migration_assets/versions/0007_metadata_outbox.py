"""Permit protected Metadata commands to append to the transactional outbox.

Revision ID: 0007_metadata_outbox
Revises: 0006_governance_outbox
"""

from collections.abc import Sequence

from alembic import op

from businessos.migration_assets.metadata_role import assert_metadata_role_safe

revision: str = "0007_metadata_outbox"
down_revision: str | Sequence[str] | None = "0006_governance_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    assert_metadata_role_safe(op.get_bind())
    expression = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    op.execute("GRANT USAGE ON SCHEMA eventing TO businessos_metadata")
    op.execute("GRANT SELECT, INSERT ON eventing.outbox_messages TO businessos_metadata")
    op.execute("ALTER TABLE eventing.outbox_messages ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE eventing.outbox_messages FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY outbox_messages_metadata_tenant ON eventing.outbox_messages "
        f"TO businessos_metadata USING ({expression}) WITH CHECK ({expression})"
    )


def downgrade() -> None:
    op.execute("DROP POLICY outbox_messages_metadata_tenant ON eventing.outbox_messages")
    op.execute("REVOKE SELECT, INSERT ON eventing.outbox_messages FROM businessos_metadata")
    op.execute("REVOKE USAGE ON SCHEMA eventing FROM businessos_metadata")
