"""Real PostgreSQL proof of the ADR-010 Organization/Policy authority boundary."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
from businessos_identity import CreateUser, GrantMembership
from businessos_organization import (
    AssignPrincipal,
    CreateCompany,
    CreateEnterpriseGroup,
    CreateLegalEntity,
    DelegateScope,
    OrganizationScopeType,
    SelectActiveScope,
)
from businessos_policy import (
    AssignPermissionToRoleCommand,
    AssignRoleToSubjectCommand,
    CreateDelegationCommand,
    CreateRoleCommand,
    DelegationGrantRecord,
    PolicyModule,
    RecordAccessScope,
    RegisterPermissionCommand,
    RevokeDelegationCommand,
    RoleRecord,
    ScopeType,
    SetRecordPolicyCommand,
)
from businessos_policy.delegation_authority import authority_lock_key

from businessos.bootstrap import create_application
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


def _delegation(
    tenant_id: UUID, recipient_id: UUID, company_id: UUID, actions: tuple[str, ...]
) -> DelegateScope:
    now = datetime.now(UTC)
    return DelegateScope(
        tenant_id=tenant_id,
        recipient_principal_id=recipient_id,
        scope_type=OrganizationScopeType.COMPANY,
        scope_id=company_id,
        allowed_actions=actions,
        valid_from=now,
        valid_until=now + timedelta(minutes=20),
        reason="ADR-010 action authority proof",
    )


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_policy_authority_is_target_aware_and_rejects_partial_actions(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = create_application(
        _settings(postgres_database.runtime_url),
        modules=tuple(
            PolicyModule(action_resources={"billing.refund": "billing"})
            if module.manifest.module_id == "foundation.policy"
            else module
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
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    await app.startup()
    tenant_id, grantor_id, recipient_id = uuid4(), uuid4(), uuid4()
    group_id, legal_id, company_a, company_b = uuid4(), uuid4(), uuid4(), uuid4()
    _seed_tenant(postgres_database.migration_url, tenant_id, "adr010-authority", status="active")
    context = _context(tenant_id, grantor_id)
    try:
        for principal_id in (grantor_id, recipient_id):
            await _dispatch(
                app,
                CreateUser(
                    tenant_id=tenant_id,
                    user_id=principal_id,
                    email=f"{principal_id}@example.test",
                    display_name="ADR authority principal",
                ),
                context,
            )
            await _dispatch(
                app,
                GrantMembership(
                    tenant_id=tenant_id, principal_id=principal_id, principal_type="user"
                ),
                context,
            )
        await _dispatch(
            app,
            CreateEnterpriseGroup(id=group_id, tenant_id=tenant_id, code="GROUP", name="Group"),
            context,
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
            context,
        )
        for company_id, code in ((company_a, "A"), (company_b, "B")):
            await _dispatch(
                app,
                CreateCompany(
                    id=company_id,
                    tenant_id=tenant_id,
                    code=code,
                    name=code,
                    legal_entity_id=legal_id,
                    base_currency="USD",
                    timezone="UTC",
                ),
                context,
            )
        await _dispatch(
            app,
            AssignPrincipal(
                tenant_id=tenant_id,
                principal_id=grantor_id,
                scope_type=OrganizationScopeType.ENTERPRISE_GROUP,
                scope_id=group_id,
            ),
            context,
        )
        await _dispatch(
            app,
            RegisterPermissionCommand(
                code="organization.read", name="Read organization", category="organization"
            ),
            context,
        )
        await _dispatch(
            app,
            RegisterPermissionCommand(
                code="organization.*", name="Organization actions", category="organization"
            ),
            context,
        )
        role = cast(
            RoleRecord,
            await _dispatch(
                app,
                CreateRoleCommand(tenant_id=tenant_id, code="delegator", name="Delegator"),
                context,
            ),
        )
        role_id = role.id
        await _dispatch(
            app,
            AssignPermissionToRoleCommand(
                tenant_id=tenant_id, role_id=role_id, permission_code="organization.read"
            ),
            context,
        )
        assignment_start = datetime.now(UTC) - timedelta(minutes=1)
        assignment_end = datetime.now(UTC) + timedelta(hours=1)
        await _dispatch(
            app,
            AssignRoleToSubjectCommand(
                tenant_id=tenant_id,
                subject_id=grantor_id,
                subject_type="user",
                role_id=role_id,
                scope_type=ScopeType.COMPANY,
                scope_id=company_a,
                valid_from=assignment_start,
                valid_to=assignment_end,
            ),
            context,
        )
        allowed = cast(
            dict[str, UUID],
            await _dispatch(
                app,
                _delegation(tenant_id, recipient_id, company_a, ("organization.read",)),
                context,
            ),
        )
        assert allowed["delegation_id"]

        for target, actions in (
            (company_b, ("organization.read",)),
            (company_a, ("organization.read", "organization.manage")),
            (company_a, ("organization.read", "unknown.action")),
            (company_a, ("billing.refund",)),
        ):
            with pytest.raises(BusinessOSError) as denied:
                await _dispatch(app, _delegation(tenant_id, recipient_id, target, actions), context)
            assert denied.value.code == "forbidden"

        with pytest.raises(BusinessOSError) as cross_tenant:
            await _dispatch(
                app,
                _delegation(uuid4(), recipient_id, company_a, ("organization.read",)),
                context,
            )
        assert cross_tenant.value.code == "forbidden"

        # A framework manage permission and Organization scope alone cannot
        # manufacture a business action. Explicit Policy registration and
        # target-scoped permission are both required.
        await _dispatch(
            app,
            RegisterPermissionCommand(
                code="billing.refund", name="Refund billing", category="billing"
            ),
            context,
        )
        await _dispatch(
            app,
            AssignPermissionToRoleCommand(
                tenant_id=tenant_id, role_id=role_id, permission_code="billing.refund"
            ),
            context,
        )
        await _dispatch(
            app,
            _delegation(tenant_id, recipient_id, company_a, ("billing.refund",)),
            context,
        )
        with pytest.raises(BusinessOSError) as wrong_billing_target:
            await _dispatch(
                app,
                _delegation(tenant_id, recipient_id, company_b, ("billing.refund",)),
                context,
            )
        assert wrong_billing_target.value.code == "forbidden"

        await _dispatch(
            app,
            AssignPermissionToRoleCommand(
                tenant_id=tenant_id, role_id=role_id, permission_code="organization.*"
            ),
            context,
        )
        await _dispatch(
            app,
            _delegation(tenant_id, recipient_id, company_a, ("organization.manage",)),
            context,
        )

        with psycopg.connect(
            postgres_database.migration_url.replace("postgresql+psycopg://", "postgresql://", 1)
        ) as connection:
            rows = connection.execute(
                "SELECT allowed_actions FROM platform_org.delegated_scopes WHERE tenant_id = %s",
                (tenant_id,),
            ).fetchall()
        assert len(rows) == 3
        assert {tuple(row[0]) for row in rows} == {
            ("organization.read",),
            ("organization.manage",),
            ("billing.refund",),
        }

        recipient_context = _context(tenant_id, recipient_id)
        await _dispatch(
            app,
            SelectActiveScope(
                tenant_id=tenant_id,
                company_id=company_a,
                delegation_id=allowed["delegation_id"],
                action="organization.read",
            ),
            recipient_context,
        )

        # Policy delegation is the only action grant for this second grantor.
        # Queue its revocation and an Organization delegation against the same
        # tenant lock; either committed serial order is safe.
        onward_id = uuid4()
        await _dispatch(
            app,
            CreateUser(
                tenant_id=tenant_id,
                user_id=onward_id,
                email=f"{onward_id}@example.test",
                display_name="Onward delegatee",
            ),
            context,
        )
        await _dispatch(
            app,
            GrantMembership(tenant_id=tenant_id, principal_id=onward_id, principal_type="user"),
            context,
        )
        await _dispatch(
            app,
            AssignPrincipal(
                tenant_id=tenant_id,
                principal_id=recipient_id,
                scope_type=OrganizationScopeType.ENTERPRISE_GROUP,
                scope_id=group_id,
            ),
            context,
        )
        policy_delegation = cast(
            DelegationGrantRecord,
            await _dispatch(
                app,
                CreateDelegationCommand(
                    tenant_id=tenant_id,
                    delegator_id=grantor_id,
                    delegator_type="user",
                    delegatee_id=recipient_id,
                    delegatee_type="user",
                    role_id=role_id,
                    scope_type=ScopeType.COMPANY,
                    scope_id=company_a,
                    valid_from=assignment_start,
                    valid_to=assignment_end,
                ),
                context,
            ),
        )
        lock_connection = await psycopg.AsyncConnection.connect(
            postgres_database.migration_url.replace("postgresql+psycopg://", "postgresql://", 1)
        )
        try:
            await lock_connection.execute(
                "SELECT pg_advisory_xact_lock(%s)", (authority_lock_key(tenant_id),)
            )
            revoke_task = asyncio.create_task(
                _dispatch(
                    app,
                    RevokeDelegationCommand(
                        tenant_id=tenant_id,
                        delegation_id=policy_delegation.id,
                        reason="ADR-010 concurrency proof",
                    ),
                    context,
                )
            )
            await asyncio.sleep(0.2)
            assert not revoke_task.done()
            onward_task = asyncio.create_task(
                _dispatch(
                    app,
                    _delegation(tenant_id, onward_id, company_a, ("organization.read",)),
                    recipient_context,
                )
            )
            await asyncio.sleep(0.2)
            assert not onward_task.done()
            await lock_connection.commit()
            await asyncio.wait_for(revoke_task, timeout=10)
            try:
                onward = await asyncio.wait_for(onward_task, timeout=10)
            except BusinessOSError as denied_after_revoke:
                assert denied_after_revoke.code == "forbidden"
            else:
                # This is legal only when delegation won the lock first. Its
                # subsequent use must still fail after Policy revocation.
                onward_id_value = cast(dict[str, UUID], onward)["delegation_id"]
                with pytest.raises(BusinessOSError) as revoked_on_use:
                    await _dispatch(
                        app,
                        SelectActiveScope(
                            tenant_id=tenant_id,
                            company_id=company_a,
                            delegation_id=onward_id_value,
                        ),
                        _context(tenant_id, onward_id),
                    )
                assert revoked_on_use.value.code == "forbidden"
        finally:
            await lock_connection.rollback()
            await lock_connection.close()

        await _dispatch(
            app,
            SetRecordPolicyCommand(
                tenant_id=tenant_id,
                resource_type="organization",
                role_id=role_id,
                access_scope=RecordAccessScope.DENY,
            ),
            context,
        )
        with pytest.raises(BusinessOSError) as policy_denied:
            await _dispatch(
                app,
                _delegation(tenant_id, recipient_id, company_a, ("organization.read",)),
                context,
            )
        assert policy_denied.value.code == "forbidden"
        with pytest.raises(BusinessOSError) as revoked_on_consumption:
            await _dispatch(
                app,
                SelectActiveScope(
                    tenant_id=tenant_id,
                    company_id=company_a,
                    delegation_id=allowed["delegation_id"],
                    action="organization.read",
                ),
                recipient_context,
            )
        assert revoked_on_consumption.value.code == "forbidden"

        await app.runtime.lifecycle.disable("foundation.policy")
        with pytest.raises(BusinessOSError) as unavailable:
            await _dispatch(
                app,
                _delegation(tenant_id, recipient_id, company_a, ("organization.read",)),
                context,
            )
        assert unavailable.value.code == "configuration_error"
    finally:
        await app.shutdown()
        # This scenario writes typed authority and delegation provenance; the
        # forward migrations correctly block a lossy downgrade. The disposable
        # database fixture removes the database after the test.
