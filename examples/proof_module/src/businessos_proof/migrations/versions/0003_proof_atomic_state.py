"""Add command idempotency to proof state.

Revision ID: proof_0003
Revises: proof_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "proof_0003"
down_revision: str | Sequence[str] | None = "proof_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "proof_records",
        sa.Column("command_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="mod_example_phase1_proof",
    )
    op.add_column(
        "proof_records",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="mod_example_phase1_proof",
    )
    op.execute(
        "UPDATE mod_example_phase1_proof.proof_records "
        "SET command_id = gen_random_uuid() WHERE command_id IS NULL"
    )
    op.alter_column(
        "proof_records",
        "command_id",
        nullable=False,
        schema="mod_example_phase1_proof",
    )
    op.create_unique_constraint(
        "uq_proof_records_tenant_command",
        "proof_records",
        ["tenant_id", "command_id"],
        schema="mod_example_phase1_proof",
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_proof_records_tenant_command",
        "proof_records",
        schema="mod_example_phase1_proof",
        type_="unique",
    )
    op.drop_column(
        "proof_records",
        "command_id",
        schema="mod_example_phase1_proof",
    )
    op.drop_column(
        "proof_records",
        "created_at",
        schema="mod_example_phase1_proof",
    )
