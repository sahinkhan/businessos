"""Restrict workload admission to the dedicated worker and operations roles.

Revision ID: identity_0005
Revises: identity_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "identity_0005"
down_revision: str | Sequence[str] | None = "identity_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FUNCTION = "platform_identity.admit_workload(uuid, uuid, bigint, text, text)"


def upgrade() -> None:
    # The worker role is provisioned by the administrator's role transition.
    # No ordinary application session may acquire the authority row lock.
    op.execute(f"REVOKE EXECUTE ON FUNCTION {_FUNCTION} FROM businessos_app")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_FUNCTION} TO businessos_worker")


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM platform_identity.installation_workloads)")
    ).scalar_one():
        raise RuntimeError("Cannot downgrade worker admission role while workloads exist")
    # Preserve app-role denial even while stepping back through the unmerged
    # identity_0004 candidate. Its next downgrade drops the empty registry.
    op.execute(f"REVOKE EXECUTE ON FUNCTION {_FUNCTION} FROM businessos_worker")
