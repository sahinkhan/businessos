"""Mark certified Audit evidence as a forward-only security boundary.

Revision ID: audit_0005
Revises: audit_0004
"""

from collections.abc import Sequence

revision: str = "audit_0005"
down_revision: str | Sequence[str] | None = "audit_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The revision itself records the forward-only boundary; historical Audit
    # revisions and their certified fingerprints remain untouched.
    pass


def downgrade() -> None:
    raise RuntimeError(
        "audit_0005 downgrade refused: certified Audit evidence and append-only "
        "protection require reviewed restore or forward repair"
    )
