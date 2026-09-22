"""Delegation is bounded by a live, transactionally locked grantor authority chain."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import businessos_identity.authority as identity_authority
import pytest
from businessos_identity import (
    CreateUser,
    GrantMembership,
    MembershipRecord,
    RevokeMembership,
    lock_membership_for_authority,
)
from businessos_organization import (
    AssignPrincipal,
    CreateCompany,
    CreateEnterpriseGroup,
    CreateLegalEntity,
    DelegateScope,
    OrganizationScopeType,
    SelectActiveScope,
)

from businessos.bootstrap import create_application
from businessos.context import RequestContext
from businessos.errors import BusinessOSError
from businessos.sdk import TransactionalPersistence
from businessos.security import Authorizer
from tests.conftest import PostgreSQLTestDatabase
from tests.integration.test_phase2_foundations import (
    AllowAllPolicy,
    _context,
    _dispatch,
    _modules_with_authority,
    _seed_tenant,
    _settings,
)


async def _setup(
    postgres_database: PostgreSQLTestDatabase,
) -> tuple[Any, UUID, UUID, UUID, UUID, UUID, RequestContext]:
    app = create_application(
        _settings(postgres_database.runtime_url),
        modules=_modules_with_authority(),
        authorizer=Authorizer(AllowAllPolicy()),
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    await app.startup()
    tenant_id, grantor_id, recipient_id = uuid4(), uuid4(), uuid4()
    group_id, legal_id, company_a, company_b = uuid4(), uuid4(), uuid4(), uuid4()
    _seed_tenant(
        postgres_database.migration_url, tenant_id, "delegation-authority", status="active"
    )
    context = _context(tenant_id, grantor_id)
    for principal_id, email in (
        (grantor_id, "grantor@example.test"),
        (recipient_id, "recipient@example.test"),
    ):
        await _dispatch(
            app,
            CreateUser(
                tenant_id=tenant_id,
                user_id=principal_id,
                email=email,
                display_name=email,
            ),
            context,
        )
        await _dispatch(
            app,
            GrantMembership(tenant_id=tenant_id, principal_id=principal_id, principal_type="user"),
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
    return app, tenant_id, grantor_id, recipient_id, company_a, company_b, context


def _delegate(
    tenant_id: UUID,
    recipient_id: UUID,
    company_id: UUID,
    *,
    actions: tuple[str, ...] = ("organization.read",),
    start: datetime | None = None,
    end: datetime | None = None,
) -> DelegateScope:
    now = datetime.now(UTC)
    return DelegateScope(
        tenant_id=tenant_id,
        recipient_principal_id=recipient_id,
        scope_type=OrganizationScopeType.COMPANY,
        scope_id=company_id,
        allowed_actions=actions,
        valid_from=start or now,
        valid_until=end or now + timedelta(minutes=30),
        reason="bounded authority regression",
    )


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_delegation_rejects_scope_period_membership_and_action_escalation(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app, tenant_id, grantor_id, recipient_id, company_a, company_b, context = await _setup(
        postgres_database
    )
    try:
        now = datetime.now(UTC)
        await _dispatch(
            app,
            AssignPrincipal(
                tenant_id=tenant_id,
                principal_id=grantor_id,
                scope_type=OrganizationScopeType.COMPANY,
                scope_id=company_a,
                valid_from=now - timedelta(hours=2),
                valid_until=now - timedelta(hours=1),
            ),
            context,
        )
        await _dispatch(
            app,
            AssignPrincipal(
                tenant_id=tenant_id,
                principal_id=grantor_id,
                scope_type=OrganizationScopeType.COMPANY,
                scope_id=company_a,
                valid_from=now + timedelta(hours=1),
                valid_until=now + timedelta(hours=2),
            ),
            context,
        )
        with pytest.raises(BusinessOSError) as not_effective:
            await _dispatch(
                app,
                _delegate(tenant_id, recipient_id, company_a),
                context,
            )
        assert not_effective.value.code == "forbidden"
        await _dispatch(
            app,
            AssignPrincipal(
                tenant_id=tenant_id,
                principal_id=grantor_id,
                scope_type=OrganizationScopeType.COMPANY,
                scope_id=company_a,
                valid_from=now - timedelta(minutes=1),
                valid_until=now + timedelta(minutes=20),
            ),
            context,
        )
        allowed = cast(
            dict[str, UUID],
            await _dispatch(
                app,
                _delegate(tenant_id, recipient_id, company_a, end=now + timedelta(minutes=10)),
                context,
            ),
        )
        assert allowed["delegation_id"] is not None
        for denied in (
            _delegate(tenant_id, recipient_id, company_b),
            _delegate(tenant_id, recipient_id, company_a, end=now + timedelta(hours=1)),
        ):
            with pytest.raises(BusinessOSError) as error:
                await _dispatch(app, denied, context)
            assert error.value.code == "forbidden"

        # A delegated grant is action-limited even when its original grantor
        # has a broad assignment. It cannot be used as a wider source grant.
        recipient_context = _context(tenant_id, recipient_id)
        assert recipient_context.tenant is not None
        recipient_context = replace(
            recipient_context,
            tenant=replace(recipient_context.tenant, delegation_id=allowed["delegation_id"]),
        )
        with pytest.raises(BusinessOSError) as action_error:
            await _dispatch(
                app,
                _delegate(
                    tenant_id,
                    grantor_id,
                    company_a,
                    actions=("organization.manage",),
                    end=now + timedelta(minutes=5),
                ),
                recipient_context,
            )
        assert action_error.value.code == "forbidden"
        with pytest.raises(BusinessOSError) as widened_error:
            await _dispatch(
                app,
                _delegate(
                    tenant_id,
                    grantor_id,
                    company_a,
                    actions=("organization.read", "organization.manage"),
                    end=now + timedelta(minutes=5),
                ),
                recipient_context,
            )
        assert widened_error.value.code == "forbidden"

        other_tenant, other_group, other_legal, other_company = (uuid4(), uuid4(), uuid4(), uuid4())
        _seed_tenant(
            postgres_database.migration_url, other_tenant, "other-delegation", status="active"
        )
        other_context = _context(other_tenant)
        await _dispatch(
            app,
            CreateEnterpriseGroup(
                id=other_group, tenant_id=other_tenant, code="OTHER", name="Other"
            ),
            other_context,
        )
        await _dispatch(
            app,
            CreateLegalEntity(
                id=other_legal,
                tenant_id=other_tenant,
                code="OTHER",
                name="Other",
                enterprise_group_id=other_group,
                country_code="US",
            ),
            other_context,
        )
        await _dispatch(
            app,
            CreateCompany(
                id=other_company,
                tenant_id=other_tenant,
                code="OTHER",
                name="Other",
                legal_entity_id=other_legal,
                base_currency="USD",
                timezone="UTC",
            ),
            other_context,
        )
        with pytest.raises(BusinessOSError) as cross_tenant:
            await _dispatch(app, _delegate(tenant_id, recipient_id, other_company), context)
        assert cross_tenant.value.code == "invalid_organization_scope"
        await _dispatch(
            app,
            RevokeMembership(tenant_id=tenant_id, principal_id=recipient_id, principal_type="user"),
            context,
        )
        with pytest.raises(BusinessOSError) as inactive_recipient:
            await _dispatch(app, _delegate(tenant_id, recipient_id, company_a), context)
        assert inactive_recipient.value.code == "forbidden"
        await _dispatch(
            app,
            RevokeMembership(tenant_id=tenant_id, principal_id=grantor_id, principal_type="user"),
            context,
        )
        with pytest.raises(BusinessOSError):
            await _dispatch(
                app,
                _delegate(tenant_id, recipient_id, company_a),
                context,
            )
    finally:
        await app.shutdown()
        # Typed authority/provenance prevents a lossy downgrade; the fixture
        # drops this isolated database after the test.


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_concurrent_revocation_invalidates_stored_delegation(
    postgres_database: PostgreSQLTestDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, tenant_id, grantor_id, recipient_id, company_a, _, context = await _setup(
        postgres_database
    )
    try:
        await _dispatch(
            app,
            AssignPrincipal(
                tenant_id=tenant_id,
                principal_id=grantor_id,
                scope_type=OrganizationScopeType.COMPANY,
                scope_id=company_a,
            ),
            context,
        )
        locked = asyncio.Event()
        release = asyncio.Event()
        original = lock_membership_for_authority

        async def paused_lock(
            persistence: TransactionalPersistence,
            locked_tenant_id: UUID,
            principal_id: UUID,
            principal_type: Literal["user", "service_account", "device"],
        ) -> MembershipRecord:
            result = await original(persistence, locked_tenant_id, principal_id, principal_type)
            if principal_id == grantor_id:
                locked.set()
                await release.wait()
            return result

        monkeypatch.setattr(identity_authority, "lock_membership_for_authority", paused_lock)
        creation = asyncio.create_task(
            _dispatch(app, _delegate(tenant_id, recipient_id, company_a), context)
        )
        await asyncio.wait_for(locked.wait(), 5)
        revocation = asyncio.create_task(
            _dispatch(
                app,
                RevokeMembership(
                    tenant_id=tenant_id, principal_id=grantor_id, principal_type="user"
                ),
                context,
            )
        )
        await asyncio.sleep(0.1)
        assert not revocation.done()  # The grantor's membership row remains locked.
        release.set()
        created = cast(dict[str, UUID], await asyncio.wait_for(creation, 5))
        await asyncio.wait_for(revocation, 5)
        with pytest.raises(BusinessOSError) as rejected:
            await _dispatch(
                app,
                SelectActiveScope(
                    tenant_id=tenant_id,
                    company_id=company_a,
                    delegation_id=created["delegation_id"],
                ),
                _context(tenant_id, recipient_id),
            )
        assert rejected.value.code == "forbidden"
    finally:
        await app.shutdown()
        # Typed authority/provenance prevents a lossy downgrade; the fixture
        # drops this isolated database after the test.
