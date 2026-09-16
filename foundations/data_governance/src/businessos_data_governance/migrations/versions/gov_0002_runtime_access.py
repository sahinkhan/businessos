"""Grant tenant-isolated runtime access to governance storage.

Revision ID: gov_0002
Revises: gov_0001
"""

from collections.abc import Sequence

from alembic import op

revision: str = "gov_0002"
down_revision: str | Sequence[str] | None = "gov_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "platform_gov"


def upgrade() -> None:
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
