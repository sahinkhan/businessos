"""Register installation workloads without making them tenant principals.

Revision ID: identity_0004
Revises: identity_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "identity_0004"
down_revision: str | Sequence[str] | None = "identity_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "platform_identity"
TABLE = "installation_workloads"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("installation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workload_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("process_class", sa.String(100), nullable=False),
        sa.Column("allowed_purposes", postgresql.ARRAY(sa.String(100)), nullable=False),
        sa.Column("credential_reference", sa.String(500), nullable=False),
        sa.Column("credential_digest", postgresql.BYTEA(), nullable=False),
        sa.Column("credential_generation", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("rotated_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("installation_id", "workload_id", name="pk_installation_workloads"),
        sa.UniqueConstraint("installation_id", "name", name="uq_installation_workload_name"),
        sa.CheckConstraint("credential_generation > 0", name="workload_generation_positive"),
        sa.CheckConstraint("octet_length(credential_digest) = 32", name="workload_digest_sha256"),
        sa.CheckConstraint("cardinality(allowed_purposes) > 0", name="workload_purpose_nonempty"),
        schema=SCHEMA,
    )
    op.execute(f"REVOKE ALL ON TABLE {SCHEMA}.{TABLE} FROM PUBLIC, businessos_app")
    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO businessos_ops")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {SCHEMA}.{TABLE} TO businessos_ops")
    # The application role can only ask Identity to hold a specific active
    # workload row. It cannot enumerate or mutate installation authority.
    op.execute(
        """
        CREATE FUNCTION platform_identity.admit_workload(
            p_installation uuid, p_workload uuid, p_generation bigint,
            p_process_class text, p_purpose text
        ) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
        BEGIN
          PERFORM 1 FROM platform_identity.installation_workloads
          WHERE installation_id = p_installation AND workload_id = p_workload
            AND active AND revoked_at IS NULL
            AND credential_generation = p_generation
            AND process_class = p_process_class
            AND p_purpose = ANY(allowed_purposes)
          FOR SHARE;
          RETURN FOUND;
        END;
        $$
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION platform_identity.admit_workload("
        "uuid, uuid, bigint, text, text) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION platform_identity.admit_workload("
        "uuid, uuid, bigint, text, text) TO businessos_app, businessos_ops"
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {SCHEMA}.{TABLE})")).scalar_one():
        raise RuntimeError("Cannot downgrade Identity workload registry while workloads exist")
    op.execute("DROP FUNCTION platform_identity.admit_workload(uuid, uuid, bigint, text, text)")
    op.drop_table(TABLE, schema=SCHEMA)
