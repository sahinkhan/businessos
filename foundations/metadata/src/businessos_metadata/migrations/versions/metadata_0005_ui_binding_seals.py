"""Seal complete UI compatibility sets before activation.

Revision ID: metadata_0005_ui_binding_seals
Revises: metadata_0004_ui_bindings
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

from businessos.migration_assets.metadata_role import assert_metadata_role_safe

revision: str = "metadata_0005_ui_binding_seals"
down_revision: str | Sequence[str] | None = "metadata_0004_ui_bindings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    assert_metadata_role_safe(connection)
    op.execute(
        "LOCK TABLE platform_metadata.ui_overlays, platform_metadata.ui_overlay_revisions, "
        "platform_metadata.ui_revision_module_bindings IN ACCESS EXCLUSIVE MODE"
    )
    # The previous candidate did not certify the completeness of retained sets.
    # Neither counters nor current module identities can reconstruct that proof.
    if connection.execute(
        text("SELECT 1 FROM platform_metadata.ui_overlay_revisions LIMIT 1")
    ).first():
        raise RuntimeError("metadata_0005 upgrade refused: unsealed UI revision history")
    # KEY SHARE must protect the compatibility identity, not only module_id.
    # PostgreSQL takes UPDATE for key changes and NO KEY UPDATE for counters.
    op.execute(
        "ALTER TABLE platform_metadata.module_fence ADD CONSTRAINT "
        "uq_module_compatibility_identity UNIQUE (module_id,artifact_identity,generation)"
    )
    op.execute("""
      CREATE TABLE platform_metadata.ui_revision_binding_seals (
        tenant_id UUID NOT NULL, overlay_id UUID NOT NULL, revision_id UUID NOT NULL,
        PRIMARY KEY (tenant_id,revision_id),
        FOREIGN KEY (tenant_id,overlay_id,revision_id)
          REFERENCES platform_metadata.ui_overlay_revisions(tenant_id,overlay_id,id)
          ON DELETE RESTRICT
      );
      ALTER TABLE platform_metadata.ui_revision_binding_seals ENABLE ROW LEVEL SECURITY;
      ALTER TABLE platform_metadata.ui_revision_binding_seals FORCE ROW LEVEL SECURITY;
      CREATE POLICY ui_revision_binding_seals_tenant
        ON platform_metadata.ui_revision_binding_seals TO businessos_metadata
        USING (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)
        WITH CHECK (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
      CREATE POLICY ui_revision_binding_seals_migration
        ON platform_metadata.ui_revision_binding_seals TO businessos_migrator
        USING (true) WITH CHECK (true);
      REVOKE ALL ON platform_metadata.ui_revision_binding_seals
        FROM PUBLIC,businessos_app,businessos_worker,businessos_ops;
      GRANT SELECT,INSERT ON platform_metadata.ui_revision_binding_seals TO businessos_metadata;
      CREATE TRIGGER immutable_ui_binding_seal BEFORE UPDATE OR DELETE
        ON platform_metadata.ui_revision_binding_seals FOR EACH ROW
        EXECUTE FUNCTION platform_metadata.reject_revision_mutation();
    """)
    op.execute("""
      CREATE FUNCTION platform_metadata.check_ui_binding_insert() RETURNS trigger
      LANGUAGE plpgsql AS $$ BEGIN
        PERFORM 1 FROM platform_metadata.ui_overlays
          WHERE tenant_id=NEW.tenant_id AND id=NEW.overlay_id FOR UPDATE;
        IF EXISTS (SELECT 1 FROM platform_metadata.ui_revision_binding_seals
          WHERE tenant_id=NEW.tenant_id AND revision_id=NEW.revision_id)
        THEN RAISE EXCEPTION 'UI binding set is sealed'; END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER check_ui_binding_insert BEFORE INSERT
        ON platform_metadata.ui_revision_module_bindings FOR EACH ROW
        EXECUTE FUNCTION platform_metadata.check_ui_binding_insert();
      REVOKE ALL ON FUNCTION platform_metadata.check_ui_binding_insert() FROM PUBLIC;
    """)
    op.execute("""
      CREATE FUNCTION platform_metadata.check_ui_binding_seal() RETURNS trigger
      LANGUAGE plpgsql AS $$ DECLARE binding_count bigint; BEGIN
        PERFORM 1 FROM platform_metadata.ui_overlays
          WHERE tenant_id=NEW.tenant_id AND id=NEW.overlay_id FOR UPDATE;
        SELECT count(*) INTO binding_count
          FROM platform_metadata.ui_revision_module_bindings
          WHERE tenant_id=NEW.tenant_id AND revision_id=NEW.revision_id;
        IF binding_count NOT BETWEEN 1 AND 128 THEN
          RAISE EXCEPTION 'UI binding set size invalid'; END IF;
        PERFORM f.module_id FROM platform_metadata.module_fence f
          JOIN platform_metadata.ui_revision_module_bindings b ON b.module_id=f.module_id
          WHERE b.tenant_id=NEW.tenant_id AND b.revision_id=NEW.revision_id
          ORDER BY f.module_id FOR KEY SHARE OF f;
        IF EXISTS (
          SELECT 1 FROM platform_metadata.ui_revision_module_bindings b
          LEFT JOIN platform_metadata.module_fence f ON f.module_id=b.module_id
          WHERE b.tenant_id=NEW.tenant_id AND b.revision_id=NEW.revision_id
            AND (f.module_id IS NULL OR (b.artifact_identity,b.generation)
                 IS DISTINCT FROM (f.artifact_identity,f.generation)))
        THEN RAISE EXCEPTION 'UI binding identity invalid'; END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER check_ui_binding_seal BEFORE INSERT
        ON platform_metadata.ui_revision_binding_seals FOR EACH ROW
        EXECUTE FUNCTION platform_metadata.check_ui_binding_seal();
      REVOKE ALL ON FUNCTION platform_metadata.check_ui_binding_seal() FROM PUBLIC;
      CREATE FUNCTION platform_metadata.require_ui_binding_seal() RETURNS trigger
      LANGUAGE plpgsql AS $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM platform_metadata.ui_revision_binding_seals
          WHERE tenant_id=NEW.tenant_id AND revision_id=NEW.id)
        THEN RAISE EXCEPTION 'UI revision requires sealed bindings'; END IF;
        RETURN NEW;
      END $$;
      CREATE CONSTRAINT TRIGGER require_ui_binding_seal AFTER INSERT
        ON platform_metadata.ui_overlay_revisions DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION platform_metadata.require_ui_binding_seal();
      REVOKE ALL ON FUNCTION platform_metadata.require_ui_binding_seal() FROM PUBLIC;
      CREATE FUNCTION platform_metadata.require_active_ui_binding_seal() RETURNS trigger
      LANGUAGE plpgsql AS $$ BEGIN
        IF NEW.active_revision_id IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM platform_metadata.ui_revision_binding_seals
          WHERE tenant_id=NEW.tenant_id AND revision_id=NEW.active_revision_id)
        THEN RAISE EXCEPTION 'Active UI revision requires sealed bindings'; END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER require_active_ui_binding_seal BEFORE UPDATE OF active_revision_id
        ON platform_metadata.ui_overlays FOR EACH ROW
        EXECUTE FUNCTION platform_metadata.require_active_ui_binding_seal();
      REVOKE ALL ON FUNCTION platform_metadata.require_active_ui_binding_seal() FROM PUBLIC;
    """)


def downgrade() -> None:
    connection = op.get_bind()
    op.execute(
        "LOCK TABLE platform_metadata.ui_overlays, platform_metadata.ui_overlay_revisions, "
        "platform_metadata.ui_revision_module_bindings, "
        "platform_metadata.ui_revision_binding_seals IN ACCESS EXCLUSIVE MODE"
    )
    if connection.execute(text("SELECT 1 FROM platform_metadata.ui_overlays LIMIT 1")).first():
        raise RuntimeError("metadata_0005 downgrade refused: retained UI overlay history")
    for table, trigger in (
        ("ui_overlays", "require_active_ui_binding_seal"),
        ("ui_overlay_revisions", "require_ui_binding_seal"),
        ("ui_revision_module_bindings", "check_ui_binding_insert"),
    ):
        op.execute(f"DROP TRIGGER {trigger} ON platform_metadata.{table}")
    op.execute("DROP TABLE platform_metadata.ui_revision_binding_seals")
    op.execute(
        "ALTER TABLE platform_metadata.module_fence "
        "DROP CONSTRAINT uq_module_compatibility_identity"
    )
    for function in (
        "check_ui_binding_insert",
        "check_ui_binding_seal",
        "require_ui_binding_seal",
        "require_active_ui_binding_seal",
    ):
        op.execute(f"DROP FUNCTION platform_metadata.{function}()")
