"""Add canonical principal types to organization grants.

Revision ID: organization_0002
Revises: organization_0001, identity_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "organization_0002"
down_revision: str | Sequence[str] | None = ("organization_0001", "identity_0002")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "assignments",
        sa.Column("principal_type", sa.String(length=30), server_default="user", nullable=False),
        schema="platform_org",
    )
    op.create_check_constraint(
        "assignment_principal_type",
        "assignments",
        "principal_type IN ('user','service_account','device')",
        schema="platform_org",
    )
    op.add_column(
        "delegated_scopes",
        sa.Column(
            "recipient_principal_type",
            sa.String(length=30),
            server_default="user",
            nullable=False,
        ),
        schema="platform_org",
    )
    op.create_check_constraint(
        "delegation_recipient_principal_type",
        "delegated_scopes",
        "recipient_principal_type IN ('user','service_account','device')",
        schema="platform_org",
    )


def downgrade() -> None:
    op.drop_constraint(
        "delegation_recipient_principal_type",
        "delegated_scopes",
        schema="platform_org",
        type_="check",
    )
    op.drop_column("delegated_scopes", "recipient_principal_type", schema="platform_org")
    op.drop_constraint(
        "assignment_principal_type",
        "assignments",
        schema="platform_org",
        type_="check",
    )
    op.drop_column("assignments", "principal_type", schema="platform_org")
