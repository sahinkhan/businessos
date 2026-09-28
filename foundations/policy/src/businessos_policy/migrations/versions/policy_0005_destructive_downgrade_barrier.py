"""Mark certified Policy authority as a forward-only security boundary.

Revision ID: policy_0005
Revises: policy_0004
"""

from collections.abc import Sequence

revision: str = "policy_0005"
down_revision: str | Sequence[str] | None = "policy_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The revision itself records the forward-only boundary; historical Policy
    # revisions and their certified fingerprints remain untouched.
    pass


def downgrade() -> None:
    raise RuntimeError(
        "policy_0005 downgrade refused: certified Policy authority and SoD "
        "protection require reviewed restore or forward repair"
    )
