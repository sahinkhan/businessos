"""Real PostgreSQL witnesses for ADR-024 independent completeness authority."""

import json
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy.engine import make_url

from businessos.errors import ConfigurationError
from businessos.metadata_execution import _MetadataPool
from businessos.publication_database import _PublicationPool
from tests.conftest import PostgreSQLTestDatabase
from tests.integration.test_phase5a_metadata import _app, _Policy, _url

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.parametrize(
    "profile", ["ui_publication", "metadata", "runtime", "worker", "operations"]
)
def test_provenance_rls_and_transaction_context_reset(
    postgres_database: PostgreSQLTestDatabase,
    profile: str,
) -> None:
    tenant, overlay, view = _seed(postgres_database)
    revision = uuid4()
    with psycopg.connect(_url(postgres_database.ui_publication_url)) as connection:
        connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant),))
        _expected(connection, tenant, overlay, view, revision)
        _revision(connection, tenant, overlay, revision)
    url = getattr(postgres_database, profile + "_url")
    with psycopg.connect(_url(url), autocommit=True) as connection:
        for table in ("ui_expected_provenance", "ui_expected_members", "ui_revision_binding_seals"):
            query = f"SELECT count(*) FROM platform_metadata.{table}"
            if profile in {"runtime", "worker", "operations"}:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    with connection.transaction():
                        connection.execute(
                            "SELECT set_config('app.tenant_id',%s,true)", (str(tenant),)
                        )
                        connection.execute(query)
                continue
            assert connection.execute(query).fetchone() == (0,)
            with connection.transaction():
                connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant),))
                expected = 6 if table == "ui_expected_members" else 1
                assert connection.execute(query).fetchone() == (expected,)
            assert connection.execute(query).fetchone() == (0,)
            with connection.transaction():
                connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(uuid4()),))
                assert connection.execute(query).fetchone() == (0,)
            with pytest.raises(psycopg.errors.InvalidTextRepresentation):
                with connection.transaction():
                    connection.execute("SELECT set_config('app.tenant_id','invalid',true)")
                    connection.execute(query)
            assert connection.execute(query).fetchone() == (0,)


def test_committed_proof_and_lineage_are_immutable_to_both_runtime_profiles(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    tenant, overlay, view = _seed(postgres_database)
    revision = uuid4()
    with psycopg.connect(_url(postgres_database.ui_publication_url)) as connection:
        connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant),))
        _expected(connection, tenant, overlay, view, revision)
        _revision(connection, tenant, overlay, revision)
    for url in (postgres_database.ui_publication_url, postgres_database.metadata_url):
        with psycopg.connect(_url(url), autocommit=True) as connection:
            for table in (
                "ui_expected_provenance",
                "ui_expected_members",
                "ui_revision_binding_seals",
                "ui_revision_module_bindings",
                "ui_overlay_revisions",
                "ui_installation_lineage",
            ):
                column = "singleton" if table == "ui_installation_lineage" else "tenant_id"
                for statement in (
                    f"DELETE FROM platform_metadata.{table}",
                    f"UPDATE platform_metadata.{table} SET {column}={column}",
                ):
                    with pytest.raises(psycopg.Error):
                        with connection.transaction():
                            connection.execute(
                                "SELECT set_config('app.tenant_id',%s,true)", (str(tenant),)
                            )
                            connection.execute(statement)


@pytest.mark.asyncio
async def test_private_profile_validates_narrow_grants(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    _seed(postgres_database)
    for pool_type, url in (
        (_PublicationPool, postgres_database.ui_publication_url),
        (_MetadataPool, postgres_database.metadata_url),
    ):
        pool = pool_type(url, size=1, timeout=2, database_name=str(make_url(url).database))
        try:
            await pool.validate()
        finally:
            await pool.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["view", "default", "trigger", "grant", "verifier", "rls"])
