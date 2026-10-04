"""Bounded published presentation overlays; frozen definition grammar is unchanged.

Revision ID: metadata_0003_ui_overlays
Revises: metadata_0002_custom_entities
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

from businessos.migration_assets.metadata_role import assert_metadata_role_safe

revision: str = "metadata_0003_ui_overlays"
down_revision: str | Sequence[str] | None = "metadata_0002_custom_entities"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    assert_metadata_role_safe(op.get_bind())
    op.execute("""
      CREATE TABLE platform_metadata.ui_overlays (
        id UUID PRIMARY KEY, tenant_id UUID NOT NULL, view_id UUID NOT NULL,
        scope_kind VARCHAR(20) NOT NULL, scope_id UUID NOT NULL,
        lifecycle VARCHAR(20) NOT NULL DEFAULT 'draft',
        draft_generation BIGINT NOT NULL DEFAULT 1,
        draft_document JSONB NOT NULL, draft_compatibility_digest VARCHAR(64) NOT NULL,
        active_generation BIGINT NOT NULL DEFAULT 0, active_revision_id UUID,
        created_by UUID NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_ui_overlay_tenant_id UNIQUE (tenant_id,id),
        CONSTRAINT uq_ui_overlay_scope UNIQUE (tenant_id,view_id,scope_kind,scope_id),
        CONSTRAINT ck_ui_overlay_scope CHECK (scope_kind IN ('tenant','company','site','user')
          AND (scope_kind <> 'tenant' OR scope_id=tenant_id)),
        CONSTRAINT ck_ui_overlay_lifecycle CHECK (lifecycle IN ('draft','published','retired')
          AND ((lifecycle='published') = (active_revision_id IS NOT NULL))),
        CONSTRAINT ck_ui_overlay_generation CHECK (draft_generation>0 AND active_generation>=0),
        CONSTRAINT ck_ui_overlay_digest CHECK (draft_compatibility_digest ~ '^[a-f0-9]{64}$'),
        CONSTRAINT ck_ui_overlay_document CHECK (jsonb_typeof(draft_document)='object'
          AND octet_length(draft_document::text)<=65536)
      )
    """)
    op.execute("""
      CREATE TABLE platform_metadata.ui_overlay_revisions (
        id UUID PRIMARY KEY, tenant_id UUID NOT NULL, overlay_id UUID NOT NULL,
        sequence BIGINT NOT NULL CHECK (sequence BETWEEN 1 AND 64),
        document JSONB NOT NULL, digest VARCHAR(64) NOT NULL,
        compatibility_digest VARCHAR(64) NOT NULL,
        published_by UUID NOT NULL, published_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT fk_ui_revision_overlay FOREIGN KEY (tenant_id,overlay_id)
          REFERENCES platform_metadata.ui_overlays(tenant_id,id) ON DELETE RESTRICT,
        CONSTRAINT uq_ui_revision_sequence UNIQUE (tenant_id,overlay_id,sequence),
        CONSTRAINT uq_ui_revision_pin UNIQUE (tenant_id,overlay_id,id),
        CONSTRAINT ck_ui_revision_digest CHECK (digest ~ '^[a-f0-9]{64}$'
          AND compatibility_digest ~ '^[a-f0-9]{64}$'),
        CONSTRAINT ck_ui_revision_document CHECK (jsonb_typeof(document)='object'
          AND octet_length(document::text)<=65536)
      )
    """)
    op.execute(
        "ALTER TABLE platform_metadata.ui_overlays ADD CONSTRAINT fk_ui_active_revision "
        "FOREIGN KEY (tenant_id,id,active_revision_id) REFERENCES "
        "platform_metadata.ui_overlay_revisions(tenant_id,overlay_id,id) ON DELETE RESTRICT"
    )
    for table in ("ui_overlays", "ui_overlay_revisions"):
        op.execute(f"ALTER TABLE platform_metadata.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE platform_metadata.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant ON platform_metadata.{table} "
            "TO businessos_metadata USING "
            "(tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)"
        )
        op.execute(
            f"CREATE POLICY {table}_migration ON platform_metadata.{table} "
            "TO businessos_migrator USING (true) WITH CHECK (true)"
        )
        op.execute(
            f"REVOKE ALL ON platform_metadata.{table} FROM PUBLIC, "
            "businessos_app, businessos_worker, businessos_ops"
        )
    op.execute("GRANT SELECT,INSERT,UPDATE ON platform_metadata.ui_overlays TO businessos_metadata")
    op.execute(
        "GRANT SELECT,INSERT ON platform_metadata.ui_overlay_revisions TO businessos_metadata"
    )
    op.execute("""
      CREATE FUNCTION platform_metadata.check_ui_overlay() RETURNS trigger
      LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP='DELETE' THEN RAISE EXCEPTION 'UI overlay history is retained'; END IF;
        IF TG_OP='INSERT' THEN
          PERFORM pg_advisory_xact_lock(hashtextextended('ui-quota:' || NEW.tenant_id::text,0));
          IF NEW.lifecycle<>'draft' OR NEW.active_generation<>0 OR NEW.draft_generation<>1
             OR (SELECT count(*) FROM platform_metadata.ui_overlays
                 WHERE tenant_id=NEW.tenant_id)>=1024
          THEN RAISE EXCEPTION 'UI overlay initial state or tenant quota invalid'; END IF;
        ELSE
          IF (NEW.id,NEW.tenant_id,NEW.view_id,NEW.scope_kind,NEW.scope_id,
              NEW.created_by,NEW.created_at)
             IS DISTINCT FROM
             (OLD.id,OLD.tenant_id,OLD.view_id,OLD.scope_kind,OLD.scope_id,OLD.created_by,OLD.created_at)
          THEN RAISE EXCEPTION 'UI overlay identity is immutable'; END IF;
          IF OLD.lifecycle='retired' THEN RAISE EXCEPTION 'UI overlay retired'; END IF;
          IF (NEW.draft_document,NEW.draft_compatibility_digest) IS DISTINCT FROM
             (OLD.draft_document,OLD.draft_compatibility_digest) THEN
            IF NEW.draft_generation<>OLD.draft_generation+1
              OR (NEW.active_generation,NEW.active_revision_id,NEW.lifecycle) IS DISTINCT FROM
                 (OLD.active_generation,OLD.active_revision_id,OLD.lifecycle)
            THEN RAISE EXCEPTION 'UI draft concurrency invalid'; END IF;
          ELSIF NEW.draft_generation<>OLD.draft_generation THEN
            RAISE EXCEPTION 'UI draft generation invalid';
          END IF;
          IF (NEW.active_revision_id,NEW.lifecycle) IS DISTINCT FROM
             (OLD.active_revision_id,OLD.lifecycle)
             OR NEW.active_generation<>OLD.active_generation THEN
            IF NEW.active_generation<>OLD.active_generation+1 OR NEW.lifecycle='draft'
            THEN RAISE EXCEPTION 'UI active generation invalid'; END IF;
          END IF;
        END IF;
        RETURN NEW;
      END $$
    """)
    op.execute("""
      CREATE FUNCTION platform_metadata.check_ui_revision() RETURNS trigger
      LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'UI revision is immutable'; END IF;
        -- Serialize sequence/quota checks even for direct protected-role SQL.
        PERFORM 1 FROM platform_metadata.ui_overlays
          WHERE tenant_id=NEW.tenant_id AND id=NEW.overlay_id FOR UPDATE;
        IF NEW.sequence<>(SELECT count(*)+1 FROM platform_metadata.ui_overlay_revisions
            WHERE tenant_id=NEW.tenant_id AND overlay_id=NEW.overlay_id)
        THEN RAISE EXCEPTION 'UI revision sequence invalid'; END IF;
        RETURN NEW;
      END $$
    """)
    for table, function in (
        ("ui_overlays", "check_ui_overlay"),
        ("ui_overlay_revisions", "check_ui_revision"),
    ):
        op.execute(
            f"CREATE TRIGGER {function} BEFORE INSERT OR UPDATE OR DELETE "
            f"ON platform_metadata.{table} FOR EACH ROW "
            f"EXECUTE FUNCTION platform_metadata.{function}()"
        )
        op.execute(f"REVOKE ALL ON FUNCTION platform_metadata.{function}() FROM PUBLIC")


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        text(
            "LOCK TABLE platform_metadata.ui_overlays, "
            "platform_metadata.ui_overlay_revisions IN ACCESS EXCLUSIVE MODE"
        )
    )
    if connection.execute(text("SELECT 1 FROM platform_metadata.ui_overlays LIMIT 1")).first():
        raise RuntimeError("metadata_0003 downgrade refused: retained UI overlay history")
    op.execute("ALTER TABLE platform_metadata.ui_overlays DROP CONSTRAINT fk_ui_active_revision")
    op.execute("DROP TABLE platform_metadata.ui_overlay_revisions")
    op.execute("DROP TABLE platform_metadata.ui_overlays")
    op.execute("DROP FUNCTION platform_metadata.check_ui_revision()")
    op.execute("DROP FUNCTION platform_metadata.check_ui_overlay()")
