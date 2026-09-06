"""Create the installed-module migration inventory.

Revision ID: 0002_module_migration_inventory
Revises: 0001_phase1_kernel
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_module_migration_inventory"
down_revision: str | Sequence[str] | None = "0001_phase1_kernel"
branch_labels: str | Sequence[str] | None = ("businessos_core",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "installed_module_migrations",
        sa.Column("module_id", sa.String(length=200), nullable=False),
        sa.Column("module_version", sa.String(length=50), nullable=False),
        sa.Column("migration_namespace", sa.String(length=200), nullable=False),
        sa.Column("locations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("revision_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("lifecycle_state", sa.String(length=30), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("module_id", name="pk_installed_module_migrations"),
        schema="platform_module",
    )
    op.execute(
        "REVOKE ALL ON platform_module.installed_module_migrations FROM PUBLIC, businessos_app"
    )
    op.execute("GRANT SELECT ON platform_module.installed_module_migrations TO businessos_app")
    op.execute("GRANT SELECT ON platform_module.installed_module_migrations TO businessos_ops")


def downgrade() -> None:
    op.drop_table("installed_module_migrations", schema="platform_module")
