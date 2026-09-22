"""PostgreSQL evidence for ADR-011's immutable delegation source path."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from businessos_identity import (
    CreateUser,
    GrantMembership,
    RegisterServiceAccount,
    RevokeMembership,
)
from businessos_identity.authority import DatabaseMembershipAuthority
from businessos_identity.principal_binding import clear_authenticated_principal
from businessos_organization import (
    AssignPrincipal,
    CreateCompany,
    CreateEnterpriseGroup,
    CreateLegalEntity,
    CreateOperatingSite,
    DelegateScope,
    OrganizationScopeType,
    OrganizationSnapshot,
    ReadOrganization,
    RegisterSiteType,
    RevokeOrganizationDelegation,
    RevokePrincipalAssignment,
    SelectActiveScope,
)
from businessos_policy import (
    AssignPermissionToRoleCommand,
    AssignRoleToSubjectCommand,
    CreateDelegationCommand,
    CreateRoleCommand,
    DelegationGrantRecord,
    PolicyModule,
    RegisterPermissionCommand,
    RevokeDelegationCommand,
    RoleRecord,
    ScopeType,
)
from businessos_policy.delegation_authority import PolicyDelegationActionAuthority

from businessos.application import BusinessOSApplication
from businessos.bootstrap import create_application
from businessos.context import RequestContext, TenantContext
from businessos.errors import BusinessOSError
from businessos.modules import discover_modules
from businessos.security import Authorizer
from tests.conftest import PostgreSQLTestDatabase
from tests.integration.test_phase2_delegation_authority import _delegate, _setup
from tests.integration.test_phase2_foundations import (
    AllowAllPolicy,
    _context,
    _dispatch,
    _query,
    _seed_tenant,
    _settings,
)


def _selected(context: RequestContext, delegation_id: UUID) -> RequestContext:
    assert context.tenant is not None
    return replace(context, tenant=replace(context.tenant, delegation_id=delegation_id))


async def _add_user(
    app: object, tenant_id: UUID, principal_id: UUID, actor: RequestContext
) -> None:
    await _dispatch(
        app,
        CreateUser(
            tenant_id=tenant_id,
            user_id=principal_id,
            email=f"{principal_id}@example.test",
            display_name="Delegation principal",
        ),
        actor,
    )
    await _dispatch(
        app,
        GrantMembership(tenant_id=tenant_id, principal_id=principal_id, principal_type="user"),
        actor,
    )


async def _real_policy_setup(
    database: PostgreSQLTestDatabase,
) -> tuple[BusinessOSApplication, UUID, UUID, UUID, UUID, UUID, UUID, UUID, UUID, RequestContext]:
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
    tenant_id, policy_owner, root_id, middle_id, child_id = (uuid4() for _ in range(5))
    group_id, legal_id, company_id = (uuid4() for _ in range(3))
    _seed_tenant(database.migration_url, tenant_id, "adr011-policy", status="active")
    owner_context = _context(tenant_id, policy_owner)
    for principal_id in (policy_owner, root_id, middle_id, child_id):
        await _add_user(app, tenant_id, principal_id, owner_context)
    await _dispatch(
        app,
        CreateEnterpriseGroup(id=group_id, tenant_id=tenant_id, code="GROUP", name="Group"),
        owner_context,
    )
    await _dispatch(
        app,
        CreateLegalEntity(
            id=legal_id,
            tenant_id=tenant_id,
            code="LEGAL",
            name="Legal",
            enterprise_group_id=group_id,
            country_code="US",
        ),
        owner_context,
    )
    await _dispatch(
        app,
        CreateCompany(
            id=company_id,
            tenant_id=tenant_id,
            code="COMPANY",
            name="Company",
            legal_entity_id=legal_id,
            base_currency="USD",
            timezone="UTC",
        ),
        owner_context,
    )
    assignment_id = uuid4()
    await _dispatch(
        app,
        AssignPrincipal(
            id=assignment_id,
            tenant_id=tenant_id,
            principal_id=root_id,
            scope_type=OrganizationScopeType.COMPANY,
            scope_id=company_id,
        ),
        owner_context,
    )
    await _dispatch(
        app,
        RegisterPermissionCommand(
            code="organization.read", name="Read organization", category="organization"
        ),
        owner_context,
    )
    role = cast(
        RoleRecord,
        await _dispatch(
            app,
            CreateRoleCommand(tenant_id=tenant_id, code="authority", name="Authority"),
            owner_context,
        ),
    )
    await _dispatch(
        app,
        AssignPermissionToRoleCommand(
            tenant_id=tenant_id, role_id=role.id, permission_code="organization.read"
        ),
        owner_context,
    )
    await _dispatch(
        app,
        AssignRoleToSubjectCommand(
            tenant_id=tenant_id,
            subject_id=policy_owner,
            subject_type="user",
            role_id=role.id,
            scope_type=ScopeType.COMPANY,
            scope_id=company_id,
        ),
        owner_context,
    )
    return (
        app,
        tenant_id,
        policy_owner,
        root_id,
        middle_id,
        child_id,
        company_id,
        assignment_id,
        role.id,
        owner_context,
    )


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_transitive_creation_consumption_intersection_and_parent_revocation(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app, tenant_id, root_id, middle_id, company_a, company_b, root_context = await _setup(
        postgres_database
    )
    child_id = uuid4()
    now = datetime.now(UTC)
    parent_end = now + timedelta(minutes=20)
    try:
        await _add_user(app, tenant_id, child_id, root_context)
        assignment_id = uuid4()
        await _dispatch(
            app,
            AssignPrincipal(
                id=assignment_id,
                tenant_id=tenant_id,
                principal_id=root_id,
                scope_type=OrganizationScopeType.COMPANY,
                scope_id=company_a,
            ),
            root_context,
        )
        parent = cast(
            dict[str, UUID],
            await _dispatch(
                app,
                _delegate(
                    tenant_id,
                    middle_id,
                    company_a,
                    actions=("organization.read", "organization.manage"),
                    start=now,
                    end=parent_end,
                ),
                root_context,
            ),
        )
        middle_context = _selected(_context(tenant_id, middle_id), parent["delegation_id"])
        child = cast(
            dict[str, UUID],
            await _dispatch(
                app,
                _delegate(
                    tenant_id,
                    child_id,
                    company_a,
                    actions=("organization.read",),
                    start=now,
                    end=parent_end - timedelta(minutes=1),
                ),
                middle_context,
            ),
        )
        child_context = _context(tenant_id, child_id)
        selected = await _dispatch(
            app,
            SelectActiveScope(
                tenant_id=tenant_id,
                company_id=company_a,
                delegation_id=child["delegation_id"],
            ),
            child_context,
        )
        assert cast(TenantContext, selected).delegation_id == child["delegation_id"]
        snapshot = cast(
            OrganizationSnapshot,
            await _query(app, ReadOrganization(tenant_id=tenant_id), root_context),
        )
        grant = next(row for row in snapshot.delegations if row.id == child["delegation_id"])
        assert grant.authority_source_kind == "delegation"
        assert grant.parent_delegation_id == parent["delegation_id"]

        for command in (
            _delegate(tenant_id, child_id, company_b, start=now, end=parent_end),
            _delegate(
                tenant_id,
                child_id,
                company_a,
                actions=("billing.refund",),
                start=now,
                end=parent_end,
            ),
            _delegate(
                tenant_id,
                child_id,
                company_a,
                start=now,
                end=parent_end + timedelta(seconds=1),
            ),
        ):
            with pytest.raises(BusinessOSError) as rejected:
                await _dispatch(app, command, middle_context)
            assert rejected.value.code == "forbidden"

        with pytest.raises(BusinessOSError) as cycle:
            await _dispatch(
                app,
                _delegate(tenant_id, root_id, company_a, start=now, end=parent_end),
                middle_context,
            )
        assert cycle.value.code == "forbidden"
        with pytest.raises(BusinessOSError) as longer_cycle:
            await _dispatch(
                app,
                _delegate(tenant_id, root_id, company_a, start=now, end=parent_end),
                _selected(child_context, child["delegation_id"]),
            )
        assert longer_cycle.value.code == "forbidden"

        await _dispatch(
            app,
            RevokeOrganizationDelegation(
                tenant_id=tenant_id,
                delegation_id=parent["delegation_id"],
                reason="Review revoked upstream delegation",
            ),
            root_context,
        )
        with pytest.raises(BusinessOSError) as revoked:
            await _dispatch(
                app,
                SelectActiveScope(
                    tenant_id=tenant_id,
                    company_id=company_a,
                    delegation_id=child["delegation_id"],
                ),
                child_context,
            )
        assert revoked.value.code == "forbidden"
        await _dispatch(
            app,
            RevokePrincipalAssignment(
                tenant_id=tenant_id,
                assignment_id=assignment_id,
                reason="Remove root scope",
            ),
            root_context,
        )
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_membership_revocation_invalidates_child_without_deleting_it(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app, tenant_id, root_id, middle_id, company_a, _, root_context = await _setup(postgres_database)
    child_id = uuid4()
    now = datetime.now(UTC)
    end = now + timedelta(minutes=25)
    try:
        await _add_user(app, tenant_id, child_id, root_context)
        await _dispatch(
            app,
            AssignPrincipal(
                tenant_id=tenant_id,
                principal_id=root_id,
                scope_type=OrganizationScopeType.COMPANY,
                scope_id=company_a,
            ),
            root_context,
        )
        parent = cast(
            dict[str, UUID],
            await _dispatch(
                app,
                _delegate(tenant_id, middle_id, company_a, start=now, end=end),
                root_context,
            ),
        )
        child = cast(
            dict[str, UUID],
            await _dispatch(
                app,
                _delegate(tenant_id, child_id, company_a, start=now, end=end),
                _selected(_context(tenant_id, middle_id), parent["delegation_id"]),
            ),
        )
        await _dispatch(
            app,
            RevokeMembership(tenant_id=tenant_id, principal_id=middle_id, principal_type="user"),
            root_context,
        )
        with pytest.raises(BusinessOSError) as rejected:
            await _dispatch(
                app,
                SelectActiveScope(
                    tenant_id=tenant_id,
                    company_id=company_a,
                    delegation_id=child["delegation_id"],
                ),
                _context(tenant_id, child_id),
            )
        assert rejected.value.code == "forbidden"
        snapshot = cast(
            OrganizationSnapshot,
            await _query(app, ReadOrganization(tenant_id=tenant_id), root_context),
        )
        assert any(grant.id == child["delegation_id"] for grant in snapshot.delegations)
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_site_delegation_cannot_select_its_explicit_company_ancestor(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app, tenant_id, root_id, recipient_id, company_id, _, root_context = await _setup(
        postgres_database
    )
    site_type_id, site_id = uuid4(), uuid4()
    now = datetime.now(UTC)
    try:
        await _dispatch(
            app,
            RegisterSiteType(
                id=site_type_id,
                tenant_id=tenant_id,
                code="branch",
                name="Branch",
            ),
            root_context,
        )
        await _dispatch(
            app,
            CreateOperatingSite(
                id=site_id,
                tenant_id=tenant_id,
                code="SITE",
                name="Site",
                company_id=company_id,
                site_type_id=site_type_id,
                timezone="UTC",
            ),
            root_context,
        )
        await _dispatch(
            app,
            AssignPrincipal(
                tenant_id=tenant_id,
                principal_id=root_id,
                scope_type=OrganizationScopeType.OPERATING_SITE,
                scope_id=site_id,
            ),
            root_context,
        )
        grant = cast(
            dict[str, UUID],
            await _dispatch(
                app,
                DelegateScope(
                    tenant_id=tenant_id,
                    recipient_principal_id=recipient_id,
                    scope_type=OrganizationScopeType.OPERATING_SITE,
                    scope_id=site_id,
                    allowed_actions=("organization.read",),
                    valid_from=now,
                    valid_until=now + timedelta(minutes=20),
                    reason="Site-only authority",
                ),
                root_context,
            ),
        )
        with pytest.raises(BusinessOSError) as widened:
            await _dispatch(
                app,
                SelectActiveScope(
                    tenant_id=tenant_id,
                    company_id=company_id,
                    operating_site_id=site_id,
                    delegation_id=grant["delegation_id"],
                ),
                _context(tenant_id, recipient_id),
            )
        assert widened.value.code == "forbidden"
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_unbound_caller_type_cannot_create_delegation(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app, tenant_id, root_id, recipient_id, company_id, _, root_context = await _setup(
        postgres_database
    )
    try:
        await _dispatch(
            app,
            AssignPrincipal(
                tenant_id=tenant_id,
                principal_id=root_id,
                scope_type=OrganizationScopeType.COMPANY,
                scope_id=company_id,
            ),
            root_context,
        )
        clear_authenticated_principal()
        assert app.runtime is not None
        async with app.container.request_scope() as dependencies:
            with pytest.raises(BusinessOSError) as rejected:
                await app.runtime.messages.command(
                    _delegate(tenant_id, recipient_id, company_id),
                    root_context,
                    dependencies,
                )
        assert rejected.value.code == "unauthenticated"
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_typed_principal_collision_and_cross_tenant_parent_fail_closed(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app, tenant_id, root_id, recipient_id, company_a, _, root_context = await _setup(
        postgres_database
    )
    try:
        await _dispatch(
            app,
            AssignPrincipal(
                tenant_id=tenant_id,
                principal_id=root_id,
                scope_type=OrganizationScopeType.COMPANY,
                scope_id=company_a,
            ),
            root_context,
        )
        parent = cast(
            dict[str, UUID],
            await _dispatch(app, _delegate(tenant_id, recipient_id, company_a), root_context),
        )
        for identifier in (root_id, recipient_id):
            await _dispatch(
                app,
                RegisterServiceAccount(
                    tenant_id=tenant_id,
                    service_account_id=identifier,
                    name=f"Service {identifier}",
                    credential_secret_reference=f"test://{identifier}",
                ),
                root_context,
            )
            await _dispatch(
                app,
                GrantMembership(
                    tenant_id=tenant_id,
                    principal_id=identifier,
                    principal_type="service_account",
                ),
                root_context,
            )
        with pytest.raises(BusinessOSError) as borrowed_recipient:
            await _dispatch(
                app,
                SelectActiveScope(
                    tenant_id=tenant_id,
                    principal_type="service_account",
                    company_id=company_a,
                    delegation_id=parent["delegation_id"],
                ),
                _context(tenant_id, recipient_id),
                principal_type="service_account",
            )
        assert borrowed_recipient.value.code == "forbidden"
        with pytest.raises(BusinessOSError) as borrowed_assignment:
            await _dispatch(
                app,
                _delegate(tenant_id, recipient_id, company_a).model_copy(
                    update={"grantor_principal_type": "service_account"}
                ),
                _context(tenant_id, root_id),
                principal_type="service_account",
            )
        assert borrowed_assignment.value.code == "forbidden"

        other_tenant = uuid4()
        _seed_tenant(postgres_database.migration_url, other_tenant, "adr011-other", status="active")
        with pytest.raises(BusinessOSError) as cross_tenant:
            await _dispatch(
                app,
                SelectActiveScope(
                    tenant_id=other_tenant,
                    company_id=company_a,
                    delegation_id=parent["delegation_id"],
                ),
                _context(other_tenant, recipient_id),
            )
        assert cross_tenant.value.code in {"invalid_organization_scope", "forbidden"}
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_sixteen_edges_are_usable_but_seventeenth_is_rejected(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app, tenant_id, root_id, first_id, company_a, _, root_context = await _setup(postgres_database)
    now = datetime.now(UTC)
    end = now + timedelta(hours=1)
    try:
        await _dispatch(
            app,
            AssignPrincipal(
                tenant_id=tenant_id,
                principal_id=root_id,
                scope_type=OrganizationScopeType.COMPANY,
                scope_id=company_a,
            ),
            root_context,
        )
        previous_context = root_context
        last_id = root_id
        parent_id: UUID | None = None
        for edge in range(1, 18):
            recipient_id = first_id if edge == 1 else uuid4()
            if edge > 1:
                await _add_user(app, tenant_id, recipient_id, root_context)
            command = _delegate(tenant_id, recipient_id, company_a, start=now, end=end)
            if edge == 17:
                with pytest.raises(BusinessOSError) as too_deep:
                    await _dispatch(app, command, previous_context)
                assert too_deep.value.code == "forbidden"
                break
            result = cast(dict[str, UUID], await _dispatch(app, command, previous_context))
            last_id = recipient_id
            parent_id = result["delegation_id"]
            previous_context = _selected(_context(tenant_id, recipient_id), parent_id)
        assert parent_id is not None
        selected = await _dispatch(
            app,
            SelectActiveScope(
                tenant_id=tenant_id,
                company_id=company_a,
                delegation_id=parent_id,
            ),
            _context(tenant_id, last_id),
        )
        assert cast(TenantContext, selected).delegation_id == parent_id
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_real_policy_root_revocation_and_assignment_loss_invalidate_descendant(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    (
        app,
        tenant_id,
        policy_owner,
        root_id,
        middle_id,
        child_id,
        company_id,
        assignment_id,
        role_id,
        owner_context,
    ) = await _real_policy_setup(postgres_database)
    now = datetime.now(UTC)
    end = now + timedelta(minutes=20)
    try:
        await _dispatch(
            app,
            AssignRoleToSubjectCommand(
                tenant_id=tenant_id,
                subject_id=root_id,
                role_id=role_id,
                scope_type=ScopeType.COMPANY,
                scope_id=company_id,
            ),
            owner_context,
        )
        with pytest.raises(BusinessOSError) as unverified_policy_grant:
            await _dispatch(
                app,
                _delegate(tenant_id, middle_id, company_id, start=now, end=end),
                _context(tenant_id, root_id),
            )
        assert unverified_policy_grant.value.code == "forbidden"
        policy_grant = cast(
            DelegationGrantRecord,
            await _dispatch(
                app,
                CreateDelegationCommand(
                    tenant_id=tenant_id,
                    delegator_id=policy_owner,
                    delegator_type="user",
                    delegatee_id=root_id,
                    delegatee_type="user",
                    role_id=role_id,
                    scope_type=ScopeType.COMPANY,
                    scope_id=company_id,
                    valid_from=now - timedelta(minutes=1),
                    valid_to=end + timedelta(minutes=5),
                ),
                owner_context,
            ),
        )
        parent = cast(
            dict[str, UUID],
            await _dispatch(
                app,
                _delegate(tenant_id, middle_id, company_id, start=now, end=end),
                _context(tenant_id, root_id),
            ),
        )
        child = cast(
            dict[str, UUID],
            await _dispatch(
                app,
                _delegate(tenant_id, child_id, company_id, start=now, end=end),
                _selected(_context(tenant_id, middle_id), parent["delegation_id"]),
            ),
        )
        child_context = _context(tenant_id, child_id)
        selected = await _dispatch(
            app,
            SelectActiveScope(
                tenant_id=tenant_id,
                company_id=company_id,
                delegation_id=child["delegation_id"],
            ),
            child_context,
        )
        assert cast(TenantContext, selected).delegation_id == child["delegation_id"]
        await _dispatch(
            app,
            RevokeDelegationCommand(
                tenant_id=tenant_id,
                delegation_id=policy_grant.id,
                reason="Revoke Policy root authority",
            ),
            owner_context,
        )
        with pytest.raises(BusinessOSError) as revoked:
            await _dispatch(
                app,
                SelectActiveScope(
                    tenant_id=tenant_id,
                    company_id=company_id,
                    delegation_id=child["delegation_id"],
                ),
                child_context,
            )
        assert revoked.value.code == "forbidden"
        await _dispatch(
            app,
            RevokePrincipalAssignment(
                tenant_id=tenant_id,
                assignment_id=assignment_id,
                reason="Revoke Organization root assignment",
            ),
            owner_context,
        )
        with pytest.raises(BusinessOSError) as assignment_revoked:
            await _dispatch(
                app,
                SelectActiveScope(
                    tenant_id=tenant_id,
                    company_id=company_id,
                    delegation_id=child["delegation_id"],
                ),
                child_context,
            )
        assert assignment_revoked.value.code == "forbidden"
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize("revoke_kind", ("parent", "policy", "assignment"))
@pytest.mark.parametrize("first", ("creation", "revocation"))
async def test_child_creation_and_revocation_serialize_in_both_orders(
    postgres_database: PostgreSQLTestDatabase,
    monkeypatch: pytest.MonkeyPatch,
    revoke_kind: str,
    first: str,
) -> None:
    (
        app,
        tenant_id,
        policy_owner,
        root_id,
        middle_id,
        child_id,
        company_id,
        assignment_id,
        role_id,
        owner_context,
    ) = await _real_policy_setup(postgres_database)
    now = datetime.now(UTC)
    end = now + timedelta(minutes=20)
    try:
        policy_grant = cast(
            DelegationGrantRecord,
            await _dispatch(
                app,
                CreateDelegationCommand(
                    tenant_id=tenant_id,
                    delegator_id=policy_owner,
                    delegator_type="user",
                    delegatee_id=root_id,
                    delegatee_type="user",
                    role_id=role_id,
                    scope_type=ScopeType.COMPANY,
                    scope_id=company_id,
                    valid_from=now - timedelta(minutes=1),
                    valid_to=end + timedelta(minutes=5),
                ),
                owner_context,
            ),
        )
        parent = cast(
            dict[str, UUID],
            await _dispatch(
                app,
                _delegate(tenant_id, middle_id, company_id, start=now, end=end),
                _context(tenant_id, root_id),
            ),
        )
        middle_context = _selected(_context(tenant_id, middle_id), parent["delegation_id"])
        child_command = _delegate(tenant_id, child_id, company_id, start=now, end=end)
        revocation_command = {
            "parent": RevokeOrganizationDelegation(
                tenant_id=tenant_id,
                delegation_id=parent["delegation_id"],
                reason="Concurrent parent revocation",
            ),
            "policy": RevokeDelegationCommand(
                tenant_id=tenant_id,
                delegation_id=policy_grant.id,
                reason="Concurrent root Policy revocation",
            ),
            "assignment": RevokePrincipalAssignment(
                tenant_id=tenant_id,
                assignment_id=assignment_id,
                reason="Concurrent root assignment revocation",
            ),
        }[revoke_kind]
        entered = asyncio.Event()
        release = asyncio.Event()
        original_memberships = DatabaseMembershipAuthority.lock_many
        original_acquire = PolicyDelegationActionAuthority.acquire
        revocation_task: asyncio.Task[object] | None = None

        async def paused_memberships(self: DatabaseMembershipAuthority, *args: Any) -> Any:
            result = await original_memberships(self, *args)
            principals = args[2]
            if first == "creation" and any(
                principal.principal_id == child_id for principal in principals
            ):
                entered.set()
                await release.wait()
            return result

        async def paused_acquire(self: PolicyDelegationActionAuthority, *args: Any) -> None:
            await original_acquire(self, *args)
            if first == "revocation" and asyncio.current_task() is revocation_task:
                entered.set()
                await release.wait()

        if first == "creation":
            monkeypatch.setattr(DatabaseMembershipAuthority, "lock_many", paused_memberships)
        else:
            monkeypatch.setattr(PolicyDelegationActionAuthority, "acquire", paused_acquire)

        async def revoke() -> object:
            return await _dispatch(app, revocation_command, owner_context)

        if first == "creation":
            creation = asyncio.create_task(_dispatch(app, child_command, middle_context))
            await asyncio.wait_for(entered.wait(), 5)
            revocation_task = asyncio.create_task(revoke())
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(revocation_task), 0.1)
            release.set()
            child = cast(dict[str, UUID], await asyncio.wait_for(creation, 5))
            await asyncio.wait_for(revocation_task, 5)
            with pytest.raises(BusinessOSError):
                await _dispatch(
                    app,
                    SelectActiveScope(
                        tenant_id=tenant_id,
                        company_id=company_id,
                        delegation_id=child["delegation_id"],
                    ),
                    _context(tenant_id, child_id),
                )
        else:
            revocation_task = asyncio.create_task(revoke())
            await asyncio.wait_for(entered.wait(), 5)
            creation = asyncio.create_task(_dispatch(app, child_command, middle_context))
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(creation), 0.1)
            release.set()
            await asyncio.wait_for(revocation_task, 5)
            with pytest.raises(BusinessOSError) as rejected:
                await asyncio.wait_for(creation, 5)
            assert rejected.value.code == "forbidden"
    finally:
        await app.shutdown()
