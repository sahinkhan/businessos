"""Metadata definitions, immutable revisions and shared module publication fence.

Revision ID: metadata_0001
Revises: gov_0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "metadata_0001"
down_revision: str | Sequence[str] | None = "gov_0005"
branch_labels: str | Sequence[str] | None = ("foundation_metadata",)
depends_on: str | Sequence[str] | None = None

SCHEMA = "platform_metadata"
TENANT_TABLES = ("definitions", "revisions", "revision_module_bindings")
TENANT_MATCH = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def _isolate(table: str) -> None:
    qualified = f"{SCHEMA}.{table}"
    op.execute(f"ALTER TABLE {qualified} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {qualified} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_tenant ON {qualified} TO businessos_app "
        f"USING ({TENANT_MATCH}) WITH CHECK ({TENANT_MATCH})"
    )
    op.execute(
        f"CREATE POLICY {table}_migration ON {qualified} TO businessos_migrator "
        "USING (true) WITH CHECK (true)"
    )
    op.execute(f"REVOKE ALL ON {qualified} FROM PUBLIC, businessos_worker, businessos_ops")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {qualified} TO businessos_app")


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    op.execute(f"REVOKE ALL ON SCHEMA {SCHEMA} FROM PUBLIC")
    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO businessos_app")
    op.create_table(
        "module_fence",
        sa.Column("module_id", sa.String(150), primary_key=True),
        sa.Column("artifact_identity", sa.String(200), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("active_bindings", sa.BigInteger(), nullable=False, server_default="0"),
        sa.CheckConstraint("generation > 0", name="ck_metadata_module_generation"),
        sa.CheckConstraint("active_bindings >= 0", name="ck_metadata_active_bindings"),
        schema=SCHEMA,
    )
    op.execute(
        f"REVOKE ALL ON {SCHEMA}.module_fence FROM PUBLIC, businessos_worker, businessos_ops"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {SCHEMA}.module_fence TO businessos_app")
    op.create_table(
        "contract_fence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("schema_generation", sa.BigInteger(), nullable=False),
        sa.Column("ui_generation", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_metadata_contract_singleton"),
        sa.CheckConstraint(
            "schema_generation > 0 AND ui_generation > 0", name="ck_metadata_contract_generations"
        ),
        schema=SCHEMA,
    )
    op.execute(
        f"INSERT INTO {SCHEMA}.contract_fence (id, schema_generation, ui_generation) "
        "VALUES (1, 1, 1)"
    )
    op.execute(
        f"REVOKE ALL ON {SCHEMA}.contract_fence FROM PUBLIC, businessos_worker, businessos_ops"
    )
    # PostgreSQL row locks require UPDATE privilege on at least one column.
    # The singleton key is constrained to 1; ordinary app code cannot alter generations.
    op.execute(f"GRANT SELECT, UPDATE (id) ON {SCHEMA}.contract_fence TO businessos_app")
    op.create_table(
        "definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_module_id", sa.String(150), nullable=False),
        sa.Column("resource_namespace", sa.String(200), nullable=False),
        sa.Column("owner_contract_version", sa.String(30), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("lifecycle", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("draft_generation", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("draft_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("active_revision_id", postgresql.UUID(as_uuid=True)),
        sa.Column("active_generation", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("kind IN ('field_set','reference_set')", name="ck_metadata_kind"),
        sa.CheckConstraint(
            "lifecycle IN ('draft','published','retired')", name="ck_metadata_lifecycle"
        ),
        sa.CheckConstraint(
            "draft_generation > 0 AND active_generation >= 0",
            name="ck_metadata_definition_generations",
        ),
        sa.UniqueConstraint(
            "tenant_id", "resource_namespace", "kind", name="uq_metadata_definition_identity"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_metadata_definition_tenant_id"),
        schema=SCHEMA,
    )
    op.create_table(
        "revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("definition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("schema_generation", sa.BigInteger(), nullable=False),
        sa.Column("ui_generation", sa.BigInteger(), nullable=False),
        sa.Column("published_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "published_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("provenance", sa.String(200), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "definition_id"],
            [f"{SCHEMA}.definitions.tenant_id", f"{SCHEMA}.definitions.id"],
            ondelete="RESTRICT",
            name="fk_metadata_revision_definition_tenant",
        ),
        sa.UniqueConstraint(
            "tenant_id", "definition_id", "sequence", name="uq_metadata_revision_sequence"
        ),
        sa.UniqueConstraint(
            "tenant_id", "definition_id", "id", name="uq_metadata_revision_active_target"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_metadata_revision_tenant_id"),
        sa.CheckConstraint(
            "sequence > 0 AND schema_generation > 0 AND ui_generation > 0",
            name="ck_metadata_revision_generations",
        ),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_metadata_active_revision_tenant",
        "definitions",
        "revisions",
        ["tenant_id", "id", "active_revision_id"],
        ["tenant_id", "definition_id", "id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_table(
        "revision_module_bindings",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module_id", sa.String(150), nullable=False),
        sa.Column("artifact_identity", sa.String(200), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "revision_id"],
            [f"{SCHEMA}.revisions.tenant_id", f"{SCHEMA}.revisions.id"],
            ondelete="RESTRICT",
            name="fk_metadata_binding_revision_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["module_id"],
            [f"{SCHEMA}.module_fence.module_id"],
            ondelete="RESTRICT",
            name="fk_metadata_binding_module",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "revision_id", "module_id"),
        sa.CheckConstraint("generation > 0", name="ck_metadata_binding_generation"),
        schema=SCHEMA,
    )
    for table in TENANT_TABLES:
        _isolate(table)
    # Revisions and their dependency snapshots are append-only even for a role
    # with UPDATE privileges on ordinary draft state. Historical rollback only
    # changes the definition's active pointer.
    op.execute(
        "CREATE FUNCTION platform_metadata.reject_revision_mutation() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'published metadata history is immutable'; "
        "END $$"
    )
    for table in ("revisions", "revision_module_bindings"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {SCHEMA}.{table} "
            "FOR EACH ROW EXECUTE FUNCTION platform_metadata.reject_revision_mutation()"
        )
    # The counter is maintained in the same transaction as every pointer
    # change. Module lifecycle checks it under the same row lock.
    op.execute(
        "CREATE FUNCTION platform_metadata.adjust_active_bindings() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ DECLARE item RECORD; changed_count integer; BEGIN "
        "IF TG_OP = 'UPDATE' AND NEW.active_revision_id IS NOT DISTINCT FROM "
        "OLD.active_revision_id "
        "THEN RETURN NEW; END IF; "
        "IF TG_OP = 'UPDATE' AND OLD.active_revision_id IS NOT NULL THEN "
        "FOR item IN SELECT module_id, artifact_identity, generation FROM "
        "platform_metadata.revision_module_bindings WHERE tenant_id = OLD.tenant_id "
        "AND revision_id = OLD.active_revision_id ORDER BY module_id LOOP "
        "UPDATE platform_metadata.module_fence SET active_bindings = active_bindings - 1 "
        "WHERE module_id = item.module_id AND artifact_identity = item.artifact_identity "
        "AND generation = item.generation AND active_bindings > 0; "
        "GET DIAGNOSTICS changed_count = ROW_COUNT; "
        "IF changed_count <> 1 THEN RAISE EXCEPTION 'stale metadata binding'; END IF; "
        "END LOOP; END IF; "
        "IF NEW.active_revision_id IS NOT NULL THEN "
        "FOR item IN SELECT module_id, artifact_identity, generation FROM "
        "platform_metadata.revision_module_bindings WHERE tenant_id = NEW.tenant_id "
        "AND revision_id = NEW.active_revision_id ORDER BY module_id LOOP "
        "UPDATE platform_metadata.module_fence SET active_bindings = active_bindings + 1 "
        "WHERE module_id = item.module_id AND artifact_identity = item.artifact_identity "
        "AND generation = item.generation; "
        "GET DIAGNOSTICS changed_count = ROW_COUNT; "
        "IF changed_count <> 1 THEN RAISE EXCEPTION 'stale metadata binding'; END IF; "
        "END LOOP; END IF; RETURN NEW; END $$"
    )
    op.execute(
        "CREATE TRIGGER definitions_active_bindings AFTER INSERT OR UPDATE OF active_revision_id "
        "ON platform_metadata.definitions FOR EACH ROW "
        "EXECUTE FUNCTION platform_metadata.adjust_active_bindings()"
    )


def downgrade() -> None:
    raise RuntimeError(
        "metadata_0001 downgrade refused: immutable published revisions and module "
        "compatibility evidence require reviewed operator recovery"
    )