async def test_private_profile_rejects_indirect_or_weakened_authority(
    postgres_database: PostgreSQLTestDatabase,
    tamper: str,
) -> None:
    _seed(postgres_database)
    sql = {
        "view": "CREATE VIEW platform_metadata.exposed_expected AS SELECT * FROM "
        "platform_metadata.ui_expected_members; GRANT INSERT,UPDATE,DELETE ON "
        "platform_metadata.exposed_expected TO businessos_metadata",
        "default": "ALTER DEFAULT PRIVILEGES IN SCHEMA platform_metadata GRANT INSERT "
        "ON TABLES TO businessos_metadata",
        "trigger": "CREATE FUNCTION platform_metadata.unsafe_trigger() RETURNS trigger "
        "LANGUAGE plpgsql SECURITY DEFINER AS $$ BEGIN RETURN NEW; END $$; "
        "REVOKE ALL ON FUNCTION platform_metadata.unsafe_trigger() FROM PUBLIC; "
        "CREATE TRIGGER unsafe_side_path BEFORE INSERT ON platform_metadata.ui_overlays "
        "FOR EACH ROW EXECUTE FUNCTION platform_metadata.unsafe_trigger()",
        "grant": "GRANT INSERT ON platform_metadata.ui_expected_members TO businessos_metadata",
        "verifier": "ALTER TABLE platform_metadata.ui_revision_binding_seals "
        "DISABLE TRIGGER check_ui_binding_seal",
        "rls": "ALTER TABLE platform_metadata.ui_expected_members NO FORCE ROW LEVEL SECURITY",
    }[tamper]
    with psycopg.connect(_url(postgres_database.migration_url)) as connection:
        connection.execute(sql)
    url = postgres_database.ui_publication_url
    pool = _PublicationPool(url, size=1, timeout=2, database_name=str(make_url(url).database))
    try:
        with pytest.raises(ConfigurationError):
            await pool.validate()
    finally:
        await pool.close()


def _seed(database: PostgreSQLTestDatabase) -> tuple[UUID, UUID, UUID]:
    _app(database, _Policy()).runtime.migrations.upgrade(database.migration_url)
    tenant, overlay, view = uuid4(), uuid4(), uuid4()
    with psycopg.connect(_url(database.migration_url)) as connection:
        for module in "abcdefg":
            connection.execute(
                "INSERT INTO platform_metadata.module_fence VALUES (%s,%s,1,0)",
                ("example." + module, "artifact-" + module),
            )
    with psycopg.connect(_url(database.metadata_url)) as connection:
        connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant),))
        connection.execute(
            "INSERT INTO platform_metadata.ui_overlays "
            "(id,tenant_id,view_id,scope_kind,scope_id,draft_document,"
            "draft_compatibility_digest,created_by) VALUES (%s,%s,%s,'tenant',%s,'{}',%s,%s)",
            (overlay, tenant, view, tenant, "b" * 64, uuid4()),
        )
    return tenant, overlay, view


def _expected(
    connection: psycopg.Connection[tuple[object, ...]],
    tenant: UUID,
    overlay: UUID,
    view: UUID,
    revision: UUID,
    *,
    override: dict[str, Any] | None = None,
) -> None:
    values = {
        "tenant": tenant,
        "overlay": overlay,
        "view": view,
        "revision": revision,
        "scope_kind": "tenant",
        "scope_id": tenant,
        "draft": 1,
        "active": 0,
        "document": "{}",
        "digest": "a" * 64,
        "compatibility": "b" * 64,
        "declarations": json.dumps([{"key": "base"}]),
        "schema": 1,
        "ui": 1,
    }
    values.update(override or {})
    connection.execute(
        "INSERT INTO platform_metadata.ui_expected_provenance "
        "(tenant_id,overlay_id,revision_id,view_id,scope_kind,scope_id,lineage_id,model_version,"
        "purpose,issuer_version,document,document_digest,compatibility_digest,"
        "declaration_provenance,schema_generation,ui_generation,"
        "draft_generation,prior_active_generation) "
        "SELECT %(tenant)s,%(overlay)s,%(revision)s,%(view)s,%(scope_kind)s,%(scope_id)s,"
        "lineage_id,1,'published-ui-completeness',1,%(document)s::jsonb,%(digest)s,"
        "%(compatibility)s,%(declarations)s::jsonb,%(schema)s,%(ui)s,%(draft)s,%(active)s "
        "FROM platform_metadata.ui_installation_lineage",
        values,
    )
    for module in "abcdef":
        connection.execute(
            "INSERT INTO platform_metadata.ui_expected_members VALUES (%s,%s,%s,%s,%s,1)",
            (tenant, overlay, revision, "example." + module, "artifact-" + module),
        )


