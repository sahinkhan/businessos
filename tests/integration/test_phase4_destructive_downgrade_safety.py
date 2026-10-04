"""Real PostgreSQL proof of the Phase 4 owner-local downgrade floors."""

from __future__ import annotations

from uuid import uuid4

import psycopg
import pytest

from businessos.migrations import MigrationCoordinator
from businessos.modules import ModuleRegistry, discover_modules
from businessos.modules.installation_inventory import approved_artifacts_from_operator_inventory
from businessos.version import runtime_version
from tests.conftest import PostgreSQLTestDatabase


def _coordinator(*, include_metadata: bool) -> MigrationCoordinator:
    modules = tuple(
        module
        for module in discover_modules()
        if include_metadata or module.manifest.module_id != "foundation.metadata"
    )
    registry = ModuleRegistry(
        platform_version=runtime_version(),
        sdk_version="0.1.0",
        approved_artifacts=approved_artifacts_from_operator_inventory(modules),
    )
    for module in modules:
        registry.add(module)
    return MigrationCoordinator(registry)


def _raw(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _snapshot(url: str) -> tuple[tuple[tuple[object, ...], ...], ...]:
    """Capture evidence, inventory, and SQL protections before a refusal."""
    with psycopg.connect(_raw(url)) as connection:
        return tuple(
            tuple(connection.execute(query).fetchall())
            for query in (
                "SELECT version_num FROM alembic_version ORDER BY version_num",
                "SELECT module_id, revision_manifest::text FROM "
                "platform_module.installed_module_migrations ORDER BY module_id",
                "SELECT to_jsonb(t)::text FROM platform_audit.audit_logs t ORDER BY id",
                "SELECT to_jsonb(t)::text FROM platform_policy.roles t ORDER BY id",
                "SELECT to_jsonb(t)::text FROM platform_policy.role_permissions t ORDER BY id",
                "SELECT to_jsonb(t)::text FROM platform_policy.sod_rules t ORDER BY id",
                "SELECT to_jsonb(t)::text FROM platform_policy.subject_role_assignments t "
                "ORDER BY id",
                "SELECT to_jsonb(t)::text FROM platform_policy.delegations t ORDER BY id",
                "SELECT to_jsonb(t)::text FROM platform_policy.support_access_grants t ORDER BY id",
                "SELECT to_jsonb(t)::text FROM platform_policy.record_policies t ORDER BY id",
                "SELECT to_jsonb(t)::text FROM platform_policy.field_policies t ORDER BY id",
                "SELECT to_jsonb(t)::text FROM platform_policy.approval_limits t ORDER BY id",
                "SELECT to_jsonb(t)::text FROM platform_gov.retention_policies_v2 t ORDER BY id",
                "SELECT to_jsonb(t)::text FROM platform_gov.legal_holds_v2 t ORDER BY id",
                "SELECT to_jsonb(t)::text FROM platform_gov.destructive_decisions_v2 t ORDER BY id",
                "SELECT to_jsonb(t)::text FROM platform_currency.currencies t ORDER BY code",
                "SELECT n.nspname, c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                "c.relacl::text FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname IN ('platform_audit', 'platform_policy', 'platform_gov', "
                "'eventing') AND c.relkind = 'r' ORDER BY 1, 2",
                "SELECT n.nspname, c.relname, t.tgname, pg_get_triggerdef(t.oid) "
                "FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE NOT t.tgisinternal "
                "AND n.nspname IN ('platform_audit', 'platform_policy', 'platform_gov') "
                "ORDER BY 1, 2, 3",
                "SELECT schemaname, tablename, policyname, roles::text, qual, with_check "
                "FROM pg_policies WHERE schemaname IN "
                "('platform_audit', 'platform_policy', 'platform_gov') ORDER BY 1, 2, 3",
                "SELECT n.nspname, p.proname, pg_get_functiondef(p.oid) "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname IN ('platform_audit', 'platform_policy', 'platform_gov') "
                "ORDER BY 1, 2, 3",
            )
        )


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.parametrize("include_metadata", [False, True])
def test_audit_policy_targeted_and_base_refuse_atomically(
    postgres_database: PostgreSQLTestDatabase,
    include_metadata: bool,
) -> None:
    migrations = _coordinator(include_metadata=include_metadata)
    migrations.upgrade(postgres_database.migration_url)
    tenant = uuid4()
    role = uuid4()
    with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
        connection.execute(
            "INSERT INTO platform_audit.audit_logs "
            "(id, tenant_id, actor_id, action, resource_type, checksum, integrity_version) "
            "VALUES (%s, %s, 'owner', 'oldest', 'test', %s, '1')",
            (uuid4(), tenant, "f" * 64),
        )
        connection.execute(
            "INSERT INTO platform_audit.audit_logs "
            "(id, tenant_id, actor_id, action, resource_type, checksum, integrity_version) "
            "VALUES (%s, %s, 'owner', 'legacy', 'test', %s, '2')",
            (uuid4(), tenant, "0" * 64),
        )
        connection.execute(
            "INSERT INTO platform_audit.audit_logs "
            "(id, tenant_id, actor_id, action, resource_type, checksum, integrity_version, "
            "provenance_v3, evidence_v3, source_event_id, projection_kind) "
            "VALUES (%s, %s, 'owner', 'trusted', 'test', %s, '3', '{}', '{}', %s, 'event')",
            (uuid4(), tenant, "1" * 64, uuid4()),
        )
        connection.execute(
            "INSERT INTO platform_policy.roles (id, tenant_id, code, name) "
            "VALUES (%s, %s, 'reviewer', 'Reviewer')",
            (role, tenant),
        )
        connection.execute(
            "INSERT INTO platform_policy.permissions (code, name, category) "
            "VALUES ('closeout.read', 'Read', 'test')"
        )
        connection.execute(
            "INSERT INTO platform_policy.role_permissions "
            "(id, tenant_id, role_id, permission_code) VALUES (%s, %s, %s, 'closeout.read')",
            (uuid4(), tenant, role),
        )
        subject = uuid4()
        delegatee = uuid4()
        connection.execute(
            "INSERT INTO platform_policy.subject_role_assignments "
            "(id, tenant_id, subject_id, subject_type, role_id) "
            "VALUES (%s, %s, %s, 'user', %s)",
            (uuid4(), tenant, subject, role),
        )
        connection.execute(
            "INSERT INTO platform_policy.delegations "
            "(id, tenant_id, delegator_id, delegator_type, delegatee_id, delegatee_type, "
            "role_id, valid_from, valid_to) "
            "VALUES (%s, %s, %s, 'user', %s, 'user', %s, now(), now() + interval '1 day')",
            (uuid4(), tenant, subject, delegatee, role),
        )
        connection.execute(
            "INSERT INTO platform_policy.sod_rules "
            "(id, tenant_id, code, name, permission_a, permission_b) "
            "VALUES (%s, %s, 'separation', 'Separation', 'closeout.read', 'closeout.write')",
            (uuid4(), tenant),
        )
        connection.execute(
            "INSERT INTO platform_policy.record_policies "
            "(id, tenant_id, resource_type, role_id, access_scope) "
            "VALUES (%s, %s, 'test', %s, 'owned')",
            (uuid4(), tenant, role),
        )
        connection.execute(
            "INSERT INTO platform_policy.field_policies "
            "(id, tenant_id, resource_type, field_name, role_id) "
            "VALUES (%s, %s, 'test', 'secret', %s)",
            (uuid4(), tenant, role),
        )
        connection.execute(
            "INSERT INTO platform_policy.approval_limits "
            "(id, tenant_id, action_type, currency, amount_limit, role_id) "
            "VALUES (%s, %s, 'approve', 'USD', 100, %s)",
            (uuid4(), tenant, role),
        )
        connection.execute(
            "INSERT INTO platform_policy.support_access_grants "
            "(id, tenant_id, support_principal_id, support_principal_type, approved_by, "
            "approved_by_type, reason, valid_from, valid_to) "
            "VALUES (%s, %s, %s, 'user', %s, 'user', 'closeout', now(), "
            "now() + interval '1 day')",
            (uuid4(), tenant, uuid4(), subject),
        )
        connection.commit()
    before = _snapshot(postgres_database.migration_url)
    audit_head = "metadata_0005_ui_binding_seals" if include_metadata else "audit_0006"
    assert {str(row[0]) for row in before[0]} >= {"proof_0004", "policy_0005", audit_head}
    audit_refusal = "metadata_0001" if include_metadata else "audit_0005"
    for target, reason in (
        ("audit_0004", f"{audit_refusal} downgrade refused"),
        ("audit_0002", f"{audit_refusal} downgrade refused"),
        ("policy_0004", "policy_0005 downgrade refused"),
        ("policy_0002", "policy_0005 downgrade refused"),
        ("base", "downgrade refused"),
    ):
        for _ in range(2):
            with pytest.raises(Exception, match=reason):
                migrations.downgrade(postgres_database.migration_url, target)
            assert _snapshot(postgres_database.migration_url) == before
    with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
        trigger = connection.execute(
            "SELECT 1 FROM pg_trigger WHERE tgname = 'audit_logs_append_only' AND NOT tgisinternal"
        ).fetchone()
        assert trigger is not None
    with psycopg.connect(_raw(postgres_database.runtime_url)) as connection:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant),))
        with pytest.raises(psycopg.Error):
            connection.execute("UPDATE platform_audit.audit_logs SET action = 'changed'")
        connection.rollback()
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant),))
        with pytest.raises(psycopg.Error):
            connection.execute("DELETE FROM platform_audit.audit_logs")


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.parametrize("include_metadata", [False, True])
def test_existing_prebarrier_data_survives_forward_upgrade(
    postgres_database: PostgreSQLTestDatabase,
    include_metadata: bool,
) -> None:
    migrations = _coordinator(include_metadata=include_metadata)
    migrations.upgrade(postgres_database.migration_url, "audit_0004")
    migrations.upgrade(postgres_database.migration_url, "policy_0004")
    tenant = uuid4()
    evidence = uuid4()
    with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
        connection.execute(
            "INSERT INTO platform_audit.audit_logs "
            "(id, tenant_id, actor_id, action, resource_type, checksum, integrity_version) "
            "VALUES (%s, %s, 'owner', 'existing', 'test', %s, '2')",
            (evidence, tenant, "a" * 64),
        )
        connection.commit()
    migrations.upgrade(postgres_database.migration_url)
    before = _snapshot(postgres_database.migration_url)
    assert any(str(evidence) in str(row[0]) for row in before[2])
    audit_refusal = "metadata_0001" if include_metadata else "audit_0005"
    with pytest.raises(Exception, match=f"{audit_refusal} downgrade refused"):
        migrations.downgrade(postgres_database.migration_url, "audit_0004")
    assert _snapshot(postgres_database.migration_url) == before
