"""Create metadata definition, immutable revision, active pointer, and fence foundation schema.

Revision ID: meta_0001
Revises: audit_0001
"""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "meta_0001"
down_revision: str | Sequence[str] | None = "audit_0001"
branch_labels: str | Sequence[str] | None = ("foundation_metadata",)
depends_on: str | Sequence[str] | None = None

SCHEMA = "platform_metadata"
TABLES = (
    "metadata_definitions",
    "metadata_revisions",
    "metadata_active_pointers",
    "metadata_publication_fences",
)


def _isolate(table: str) -> None:
    qualified = f"{SCHEMA}.{table}"
    expression = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(f"ALTER TABLE {qualified} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {qualified} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {qualified} TO businessos_app "
        f"USING ({expression}) WITH CHECK ({expression})"
    )
    op.execute(
        f"CREATE POLICY {table}_migration_access ON {qualified} TO businessos_migrator "
        "USING (true) WITH CHECK (true)"
    )
    op.execute(
        f"CREATE POLICY {table}_ops_tenant ON {qualified} TO businessos_ops "
        f"USING ({expression}) WITH CHECK ({expression})"
    )
    op.execute(
        f"CREATE POLICY {table}_worker_tenant ON {qualified} TO businessos_worker "
        f"USING ({expression}) WITH CHECK ({expression})"
    )


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.execute(f"REVOKE ALL ON SCHEMA {SCHEMA} FROM PUBLIC")

    op.create_table(
        "metadata_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_namespace", sa.String(length=100), nullable=False),
        sa.Column("definition_kind", sa.String(length=50), nullable=False),
        sa.Column("stable_key", sa.String(length=100), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=50), nullable=False, server_default="draft"),
        sa.Column("draft_generation", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("draft_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("active_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("active_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "owner_namespace",
            "definition_kind",
            "stable_key",
            name="uq_metadata_definition_key",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_metadata_definitions_tenant_namespace",
        "metadata_definitions",
        ["tenant_id", "owner_namespace"],
        schema=SCHEMA,
    )

    op.create_table(
        "metadata_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("definition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_seq", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=20), nullable=False, server_default="1"),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["definition_id"],
            [f"{SCHEMA}.metadata_definitions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "definition_id", "revision_seq", name="uq_metadata_revision_seq"
        ),
        sa.UniqueConstraint(
            "tenant_id", "definition_id", "content_digest", name="uq_metadata_revision_digest"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_metadata_revisions_tenant_definition",
        "metadata_revisions",
        ["tenant_id", "definition_id"],
        schema=SCHEMA,
    )

    op.create_table(
        "metadata_active_pointers",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("definition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("active_generation", sa.Integer(), nullable=False),
        sa.Column(
            "activated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("activated_by", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(
            ["definition_id"],
            [f"{SCHEMA}.metadata_definitions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            [f"{SCHEMA}.metadata_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "definition_id", name="pk_metadata_active_pointers"),
        schema=SCHEMA,
    )

    op.create_table(
        "metadata_publication_fences",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fence_scope", sa.String(length=100), nullable=False),
        sa.Column("metadata_generation", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("module_base_generation", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("schema_ui_generation", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("dependencies_generation", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "last_fenced_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_fenced_by", sa.String(length=100), nullable=False, server_default="system"
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "fence_scope", name="pk_metadata_publication_fences"
        ),
        schema=SCHEMA,
    )

    for table in TABLES:
        _isolate(table)

    op.execute(
        f"GRANT USAGE ON SCHEMA {SCHEMA} TO businessos_app, businessos_ops, businessos_worker"
    )
    for table in (
        "metadata_definitions",
        "metadata_active_pointers",
        "metadata_publication_fences",
    ):
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {SCHEMA}.{table} "
            "TO businessos_app, businessos_ops, businessos_worker"
        )
    # Revisions are strictly append-only (immutable) for runtime roles
    op.execute(
        f"REVOKE UPDATE, DELETE, TRUNCATE ON {SCHEMA}.metadata_revisions "
        "FROM PUBLIC, businessos_app, businessos_worker, businessos_ops"
    )
    op.execute(
        f"GRANT SELECT, INSERT ON {SCHEMA}.metadata_revisions "
        "TO businessos_app, businessos_ops, businessos_worker"
    )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table, schema=SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