def _revision(
    connection: psycopg.Connection[tuple[object, ...]],
    tenant: UUID,
    overlay: UUID,
    revision: UUID,
    *,
    members: str = "abcdef",
    wrong_artifact: bool = False,
    stale_generation: bool = False,
    document: str = "{}",
    digest: str = "a" * 64,
    declarations: str = '[{"key":"base"}]',
) -> None:
    connection.execute(
        "INSERT INTO platform_metadata.ui_overlay_revisions "
        "(id,tenant_id,overlay_id,sequence,document,digest,compatibility_digest,published_by,"
        "declaration_provenance,schema_generation,ui_generation,"
        "draft_generation,prior_active_generation) "
        "VALUES (%s,%s,%s,1,%s::jsonb,%s,%s,%s,%s::jsonb,1,1,1,0)",
        (revision, tenant, overlay, document, digest, "b" * 64, uuid4(), declarations),
    )
    for module in members:
        connection.execute(
            "INSERT INTO platform_metadata.ui_revision_module_bindings "
            "(tenant_id,overlay_id,revision_id,module_id,artifact_identity,generation) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (
                tenant,
                overlay,
                revision,
                "example." + module,
                "wrong" if wrong_artifact else "artifact-" + module,
                2 if stale_generation else 1,
            ),
        )
    connection.execute(
        "INSERT INTO platform_metadata.ui_revision_binding_seals VALUES (%s,%s,%s)",
        (tenant, overlay, revision),
    )
    connection.execute(
        "UPDATE platform_metadata.ui_overlays SET lifecycle='published',active_revision_id=%s,"
        "active_generation=1 WHERE tenant_id=%s AND id=%s",
        (revision, tenant, overlay),
    )


@pytest.mark.parametrize(
    "members", ["a", "bcdef", "abdef", "abcde", "abcdee", "abcdeff", "abcdefg", "abcdeg"]
)
def test_sql_rejects_incomplete_or_duplicate_binding_set(
    postgres_database: PostgreSQLTestDatabase,
    members: str,
) -> None:
    tenant, overlay, view = _seed(postgres_database)
    revision = uuid4()
    with pytest.raises(psycopg.Error):
        with psycopg.connect(_url(postgres_database.ui_publication_url)) as connection:
            connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant),))
            _expected(connection, tenant, overlay, view, revision)
            _revision(connection, tenant, overlay, revision, members=members)
    with psycopg.connect(_url(postgres_database.migration_url)) as connection:
        assert connection.execute(
            "SELECT count(*) FROM platform_metadata.ui_expected_provenance"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM platform_metadata.ui_overlay_revisions"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT sum(active_bindings) FROM platform_metadata.module_fence"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT active_revision_id FROM platform_metadata.ui_overlays"
        ).fetchone() == (None,)


def test_private_exact_set_seals_and_ordinary_subset_exploit_is_rejected(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    tenant, overlay, view = _seed(postgres_database)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with psycopg.connect(_url(postgres_database.metadata_url)) as connection:
            connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant),))
            _expected(connection, tenant, overlay, view, uuid4())
    with pytest.raises(psycopg.errors.RaiseException, match="authenticated expected context"):
        with psycopg.connect(_url(postgres_database.metadata_url)) as connection:
            connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant),))
            _revision(connection, tenant, overlay, uuid4(), members="a")
    revision = uuid4()
    with psycopg.connect(_url(postgres_database.ui_publication_url)) as connection:
        connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant),))
        _expected(connection, tenant, overlay, view, revision)
        _revision(connection, tenant, overlay, revision)
    with psycopg.connect(_url(postgres_database.migration_url)) as connection:
        assert connection.execute(
            "SELECT sum(active_bindings) FROM platform_metadata.module_fence"
        ).fetchone() == (6,)
        assert connection.execute(
            "SELECT active_revision_id FROM platform_metadata.ui_overlays"
        ).fetchone() == (revision,)


