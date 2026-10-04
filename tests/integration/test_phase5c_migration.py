"""Exact certified-head transition, retained state, replay and refusal coverage."""

import json
from uuid import uuid4

import psycopg
import pytest
from businessos_metadata.contracts import DefinitionSnapshot, FieldDefinition
from businessos_metadata.module import ArchiveCustomEntity

from businessos.migrations import MigrationCoordinator
from businessos.modules import ModuleRegistry, discover_modules
from businessos.modules.installation_inventory import approved_artifacts_from_operator_inventory
from businessos.version import runtime_version
from tests.conftest import PostgreSQLTestDatabase
from tests.integration.test_phase5a_metadata import _url
from tests.integration.test_phase5c_custom_entities import (
    Harness,
    _command,
    _create,
    _type,
)
from tests.integration.test_phase5c_custom_entities import entity_harness as entity_harness

pytestmark = [pytest.mark.integration, pytest.mark.postgres]
BASE_HEADS = {
    "geography_0003",
    "identity_0005",
    "metadata_0001",
    "organization_0003",
    "party_0003_custom_fields",
    "policy_0005",
    "proof_0004",
    "tenant_0002",
}
CANDIDATE_HEADS = (BASE_HEADS - {"metadata_0001"}) | {"metadata_0005_ui_binding_seals"}


def _migrations() -> MigrationCoordinator:
    modules = tuple(discover_modules())
    registry = ModuleRegistry(
        platform_version=runtime_version(),
        sdk_version="0.1.0",
        approved_artifacts=approved_artifacts_from_operator_inventory(modules),
    )
    for module in modules:
        registry.add(module)
    result = MigrationCoordinator(registry)
    assert set(result.plan().heads) == CANDIDATE_HEADS
    edge = next(r for r in result.plan().revisions if r.revision == "metadata_0002_custom_entities")
    assert edge.down_revisions == ("metadata_0001",)
    return result


def _heads(database: PostgreSQLTestDatabase) -> set[str]:
    with psycopg.connect(_url(database.migration_url)) as db:
        return {row[0] for row in db.execute("SELECT version_num FROM alembic_version")}


def test_exact_certified_heads_retained_upgrade_replay_and_empty_downgrade(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    migrations = _migrations()
    for head in sorted(BASE_HEADS):
        migrations.upgrade(postgres_database.migration_url, head)
    assert _heads(postgres_database) == BASE_HEADS
    tenant, identity, actor = uuid4(), uuid4(), uuid4()
    field = FieldDefinition(field_id=uuid4(), name="retained", value_type="text")
    snapshot = DefinitionSnapshot(kind="field_set", fields=(field,)).model_dump(mode="json")
    with psycopg.connect(_url(postgres_database.migration_url)) as db:
        assert db.execute("SELECT to_regclass('platform_metadata.custom_entities')").fetchone() == (
            None,
        )
        db.execute(
            "UPDATE platform_module.installed_module_migrations "
            "SET revision_ids=revision_ids-'metadata_0002_custom_entities'"
            "-'metadata_0003_ui_overlays'-'metadata_0004_ui_bindings'"
            "-'metadata_0005_ui_binding_seals', "
            "revision_manifest=(SELECT jsonb_agg(value) "
            "FROM jsonb_array_elements(revision_manifest) "
            "WHERE value->>'revision' NOT IN "
            "('metadata_0002_custom_entities','metadata_0003_ui_overlays',"
            "'metadata_0004_ui_bindings','metadata_0005_ui_binding_seals')) "
            "WHERE module_id='foundation.metadata'"
        )
        assert db.execute(
            "SELECT revision_ids FROM platform_module.installed_module_migrations "
            "WHERE module_id='foundation.metadata'"
        ).fetchone() == (["metadata_0001"],)
        db.execute(
            "INSERT INTO platform_metadata.definitions (id,tenant_id,owner_module_id,"
            "resource_namespace,owner_contract_version,kind,lifecycle,draft_snapshot,created_by) "
            "VALUES (%s,%s,'foundation.party','foundation.party.party','1',"
            "'field_set','draft',%s::jsonb,%s)",
            (identity, tenant, json.dumps(snapshot), actor),
        )
        retained = db.execute("SELECT to_jsonb(d) FROM platform_metadata.definitions d").fetchall()
    migrations.upgrade(postgres_database.migration_url)
    migrations.upgrade(postgres_database.migration_url)
    assert _heads(postgres_database) == CANDIDATE_HEADS
    with psycopg.connect(_url(postgres_database.migration_url)) as db:
        assert (
            db.execute("SELECT to_jsonb(d) FROM platform_metadata.definitions d").fetchall()
            == retained
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            db.execute(
                "INSERT INTO platform_metadata.definitions SELECT %s, tenant_id,owner_module_id,"
                "resource_namespace,owner_contract_version,kind,lifecycle,draft_generation,draft_snapshot,"
                "active_revision_id,active_generation,created_by,created_at,updated_at "
                "FROM platform_metadata.definitions WHERE id=%s",
                (uuid4(), identity),
            )
        db.rollback()
    migrations.downgrade(postgres_database.migration_url, "metadata_0001")
    assert _heads(postgres_database) == BASE_HEADS
    with psycopg.connect(_url(postgres_database.migration_url)) as db:
        assert db.execute("SELECT to_regclass('platform_metadata.custom_entities')").fetchone() == (
            None,
        )
        assert (
            db.execute("SELECT to_jsonb(d) FROM platform_metadata.definitions d").fetchall()
            == retained
        )
    migrations.upgrade(postgres_database.migration_url)
    assert _heads(postgres_database) == CANDIDATE_HEADS


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["types", "current", "archived"])
async def test_downgrade_refuses_before_any_destructive_statement(
    entity_harness: Harness, postgres_database: PostgreSQLTestDatabase, state: str
) -> None:
    app, context, _, field, _ = entity_harness
    # The protected Metadata fixture installs all foundations, excluding the
    # separate example proof module. The full-graph transition test includes it.
    expected_fixture_heads = CANDIDATE_HEADS - {"proof_0004"}
    assert _heads(postgres_database) == expected_fixture_heads
    await _type(app, context, field)
    if state != "types":
        row = await _create(entity_harness)
        if state == "archived":
            await _command(
                app,
                ArchiveCustomEntity(instance_id=row.identity.instance_id, expected_version=1),
                context,
            )
    with psycopg.connect(_url(postgres_database.migration_url)) as db:
        before = db.execute(
            "SELECT to_jsonb(c) FROM platform_metadata.custom_entities c ORDER BY id"
        ).fetchall()
        types = db.execute(
            "SELECT to_jsonb(d) FROM platform_metadata.definitions d ORDER BY id"
        ).fetchall()
    with pytest.raises(RuntimeError, match="metadata_0002 downgrade refused"):
        app.runtime.migrations.downgrade(postgres_database.migration_url, "metadata_0001")
    with psycopg.connect(_url(postgres_database.migration_url)) as db:
        assert (
            db.execute(
                "SELECT to_jsonb(c) FROM platform_metadata.custom_entities c ORDER BY id"
            ).fetchall()
            == before
        )
        assert (
            db.execute(
                "SELECT to_jsonb(d) FROM platform_metadata.definitions d ORDER BY id"
            ).fetchall()
            == types
        )
        assert db.execute(
            "SELECT count(*) FROM pg_constraint WHERE conname='uq_metadata_revision_pin'"
        ).fetchone() == (1,)
    assert _heads(postgres_database) == expected_fixture_heads
