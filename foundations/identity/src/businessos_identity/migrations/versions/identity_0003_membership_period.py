"""Enforce a strict half-open membership period.

Revision ID: identity_0003
Revises: identity_0002
"""

from collections.abc import Sequence

from alembic import op

revision: str = "identity_0003"
down_revision: str | Sequence[str] | None = "identity_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # An empty historical interval cannot be interpreted as a valid membership.
    # Fail visibly rather than silently repairing authorization data.
    op.drop_constraint("ck_memberships_membership_dates", "memberships", schema="platform_identity")
    op.create_check_constraint(
        "membership_dates",
        "memberships",
        "valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from",
        schema="platform_identity",
    )


def downgrade() -> None:
    op.drop_constraint("ck_memberships_membership_dates", "memberships", schema="platform_identity")
    op.create_check_constraint(
        "membership_dates",
        "memberships",
        "valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from",
        schema="platform_identity",
    )
