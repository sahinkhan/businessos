"""ADR-024 authenticated exact-set provenance and activation privilege separation.

Historical candidate seals cannot establish completeness and are never backfilled.
"""

from alembic import op
from sqlalchemy import text

from businessos.migration_assets.metadata_role import assert_metadata_role_safe
from businessos.migration_assets.publication_role import assert_publication_roles_safe

revision = "metadata_0006_ui_provenance"
down_revision = "metadata_0005_ui_binding_seals"
branch_labels = None
depends_on = None

_TENANT = "tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid"


def upgrade() -> None:
    connection = op.get_bind()
    assert_metadata_role_safe(connection)
    assert_publication_roles_safe(connection)
    op.execute(
        "LOCK TABLE platform_metadata.ui_overlays, platform_metadata.ui_overlay_revisions, "
        "platform_metadata.ui_revision_module_bindings, "
        "platform_metadata.ui_revision_binding_seals IN ACCESS EXCLUSIVE MODE"
    )
    if connection.execute(
        text("SELECT 1 FROM platform_metadata.ui_overlay_revisions LIMIT 1")
    ).first():
        raise RuntimeError("metadata_0006 upgrade refused: unauthenticated UI revision history")
    op.execute("""
      CREATE TABLE platform_metadata.ui_installation_lineage (
        singleton INTEGER PRIMARY KEY CHECK (singleton=1),
        lineage_id UUID NOT NULL UNIQUE
      );
      INSERT INTO platform_metadata.ui_installation_lineage VALUES (1,gen_random_uuid());
      CREATE TRIGGER immutable_ui_lineage BEFORE UPDATE OR DELETE
        ON platform_metadata.ui_installation_lineage FOR EACH ROW
        EXECUTE FUNCTION platform_metadata.reject_revision_mutation();
      REVOKE ALL ON platform_metadata.ui_installation_lineage
        FROM PUBLIC,businessos_metadata,businessos_app,businessos_worker,businessos_ops;
      GRANT SELECT ON platform_metadata.ui_installation_lineage
        TO businessos_metadata,businessos_ui_publication;

      ALTER TABLE platform_metadata.ui_overlay_revisions
        ADD COLUMN declaration_provenance JSONB NOT NULL,
        ADD COLUMN schema_generation BIGINT NOT NULL CHECK (schema_generation>0),
        ADD COLUMN ui_generation BIGINT NOT NULL CHECK (ui_generation>0),
        ADD COLUMN draft_generation BIGINT NOT NULL CHECK (draft_generation>0),
        ADD COLUMN prior_active_generation BIGINT NOT NULL CHECK (prior_active_generation>=0);

      CREATE TABLE platform_metadata.ui_expected_provenance (
        tenant_id UUID NOT NULL, overlay_id UUID NOT NULL, revision_id UUID NOT NULL,
        view_id UUID NOT NULL, scope_kind VARCHAR(20) NOT NULL, scope_id UUID NOT NULL,
        lineage_id UUID NOT NULL REFERENCES platform_metadata.ui_installation_lineage(lineage_id),
        model_version INTEGER NOT NULL CHECK (model_version=1),
        purpose TEXT NOT NULL CHECK (purpose='published-ui-completeness'),
        issuer_version INTEGER NOT NULL CHECK (issuer_version=1),
        document JSONB NOT NULL,
        document_digest VARCHAR(64) NOT NULL CHECK (document_digest ~ '^[a-f0-9]{64}$'),
        compatibility_digest VARCHAR(64) NOT NULL CHECK (compatibility_digest ~ '^[a-f0-9]{64}$'),
        declaration_provenance JSONB NOT NULL,
        schema_generation BIGINT NOT NULL CHECK (schema_generation>0),
        ui_generation BIGINT NOT NULL CHECK (ui_generation>0),
        draft_generation BIGINT NOT NULL CHECK (draft_generation>0),
        prior_active_generation BIGINT NOT NULL CHECK (prior_active_generation>=0),
        PRIMARY KEY (tenant_id,revision_id),
        UNIQUE (tenant_id,overlay_id,revision_id),
        FOREIGN KEY (tenant_id,overlay_id,revision_id)
          REFERENCES platform_metadata.ui_overlay_revisions(tenant_id,overlay_id,id)
          ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
        CHECK (jsonb_typeof(document)='object' AND octet_length(document::text)<=65536),
        CHECK (jsonb_typeof(declaration_provenance)='array'
          AND jsonb_array_length(declaration_provenance) BETWEEN 1 AND 128
          AND octet_length(declaration_provenance::text)<=65536)
      );
      CREATE TABLE platform_metadata.ui_expected_members (
        tenant_id UUID NOT NULL, overlay_id UUID NOT NULL, revision_id UUID NOT NULL,
        module_id VARCHAR(120) COLLATE "C" NOT NULL CHECK (module_id ~ '^[a-z][a-z0-9_.-]+$'),
        artifact_identity TEXT COLLATE "C" NOT NULL
          CHECK (octet_length(artifact_identity) BETWEEN 1 AND 800),
        generation BIGINT NOT NULL CHECK (generation>0),
        PRIMARY KEY (tenant_id,revision_id,module_id),
        FOREIGN KEY (tenant_id,overlay_id,revision_id)
          REFERENCES platform_metadata.ui_expected_provenance(tenant_id,overlay_id,revision_id)
          ON DELETE RESTRICT
      );
      ALTER TABLE platform_metadata.ui_revision_binding_seals
        ADD CONSTRAINT fk_ui_seal_expected FOREIGN KEY (tenant_id,overlay_id,revision_id)
        REFERENCES platform_metadata.ui_expected_provenance(tenant_id,overlay_id,revision_id)
        ON DELETE RESTRICT;
    """)
    for table in ("ui_expected_provenance", "ui_expected_members"):
        op.execute(f"ALTER TABLE platform_metadata.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE platform_metadata.{table} FORCE ROW LEVEL SECURITY")
        for role in ("businessos_metadata", "businessos_ui_publication"):
            op.execute(
                f"CREATE POLICY {table}_{role} ON platform_metadata.{table} TO {role} "
                f"USING ({_TENANT}) WITH CHECK ({_TENANT})"
            )
        op.execute(
            f"CREATE POLICY {table}_migration ON platform_metadata.{table} "
            "TO businessos_migrator USING (true) WITH CHECK (true)"
        )
        op.execute(
            f"REVOKE ALL ON platform_metadata.{table} FROM PUBLIC,businessos_metadata,"
            "businessos_app,businessos_worker,businessos_ops,businessos_governance"
        )
        op.execute(f"GRANT SELECT ON platform_metadata.{table} TO businessos_metadata")
        op.execute(f"GRANT SELECT,INSERT ON platform_metadata.{table} TO businessos_ui_publication")
        op.execute(
            f"CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE "
            f"ON platform_metadata.{table} FOR EACH ROW "
            "EXECUTE FUNCTION platform_metadata.reject_revision_mutation()"
        )
    op.execute("""
      GRANT USAGE ON SCHEMA platform_metadata,platform_audit,eventing
        TO businessos_ui_publication;
      GRANT SELECT,INSERT,UPDATE ON platform_metadata.ui_overlays TO businessos_ui_publication;
      GRANT SELECT,INSERT ON platform_metadata.ui_overlay_revisions,
        platform_metadata.ui_revision_module_bindings,platform_metadata.ui_revision_binding_seals,
        platform_audit.audit_logs,eventing.outbox_messages TO businessos_ui_publication;
      GRANT SELECT,UPDATE(id) ON platform_metadata.contract_fence TO businessos_ui_publication;
      REVOKE INSERT,UPDATE ON platform_metadata.module_fence FROM businessos_metadata;
      GRANT UPDATE(module_id) ON platform_metadata.module_fence TO businessos_metadata;
      GRANT SELECT,INSERT(module_id,artifact_identity,generation),
        UPDATE(module_id,artifact_identity,generation) ON platform_metadata.module_fence
        TO businessos_ui_publication;
      CREATE FUNCTION platform_metadata.check_module_identity() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$ BEGIN
        IF TG_OP='UPDATE' AND NEW.module_id IS DISTINCT FROM OLD.module_id
          THEN RAISE EXCEPTION 'module identity is immutable'; END IF;
        IF TG_OP='UPDATE' AND (NEW.artifact_identity,NEW.generation) IS DISTINCT FROM
          (OLD.artifact_identity,OLD.generation) AND
          (OLD.active_bindings<>0 OR NEW.generation<>OLD.generation+1)
          THEN RAISE EXCEPTION 'module activation is incompatible'; END IF;
        RETURN NEW;
      END $$;
      REVOKE ALL ON FUNCTION platform_metadata.check_module_identity() FROM PUBLIC;
      CREATE TRIGGER check_module_identity BEFORE UPDATE ON platform_metadata.module_fence
        FOR EACH ROW EXECUTE FUNCTION platform_metadata.check_module_identity();
    """)
    for qualified in (
        "platform_metadata.ui_overlays",
        "platform_metadata.ui_overlay_revisions",
        "platform_metadata.ui_revision_module_bindings",
        "platform_metadata.ui_revision_binding_seals",
        "platform_audit.audit_logs",
        "eventing.outbox_messages",
    ):
        op.execute(
            f"CREATE POLICY ui_publication_tenant ON {qualified} TO businessos_ui_publication "
            f"USING ({_TENANT}) WITH CHECK ({_TENANT})"
        )
    _provenance_triggers()
    _counter_privileges()


