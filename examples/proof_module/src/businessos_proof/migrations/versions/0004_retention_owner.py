"""Enroll proof records as a governed ADR-018 resource owner.

Revision ID: proof_0004
Revises: proof_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "proof_0004"
down_revision: str | Sequence[str] | None = "proof_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "mod_example_phase1_proof.proof_records"
TENANT = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.add_column(
        "proof_records",
        sa.Column("retention_category", sa.String(100), nullable=False, server_default="proof"),
        schema="mod_example_phase1_proof",
    )
    op.add_column(
        "proof_records",
        sa.Column(
            "retention_anchor_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="mod_example_phase1_proof",
    )
    op.add_column(
        "proof_records",
        sa.Column("lifecycle", sa.String(20), nullable=False, server_default="current"),
        schema="mod_example_phase1_proof",
    )
    op.execute(
        f"UPDATE {TABLE} SET retention_anchor_at = created_at "
        "WHERE retention_anchor_at IS DISTINCT FROM created_at"
    )
    op.create_check_constraint(
        "ck_proof_records_lifecycle",
        "proof_records",
        "lifecycle IN ('current', 'archived', 'anonymized', 'purged')",
        schema="mod_example_phase1_proof",
    )
    op.execute(f"DROP POLICY proof_records_tenant_isolation ON {TABLE}")
    op.execute(
        f"CREATE POLICY proof_records_app_select ON {TABLE} FOR SELECT TO businessos_app "
        f"USING ({TENANT})"
    )
    op.execute(
        f"CREATE POLICY proof_records_app_insert ON {TABLE} FOR INSERT TO businessos_app "
        f"WITH CHECK ({TENANT} AND lifecycle = 'current')"
    )
    op.execute(
        f"CREATE POLICY proof_records_app_update ON {TABLE} FOR UPDATE TO businessos_app "
        f"USING ({TENANT} AND lifecycle = 'current') "
        f"WITH CHECK ({TENANT} AND lifecycle = 'current')"
    )
    op.execute(
        f"CREATE POLICY proof_records_governance_tenant ON {TABLE} "
        f"TO businessos_governance USING ({TENANT}) WITH CHECK ({TENANT})"
    )
    op.execute("GRANT USAGE ON SCHEMA mod_example_phase1_proof TO businessos_governance")
    op.execute(
        f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON {TABLE} "
        "FROM PUBLIC, businessos_app, businessos_worker"
    )
    op.execute(f"GRANT SELECT ON {TABLE} TO businessos_app, businessos_governance")
    op.execute(f"GRANT INSERT (id, tenant_id, command_id, value) ON {TABLE} TO businessos_app")
    op.execute(f"GRANT UPDATE (description) ON {TABLE} TO businessos_app")
    op.execute(f"GRANT UPDATE (lifecycle, value, description) ON {TABLE} TO businessos_governance")


def downgrade() -> None:
    raise RuntimeError(
        "proof_0004 downgrade refused: governed owner lifecycle and grant evidence "
        "requires reviewed operator recovery"
    )