@pytest.mark.parametrize(
    "field",
    [
        "tenant",
        "overlay",
        "view",
        "revision",
        "scope_id",
        "scope_kind",
        "draft",
        "active",
        "document",
        "digest",
        "compatibility",
        "declarations",
        "schema",
        "ui",
    ],
)
def test_sql_rejects_provenance_context_substitution(
    postgres_database: PostgreSQLTestDatabase,
    field: str,
) -> None:
    tenant, overlay, view = _seed(postgres_database)
    bad: dict[str, object] = {
        "tenant": uuid4(),
        "overlay": uuid4(),
        "view": uuid4(),
        "revision": uuid4(),
        "scope_id": uuid4(),
        "scope_kind": "company",
        "draft": 2,
        "active": 1,
        "document": '{"substituted":true}',
        "digest": "c" * 64,
        "compatibility": "c" * 64,
        "declarations": '[{"key":"other"}]',
        "schema": 2,
        "ui": 2,
    }
    with pytest.raises(psycopg.Error):
        with psycopg.connect(_url(postgres_database.ui_publication_url)) as connection:
            connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant),))
            revision = uuid4()
            _expected(connection, tenant, overlay, view, revision, override={field: bad[field]})
            _revision(connection, tenant, overlay, revision)
    with psycopg.connect(_url(postgres_database.migration_url)) as connection:
        assert connection.execute(
            "SELECT count(*) FROM platform_metadata.ui_expected_provenance"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT active_revision_id FROM platform_metadata.ui_overlays"
        ).fetchone() == (None,)


@pytest.mark.parametrize("wrong_artifact,stale_generation", [(True, False), (False, True)])
def test_sql_rejects_same_count_wrong_identity(
    postgres_database: PostgreSQLTestDatabase,
    wrong_artifact: bool,
    stale_generation: bool,
) -> None:
    tenant, overlay, view = _seed(postgres_database)
    with pytest.raises(psycopg.errors.RaiseException, match="authenticated complete set"):
        with psycopg.connect(_url(postgres_database.ui_publication_url)) as connection:
            connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant),))
            revision = uuid4()
            _expected(connection, tenant, overlay, view, revision)
            _revision(
                connection,
                tenant,
                overlay,
                revision,
                wrong_artifact=wrong_artifact,
                stale_generation=stale_generation,
            )