def _provenance_triggers() -> None:
    op.execute("""
      CREATE FUNCTION platform_metadata.check_ui_expected_header() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$ BEGIN
        PERFORM 1 FROM platform_metadata.ui_overlays o WHERE o.tenant_id=NEW.tenant_id
          AND o.id=NEW.overlay_id AND o.view_id=NEW.view_id
          AND o.scope_kind=NEW.scope_kind AND o.scope_id=NEW.scope_id
          AND o.draft_generation=NEW.draft_generation
          AND o.active_generation=NEW.prior_active_generation
          AND o.draft_document=NEW.document
          AND o.draft_compatibility_digest=NEW.compatibility_digest
          AND o.lifecycle<>'retired' FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION 'UI expected context mismatch'; END IF;
        PERFORM 1 FROM platform_metadata.contract_fence WHERE id=1
          AND schema_generation=NEW.schema_generation AND ui_generation=NEW.ui_generation
          FOR SHARE;
        IF NOT FOUND THEN RAISE EXCEPTION 'UI expected contract mismatch'; END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER check_ui_expected_header BEFORE INSERT
        ON platform_metadata.ui_expected_provenance FOR EACH ROW
        EXECUTE FUNCTION platform_metadata.check_ui_expected_header();
      REVOKE ALL ON FUNCTION platform_metadata.check_ui_expected_header() FROM PUBLIC;

      CREATE FUNCTION platform_metadata.check_ui_expected_member() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$ BEGIN
        PERFORM 1 FROM platform_metadata.ui_overlays WHERE tenant_id=NEW.tenant_id
          AND id=NEW.overlay_id FOR UPDATE;
        IF EXISTS (SELECT 1 FROM platform_metadata.ui_revision_binding_seals
          WHERE tenant_id=NEW.tenant_id AND revision_id=NEW.revision_id)
          THEN RAISE EXCEPTION 'UI expected set is sealed'; END IF;
        IF (SELECT count(*) FROM platform_metadata.ui_expected_members
          WHERE tenant_id=NEW.tenant_id AND revision_id=NEW.revision_id)>=128
          THEN RAISE EXCEPTION 'UI expected member budget exceeded'; END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER check_ui_expected_member BEFORE INSERT
        ON platform_metadata.ui_expected_members FOR EACH ROW
        EXECUTE FUNCTION platform_metadata.check_ui_expected_member();
      REVOKE ALL ON FUNCTION platform_metadata.check_ui_expected_member() FROM PUBLIC;

      CREATE OR REPLACE FUNCTION platform_metadata.check_ui_binding_seal() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$ BEGIN
        PERFORM 1 FROM platform_metadata.ui_overlays WHERE tenant_id=NEW.tenant_id
          AND id=NEW.overlay_id FOR UPDATE;
        IF NOT EXISTS (
          SELECT 1 FROM platform_metadata.ui_expected_provenance e
          JOIN platform_metadata.ui_overlay_revisions r
            ON (r.tenant_id,r.overlay_id,r.id)=(e.tenant_id,e.overlay_id,e.revision_id)
          JOIN platform_metadata.ui_overlays o ON (o.tenant_id,o.id)=(e.tenant_id,e.overlay_id)
          JOIN platform_metadata.ui_installation_lineage l ON l.lineage_id=e.lineage_id
          WHERE (e.tenant_id,e.overlay_id,e.revision_id)=
            (NEW.tenant_id,NEW.overlay_id,NEW.revision_id)
            AND (o.view_id,o.scope_kind,o.scope_id)=(e.view_id,e.scope_kind,e.scope_id)
            AND (r.document,r.digest,r.compatibility_digest,r.declaration_provenance,
                 r.schema_generation,r.ui_generation,r.draft_generation,r.prior_active_generation)
              IS NOT DISTINCT FROM
                (e.document,e.document_digest,e.compatibility_digest,e.declaration_provenance,
                 e.schema_generation,e.ui_generation,e.draft_generation,e.prior_active_generation))
          THEN RAISE EXCEPTION 'UI authenticated expected context required'; END IF;
        IF (SELECT count(*) FROM platform_metadata.ui_expected_members
          WHERE tenant_id=NEW.tenant_id AND revision_id=NEW.revision_id) NOT BETWEEN 1 AND 128
          THEN RAISE EXCEPTION 'UI expected member budget invalid'; END IF;
        IF EXISTS (
          (SELECT module_id COLLATE "C",artifact_identity COLLATE "C",generation
            FROM platform_metadata.ui_expected_members
            WHERE tenant_id=NEW.tenant_id AND revision_id=NEW.revision_id
           EXCEPT SELECT module_id COLLATE "C",artifact_identity COLLATE "C",generation
            FROM platform_metadata.ui_revision_module_bindings
            WHERE tenant_id=NEW.tenant_id AND revision_id=NEW.revision_id)
          UNION ALL
          (SELECT module_id COLLATE "C",artifact_identity COLLATE "C",generation
            FROM platform_metadata.ui_revision_module_bindings
            WHERE tenant_id=NEW.tenant_id AND revision_id=NEW.revision_id
           EXCEPT SELECT module_id COLLATE "C",artifact_identity COLLATE "C",generation
            FROM platform_metadata.ui_expected_members
            WHERE tenant_id=NEW.tenant_id AND revision_id=NEW.revision_id))
          THEN RAISE EXCEPTION 'UI bindings differ from authenticated complete set'; END IF;
        PERFORM f.module_id FROM platform_metadata.module_fence f
          JOIN platform_metadata.ui_expected_members e ON e.module_id=f.module_id
          WHERE e.tenant_id=NEW.tenant_id AND e.revision_id=NEW.revision_id
          ORDER BY f.module_id COLLATE "C" FOR KEY SHARE OF f;
        IF EXISTS (SELECT 1 FROM platform_metadata.ui_expected_members e
          LEFT JOIN platform_metadata.module_fence f ON f.module_id=e.module_id
          WHERE e.tenant_id=NEW.tenant_id AND e.revision_id=NEW.revision_id AND
            (f.module_id IS NULL OR (e.artifact_identity COLLATE "C",e.generation)
             IS DISTINCT FROM (f.artifact_identity COLLATE "C",f.generation)))
          THEN RAISE EXCEPTION 'UI expected compatibility identity invalid'; END IF;
        RETURN NEW;
      END $$;
      CREATE FUNCTION platform_metadata.require_expected_ui_seal() RETURNS trigger
      LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM platform_metadata.ui_revision_binding_seals
          WHERE (tenant_id,overlay_id,revision_id)=(NEW.tenant_id,NEW.overlay_id,NEW.revision_id))
          THEN RAISE EXCEPTION 'UI expected provenance requires seal'; END IF;
        RETURN NEW;
      END $$;
      CREATE CONSTRAINT TRIGGER require_expected_ui_seal AFTER INSERT
        ON platform_metadata.ui_expected_provenance DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION platform_metadata.require_expected_ui_seal();
      REVOKE ALL ON FUNCTION platform_metadata.require_expected_ui_seal() FROM PUBLIC;
    """)


