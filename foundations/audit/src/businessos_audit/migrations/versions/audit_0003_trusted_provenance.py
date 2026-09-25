"""Add trusted V2 provenance and source-event uniqueness.

Revision ID: audit_0003
Revises: audit_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "audit_0003"
down_revision: str | Sequence[str] | None = "audit_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "platform_audit"
TABLE = "audit_logs"


def upgrade() -> None:
    op.add_column(
        TABLE, sa.Column("provenance_v3", postgresql.JSONB(), nullable=True), schema=SCHEMA
    )
    op.add_column(TABLE, sa.Column("evidence_v3", postgresql.JSONB(), nullable=True), schema=SCHEMA)
    op.add_column(
        TABLE,
        sa.Column("source_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(TABLE, sa.Column("projection_kind", sa.String(50), nullable=True), schema=SCHEMA)
    op.create_index(
        "uq_audit_v3_source_projection",
        TABLE,
        ["tenant_id", "source_event_id", "projection_kind"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("source_event_id IS NOT NULL"),
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.{TABLE} ADD CONSTRAINT audit_v3_provenance_complete "
        "CHECK (integrity_version <> '3' OR "
        "(provenance_v3 IS NOT NULL AND evidence_v3 IS NOT NULL))"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.{TABLE} ADD CONSTRAINT audit_v3_source_projection_pair "
        "CHECK ((source_event_id IS NULL) = (projection_kind IS NULL))"
    )


def downgrade() -> None:
    connection = op.get_bind()
    count = connection.execute(
        sa.text(f"SELECT count(*) FROM {SCHEMA}.{TABLE} WHERE integrity_version = '3'")
    ).scalar_one()
    if count:
        raise RuntimeError("Cannot downgrade Audit V3 with existing trusted evidence")
    op.execute(f"ALTER TABLE {SCHEMA}.{TABLE} DROP CONSTRAINT audit_v3_source_projection_pair")
    op.execute(f"ALTER TABLE {SCHEMA}.{TABLE} DROP CONSTRAINT audit_v3_provenance_complete")
    op.drop_index("uq_audit_v3_source_projection", table_name=TABLE, schema=SCHEMA)
    for column in ("projection_kind", "source_event_id", "evidence_v3", "provenance_v3"):
        op.drop_column(TABLE, column, schema=SCHEMA)
