"""Extend module inventory with immutable revision graph facts.

Revision ID: 0003_migration_graph_inventory
Revises: 0002_module_migration_inventory
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_migration_graph_inventory"
down_revision: str | Sequence[str] | None = "0002_module_migration_inventory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "installed_module_migrations",
        sa.Column(
            "distribution_identity",
            sa.String(length=255),
            nullable=False,
            server_default="legacy:unknown",
        ),
        schema="platform_module",
    )
    op.add_column(
        "installed_module_migrations",
        sa.Column("inventory_format", sa.Integer(), nullable=False, server_default="1"),
        schema="platform_module",
    )
    op.add_column(
        "installed_module_migrations",
        sa.Column(
            "revision_manifest",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        schema="platform_module",
    )


def downgrade() -> None:
    op.drop_column("installed_module_migrations", "revision_manifest", schema="platform_module")
    op.drop_column("installed_module_migrations", "inventory_format", schema="platform_module")
    op.drop_column("installed_module_migrations", "distribution_identity", schema="platform_module")
