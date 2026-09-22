"""Real PostgreSQL proofs that Policy delegations cannot widen their source."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from businessos_organization import (
    AssignPrincipal,
    CreateCompany,
    CreateEnterpriseGroup,
    CreateLegalEntity,
    OrganizationScopeType,
)
from businessos_policy import (
    AssignRoleToSubjectCommand,
    CreateDelegationCommand,
    CreateRoleCommand,
    DelegationGrantRecord,
    RevokeDelegationCommand,
    RoleRecord,
    ScopeType,
)
from businessos_policy.delegation_authority import PolicyDelegationActionAuthority

from businessos.errors import BusinessOSError
from tests.conftest import PostgreSQLTestDatabase
from tests.integration.test_phase2_adr011 import _real_policy_setup
from tests.integration.test_phase2_delegation_authority import _delegate
from tests.integration.test_phase2_foundations import _context, _dispatch, _seed_tenant


def _grant(
    tenant_id: UUID,
    delegator_id: UUID,
    delegatee_id: UUID,
    role_id: UUID,
    scope_type: ScopeType,
    scope_id: UUID | None,
    start: datetime,
    end: datetime,
) -> CreateDelegationCommand:
    return CreateDelegationCommand(
        tenant_id=tenant_id,
        delegator_id=delegator_id,
        delegator_type="user",
        delegatee_id=delegatee_id,
        delegatee_type="user",
        role_id=role_id,
        scope_type=scope_type,
        scope_id=scope_id,
        valid_from=start,
        valid_to=end,
    )


def _delegation_count(database: PostgreSQLTestDatabase, tenant_id: UUID) -> int:
    url = database.migration_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(url) as connection:
        row = connection.execute(
            "SELECT count(*) FROM platform_policy.delegations WHERE tenant_id = %s", (tenant_id,)
        ).fetchone()
    assert row is not None
    return cast(int, row[0])


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_policy_grant_same_company_and_tenant_narrowing(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app, tenant, owner, root, middle, _, company, _, role, context = await _real_policy_setup(
        postgres_database
    )
    now = datetime.now(UTC)
    try:
        same = await _dispatch(
            app,
            _grant(
                tenant,
                owner,
                root,
                role,
                ScopeType.COMPANY,
                company,
                now - timedelta(minutes=1),
                now + timedelta(hours=1),
            ),
            context,
        )
        assert isinstance(same, DelegationGrantRecord)
        await _dispatch(
            app,
            AssignRoleToSubjectCommand(
                tenant_id=tenant,
                subject_id=middle,
                subject_type="user",
                role_id=role,
                scope_type=ScopeType.TENANT,
            ),
            context,
        )
        narrowed = await _dispatch(
            app,
            _grant(
                tenant,
                middle,
                owner,
                role,
                ScopeType.COMPANY,
                company,
                now - timedelta(minutes=1),
                now + timedelta(hours=1),
            ),
            context,
        )
        assert isinstance(narrowed, DelegationGrantRecord)
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["other_company", "tenant"])
async def test_policy_grant_rejects_scope_widening_without_partial_row(
    postgres_database: PostgreSQLTestDatabase, target: str
) -> None:
    app, tenant, owner, root, _, _, _, _, role, context = await _real_policy_setup(
        postgres_database
    )
    now = datetime.now(UTC)
    scope_type = ScopeType.TENANT if target == "tenant" else ScopeType.COMPANY
    scope_id = None if target == "tenant" else uuid4()
    try:
        with pytest.raises(BusinessOSError) as denied:
            await _dispatch(
                app,
                _grant(
                    tenant,
                    owner,
                    root,
                    role,
                    scope_type,
                    scope_id,
                    now - timedelta(minutes=1),
                    now + timedelta(hours=1),
                ),
                context,
            )
        assert denied.value.code == "delegation_authority_missing"
        assert _delegation_count(postgres_database, tenant) == 0
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_policy_grant_ignores_cross_tenant_source_row(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app, _, owner, root, _, _, _, _, _, _ = await _real_policy_setup(postgres_database)
    tenant_b = uuid4()
    _seed_tenant(postgres_database.migration_url, tenant_b, "other-policy-tenant", status="active")
    context_b = _context(tenant_b, owner)
    now = datetime.now(UTC)
    try:
        role_b = cast(
            RoleRecord,
            await _dispatch(
                app,
                CreateRoleCommand(tenant_id=tenant_b, code="other", name="Other tenant role"),
                context_b,
            ),
        )
        # This same typed principal has authority in tenant A, but no
        # assignment in B. Composite FKs also prevent transplanting A's row.
        with pytest.raises(BusinessOSError) as denied:
            await _dispatch(
                app,
                _grant(
                    tenant_b,
                    owner,
                    root,
                    role_b.id,
                    ScopeType.TENANT,
                    None,
                    now - timedelta(minutes=1),
                    now + timedelta(hours=1),
                ),
                context_b,
            )
        assert denied.value.code == "delegation_authority_missing"
        assert _delegation_count(postgres_database, tenant_b) == 0
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize("period", ["inside", "before", "after", "future", "expired"])
async def test_policy_grant_requires_live_source_covering_full_period(
    postgres_database: PostgreSQLTestDatabase, period: str
) -> None:
    app, tenant, _, root, middle, _, company, _, role, context = await _real_policy_setup(
        postgres_database
    )
    now = datetime.now(UTC)
    bounds = {
        "inside": (-2, 2, -1, 1),
        "before": (-1, 2, -2, 1),
        "after": (-2, 1, -1, 2),
        "future": (1, 3, 1, 2),
        "expired": (-3, -1, -2, 1),
    }
    source_start, source_end, grant_start, grant_end = bounds[period]
    try:
        await _dispatch(
            app,
            AssignRoleToSubjectCommand(
                tenant_id=tenant,
                subject_id=root,
                subject_type="user",
                role_id=role,
                scope_type=ScopeType.COMPANY,
                scope_id=company,
                valid_from=now + timedelta(days=source_start),
                valid_to=now + timedelta(days=source_end),
            ),
            context,
        )
        command = _grant(
            tenant,
            root,
            middle,
            role,
            ScopeType.COMPANY,
            company,
            now + timedelta(days=grant_start),
            now + timedelta(days=grant_end),
        )
        if period == "inside":
            assert isinstance(await _dispatch(app, command, context), DelegationGrantRecord)
            assert _delegation_count(postgres_database, tenant) == 1
        else:
            with pytest.raises(BusinessOSError) as denied:
                await _dispatch(app, command, context)
            assert denied.value.code == "delegation_authority_missing"
            assert _delegation_count(postgres_database, tenant) == 0
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_policy_transitive_source_cannot_widen_or_survive_parent_revocation(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app, tenant, owner, root, middle, child, company, _, role, context = await _real_policy_setup(
        postgres_database
    )
    now = datetime.now(UTC)
    start, end = now - timedelta(minutes=1), now + timedelta(hours=1)
    try:
        parent = cast(
            DelegationGrantRecord,
            await _dispatch(
                app,
                _grant(tenant, owner, root, role, ScopeType.COMPANY, company, start, end),
                context,
            ),
        )
        child_grant = await _dispatch(
            app,
            _grant(tenant, root, middle, role, ScopeType.COMPANY, company, start, end),
            context,
        )
        assert isinstance(child_grant, DelegationGrantRecord)
        with pytest.raises(BusinessOSError):
            await _dispatch(
                app,
                _grant(tenant, middle, child, role, ScopeType.COMPANY, uuid4(), start, end),
                context,
            )
        await _dispatch(
            app,
            RevokeDelegationCommand(
                tenant_id=tenant, delegation_id=parent.id, reason="Root source revoked"
            ),
            context,
        )
        with pytest.raises(BusinessOSError) as denied:
            await _dispatch(
                app,
                _grant(tenant, middle, child, role, ScopeType.COMPANY, company, start, end),
                context,
            )
        assert denied.value.code == "delegation_authority_missing"
        assert _delegation_count(postgres_database, tenant) == 2
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_organization_cannot_consume_historical_out_of_scope_policy_grant(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app, tenant, owner, root, middle, _, company_a, _, role, context = await _real_policy_setup(
        postgres_database
    )
    group_b, legal_b, company_b = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    start, end = now - timedelta(minutes=1), now + timedelta(hours=1)
    try:
        await _dispatch(
            app,
            CreateEnterpriseGroup(id=group_b, tenant_id=tenant, code="GROUP-B", name="Group B"),
            context,
        )
        await _dispatch(
            app,
            CreateLegalEntity(
                id=legal_b,
                tenant_id=tenant,
                code="LEGAL-B",
                name="Legal B",
                enterprise_group_id=group_b,
                country_code="US",
            ),
            context,
        )
        await _dispatch(
            app,
            CreateCompany(
                id=company_b,
                tenant_id=tenant,
                code="COMPANY-B",
                name="Company B",
                legal_entity_id=legal_b,
                base_currency="USD",
                timezone="UTC",
            ),
            context,
        )
        await _dispatch(
            app,
            AssignPrincipal(
                id=uuid4(),
                tenant_id=tenant,
                principal_id=root,
                scope_type=OrganizationScopeType.COMPANY,
                scope_id=company_b,
            ),
            context,
        )
        url = postgres_database.migration_url.replace("postgresql+psycopg://", "postgresql://", 1)
        with psycopg.connect(url) as connection:
            connection.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant),))
            connection.execute(
                """INSERT INTO platform_policy.delegations
                   (id, tenant_id, delegator_id, delegator_type, delegatee_id,
                    delegatee_type, role_id, scope_type, scope_id, valid_from,
                    valid_to, is_revoked)
                   VALUES (%s, %s, %s, 'user', %s, 'user', %s, 'company', %s, %s, %s, false)""",
                (uuid4(), tenant, owner, root, role, company_b, start, end),
            )
        with pytest.raises(BusinessOSError) as denied:
            await _dispatch(
                app,
                _delegate(tenant, middle, company_b, start=now, end=end),
                _context(tenant, root),
            )
        assert denied.value.code == "forbidden"
        # The same owner has real authority at A, so a properly rooted grant
        # there remains usable by the Organization adapter.
        await _dispatch(
            app,
            _grant(tenant, owner, root, role, ScopeType.COMPANY, company_a, start, end),
            context,
        )
        valid = await _dispatch(
            app,
            _delegate(tenant, middle, company_a, start=now, end=end),
            _context(tenant, root),
        )
        assert isinstance(valid, dict)
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize("first", ["creation", "revocation"])
async def test_policy_source_revocation_serializes_with_child_creation(
    postgres_database: PostgreSQLTestDatabase,
    monkeypatch: pytest.MonkeyPatch,
    first: str,
) -> None:
    app, tenant, owner, root, middle, _, company, _, role, context = await _real_policy_setup(
        postgres_database
    )
    now = datetime.now(UTC)
    start, end = now - timedelta(minutes=1), now + timedelta(hours=1)
    try:
        parent = cast(
            DelegationGrantRecord,
            await _dispatch(
                app,
                _grant(tenant, owner, root, role, ScopeType.COMPANY, company, start, end),
                context,
            ),
        )
        entered, release = asyncio.Event(), asyncio.Event()
        original_acquire = PolicyDelegationActionAuthority.acquire
        creation_task: asyncio.Task[object] | None = None
        revocation_task: asyncio.Task[object] | None = None

        async def paused_acquire(self: PolicyDelegationActionAuthority, *args: Any) -> None:
            await original_acquire(self, *args)
            current = asyncio.current_task()
            if (first == "creation" and current is creation_task) or (
                first == "revocation" and current is revocation_task
            ):
                entered.set()
                await release.wait()

        monkeypatch.setattr(PolicyDelegationActionAuthority, "acquire", paused_acquire)
        child_cmd = _grant(tenant, root, middle, role, ScopeType.COMPANY, company, start, end)
        revoke_cmd = RevokeDelegationCommand(
            tenant_id=tenant, delegation_id=parent.id, reason="Concurrent source revoke"
        )
        if first == "creation":
            creation_task = asyncio.create_task(_dispatch(app, child_cmd, context))
            await asyncio.wait_for(entered.wait(), 5)
            revocation_task = asyncio.create_task(_dispatch(app, revoke_cmd, context))
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(revocation_task), 0.1)
            release.set()
            assert isinstance(await asyncio.wait_for(creation_task, 5), DelegationGrantRecord)
            await asyncio.wait_for(revocation_task, 5)
        else:
            revocation_task = asyncio.create_task(_dispatch(app, revoke_cmd, context))
            await asyncio.wait_for(entered.wait(), 5)
            creation_task = asyncio.create_task(_dispatch(app, child_cmd, context))
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(creation_task), 0.1)
            release.set()
            await asyncio.wait_for(revocation_task, 5)
            with pytest.raises(BusinessOSError) as denied:
                await asyncio.wait_for(creation_task, 5)
            assert denied.value.code == "delegation_authority_missing"
    finally:
        await app.shutdown()