def _counter_privileges() -> None:
    # Only trigger execution reaches this NOLOGIN principal. No runtime has
    # membership or EXECUTE. FORCE RLS still constrains its binding reads.
    op.execute("""
      GRANT USAGE,CREATE ON SCHEMA platform_metadata TO businessos_metadata_fence_owner;
      GRANT SELECT,UPDATE(active_bindings) ON platform_metadata.module_fence
        TO businessos_metadata_fence_owner;
      GRANT SELECT ON platform_metadata.revision_module_bindings,
        platform_metadata.ui_revision_module_bindings TO businessos_metadata_fence_owner;
      ALTER FUNCTION platform_metadata.adjust_active_bindings()
        SET search_path=pg_catalog,pg_temp;
      ALTER FUNCTION platform_metadata.adjust_active_bindings() SECURITY DEFINER;
      ALTER FUNCTION platform_metadata.adjust_active_bindings()
        OWNER TO businessos_metadata_fence_owner;
      REVOKE ALL ON FUNCTION platform_metadata.adjust_active_bindings() FROM PUBLIC;
      ALTER FUNCTION platform_metadata.adjust_ui_active_bindings()
        SET search_path=pg_catalog,pg_temp;
      ALTER FUNCTION platform_metadata.adjust_ui_active_bindings() SECURITY DEFINER;
      ALTER FUNCTION platform_metadata.adjust_ui_active_bindings()
        OWNER TO businessos_metadata_fence_owner;
      REVOKE ALL ON FUNCTION platform_metadata.adjust_ui_active_bindings() FROM PUBLIC;
      REVOKE CREATE ON SCHEMA platform_metadata FROM businessos_metadata_fence_owner;
    """)
    for table in ("revision_module_bindings", "ui_revision_module_bindings"):
        op.execute(
            f"CREATE POLICY counter_owner_tenant ON platform_metadata.{table} "
            f"FOR SELECT TO businessos_metadata_fence_owner USING ({_TENANT})"
        )


def downgrade() -> None:
    # This transition also hardens frozen activation counters. Do not restore
    # forgeable SQL authority even on an empty installation without reviewed recovery.
    raise RuntimeError(
        "metadata_0006 downgrade refused: trusted completeness and activation grants "
        "require reviewed operator recovery"
    )
