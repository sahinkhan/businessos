"""Add the v2 proof description field.

Revision ID: proof_0002
Revises: proof_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "proof_0002"
down_revision: str | Sequence[str] | None = "proof_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "proof_records",
        sa.Column("description", sa.Text(), nullable=True),
        schema="mod_example_phase1_proof",
    )


def downgrade() -> None:
    op.drop_column("proof_records", "description", schema="mod_example_phase1_proof")
