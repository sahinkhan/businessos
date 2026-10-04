"Exact certified Phase 5C heads -> additive UI migration, retention, replay/refusal."

import json
from uuid import uuid4

import psycopg
import pytest

from tests.conftest import PostgreSQLTestDatabase
from tests.integration.test_phase5a_metadata import _app, _Policy, _url
from tests.integration.test_phase5d_ui import Harness, create, publish
from tests.integration.test_phase5d_ui import ui_harness as ui_harness

pytestmark = [pytest.mark.integration, pytest.mark.postgres]
BASE_HEADS = {
    "geography_0003",
    "identity_0005",
    "metadata_0002_custom_entities",
    "organization_0003",
    "party_0003_custom_fields",
    "policy_0005",
    "proof_0004",
    "tenant_0002",
}
CANDIDATE_HEADS = (BASE_HEADS - {"metadata_0002_custom_entities"}) | {"metadata_0003_ui_overlays"}


def test_certified_base_retained_upgrade_replay_and_empty_downgrade(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = _app(postgres_database, _Policy())
    migrations = app.runtime.migrations
    plan = migrations.plan()
    assert set(plan.heads) == CANDIDATE_HEADS - {"proof_0004"}
    edge = next(x for x in plan.revisions if x.revision == "metadata_0003_ui_overlays")
    assert edge.owner == "foundation.metadata"
    assert edge.down_revisions == ("metadata_0002_custom_entities",)
    baseline = BASE_HEADS - {"proof_0004"}
    for head in sorted(baseline):
        migrations.upgrade(postgres_database.migration_url, head)
    with psycopg.connect(_url(postgres_database.migration_url)) as connection:
        assert {
            r[0] for r in connection.execute("SELECT version_num FROM alembic_version")
        } == baseline
        assert connection.execute(
            "SELECT to_regclass('platform_metadata.ui_overlays')"
        ).fetchone() == (None,)
        connection.execute(
            "UPDATE platform_module.installed_module_migrations SET "
            "revision_ids=revision_ids-'metadata_0003_ui_overlays', "
            "revision_manifest=(SELECT jsonb_agg(value) FROM "
            "jsonb_array_elements(revision_manifest) WHERE "
            "value->>'revision'<>'metadata_0003_ui_overlays') WHERE "
            "module_id='foundation.metadata'"
        )
        assert connection.execute(
            "SELECT revision_ids FROM platform_module.installed_module_migrations "
            "WHERE module_id='foundation.metadata'"
        ).fetchone() == (["metadata_0001", "metadata_0002_custom_entities"],)
        tenant, definition, actor = uuid4(), uuid4(), uuid4()
        snapshot = {"contract_version": "1.0", "kind": "field_set", "fields": []}
        connection.execute(
            (
                "INSERT INTO platform_metadata.definitions "
                "(id,tenant_id,owner_module_id,resource_namespace,owner_contract_version,"
                "kind,lifecycle,draft_snapshot,created_by) VALUES "
                "(%s,%s,'foundation.party','foundation.party.party','1','field_set','draf"
                "t',%s::jsonb,%s)"
            ),
            (definition, tenant, json.dumps(snapshot), actor),
        )
        retained = connection.execute(
            "SELECT to_jsonb(d) FROM platform_metadata.definitions d ORDER BY id"
        ).fetchall()
    migrations.upgrade(postgres_database.migration_url)
    migrations.upgrade(postgres_database.migration_url)
    with psycopg.connect(_url(postgres_database.migration_url)) as connection:
        assert {r[0] for r in connection.execute("SELECT version_num FROM alembic_version")} == set(
            plan.heads
        )
        assert (
            connection.execute(
                "SELECT to_jsonb(d) FROM platform_metadata.definitions d ORDER BY id"
            ).fetchall()
            == retained
        )
        for table in ("ui_overlays", "ui_overlay_revisions"):
            assert connection.execute(
                ("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass"),
                ("platform_metadata." + table,),
            ).fetchone() == (True, True)
            assert connection.execute(
                "SELECT has_table_privilege('businessos_app',%s,'SELECT,INSERT,UPDATE,DELETE')",
                ("platform_metadata." + table,),
            ).fetchone() == (False,)
    migrations.downgrade(postgres_database.migration_url, "metadata_0002_custom_entities")
    with psycopg.connect(_url(postgres_database.migration_url)) as connection:
        assert {
            r[0] for r in connection.execute("SELECT version_num FROM alembic_version")
        } == baseline
        assert (
            connection.execute(
                "SELECT to_jsonb(d) FROM platform_metadata.definitions d ORDER BY id"
            ).fetchall()
            == retained
        )
    migrations.upgrade(postgres_database.migration_url)


@pytest.mark.asyncio
async def test_retained_overlay_refuses_downgrade_before_any_schema_change(
    ui_harness: Harness,
) -> None:
    h = ui_harness
    row = await publish(h, await create(h))
    with psycopg.connect(_url(h.database.migration_url)) as connection:
        before = connection.execute(
            "SELECT to_jsonb(o) FROM platform_metadata.ui_overlays o"
        ).fetchall()
        revisions = connection.execute(
            "SELECT to_jsonb(r) FROM platform_metadata.ui_overlay_revisions r"
        ).fetchall()
        assert before[0][0]["active_revision_id"] == str(row.active_revision_id)
    assert h.app.runtime is not None
    with pytest.raises(RuntimeError, match="metadata_0003 downgrade refused"):
        h.app.runtime.migrations.downgrade(
            h.database.migration_url, "metadata_0002_custom_entities"
        )
    with psycopg.connect(_url(h.database.migration_url)) as connection:
        assert (
            connection.execute("SELECT to_jsonb(o) FROM platform_metadata.ui_overlays o").fetchall()
            == before
        )
        assert (
            connection.execute(
                "SELECT to_jsonb(r) FROM platform_metadata.ui_overlay_revisions r"
            ).fetchall()
            == revisions
        )
    assert (await h.resolve()).resolved is not None
