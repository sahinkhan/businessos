"""Create the external proof module schema.

Revision ID: proof_0001
Revises: 0001_phase1_kernel
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "proof_0001"
down_revision: str | Sequence[str] | None = "0001_phase1_kernel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS mod_example_phase1_proof")
    op.create_table(
        "proof_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_proof_records"),
        schema="mod_example_phase1_proof",
    )
    op.create_index(
        "ix_proof_records_tenant_id",
        "proof_records",
        ["tenant_id"],
        schema="mod_example_phase1_proof",
    )
    op.execute("ALTER TABLE mod_example_phase1_proof.proof_records ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY proof_records_tenant_isolation "
        "ON mod_example_phase1_proof.proof_records "
        "USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_proof_records_tenant_id",
        table_name="proof_records",
        schema="mod_example_phase1_proof",
    )
    op.drop_table("proof_records", schema="mod_example_phase1_proof")
    op.execute("DROP SCHEMA IF EXISTS mod_example_phase1_proof")
