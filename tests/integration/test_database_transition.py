import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from businessos_proof import ProofModule
from psycopg import sql
from sqlalchemy.engine import make_url

from businessos.database_admin import DatabaseRolePasswords, transition_database_roles
from businessos.migrations import MigrationCoordinator
from businessos.modules import ModuleRegistry


def _url_for(
    base_url: str,
    *,
    database: str,
    username: str,
    password: str,
    sqlalchemy: bool = False,
) -> str:
    url = make_url(base_url.replace("postgresql://", "postgresql+psycopg://", 1)).set(
        database=database,
        username=username,
        password=password,
    )
    rendered = url.render_as_string(hide_password=False)
    if not sqlalchemy:
        return rendered.replace("postgresql+psycopg://", "postgresql://", 1)
    return rendered


@pytest.mark.integration
@pytest.mark.postgres
def test_retained_proof_0002_database_transitions_without_data_loss() -> None:
    admin_base = os.getenv("BOS_TEST_DATABASE_ADMIN_URL")
    migration_base = os.getenv("BOS_TEST_DATABASE_MIGRATION_URL")
    runtime_base = os.getenv("BOS_TEST_DATABASE_RUNTIME_URL")
    operations_base = os.getenv("BOS_TEST_DATABASE_OPERATIONS_URL")
    if not all((admin_base, migration_base, runtime_base, operations_base)):
        pytest.skip("separated PostgreSQL test role URLs are not configured")
    assert admin_base is not None
    assert migration_base is not None
    assert runtime_base is not None
    assert operations_base is not None

    suffix = uuid4().hex
    database_name = f"businessos_retained_{suffix}"
    legacy_role = f"businessos_legacy_{suffix}"
    legacy_password = f"legacy-{suffix}"
    admin_database_url = _url_for(
        admin_base,
        database=database_name,
        username=make_url(admin_base).username or "businessos_admin",
        password=make_url(admin_base).password or "",
    )
    legacy_database_url = _url_for(
        admin_base,
        database=database_name,
        username=legacy_role,
        password=legacy_password,
    )
    migration_database_url = _url_for(
        migration_base,
        database=database_name,
        username=make_url(migration_base).username or "businessos_migrator",
        password=make_url(migration_base).password or "",
        sqlalchemy=True,
    )
    runtime_database_url = _url_for(
        runtime_base,
        database=database_name,
        username=make_url(runtime_base).username or "businessos_app",
        password=make_url(runtime_base).password or "",
    )
    record_id = uuid4()
    tenant_id = uuid4()
    event_id = uuid4()
    passwords = DatabaseRolePasswords(
        migrator=make_url(migration_base).password or "",
        application=make_url(runtime_base).password or "",
        operations=make_url(operations_base).password or "",
    )

    with psycopg.connect(admin_base, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE ROLE {} LOGIN SUPERUSER PASSWORD {}").format(
                sql.Identifier(legacy_role), sql.Literal(legacy_password)
            )
        )
        connection.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(database_name), sql.Identifier(legacy_role)
            )
        )

    try:
        legacy_sql = Path("tests/fixtures/legacy_proof_0002.sql").read_text(encoding="utf-8")
        with psycopg.connect(legacy_database_url) as connection:
            connection.execute(legacy_sql)
            connection.execute(
                "INSERT INTO mod_example_phase1_proof.proof_records "
                "(id, tenant_id, value, description) VALUES (%s, %s, %s, %s)",
                (record_id, tenant_id, "retained-value", "retained-description"),
            )
            connection.execute(
                "INSERT INTO eventing.outbox_messages "
                "(id, tenant_id, event_type, schema_version, occurred_at, correlation_id, payload) "
                "VALUES (%s, %s, 'retained.event', 1, now(), 'retained', '{}'::jsonb)",
                (event_id, tenant_id),
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            repeated_runs = tuple(
                executor.map(
                    lambda _: transition_database_roles(admin_database_url, passwords),
                    range(2),
                )
            )
        assert repeated_runs == (None, None)

        registry = ModuleRegistry(platform_version="0.1.0", sdk_version="0.1.0")
        registry.add(ProofModule())
        MigrationCoordinator(registry).upgrade(migration_database_url)

        with psycopg.connect(admin_database_url) as connection:
            retained = connection.execute(
                "SELECT value, description FROM mod_example_phase1_proof.proof_records "
                "WHERE id = %s",
                (record_id,),
            ).fetchone()
            revisions = set(
                connection.execute("SELECT version_num FROM alembic_version").fetchall()
            )
            roles = connection.execute(
                "SELECT rolname, rolsuper, rolbypassrls, rolinherit FROM pg_roles "
                "WHERE rolname IN ('businessos_migrator', 'businessos_app', 'businessos_ops') "
                "ORDER BY rolname"
            ).fetchall()
            app_can_assume_ops = connection.execute(
                "SELECT pg_has_role('businessos_app', 'businessos_ops', 'MEMBER')"
            ).fetchone()
            owners = connection.execute(
                "SELECT n.nspname, c.relname, owner.rolname "
                "FROM pg_class AS c JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                "JOIN pg_roles AS owner ON owner.oid = c.relowner "
                "WHERE (n.nspname, c.relname) IN "
                "(('eventing', 'outbox_messages'), ('eventing', 'inbox_receipts'), "
                "('platform_module', 'module_runtime_state'), "
                "('platform_module', 'installed_module_migrations'), "
                "('mod_example_phase1_proof', 'proof_records')) "
                "ORDER BY n.nspname, c.relname"
            ).fetchall()
            rls = connection.execute(
                "SELECT n.nspname, c.relname, c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class AS c JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                "WHERE (n.nspname, c.relname) IN "
                "(('eventing', 'outbox_messages'), ('eventing', 'inbox_receipts'), "
                "('mod_example_phase1_proof', 'proof_records')) ORDER BY n.nspname, c.relname"
            ).fetchall()
        assert retained == ("retained-value", "retained-description")
        assert revisions == {("0002_module_migration_inventory",), ("proof_0003",)}
        assert roles == [
            ("businessos_app", False, False, False),
            ("businessos_migrator", False, False, False),
            ("businessos_ops", False, True, False),
        ]
        assert app_can_assume_ops == (False,)
        assert all(owner == "businessos_migrator" for _, _, owner in owners)
        assert all(enabled and forced for _, _, enabled, forced in rls)

        with psycopg.connect(runtime_database_url) as connection:
            missing_context_count = connection.execute(
                "SELECT count(*) FROM mod_example_phase1_proof.proof_records"
            ).fetchone()
            connection.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
            own_record = connection.execute(
                "SELECT value FROM mod_example_phase1_proof.proof_records WHERE id = %s",
                (record_id,),
            ).fetchone()
        assert missing_context_count == (0,)
        assert own_record == ("retained-value",)

        transition_database_roles(admin_database_url, passwords)
        with psycopg.connect(admin_database_url) as connection:
            repeated = connection.execute(
                "SELECT value, description FROM mod_example_phase1_proof.proof_records "
                "WHERE id = %s",
                (record_id,),
            ).fetchone()
        assert repeated == retained
    finally:
        with psycopg.connect(admin_base, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name))
            )
            connection.execute(
                sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(legacy_role))
            )
