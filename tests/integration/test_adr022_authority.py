"""Real PostgreSQL checks for ADR-022's protected execution boundary."""

import asyncio
from dataclasses import replace
from typing import Any, cast
from uuid import uuid4

import psycopg
import pytest
from businessos_data_governance import (
    CheckPurgeEligibilityQuery,
    CreateTenantClassificationV2Command,
    LegalHoldRecord,
    PlaceLegalHoldCommand,
)
from sqlalchemy import text
from sqlalchemy.engine import make_url

from businessos.activation import ContributionGeneration
from businessos.application import BusinessOSApplication
from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.context import RequestContext, TenantContext
from businessos.errors import ConfigurationError, NotFoundError
from businessos.messages import Command
from businessos.modules import discover_modules
from businessos.persistence import PendingOutboxMessage
from businessos.security import Authorizer
from tests.conftest import PostgreSQLTestDatabase


def _raw(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _application(database: PostgreSQLTestDatabase) -> BusinessOSApplication:
    return create_application(
        Settings(
            environment="test",
            database_url=database.runtime_url,
            governance_database_url=database.governance_url,
        ),
        modules=(
            module
            for module in discover_modules()
            if module.manifest.module_id.startswith("foundation.")
        ),
        authorizer=Authorizer(_AllowAllPolicy()),
    )


class _AllowAllPolicy:
    async def is_allowed(self, principal_id: Any, tenant: TenantContext, permission: str) -> bool:
        return True


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_adr022_startup_rejects_budget_above_postgresql_capacity(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = create_application(
        Settings(
            environment="test",
            database_url=postgres_database.runtime_url,
            governance_database_url=postgres_database.governance_url,
            database_connection_budget=10_000,
        ),
        modules=(
            module
            for module in discover_modules()
            if module.manifest.module_id.startswith("foundation.")
        ),
        authorizer=Authorizer(_AllowAllPolicy()),
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    with pytest.raises(ConfigurationError, match="PostgreSQL capacity"):
        await app.startup()
    await app.shutdown()


def _privilege(
    connection: psycopg.Connection[tuple[Any, ...]], role: str, table: str, operation: str
) -> bool:
    row = connection.execute(
        "SELECT has_table_privilege(%s, %s, %s)", (role, table, operation)
    ).fetchone()
    assert row is not None
    return bool(row[0])


@pytest.mark.integration
@pytest.mark.postgres
def test_adr022_exact_role_grants_and_tenant_rls(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = _application(postgres_database)
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)

    with psycopg.connect(postgres_database.administrator_url) as admin:
        role = admin.execute(
            "SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolinherit, "
            "rolbypassrls FROM pg_roles WHERE rolname = 'businessos_governance'"
        ).fetchone()
        memberships = admin.execute(
            "SELECT member.rolname, granted.rolname FROM pg_auth_members AS link "
            "JOIN pg_roles AS member ON member.oid = link.member "
            "JOIN pg_roles AS granted ON granted.oid = link.roleid "
            "WHERE member.rolname = 'businessos_governance' "
            "OR granted.rolname = 'businessos_governance'"
        ).fetchall()
        assert role == (True, False, False, False, False, False)
        assert memberships == []
        for table in ("retention_policies", "legal_holds"):
            qualified = f"platform_gov.{table}"
            for ordinary in ("businessos_app", "businessos_worker"):
                for operation in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                    assert not _privilege(admin, ordinary, qualified, operation)
            for operation in ("SELECT", "INSERT", "UPDATE"):
                assert _privilege(admin, "businessos_governance", qualified, operation)
        for qualified in ("platform_audit.audit_logs", "eventing.outbox_messages"):
            for operation in ("SELECT", "INSERT"):
                assert _privilege(admin, "businessos_governance", qualified, operation)
            for operation in ("UPDATE", "DELETE", "TRUNCATE"):
                assert not _privilege(admin, "businessos_governance", qualified, operation)
        for qualified in ("eventing.inbox_receipts", "eventing.event_subscriber_obligations"):
            for operation in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                assert not _privilege(admin, "businessos_governance", qualified, operation)
        protected = admin.execute(
            "SELECT n.nspname, c.relname, c.relrowsecurity, c.relforcerowsecurity "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE (n.nspname, c.relname) IN "
            "(('platform_gov','retention_policies'),('platform_gov','legal_holds'),"
            "('platform_audit','audit_logs'),('eventing','outbox_messages'))"
        ).fetchall()
        assert len(protected) == 4
        assert all(row[2:] == (True, True) for row in protected)

    tenant_a, tenant_b, hold_id = uuid4(), uuid4(), uuid4()
    with psycopg.connect(_raw(postgres_database.governance_url)) as governance:
        assert governance.execute("SELECT current_user, session_user").fetchone() == (
            "businessos_governance",
            "businessos_governance",
        )
        governance.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_a),))
        governance.execute(
            "INSERT INTO platform_gov.legal_holds "
            "(id, tenant_id, code, name, reason, entity_type, entity_id, placed_by, "
            "placed_at, is_active) VALUES "
            "(%s,%s,'case','Case','reason','party','1','actor',now(),true)",
            (hold_id, tenant_a),
        )
        governance.commit()
        governance.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_b),))
        assert (
            governance.execute(
                "SELECT id FROM platform_gov.legal_holds WHERE id = %s", (hold_id,)
            ).fetchall()
            == []
        )
        assert (
            governance.execute(
                "UPDATE platform_gov.legal_holds SET is_active = false WHERE id = %s",
                (hold_id,),
            ).rowcount
            == 0
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            governance.execute(
                "INSERT INTO platform_gov.legal_holds "
                "(id, tenant_id, code, name, reason, entity_type, entity_id, placed_by, "
                "placed_at, is_active) VALUES (%s,%s,'other','Other','reason','party','2',"
                "'actor',now(),true)",
                (uuid4(), tenant_a),
            )

    for ordinary_url in (postgres_database.runtime_url, postgres_database.worker_url):
        with psycopg.connect(_raw(ordinary_url)) as ordinary_connection:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                ordinary_connection.execute("SET ROLE businessos_governance")
            ordinary_connection.rollback()
            ordinary_connection.execute(
                "SELECT set_config('app.tenant_id', %s, false)", (str(tenant_a),)
            )
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                ordinary_connection.execute(
                    "UPDATE platform_gov.legal_holds SET is_active = false WHERE id = %s",
                    (hold_id,),
                )
    for target in ("businessos_migrator", "businessos_ops"):
        with psycopg.connect(_raw(postgres_database.governance_url)) as governance:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                governance.execute(f"SET ROLE {target}")


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_adr022_exact_routing_identity_and_failed_rotation(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = _application(postgres_database)
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    await app.startup()
    dispatcher = app.runtime.messages
    authority = dispatcher._protected_database
    assert authority is not None
    tenant = TenantContext(
        installation_id=uuid4(),
        tenant_id=uuid4(),
        principal_id=uuid4(),
        authentication_strength="mfa",
    )
    protected_command = PlaceLegalHoldCommand(
        tenant_id=tenant.tenant_id,
        code="case",
        name="Case",
        reason="reason",
        entity_type="party",
        entity_id="1",
        placed_by="actor",
    )
    protected = dispatcher.commands.resolve(protected_command)
    ordinary_command = CreateTenantClassificationV2Command(
        code="PERSONAL",
        name="Personal",
        sensitivity_level=3,
    )
    ordinary = dispatcher.commands.resolve(ordinary_command)
    query = dispatcher.queries.resolve(
        CheckPurgeEligibilityQuery(
            tenant_id=tenant.tenant_id,
            entity_type="party",
            entity_id="1",
            record_age_days=30,
        )
    )
    assert authority.requires_protected(protected, type(protected_command))
    assert not authority.requires_protected(ordinary, type(ordinary_command))
    assert not authority.requires_protected(query, cast(type[Command], CheckPurgeEligibilityQuery))
    request = RequestContext(correlation_id="adr022-dispatch", trace_id=uuid4().hex, tenant=tenant)
    async with app.container.request_scope() as dependencies:
        result = await dispatcher.command(protected_command, request, dependencies)
    assert isinstance(result, LegalHoldRecord)
    assert result.tenant_id == tenant.tenant_id
    with psycopg.connect(_raw(postgres_database.governance_url)) as governance:
        governance.execute(
            "SELECT set_config('app.tenant_id', %s, false)", (str(tenant.tenant_id),)
        )
        assert governance.execute(
            "SELECT id FROM platform_gov.legal_holds WHERE id = %s", (result.id,)
        ).fetchone() == (result.id,)
    async with authority.for_command(protected, type(protected_command), tenant) as uow:
        async with uow:
            assert (
                await uow.persistence.execute(text("SELECT current_user, session_user"))
            ).one() == ("businessos_governance", "businessos_governance")
    with pytest.raises(PermissionError):
        async with authority.for_command(ordinary, type(ordinary_command), tenant):
            pass
    with pytest.raises(PermissionError):
        async with authority.for_command(replace(protected), type(protected_command), tenant):
            pass
    assert protected.generation is not None
    stale = replace(
        protected,
        generation=ContributionGeneration(protected.owner, protected.generation.number + 1),
    )
    with pytest.raises(PermissionError):
        async with authority.for_command(stale, type(protected_command), tenant):
            pass
    async with dispatcher._unit_of_work_factory.for_tenant(tenant) as ordinary_uow:
        assert (
            await ordinary_uow.persistence.execute(text("SELECT current_user, session_user"))
        ).one() == ("businessos_app", "businessos_app")
    wrong_credential = postgres_database.runtime_url
    with pytest.raises(ConfigurationError, match="identity mismatch"):
        await authority.rotate(wrong_credential)
    with pytest.raises(ConfigurationError, match="unavailable"):
        async with authority.for_command(protected, type(protected_command), tenant):
            pass
    await authority.rotate(postgres_database.governance_url)
    async with authority.for_command(protected, type(protected_command), tenant) as restored_uow:
        async with restored_uow:
            assert (
                await restored_uow.persistence.execute(text("SELECT current_user"))
            ).scalar_one() == "businessos_governance"
    await app.shutdown()
    with pytest.raises(ConfigurationError, match="closed"):
        await authority.rotate(postgres_database.governance_url)


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_adr022_one_uow_commit_cancellation_and_next_tenant(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = _application(postgres_database)
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    await app.startup()
    authority = app.runtime.messages._protected_database
    assert authority is not None
    tenant_a, tenant_b = uuid4(), uuid4()
    context_a = TenantContext(
        installation_id=uuid4(),
        tenant_id=tenant_a,
        principal_id=uuid4(),
        authentication_strength="mfa",
    )
    context_b = replace(context_a, tenant_id=tenant_b)
    command = PlaceLegalHoldCommand(
        tenant_id=tenant_a,
        code="case",
        name="Case",
        reason="reason",
        entity_type="party",
        entity_id="1",
        placed_by="actor",
    )
    registered = app.runtime.messages.commands.resolve(command)
    committed_hold, committed_audit, committed_event = uuid4(), uuid4(), uuid4()
    cancelled_hold, cancelled_audit, cancelled_event = uuid4(), uuid4(), uuid4()

    async def write_chain(uow: Any, tenant_id: Any, hold: Any, audit: Any, event: Any) -> None:
        first_xid = (await uow.persistence.execute(text("SELECT txid_current()"))).scalar_one()
        await uow.persistence.execute(
            text(
                "INSERT INTO platform_gov.legal_holds "
                "(id, tenant_id, code, name, reason, entity_type, entity_id, placed_by, "
                "placed_at, is_active) VALUES "
                "(:id,:tenant,'case','Case','reason','party','1','actor',now(),true)"
            ),
            {"id": hold, "tenant": tenant_id},
        )
        await uow.persistence.execute(
            text(
                "INSERT INTO platform_audit.audit_logs "
                "(id,tenant_id,actor_id,action,resource_type,checksum,integrity_version) "
                "VALUES (:id,:tenant,'actor','hold','party',:checksum,'2')"
            ),
            {"id": audit, "tenant": tenant_id, "checksum": "0" * 64},
        )
        uow.add_outbox(
            PendingOutboxMessage(
                event_id=event,
                tenant_id=tenant_id,
                event_type="adr022.certification",
                schema_version=1,
                correlation_id="adr022-certification",
                payload={},
            )
        )
        await uow.persistence.flush()
        last_xid = (await uow.persistence.execute(text("SELECT txid_current()"))).scalar_one()
        assert first_xid == last_xid

    try:
        async with authority.for_command(registered, type(command), context_a) as uow:
            async with uow:
                await write_chain(uow, tenant_a, committed_hold, committed_audit, committed_event)
                await uow.commit()

        with pytest.raises(asyncio.CancelledError):
            async with authority.for_command(registered, type(command), context_b) as uow:
                async with uow:
                    await write_chain(
                        uow, tenant_b, cancelled_hold, cancelled_audit, cancelled_event
                    )
                    raise asyncio.CancelledError

        with psycopg.connect(_raw(postgres_database.migration_url)) as migrator:
            for qualified, committed, cancelled in (
                ("platform_gov.legal_holds", committed_hold, cancelled_hold),
                ("platform_audit.audit_logs", committed_audit, cancelled_audit),
                ("eventing.outbox_messages", committed_event, cancelled_event),
            ):
                assert migrator.execute(
                    f"SELECT id FROM {qualified} WHERE id = %s", (committed,)
                ).fetchone() == (committed,)
                assert (
                    migrator.execute(
                        f"SELECT id FROM {qualified} WHERE id = %s", (cancelled,)
                    ).fetchone()
                    is None
                )

        async with authority.for_command(registered, type(command), context_b) as uow:
            async with uow:
                current = (
                    await uow.persistence.execute(
                        text("SELECT current_user, current_setting('app.tenant_id')")
                    )
                ).one()
                assert current == ("businessos_governance", str(tenant_b))
                assert (
                    await uow.persistence.execute(
                        text("SELECT id FROM platform_gov.legal_holds WHERE id = :id"),
                        {"id": committed_hold},
                    )
                ).first() is None
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
def test_adr022_upgrade_rejects_indirect_ordinary_writer(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = _application(postgres_database)
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url, "gov_0003")
    writer = f"adr022_writer_{uuid4().hex}"
    with psycopg.connect(postgres_database.administrator_url, autocommit=True) as admin:
        admin.execute(f'CREATE ROLE "{writer}"')
        admin.execute(f'GRANT UPDATE ON platform_gov.legal_holds TO "{writer}"')
        admin.execute(f'GRANT "{writer}" TO businessos_app')
    try:
        with pytest.raises(RuntimeError, match="ordinary Governance role membership"):
            app.runtime.migrations.upgrade(postgres_database.migration_url)
    finally:
        with psycopg.connect(postgres_database.administrator_url, autocommit=True) as admin:
            admin.execute(f'REVOKE "{writer}" FROM businessos_app')
            admin.execute(f'REVOKE UPDATE ON platform_gov.legal_holds FROM "{writer}"')
            admin.execute(f'DROP ROLE "{writer}"')


@pytest.mark.integration
@pytest.mark.postgres
def test_adr022_upgrade_removes_legacy_public_write(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = _application(postgres_database)
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url, "gov_0003")
    with psycopg.connect(postgres_database.administrator_url, autocommit=True) as admin:
        admin.execute("GRANT UPDATE ON platform_gov.legal_holds TO PUBLIC")
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    with psycopg.connect(postgres_database.administrator_url) as admin:
        assert not _privilege(admin, "businessos_app", "platform_gov.legal_holds", "UPDATE")
        assert not _privilege(admin, "businessos_worker", "platform_gov.legal_holds", "UPDATE")


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_adr022_rotation_rejects_grant_drift_and_draining_generation(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = _application(postgres_database)
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    await app.startup()
    authority = app.runtime.messages._protected_database
    assert authority is not None
    tenant = TenantContext(
        installation_id=uuid4(),
        tenant_id=uuid4(),
        principal_id=uuid4(),
        authentication_strength="mfa",
    )
    command = PlaceLegalHoldCommand(
        tenant_id=tenant.tenant_id,
        code="case",
        name="Case",
        reason="reason",
        entity_type="party",
        entity_id="1",
        placed_by="actor",
    )
    registered = app.runtime.messages.commands.resolve(command)
    assert registered.generation is not None
    try:
        with pytest.raises(ConfigurationError, match="endpoint mismatch"):
            await authority.rotate(
                make_url(postgres_database.governance_url)
                .set(host="other")
                .render_as_string(hide_password=False)
            )
        with pytest.raises(ConfigurationError, match="unavailable"):
            async with authority.for_command(registered, type(command), tenant):
                pass
        with psycopg.connect(postgres_database.administrator_url, autocommit=True) as admin:
            admin.execute("GRANT UPDATE ON platform_audit.audit_logs TO businessos_governance")
        try:
            with pytest.raises(ConfigurationError, match="grants are unsafe"):
                await authority.rotate(postgres_database.governance_url)
        finally:
            with psycopg.connect(postgres_database.administrator_url, autocommit=True) as admin:
                admin.execute(
                    "REVOKE UPDATE ON platform_audit.audit_logs FROM businessos_governance"
                )
        await authority.rotate(postgres_database.governance_url)
        with psycopg.connect(postgres_database.administrator_url, autocommit=True) as admin:
            admin.execute(
                "GRANT UPDATE (event_type) ON eventing.outbox_messages TO businessos_governance"
            )
        try:
            with pytest.raises(ConfigurationError, match="grants are unsafe"):
                await authority.rotate(postgres_database.governance_url)
        finally:
            with psycopg.connect(postgres_database.administrator_url, autocommit=True) as admin:
                admin.execute(
                    "REVOKE UPDATE (event_type) ON eventing.outbox_messages "
                    "FROM businessos_governance"
                )
        await authority.rotate(postgres_database.governance_url)
        with psycopg.connect(postgres_database.administrator_url, autocommit=True) as admin:
            admin.execute(
                "GRANT UPDATE (id) ON platform_gov.classification_definitions "
                "TO businessos_governance"
            )
        try:
            with pytest.raises(ConfigurationError, match="grants are unsafe"):
                await authority.rotate(postgres_database.governance_url)
        finally:
            with psycopg.connect(postgres_database.administrator_url, autocommit=True) as admin:
                admin.execute(
                    "REVOKE UPDATE (id) ON platform_gov.classification_definitions "
                    "FROM businessos_governance"
                )
        await authority.rotate(postgres_database.governance_url)
        async with app.runtime.contributions.admit(registered.generation):
            draining = asyncio.create_task(
                app.runtime.contributions.close_and_drain(registered.generation, timeout_seconds=2)
            )
            await asyncio.sleep(0)
            with pytest.raises(NotFoundError, match="not active"):
                async with authority.for_command(registered, type(command), tenant):
                    pass
        await draining
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_adr022_protected_admission_checks_grants_without_readiness(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = _application(postgres_database)
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    await app.startup()
    authority = app.runtime.messages._protected_database
    assert authority is not None
    tenant = TenantContext(installation_id=uuid4(), tenant_id=uuid4(), principal_id=uuid4())
    command = PlaceLegalHoldCommand(
        tenant_id=tenant.tenant_id,
        code="case",
        name="Case",
        reason="reason",
        entity_type="party",
        entity_id="1",
        placed_by="actor",
    )
    registered = app.runtime.messages.commands.resolve(command)
    try:
        with psycopg.connect(postgres_database.administrator_url, autocommit=True) as admin:
            admin.execute("GRANT UPDATE ON platform_audit.audit_logs TO businessos_governance")
        try:
            with pytest.raises(ConfigurationError, match="grants are unsafe"):
                async with authority.for_command(registered, type(command), tenant):
                    pytest.fail("Unsafe protected command was admitted")
        finally:
            with psycopg.connect(postgres_database.administrator_url, autocommit=True) as admin:
                admin.execute(
                    "REVOKE UPDATE ON platform_audit.audit_logs FROM businessos_governance"
                )
        with pytest.raises(ConfigurationError, match="unavailable"):
            async with authority.for_command(registered, type(command), tenant):
                pytest.fail("Failed profile remained active")
    finally:
        await app.shutdown()
