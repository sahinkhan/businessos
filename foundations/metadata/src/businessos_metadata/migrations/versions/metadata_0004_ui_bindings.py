"""Forward-only UI compatibility bindings in the existing Metadata activation fence."""

from alembic import op
from sqlalchemy import text

revision = "metadata_0004_ui_bindings"
down_revision = "metadata_0003_ui_overlays"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A failed, uncertified 0003 installation cannot invent historical dependency
    # pins from a digest. Retire active overlays before this forward upgrade.
    connection = op.get_bind()
    connection.execute(text("LOCK TABLE platform_metadata.ui_overlays IN ACCESS EXCLUSIVE MODE"))
    if connection.execute(
        text(
            "SELECT 1 FROM platform_metadata.ui_overlays "
            "WHERE active_revision_id IS NOT NULL LIMIT 1"
        )
    ).first():
        raise RuntimeError(
            "metadata_0004 upgrade refused: unbound active UI revisions must be retired"
        )
    op.execute("""
      CREATE TABLE platform_metadata.ui_revision_module_bindings (
        tenant_id UUID NOT NULL, overlay_id UUID NOT NULL, revision_id UUID NOT NULL,
        module_id VARCHAR(120) NOT NULL, artifact_identity TEXT NOT NULL,
        generation BIGINT NOT NULL CHECK (generation>0),
        PRIMARY KEY (tenant_id,revision_id,module_id),
        FOREIGN KEY (tenant_id,overlay_id,revision_id)
          REFERENCES platform_metadata.ui_overlay_revisions(tenant_id,overlay_id,id)
          ON DELETE RESTRICT,
        FOREIGN KEY (module_id) REFERENCES platform_metadata.module_fence(module_id)
          ON DELETE RESTRICT
      )
    """)
    op.execute(
        "ALTER TABLE platform_metadata.ui_revision_module_bindings ENABLE ROW LEVEL SECURITY"
    )
    op.execute("ALTER TABLE platform_metadata.ui_revision_module_bindings FORCE ROW LEVEL SECURITY")
    op.execute("""
      CREATE POLICY ui_bindings_tenant ON platform_metadata.ui_revision_module_bindings
        TO businessos_metadata
        USING (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)
        WITH CHECK (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)
    """)
    op.execute("""
      CREATE POLICY ui_bindings_migration ON platform_metadata.ui_revision_module_bindings
        TO businessos_migrator USING (true) WITH CHECK (true)
    """)
    op.execute(
        "REVOKE ALL ON platform_metadata.ui_revision_module_bindings "
        "FROM PUBLIC,businessos_app,businessos_worker,businessos_ops"
    )
    op.execute(
        "GRANT SELECT,INSERT ON platform_metadata.ui_revision_module_bindings "
        "TO businessos_metadata"
    )
    op.execute("""
      CREATE TRIGGER ui_bindings_immutable BEFORE UPDATE OR DELETE
        ON platform_metadata.ui_revision_module_bindings FOR EACH ROW
        EXECUTE FUNCTION platform_metadata.reject_revision_mutation()
    """)
    op.execute("""
      CREATE FUNCTION platform_metadata.adjust_ui_active_bindings() RETURNS trigger
      LANGUAGE plpgsql AS $$ DECLARE item RECORD; changed_count integer; BEGIN
        IF NEW.active_revision_id IS NOT DISTINCT FROM OLD.active_revision_id
          THEN RETURN NEW; END IF;
        IF NEW.active_revision_id IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM platform_metadata.ui_revision_module_bindings
          WHERE tenant_id=NEW.tenant_id AND overlay_id=NEW.id AND revision_id=NEW.active_revision_id
        ) THEN RAISE EXCEPTION 'UI revision has no activation bindings'; END IF;
        FOR item IN SELECT module_id,artifact_identity,generation,
            sum(delta)::integer AS delta FROM (
          SELECT module_id,artifact_identity,generation,-1 AS delta
            FROM platform_metadata.ui_revision_module_bindings
            WHERE tenant_id=OLD.tenant_id AND revision_id=OLD.active_revision_id
          UNION ALL
          SELECT module_id,artifact_identity,generation,1 AS delta
            FROM platform_metadata.ui_revision_module_bindings
            WHERE tenant_id=NEW.tenant_id AND revision_id=NEW.active_revision_id
        ) bindings GROUP BY module_id,artifact_identity,generation ORDER BY module_id LOOP
          UPDATE platform_metadata.module_fence SET active_bindings=active_bindings+item.delta
            WHERE module_id=item.module_id AND artifact_identity=item.artifact_identity
              AND generation=item.generation AND active_bindings+item.delta>=0;
          GET DIAGNOSTICS changed_count=ROW_COUNT;
          IF changed_count<>1 THEN RAISE EXCEPTION 'stale UI activation binding'; END IF;
        END LOOP;
        RETURN NEW;
      END $$
    """)
    op.execute("REVOKE ALL ON FUNCTION platform_metadata.adjust_ui_active_bindings() FROM PUBLIC")
    op.execute("""
      CREATE TRIGGER ui_active_bindings AFTER UPDATE OF active_revision_id
        ON platform_metadata.ui_overlays FOR EACH ROW
        EXECUTE FUNCTION platform_metadata.adjust_ui_active_bindings()
    """)


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        text(
            "LOCK TABLE platform_metadata.ui_overlays, "
            "platform_metadata.ui_revision_module_bindings "
            "IN ACCESS EXCLUSIVE MODE"
        )
    )
    if connection.execute(text("SELECT 1 FROM platform_metadata.ui_overlays LIMIT 1")).first():
        raise RuntimeError("metadata_0004 downgrade refused: retained UI compatibility history")
    op.execute("DROP TRIGGER ui_active_bindings ON platform_metadata.ui_overlays")
    op.execute("DROP FUNCTION platform_metadata.adjust_ui_active_bindings()")
    op.execute("DROP TABLE platform_metadata.ui_revision_module_bindings")
