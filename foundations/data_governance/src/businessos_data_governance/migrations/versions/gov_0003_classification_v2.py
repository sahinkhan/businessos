"""Add qualified classification storage and close global runtime DML.

Revision ID: gov_0003
Revises: gov_0002

Legacy rows are deliberately left in place. Conversion requires a separately
reviewed mapping; this revision never guesses their provenance.
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "gov_0003"
down_revision: str | Sequence[str] | None = "gov_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "platform_gov"
CANONICAL = ("classification_definitions", "classification_versions")
TENANT = (
    "tenant_classifications",
    "tenant_classification_versions",
    "classification_overlays",
)


def _controls(table: str) -> tuple[sa.Column[Any] | sa.CheckConstraint, ...]:
    return (
        sa.Column("sensitivity_level", sa.Integer(), nullable=False),
        sa.Column("required_controls", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("restrictions", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("allowed_audience", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("mandatory_masking", sa.Boolean(), nullable=False),
        sa.CheckConstraint("sensitivity_level BETWEEN 1 AND 5", name=f"ck_{table}_sensitivity"),
    )


def _interval(table: str) -> tuple[sa.Column[Any] | sa.CheckConstraint, ...]:
    return (
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from", name=f"ck_{table}_interval"
        ),
    )


def _isolate(table: str) -> None:
    expression = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    qualified = f"{SCHEMA}.{table}"
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


def upgrade() -> None:
    # A legacy code cannot be declared canonical or tenant-owned by inspection.
    # Deployment must run the bounded read-only preflight and reviewed conversion
    # before certifying any existing legacy data. This additive revision is safe
    # for dirty data and immediately closes the global write privilege.
    op.execute(
        f"REVOKE INSERT, UPDATE, DELETE ON {SCHEMA}.data_classifications FROM businessos_app"
    )

    op.create_table(
        "classification_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("qualified_ref", sa.String(55), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.CheckConstraint("code ~ '^[A-Z][A-Z0-9_]{1,49}$'", name="ck_core_code"),
        sa.CheckConstraint("qualified_ref = 'core:' || code", name="ck_core_ref"),
        schema=SCHEMA,
    )
    op.create_table(
        "classification_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "definition_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{SCHEMA}.classification_definitions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        *_interval("core_versions"),
        *_controls("core_versions"),
        sa.UniqueConstraint("definition_id", "version", name="uq_core_definition_version"),
        sa.CheckConstraint("version > 0", name="ck_core_version_positive"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_classification_versions_effective",
        "classification_versions",
        ["definition_id", "valid_from", "valid_until"],
        schema=SCHEMA,
    )

    op.create_table(
        "tenant_classifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("qualified_ref", sa.String(100), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "canonical_base_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{SCHEMA}.classification_definitions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_tenant_definition_identity"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_tenant_definition_code"),
        sa.UniqueConstraint("tenant_id", "qualified_ref", name="uq_tenant_definition_ref"),
        sa.CheckConstraint("code ~ '^[A-Z][A-Z0-9_]{1,49}$'", name="ck_tenant_code"),
        sa.CheckConstraint(
            "qualified_ref = 'tenant:' || tenant_id::text || ':' || code",
            name="ck_tenant_ref",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "tenant_classification_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("definition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        *_interval("tenant_versions"),
        *_controls("tenant_versions"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "definition_id"],
            [f"{SCHEMA}.tenant_classifications.tenant_id", f"{SCHEMA}.tenant_classifications.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id", "definition_id", "version", name="uq_tenant_definition_version"
        ),
        sa.CheckConstraint("version > 0", name="ck_tenant_version_positive"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_tenant_classification_versions_effective",
        "tenant_classification_versions",
        ["tenant_id", "definition_id", "valid_from", "valid_until"],
        schema=SCHEMA,
    )
    op.create_table(
        "classification_overlays",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "canonical_definition_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{SCHEMA}.classification_definitions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        *_interval("overlays"),
        *_controls("overlays"),
        sa.UniqueConstraint(
            "tenant_id", "canonical_definition_id", "version", name="uq_tenant_overlay_version"
        ),
        sa.CheckConstraint("version > 0", name="ck_overlay_version_positive"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_classification_overlays_effective",
        "classification_overlays",
        ["tenant_id", "canonical_definition_id", "valid_from", "valid_until"],
        schema=SCHEMA,
    )

    op.create_table(
        "classification_legacy_mappings",
        sa.Column(
            "legacy_code",
            sa.String(50),
            sa.ForeignKey(f"{SCHEMA}.data_classifications.code", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("qualified_ref", sa.String(100), nullable=False),
        sa.Column("definition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("legacy_name", sa.String(100), nullable=False),
        sa.Column("legacy_sensitivity_level", sa.Integer(), nullable=False),
        sa.Column("legacy_description_sha256", sa.String(64), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_by", sa.String(200), nullable=False),
        sa.Column("evidence_reference", sa.Text(), nullable=False),
        sa.Column("tenant_provenance", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "length(approved_by) > 0 AND length(evidence_reference) > 0",
            name="ck_legacy_mapping_evidence",
        ),
        sa.CheckConstraint(
            "legacy_description_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_legacy_mapping_description_sha256",
        ),
        sa.CheckConstraint(
            "tenant_id IS NULL OR "
            "(tenant_provenance IS NOT NULL AND length(tenant_provenance) > 0)",
            name="ck_legacy_mapping_tenant_provenance",
        ),
        schema=SCHEMA,
    )

    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        "ALTER TABLE platform_gov.classification_versions ADD CONSTRAINT "
        "ex_classification_versions_effective EXCLUDE USING gist "
        "(definition_id WITH =, tstzrange(valid_from, valid_until, '[)') WITH &&)"
    )
    op.execute(
        "ALTER TABLE platform_gov.tenant_classification_versions ADD CONSTRAINT "
        "ex_tenant_classification_versions_effective EXCLUDE USING gist "
        "(tenant_id WITH =, definition_id WITH =, "
        "tstzrange(valid_from, valid_until, '[)') WITH &&)"
    )
    op.execute(
        "ALTER TABLE platform_gov.classification_overlays ADD CONSTRAINT "
        "ex_classification_overlays_effective EXCLUDE USING gist "
        "(tenant_id WITH =, canonical_definition_id WITH =, "
        "tstzrange(valid_from, valid_until, '[)') WITH &&)"
    )
    op.execute(
        "CREATE FUNCTION platform_gov.classification_identity_guard() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN "
        "PERFORM pg_advisory_xact_lock(hashtextextended('classification:' || NEW.code, 0)); "
        "IF TG_TABLE_NAME = 'classification_definitions' THEN "
        "PERFORM pg_advisory_xact_lock("
        "hashtextextended('classification-core:' || NEW.code, 0)); END IF; "
        "IF TG_OP = 'UPDATE' THEN "
        "IF NEW.id <> OLD.id OR NEW.code <> OLD.code OR "
        "NEW.qualified_ref <> OLD.qualified_ref THEN "
        "RAISE EXCEPTION 'classification identity is immutable'; END IF; "
        "IF TG_TABLE_NAME = 'tenant_classifications' THEN "
        "IF NEW.tenant_id <> OLD.tenant_id OR "
        "NEW.canonical_base_id IS DISTINCT FROM OLD.canonical_base_id THEN "
        "RAISE EXCEPTION 'classification identity is immutable'; END IF; END IF; "
        "END IF; "
        "IF TG_TABLE_NAME = 'tenant_classifications' AND "
        "EXISTS (SELECT 1 FROM platform_gov.classification_definitions "
        "WHERE code = NEW.code) THEN "
        "RAISE EXCEPTION 'tenant classification shadows canonical code'; END IF; "
        "IF TG_TABLE_NAME = 'classification_definitions' AND "
        "EXISTS (SELECT 1 FROM platform_gov.tenant_classifications "
        "WHERE code = NEW.code) THEN "
        "RAISE EXCEPTION 'canonical code collides with tenant classification'; END IF; "
        "RETURN NEW; END $$"
    )
    for table in ("classification_definitions", "tenant_classifications"):
        op.execute(
            f"CREATE TRIGGER {table}_identity_guard BEFORE INSERT OR UPDATE ON "
            f"{SCHEMA}.{table} FOR EACH ROW EXECUTE FUNCTION "
            f"{SCHEMA}.classification_identity_guard()"
        )
    op.execute(
        "CREATE FUNCTION platform_gov.classification_canonical_version_lock() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE canonical_code text; BEGIN "
        "SELECT code INTO STRICT canonical_code FROM platform_gov.classification_definitions "
        "WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.definition_id "
        "ELSE NEW.definition_id END; "
        "PERFORM pg_advisory_xact_lock(hashtextextended("
        "'classification-core:' || canonical_code, 0)); "
        "IF TG_OP = 'DELETE' THEN RETURN OLD; END IF; RETURN NEW; END $$"
    )
    op.execute(
        "CREATE TRIGGER classification_versions_canonical_lock "
        "BEFORE INSERT OR UPDATE OR DELETE ON platform_gov.classification_versions "
        "FOR EACH ROW EXECUTE FUNCTION platform_gov.classification_canonical_version_lock()"
    )
    op.execute(
        "CREATE FUNCTION platform_gov.classification_version_guard() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN "
        "IF TG_OP = 'DELETE' THEN "
        "RAISE EXCEPTION 'classification history cannot be deleted'; END IF; "
        "IF to_jsonb(NEW) - 'valid_until' <> to_jsonb(OLD) - 'valid_until' "
        "OR OLD.valid_until IS NOT NULL OR NEW.valid_until IS NULL "
        "OR NEW.valid_until <= OLD.valid_from THEN "
        "RAISE EXCEPTION 'classification semantic version is immutable'; END IF; "
        "RETURN NEW; END $$"
    )
    for table in (
        "classification_versions",
        "tenant_classification_versions",
        "classification_overlays",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_version_guard BEFORE UPDATE OR DELETE ON "
            f"{SCHEMA}.{table} FOR EACH ROW EXECUTE FUNCTION "
            f"{SCHEMA}.classification_version_guard()"
        )
    for table in ("classification_definitions", "tenant_classifications"):
        op.execute(
            f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {SCHEMA}.{table} "
            "FOR EACH ROW EXECUTE FUNCTION platform_gov.classification_version_guard()"
        )

    for table in TENANT:
        _isolate(table)
    op.execute(f"ALTER TABLE {SCHEMA}.classification_legacy_mappings ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.classification_legacy_mappings FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY classification_legacy_mappings_runtime_read ON "
        f"{SCHEMA}.classification_legacy_mappings FOR SELECT TO businessos_app "
        "USING (tenant_id IS NULL OR "
        "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)"
    )
    op.execute(
        f"CREATE POLICY classification_legacy_mappings_migration_access ON "
        f"{SCHEMA}.classification_legacy_mappings TO businessos_migrator "
        "USING (true) WITH CHECK (true)"
    )
    for table in CANONICAL:
        op.execute(f"REVOKE ALL ON {SCHEMA}.{table} FROM businessos_app")
        op.execute(f"GRANT SELECT ON {SCHEMA}.{table} TO businessos_app")
    for table in TENANT:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {SCHEMA}.{table} TO businessos_app")
    # The mapping is operator-owned evidence, never an ordinary app write surface.
    op.execute(f"REVOKE ALL ON {SCHEMA}.classification_legacy_mappings FROM businessos_app")
    op.execute(f"GRANT SELECT ON {SCHEMA}.classification_legacy_mappings TO businessos_app")

    for table in ("retention_policies", "sensitive_field_tags"):
        op.alter_column(table, "classification_code", nullable=True, schema=SCHEMA)
        op.add_column(table, sa.Column("classification_ref", sa.String(100)), schema=SCHEMA)
        op.add_column(table, sa.Column("classification_version", sa.Integer()), schema=SCHEMA)
        op.add_column(
            table,
            sa.Column("classification_definition_id", postgresql.UUID(as_uuid=True)),
            schema=SCHEMA,
        )
        op.create_index(
            f"ix_{table}_classification_v2",
            table,
            ["tenant_id", "classification_ref", "classification_version"],
            schema=SCHEMA,
        )
        op.create_check_constraint(
            f"ck_{table}_classification_reference_present",
            table,
            "classification_code IS NOT NULL OR classification_ref IS NOT NULL",
            schema=SCHEMA,
        )


def downgrade() -> None:
    connection = op.get_bind()
    checks = (
        (
            "classification_definitions",
            "SELECT 1 FROM platform_gov.classification_definitions LIMIT 1",
        ),
        ("tenant_classifications", "SELECT 1 FROM platform_gov.tenant_classifications LIMIT 1"),
        ("classification_overlays", "SELECT 1 FROM platform_gov.classification_overlays LIMIT 1"),
        (
            "classification_legacy_mappings",
            "SELECT 1 FROM platform_gov.classification_legacy_mappings LIMIT 1",
        ),
        (
            "retention_policies",
            "SELECT 1 FROM platform_gov.retention_policies "
            "WHERE classification_ref IS NOT NULL LIMIT 1",
        ),
        (
            "sensitive_field_tags",
            "SELECT 1 FROM platform_gov.sensitive_field_tags "
            "WHERE classification_ref IS NOT NULL LIMIT 1",
        ),
    )
    for label, sql in checks:
        if connection.execute(sa.text(sql)).first() is not None:
            raise RuntimeError(
                f"gov_0003 downgrade refused: {label} contains V2 data; "
                "retain this revision and use reviewed operator recovery"
            )
    # Even an empty V2 schema cannot restore the earlier global tenant-write
    # privilege safely. Refuse before any destructive DDL.
    raise RuntimeError(
        "gov_0003 downgrade refused: gov_0002 grants unsafe global classification DML; "
        "retain this revision and use reviewed operator recovery"
    )
