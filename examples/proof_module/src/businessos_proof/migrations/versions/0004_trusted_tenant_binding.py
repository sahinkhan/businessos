"""Use independently authenticated tenant identity for proof-owned data."""

from alembic import op

revision = "proof_0004"
down_revision = "proof_0003"
branch_labels = None
depends_on = "0006_trusted_tenant_binding"


def upgrade() -> None:
    op.execute(
        "ALTER POLICY proof_records_tenant_isolation ON mod_example_phase1_proof.proof_records "
        "USING (tenant_id = platform_security.current_tenant_id()) "
        "WITH CHECK (tenant_id = platform_security.current_tenant_id())"
    )


def downgrade() -> None:
    op.execute(
        "ALTER POLICY proof_records_tenant_isolation ON mod_example_phase1_proof.proof_records "
        "USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)"
    )