def test_ordinary_metadata_cannot_mutate_or_assume_issuance_authority(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    _seed(postgres_database)
    with psycopg.connect(_url(postgres_database.metadata_url), autocommit=True) as connection:
        for statement in (
            "INSERT INTO platform_metadata.ui_expected_members DEFAULT VALUES",
            "UPDATE platform_metadata.ui_expected_members SET generation=2",
            "DELETE FROM platform_metadata.ui_expected_members",
            "UPDATE platform_metadata.ui_expected_provenance SET issuer_version=1",
            "DELETE FROM platform_metadata.ui_expected_provenance",
            "UPDATE platform_metadata.ui_installation_lineage SET lineage_id=gen_random_uuid()",
            "UPDATE platform_metadata.module_fence SET active_bindings=0",
            "UPDATE platform_metadata.module_fence SET generation=2",
            "UPDATE platform_metadata.module_fence SET artifact_identity='forged'",
            "SET ROLE businessos_ui_publication",
            "SET ROLE businessos_metadata_fence_owner",
            "SELECT platform_metadata.adjust_ui_active_bindings()",
            "SELECT platform_metadata.adjust_active_bindings()",
            "SELECT platform_metadata.check_ui_expected_header()",
            "CREATE VIEW platform_metadata.forged AS SELECT 1",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(statement)


def test_candidate_0005_seal_cannot_be_backfilled_as_trusted_provenance(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    migrations = _app(postgres_database, _Policy()).runtime.migrations
    migrations.upgrade(postgres_database.migration_url, "metadata_0005_ui_binding_seals")
    tenant, overlay, view, revision = (uuid4() for _ in range(4))
    with psycopg.connect(_url(postgres_database.migration_url)) as connection:
        connection.execute(
            "INSERT INTO platform_metadata.module_fence VALUES ('example.a','a',1,0)"
        )
        connection.execute(
            "INSERT INTO platform_metadata.ui_overlays "
            "(id,tenant_id,view_id,scope_kind,scope_id,draft_document,"
            "draft_compatibility_digest,created_by) "
            "VALUES (%s,%s,%s,'tenant',%s,'{}',%s,%s)",
            (overlay, tenant, view, tenant, "b" * 64, uuid4()),
        )
        connection.execute(
            "INSERT INTO platform_metadata.ui_overlay_revisions "
            "(id,tenant_id,overlay_id,sequence,document,digest,compatibility_digest,published_by) "
            "VALUES (%s,%s,%s,1,'{}',%s,%s,%s)",
            (revision, tenant, overlay, "a" * 64, "b" * 64, uuid4()),
        )
        connection.execute(
            "INSERT INTO platform_metadata.ui_revision_module_bindings "
            "VALUES (%s,%s,%s,'example.a','a',1)",
            (tenant, overlay, revision),
        )
        connection.execute(
            "INSERT INTO platform_metadata.ui_revision_binding_seals VALUES (%s,%s,%s)",
            (tenant, overlay, revision),
        )
        before = connection.execute(
            "SELECT pg_get_functiondef('platform_metadata.check_ui_binding_seal()'::regprocedure)"
        ).fetchone()
    with pytest.raises(RuntimeError, match="unauthenticated UI revision history"):
        migrations.upgrade(postgres_database.migration_url, "metadata_0006_ui_provenance")
    with psycopg.connect(_url(postgres_database.migration_url)) as connection:
        assert connection.execute(
            "SELECT to_regclass('platform_metadata.ui_expected_provenance')"
        ).fetchone() == (None,)
        assert (
            connection.execute(
                "SELECT pg_get_functiondef("
                "'platform_metadata.check_ui_binding_seal()'::regprocedure)"
            ).fetchone()
            == before
        )
        assert connection.execute(
            "SELECT count(*) FROM platform_metadata.ui_revision_binding_seals"
        ).fetchone() == (1,)


def test_provenance_migration_grants_and_replay(postgres_database: PostgreSQLTestDatabase) -> None:
    app = _app(postgres_database, _Policy())
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    with psycopg.connect(_url(postgres_database.migration_url)) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version WHERE version_num LIKE 'metadata_%'"
        ).fetchone() == ("metadata_0006_ui_provenance",)
        for table in ("ui_expected_provenance", "ui_expected_members"):
            qualified = "platform_metadata." + table
            assert connection.execute(
                "SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass",
                (qualified,),
            ).fetchone() == (True, True)
            for role in (
                "businessos_metadata",
                "businessos_app",
                "businessos_worker",
                "businessos_ops",
                "businessos_governance",
            ):
                assert connection.execute(
                    "SELECT has_table_privilege(%s,%s,'INSERT,UPDATE,DELETE,TRUNCATE') "
                    "OR has_any_column_privilege(%s,%s,'INSERT,UPDATE')",
                    (role, qualified, role, qualified),
                ).fetchone() == (False,)
            assert connection.execute(
                "SELECT has_table_privilege('businessos_ui_publication',%s,'INSERT')",
                (qualified,),
            ).fetchone() == (True,)
        assert connection.execute(
            "SELECT has_column_privilege('businessos_metadata','platform_metadata.module_fence',"
            "'active_bindings','UPDATE') OR has_column_privilege('businessos_metadata',"
            "'platform_metadata.module_fence','artifact_identity','UPDATE')"
        ).fetchone() == (False,)
        assert connection.execute(
            "SELECT rolcanlogin,rolsuper,rolinherit,rolbypassrls FROM pg_roles "
            "WHERE rolname='businessos_ui_publication'"
        ).fetchone() == (True, False, False, False)
        assert connection.execute(
            "SELECT pg_has_role('businessos_metadata','businessos_ui_publication','MEMBER')"
        ).fetchone() == (False,)
        assert connection.execute(
            "SELECT count(*) FROM platform_metadata.ui_installation_lineage"
        ).fetchone() == (1,)
