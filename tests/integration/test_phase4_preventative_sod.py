"""PostgreSQL proof for the supported preventative SoD mutation boundary."""

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from businessos_policy import (
    AssignPermissionToRoleCommand,
    AssignRoleToSubjectCommand,
    CreateDelegationCommand,
    CreateRoleCommand,
    CreateSoDRuleCommand,
    PolicyModule,
    RegisterPermissionCommand,
    RoleRecord,
    ScopeType,
    SoDSeverity,
)
from businessos_policy.delegation_authority import authority_lock_key

from businessos.application import BusinessOSApplication
from businessos.bootstrap import create_application
from businessos.context import RequestContext
from businessos.errors import BusinessOSError
from businessos.modules import discover_modules
from businessos.security import Authorizer
from tests.conftest import PostgreSQLTestDatabase
from tests.integration.test_phase2_foundations import (
    AllowAllPolicy,
    _context,
    _dispatch,
    _seed_tenant,
    _settings,
)


async def _app(database: PostgreSQLTestDatabase) -> BusinessOSApplication:
    app = create_application(
        _settings(database.runtime_url),
        modules=tuple(
            PolicyModule() if module.manifest.module_id == "foundation.policy" else module
            for module in discover_modules()
            if module.manifest.module_id
            in {
                "foundation.tenant",
                "foundation.identity",
                "foundation.organization",
                "foundation.currency",
                "foundation.geography",
                "foundation.reference_data",
                "foundation.uom",
                "foundation.party",
                "foundation.policy",
            }
        ),
        authorizer=Authorizer(AllowAllPolicy()),
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(database.migration_url)
    await app.startup()
    return app


async def _role(
    app: BusinessOSApplication,
    tenant: UUID,
    actor: RequestContext,
    code: str,
    parent: UUID | None = None,
) -> UUID:
    record = cast(
        RoleRecord,
        await _dispatch(
            app,
            CreateRoleCommand(tenant_id=tenant, code=code, name=code, parent_role_id=parent),
            actor,
        ),
    )
    return record.id


async def _permission(
    app: BusinessOSApplication, tenant: UUID, actor: RequestContext, role: UUID, code: str
) -> None:
    await _dispatch(
        app,
        AssignPermissionToRoleCommand(tenant_id=tenant, role_id=role, permission_code=code),
        actor,
    )


async def _assign(
    app: BusinessOSApplication,
    tenant: UUID,
    actor: RequestContext,
    role: UUID,
    subject: UUID,
    kind: Literal["user", "service_account", "device"] = "user",
) -> None:
    await _dispatch(
        app,
        AssignRoleToSubjectCommand(
            tenant_id=tenant,
            role_id=role,
            subject_id=subject,
            subject_type=kind,
            scope_type=ScopeType.TENANT,
        ),
        actor,
    )


async def _delegate(
    app: BusinessOSApplication,
    tenant: UUID,
    actor: RequestContext,
    role: UUID,
    source: UUID,
    recipient: UUID,
    *,
    minutes: int = 60,
) -> None:
    now = datetime.now(UTC)
    await _dispatch(
        app,
        CreateDelegationCommand(
            tenant_id=tenant,
            delegator_id=source,
            delegator_type="user",
            delegatee_id=recipient,
            delegatee_type="user",
            role_id=role,
            scope_type=ScopeType.TENANT,
            valid_from=now,
            valid_to=now + timedelta(minutes=minutes),
        ),
        actor,
    )


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_create_role_rejects_the_257th_role_before_insert(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = await _app(postgres_database)
    tenant, actor_id = uuid4(), uuid4()
    _seed_tenant(postgres_database.migration_url, tenant, "sod-role-bound", status="active")
    actor = _context(tenant, actor_id)
    dsn = postgres_database.runtime_url.replace("postgresql+psycopg://", "postgresql://")
    try:
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            await connection.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant),))
            async with connection.cursor() as cursor:
                await cursor.executemany(
                    "INSERT INTO platform_policy.roles "
                    "(id, tenant_id, code, name, created_at, updated_at) "
                    "VALUES (%s, %s, %s, %s, now(), now())",
                    [(uuid4(), tenant, f"bound-{i}", f"Bound {i}") for i in range(256)],
                )

        with pytest.raises(BusinessOSError) as denied:
            await _role(app, tenant, actor, "bound-256")
        assert denied.value.code == "authority_unbounded"
        async with await psycopg.AsyncConnection.connect(dsn) as connection:
            await connection.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant),))
            result = await connection.execute(
                "SELECT count(*) FROM platform_policy.roles WHERE tenant_id = %s", (tenant,)
            )
            row = await result.fetchone()
            assert row is not None and row[0] == 256
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_supported_mutations_reject_projected_preventative_conflicts(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = await _app(postgres_database)
    tenant, actor_id = uuid4(), uuid4()
    _seed_tenant(postgres_database.migration_url, tenant, "sod-mutations", status="active")
    actor = _context(tenant, actor_id)
    try:
        for code in ("sod.first", "sod.second"):
            await _dispatch(
                app, RegisterPermissionCommand(code=code, name=code, category="sod"), actor
            )
        first = await _role(app, tenant, actor, "first")
        second = await _role(app, tenant, actor, "second")
        parent = await _role(app, tenant, actor, "parent")
        child = await _role(app, tenant, actor, "child", parent)
        await _permission(app, tenant, actor, first, "sod.first")
        await _permission(app, tenant, actor, second, "sod.second")
        await _dispatch(
            app,
            CreateSoDRuleCommand(
                tenant_id=tenant,
                code="pair",
                name="Pair",
                permission_a="sod.first",
                permission_b="sod.second",
            ),
            actor,
        )

        deepest = await _role(app, tenant, actor, "depth-0")
        for level in range(1, 16):
            deepest = await _role(app, tenant, actor, f"depth-{level}", deepest)
        with pytest.raises(BusinessOSError) as denied:
            await _role(app, tenant, actor, "depth-16", deepest)
        assert denied.value.code == "authority_unbounded"

        direct = uuid4()
        await _assign(app, tenant, actor, first, direct)
        with pytest.raises(BusinessOSError) as denied:
            await _assign(app, tenant, actor, second, direct)
        assert denied.value.code == "segregation_of_duties_conflict"
        dsn = postgres_database.runtime_url.replace("postgresql+psycopg://", "postgresql://")
        async with await psycopg.AsyncConnection.connect(dsn) as check:
            await check.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant),))
            result = await check.execute(
                "SELECT count(*) FROM platform_policy.subject_role_assignments "
                "WHERE tenant_id = %s AND subject_id = %s AND role_id = %s",
                (tenant, direct, second),
            )
            row = await result.fetchone()
            assert row is not None and row[0] == 0

        direct_permission_subject = uuid4()
        direct_target = await _role(app, tenant, actor, "direct-target")
        await _assign(app, tenant, actor, second, direct_permission_subject)
        await _assign(app, tenant, actor, direct_target, direct_permission_subject)
        with pytest.raises(BusinessOSError) as denied:
            await _permission(app, tenant, actor, direct_target, "sod.first")
        assert denied.value.code == "segregation_of_duties_conflict"

        inherited = uuid4()
        await _assign(app, tenant, actor, child, inherited)
        await _assign(app, tenant, actor, second, inherited)
        with pytest.raises(BusinessOSError) as denied:
            await _permission(app, tenant, actor, parent, "sod.first")
        assert denied.value.code == "segregation_of_duties_conflict"

        source, middle, recipient = uuid4(), uuid4(), uuid4()
        await _assign(app, tenant, actor, first, source)
        await _assign(app, tenant, actor, second, recipient)
        await _delegate(app, tenant, actor, first, source, middle)
        with pytest.raises(BusinessOSError) as denied:
            await _delegate(app, tenant, actor, first, middle, recipient, minutes=30)
        assert denied.value.code == "segregation_of_duties_conflict"

        delegated_recipient = uuid4()
        delegated_target = await _role(app, tenant, actor, "delegated-target")
        await _assign(app, tenant, actor, delegated_target, delegated_recipient)
        await _delegate(app, tenant, actor, first, source, delegated_recipient)
        with pytest.raises(BusinessOSError) as denied:
            await _permission(app, tenant, actor, delegated_target, "sod.second")
        assert denied.value.code == "segregation_of_duties_conflict"

        await _dispatch(
            app,
            CreateSoDRuleCommand(
                tenant_id=tenant,
                code="detective",
                name="Detective",
                permission_a="sod.first",
                permission_b="sod.second",
                severity=SoDSeverity.DETECTIVE,
            ),
            actor,
        )
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_preventative_rule_preflights_existing_typed_authority(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = await _app(postgres_database)
    tenant, actor_id, subject = uuid4(), uuid4(), uuid4()
    _seed_tenant(postgres_database.migration_url, tenant, "sod-rule-preflight", status="active")
    actor = _context(tenant, actor_id)
    try:
        for code in ("sod.first", "sod.second"):
            await _dispatch(
                app, RegisterPermissionCommand(code=code, name=code, category="sod"), actor
            )
        first = await _role(app, tenant, actor, "first")
        second = await _role(app, tenant, actor, "second")
        await _permission(app, tenant, actor, first, "sod.first")
        await _permission(app, tenant, actor, second, "sod.second")
        await _assign(app, tenant, actor, first, subject)
        await _assign(app, tenant, actor, second, subject)
        command = CreateSoDRuleCommand(
            tenant_id=tenant,
            code="pair",
            name="Pair",
            permission_a="sod.first",
            permission_b="sod.second",
        )
        with pytest.raises(BusinessOSError) as denied:
            await _dispatch(app, command, actor)
        assert denied.value.code == "segregation_of_duties_conflict"
        dsn = postgres_database.runtime_url.replace("postgresql+psycopg://", "postgresql://")
        async with await psycopg.AsyncConnection.connect(dsn) as check:
            await check.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant),))
            result = await check.execute(
                "SELECT count(*) FROM platform_policy.sod_rules WHERE tenant_id = %s AND code = %s",
                (tenant, "pair"),
            )
            row = await result.fetchone()
            assert row is not None and row[0] == 0
        await _dispatch(app, command.model_copy(update={"severity": SoDSeverity.DETECTIVE}), actor)

        other_tenant, shared_id, legacy_id = uuid4(), uuid4(), uuid4()
        _seed_tenant(
            postgres_database.migration_url, other_tenant, "sod-typed-preflight", status="active"
        )
        other_actor = _context(other_tenant, actor_id)
        other_first = await _role(app, other_tenant, other_actor, "first")
        other_second = await _role(app, other_tenant, other_actor, "second")
        await _permission(app, other_tenant, other_actor, other_first, "sod.first")
        await _permission(app, other_tenant, other_actor, other_second, "sod.second")
        await _assign(app, other_tenant, other_actor, other_first, shared_id, "user")
        await _assign(app, other_tenant, other_actor, other_second, shared_id, "device")
        await _dispatch(
            app,
            AssignRoleToSubjectCommand(
                tenant_id=other_tenant, role_id=other_first, subject_id=legacy_id
            ),
            other_actor,
        )
        await _assign(app, other_tenant, other_actor, other_second, legacy_id)
        await _dispatch(
            app,
            command.model_copy(update={"tenant_id": other_tenant, "code": "typed-pair"}),
            other_actor,
        )
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_policy_lock_rollback_and_cross_tenant_independence(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = await _app(postgres_database)
    tenant_a, tenant_b = uuid4(), uuid4()
    _seed_tenant(postgres_database.migration_url, tenant_a, "sod-lock-a", status="active")
    _seed_tenant(postgres_database.migration_url, tenant_b, "sod-lock-b", status="active")
    actor_a, actor_b = _context(tenant_a, uuid4()), _context(tenant_b, uuid4())
    try:
        role_a = await _role(app, tenant_a, actor_a, "role")
        role_b = await _role(app, tenant_b, actor_b, "role")
        dsn = postgres_database.runtime_url.replace("postgresql+psycopg://", "postgresql://")
        async with await psycopg.AsyncConnection.connect(dsn) as blocker:
            await blocker.execute(
                "SELECT pg_advisory_xact_lock(%s)", (authority_lock_key(tenant_a),)
            )
            waiting = asyncio.create_task(_assign(app, tenant_a, actor_a, role_a, uuid4()))
            async with await psycopg.AsyncConnection.connect(
                postgres_database.administrator_url, autocommit=True
            ) as observer:
                waiters = 0
                for _ in range(100):
                    result = await observer.execute(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() AND wait_event = 'advisory' "
                        "AND query LIKE '%pg_advisory_xact_lock%'"
                    )
                    row = await result.fetchone()
                    waiters = int(row[0]) if row is not None else 0
                    if waiters:
                        break
                    await asyncio.sleep(0.05)
                assert waiters >= 1
            await asyncio.wait_for(_assign(app, tenant_b, actor_b, role_b, uuid4()), 5)
            assert not waiting.done()
            await blocker.rollback()
            await asyncio.wait_for(waiting, 5)
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario",
    (
        "assignment_permission",
        "assignment_rule",
        "delegation_permission",
        "delegation_rule",
        "two_assignments",
        "parent_permission_descendant_assignment",
    ),
)
async def test_policy_tenant_lock_serializes_conflicting_mutations(
    postgres_database: PostgreSQLTestDatabase, scenario: str
) -> None:
    app = await _app(postgres_database)
    tenant, actor_id = uuid4(), uuid4()
    _seed_tenant(postgres_database.migration_url, tenant, f"sod-{scenario}", status="active")
    actor = _context(tenant, actor_id)
    try:
        for code in ("sod.first", "sod.second"):
            await _dispatch(
                app, RegisterPermissionCommand(code=code, name=code, category="sod"), actor
            )
        first = await _role(app, tenant, actor, "first")
        second = await _role(app, tenant, actor, "second")
        subject = uuid4()
        if scenario != "parent_permission_descendant_assignment":
            await _permission(app, tenant, actor, first, "sod.first")

        rule_command = CreateSoDRuleCommand(
            tenant_id=tenant,
            code="pair",
            name="Pair",
            permission_a="sod.first",
            permission_b="sod.second",
        )
        if scenario in {
            "assignment_permission",
            "delegation_permission",
            "two_assignments",
            "parent_permission_descendant_assignment",
        }:
            await _dispatch(app, rule_command, actor)
        if scenario in {"assignment_rule", "delegation_rule", "two_assignments"}:
            await _permission(app, tenant, actor, second, "sod.second")
        if scenario in {"assignment_permission", "delegation_permission"}:
            await _assign(app, tenant, actor, second, subject)
        if scenario == "assignment_rule":
            await _assign(app, tenant, actor, first, subject)
        if scenario == "delegation_rule":
            await _assign(app, tenant, actor, second, subject)

        if scenario in {"delegation_permission", "delegation_rule"}:
            source = uuid4()
            await _assign(app, tenant, actor, first, source)
            first_mutation = _delegate(app, tenant, actor, first, source, subject)
        elif scenario == "assignment_rule":
            first_mutation = _assign(app, tenant, actor, second, subject)
        elif scenario == "parent_permission_descendant_assignment":
            child = await _role(app, tenant, actor, "child", first)
            await _permission(app, tenant, actor, second, "sod.second")
            await _assign(app, tenant, actor, second, subject)
            first_mutation = _assign(app, tenant, actor, child, subject)
        else:
            first_mutation = _assign(app, tenant, actor, first, subject)

        if scenario in {"assignment_rule", "delegation_rule"}:
            second_mutation = _dispatch(app, rule_command, actor)
        elif scenario == "two_assignments":
            second_mutation = _assign(app, tenant, actor, second, subject)
        elif scenario == "parent_permission_descendant_assignment":
            second_mutation = _permission(app, tenant, actor, first, "sod.first")
        else:
            second_mutation = _permission(app, tenant, actor, second, "sod.second")

        # Both dispatches are released behind one independently held exact
        # tenant advisory lock. Commit releases that lock; serial acquisition
        # then allows exactly one safe outcome, regardless of winner.
        dsn = postgres_database.runtime_url.replace("postgresql+psycopg://", "postgresql://")
        async with await psycopg.AsyncConnection.connect(dsn) as blocker:
            await blocker.execute("SELECT pg_advisory_xact_lock(%s)", (authority_lock_key(tenant),))
            gate = asyncio.Event()
            entered = (asyncio.Event(), asyncio.Event())

            async def run(coro: Coroutine[Any, Any, object], signal: asyncio.Event) -> object:
                signal.set()
                await gate.wait()
                return await coro

            tasks = (
                asyncio.create_task(run(first_mutation, entered[0])),
                asyncio.create_task(run(second_mutation, entered[1])),
            )
            await asyncio.gather(*(signal.wait() for signal in entered))
            gate.set()
            async with await psycopg.AsyncConnection.connect(
                postgres_database.administrator_url, autocommit=True
            ) as observer:
                waiters = 0
                for _ in range(100):
                    result = await observer.execute(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() AND wait_event = 'advisory' "
                        "AND query LIKE '%pg_advisory_xact_lock%'"
                    )
                    row = await result.fetchone()
                    waiters = int(row[0]) if row is not None else 0
                    if waiters >= 2:
                        break
                    await asyncio.sleep(0.05)
                assert waiters >= 2, (scenario, waiters)
            await blocker.commit()
            outcomes = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 20)
        failures = [result for result in outcomes if isinstance(result, BaseException)]
        assert len(failures) == 1, (scenario, outcomes)
        assert isinstance(failures[0], BusinessOSError), (scenario, failures)
        assert failures[0].code == "segregation_of_duties_conflict", (scenario, failures)
    finally:
        await app.shutdown()
