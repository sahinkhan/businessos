"""Add owner-controlled Party-root custom values; Metadata references are logical only."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "party_0003_custom_fields"
down_revision: str | Sequence[str] | None = "party_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
SCHEMA = "platform_party"


def upgrade() -> None:
    op.create_table(
        "custom_values",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("party_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("definition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_digest", sa.String(64), nullable=False),
        sa.Column("value_version", sa.BigInteger(), nullable=False),
        sa.Column("value_document", postgresql.JSONB(), nullable=False),
        sa.Column("cleared", sa.Boolean(), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "party_id"],
            [f"{SCHEMA}.parties.tenant_id", f"{SCHEMA}.parties.id"],
            name="fk_party_custom_values_tenant",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("value_version > 0", name="ck_party_custom_version"),
        sa.CheckConstraint("revision_digest ~ '^[a-f0-9]{64}$'", name="ck_party_custom_digest"),
        sa.CheckConstraint(
            "jsonb_typeof(value_document) = 'object' "
            "AND octet_length(value_document::text) <= 131072",
            name="ck_party_custom_document",
        ),
        sa.CheckConstraint(
            "NOT cleared OR value_document = '{}'::jsonb", name="ck_party_custom_clear"
        ),
        schema=SCHEMA,
    )
    qualified = f"{SCHEMA}.custom_values"
    tenant = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(f"ALTER TABLE {qualified} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {qualified} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY custom_values_tenant_isolation ON {qualified} TO businessos_app "
        f"USING ({tenant}) WITH CHECK ({tenant})"
    )
    op.execute(
        f"CREATE POLICY custom_values_migration_access ON {qualified} TO businessos_migrator "
        "USING (true) WITH CHECK (true)"
    )
    op.execute(
        f"REVOKE ALL ON {qualified} FROM PUBLIC, businessos_metadata, "
        "businessos_governance, businessos_ops"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {qualified} TO businessos_app")


def downgrade() -> None:
    # No implicit loss of retained owner data, including clear-version tombstones.
    if (
        op.get_bind()
        .execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {SCHEMA}.custom_values)"))
        .scalar_one()
    ):
        raise RuntimeError("Party custom values exist; destructive downgrade is prohibited")
    op.drop_table("custom_values", schema=SCHEMA)
