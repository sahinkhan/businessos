"""Governed Metadata-owned custom entities and additive type identity.

Revision ID: metadata_0002_custom_entities
Revises: metadata_0001
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "metadata_0002_custom_entities"
down_revision: str | Sequence[str] | None = "metadata_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Ordinary resource identities keep the exact original uniqueness. Only
    # custom_entity definitions use their immutable definition UUID as type ID.
    op.execute(
        "ALTER TABLE platform_metadata.definitions DROP CONSTRAINT uq_metadata_definition_identity"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_metadata_definition_identity ON platform_metadata.definitions "
        "(tenant_id, resource_namespace, kind) WHERE kind <> 'custom_entity'"
    )
    op.execute(
        "ALTER TABLE platform_metadata.definitions DROP CONSTRAINT ck_definitions_ck_metadata_kind"
    )
    op.execute(
        "ALTER TABLE platform_metadata.definitions ADD CONSTRAINT ck_definitions_ck_metadata_kind "
        "CHECK (kind IN ('field_set','reference_set','custom_entity'))"
    )
    op.execute(
        "ALTER TABLE platform_metadata.definitions ADD CONSTRAINT "
        "ck_metadata_custom_entity_identity "
        "CHECK ((kind = 'custom_entity') = "
        "(resource_namespace = 'foundation.metadata.custom_entity') "
        "AND (kind <> 'custom_entity' OR (owner_module_id = 'foundation.metadata' "
        "AND owner_contract_version = '1')))"
    )
    op.execute(
        "ALTER TABLE platform_metadata.revisions ADD CONSTRAINT uq_metadata_revision_pin "
        "UNIQUE (tenant_id, definition_id, id, digest)"
    )
    op.execute("""
        CREATE TABLE platform_metadata.custom_entities (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL,
            definition_id UUID NOT NULL,
            revision_id UUID NOT NULL,
            revision_digest VARCHAR(64) NOT NULL,
            lifecycle VARCHAR(20) NOT NULL,
            scope_kind VARCHAR(30) NOT NULL,
            scope_id UUID NOT NULL,
            value_version BIGINT NOT NULL,
            value_document JSONB NOT NULL,
            created_by UUID NOT NULL,
            updated_by UUID NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            archived_at TIMESTAMPTZ,
            CONSTRAINT fk_metadata_custom_entity_pin
              FOREIGN KEY (tenant_id, definition_id, revision_id, revision_digest)
              REFERENCES platform_metadata.revisions (tenant_id, definition_id, id, digest)
              ON DELETE RESTRICT,
            CONSTRAINT ck_metadata_custom_entity_version CHECK (value_version > 0),
            CONSTRAINT ck_metadata_custom_entity_digest CHECK (revision_digest ~ '^[a-f0-9]{64}$'),
            CONSTRAINT ck_metadata_custom_entity_lifecycle
              CHECK (lifecycle IN ('current','archived')),
            CONSTRAINT ck_metadata_custom_entity_archive
              CHECK ((lifecycle = 'archived') = (archived_at IS NOT NULL)),
            CONSTRAINT ck_metadata_custom_entity_scope CHECK (
              scope_kind IN ('tenant','company','enterprise_group','legal_entity','business_unit',
                'division','department','team','region','operating_site','warehouse',
                'cost_center','profit_center','project') AND
              (scope_kind <> 'tenant' OR scope_id = tenant_id)),
            CONSTRAINT ck_metadata_custom_entity_document CHECK (
              jsonb_typeof(value_document) = 'object' AND
              octet_length(value_document::text) <= 1048576)
        )
    """)
    op.execute(
        "CREATE INDEX ix_metadata_custom_entity_type_scope ON platform_metadata.custom_entities "
        "(tenant_id, definition_id, scope_kind, scope_id, id)"
    )
    op.execute(
        "CREATE INDEX ix_metadata_custom_entity_lifecycle ON platform_metadata.custom_entities "
        "(tenant_id, definition_id, lifecycle, id)"
    )
    op.execute("ALTER TABLE platform_metadata.custom_entities ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE platform_metadata.custom_entities FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY custom_entities_tenant ON platform_metadata.custom_entities "
        "TO businessos_metadata USING "
        "(tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)"
    )
    op.execute(
        "CREATE POLICY custom_entities_migration ON platform_metadata.custom_entities "
        "TO businessos_migrator USING (true) WITH CHECK (true)"
    )
    op.execute(
        "REVOKE ALL ON platform_metadata.custom_entities FROM PUBLIC, "
        "businessos_app, businessos_worker, businessos_ops"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON platform_metadata.custom_entities TO businessos_metadata"
    )
    op.execute("""
        CREATE FUNCTION platform_metadata.check_custom_entity_envelope() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'custom entity destruction requires separately certified recovery';
          END IF;
          IF NOT EXISTS (SELECT 1 FROM platform_metadata.definitions d
            WHERE d.tenant_id=NEW.tenant_id AND d.id=NEW.definition_id
              AND d.kind='custom_entity') THEN
            RAISE EXCEPTION 'custom entity requires exact same-tenant entity type';
          END IF;
          IF TG_OP = 'INSERT' AND (NEW.value_version <> 1 OR NEW.lifecycle <> 'current') THEN
            RAISE EXCEPTION 'invalid custom entity initial state';
          END IF;
          IF TG_OP = 'UPDATE' THEN
            IF (NEW.id,NEW.tenant_id,NEW.definition_id,NEW.scope_kind,NEW.scope_id,
                NEW.created_by,NEW.created_at) IS DISTINCT FROM
               (OLD.id,OLD.tenant_id,OLD.definition_id,OLD.scope_kind,OLD.scope_id,
                OLD.created_by,OLD.created_at) THEN
              RAISE EXCEPTION 'custom entity identity and scope are immutable';
            END IF;
            IF OLD.lifecycle <> 'current' OR OLD.value_version = 9223372036854775807
                OR NEW.value_version <> OLD.value_version + 1 THEN
              RAISE EXCEPTION 'invalid custom entity concurrency or lifecycle';
            END IF;
            IF NEW.lifecycle='archived' AND
                (NEW.revision_id,NEW.revision_digest,NEW.value_document) IS DISTINCT FROM
                (OLD.revision_id,OLD.revision_digest,OLD.value_document) THEN
              RAISE EXCEPTION 'archive must retain exact schema and values';
            END IF;
          END IF;
          RETURN NEW;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER custom_entity_envelope BEFORE INSERT OR UPDATE OR DELETE "
        "ON platform_metadata.custom_entities FOR EACH ROW "
        "EXECUTE FUNCTION platform_metadata.check_custom_entity_envelope()"
    )
    op.execute("""
        CREATE FUNCTION platform_metadata.check_definition_identity() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
          IF (NEW.id,NEW.tenant_id,NEW.owner_module_id,NEW.resource_namespace,
              NEW.owner_contract_version,NEW.kind) IS DISTINCT FROM
             (OLD.id,OLD.tenant_id,OLD.owner_module_id,OLD.resource_namespace,
              OLD.owner_contract_version,OLD.kind) THEN
            RAISE EXCEPTION 'metadata definition identity is immutable';
          END IF;
          RETURN NEW;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER definition_identity BEFORE UPDATE ON platform_metadata.definitions "
        "FOR EACH ROW EXECUTE FUNCTION platform_metadata.check_definition_identity()"
    )
    # Invoker-security functions are reachable only as triggers. No definer or
    # ordinary caller gains a read/write path into protected Metadata tables.
    op.execute(
        "REVOKE ALL ON FUNCTION platform_metadata.check_custom_entity_envelope() FROM PUBLIC"
    )
    op.execute("REVOKE ALL ON FUNCTION platform_metadata.check_definition_identity() FROM PUBLIC")


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        text(
            "LOCK TABLE platform_metadata.definitions, platform_metadata.custom_entities "
            "IN ACCESS EXCLUSIVE MODE"
        )
    )
    if connection.execute(text("SELECT 1 FROM platform_metadata.custom_entities LIMIT 1")).first():
        raise RuntimeError("metadata_0002 downgrade refused: retained custom entity instances")
    if connection.execute(
        text("SELECT 1 FROM platform_metadata.definitions WHERE kind='custom_entity' LIMIT 1")
    ).first():
        raise RuntimeError("metadata_0002 downgrade refused: retained custom entity types")
    # All refusal checks precede every destructive statement.
    op.execute("DROP TABLE platform_metadata.custom_entities")
    op.execute("DROP FUNCTION platform_metadata.check_custom_entity_envelope()")
    op.execute("DROP TRIGGER definition_identity ON platform_metadata.definitions")
    op.execute("DROP FUNCTION platform_metadata.check_definition_identity()")
    op.execute("ALTER TABLE platform_metadata.revisions DROP CONSTRAINT uq_metadata_revision_pin")
    op.execute(
        "ALTER TABLE platform_metadata.definitions DROP CONSTRAINT "
        "ck_metadata_custom_entity_identity"
    )
    op.execute(
        "ALTER TABLE platform_metadata.definitions DROP CONSTRAINT ck_definitions_ck_metadata_kind"
    )
    op.execute(
        "ALTER TABLE platform_metadata.definitions ADD CONSTRAINT ck_definitions_ck_metadata_kind "
        "CHECK (kind IN ('field_set','reference_set'))"
    )
    op.execute("DROP INDEX platform_metadata.uq_metadata_definition_identity")
    op.execute(
        "ALTER TABLE platform_metadata.definitions ADD CONSTRAINT uq_metadata_definition_identity "
        "UNIQUE (tenant_id, resource_namespace, kind)"
    )
