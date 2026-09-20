from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import jwt
import psycopg
import pytest
from businessos_identity import (
    ConfigureOIDCProvider,
    CreateUser,
    GetMembership,
    GrantMembership,
    IdentityModule,
    MapExternalIdentity,
    MembershipRecord,
    OIDCConfiguration,
    OIDCContextResolver,
    OIDCTokenVerifier,
    RegisterDevice,
    RegisterServiceAccount,
    SetMFAPolicy,
)
from businessos_organization import (
    AssignPrincipal,
    CreateCompany,
    CreateEnterpriseGroup,
    CreateFinancialDimension,
    CreateLegalEntity,
    CreateOperatingSite,
    CreateOrgUnit,
    CreateRegion,
    CreateWarehouse,
    CreateWarehouseLocation,
    DelegateScope,
    FinancialDimensionType,
    OrganizationModule,
    OrganizationScopeType,
    OrganizationSnapshot,
    OrganizationUnitType,
    ReadOrganization,
    RegisterSiteType,
    SelectActiveScope,
)
from businessos_organization.models import ENTERPRISE_GROUPS
from businessos_tenant import (
    DatabaseTenantAccessValidator,
    GetTenant,
    GetTenantEntitlements,
    GetTenantQuotas,
    ProvisionTenant,
    SetTenantEntitlement,
    SetTenantQuota,
    TenantEntitlementRecord,
    TenantModule,
    TenantQuotaRecord,
    TenantRecord,
    TenantStatus,
    TransitionTenant,
)
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import insert, select
from sqlalchemy.exc import DBAPIError, IntegrityError

from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.context import RequestContext, TenantContext
from businessos.dependencies import UNIT_OF_WORK_FACTORY
from businessos.errors import BusinessOSError
from businessos.modules import ModuleState
from businessos.persistence import Database, SQLAlchemyUnitOfWorkFactory
from businessos.security import Authorizer, RequestIdentity
from tests.conftest import PostgreSQLTestDatabase


class AllowAllPolicy:
    async def is_allowed(self, principal_id: UUID, tenant: TenantContext, permission: str) -> bool:
        return True


class StaticKeyResolver:
    def __init__(self, key: Any) -> None:
        self.key = key

    async def resolve(self, token: str) -> Any:
        return self.key


def _settings(url: str) -> Settings:
    return Settings(environment="test", database_url=url, database_pool_size=8)


def _modules() -> tuple[TenantModule, IdentityModule, OrganizationModule]:
    return TenantModule(), IdentityModule(), OrganizationModule()


def _context(tenant_id: UUID, principal_id: UUID | None = None) -> RequestContext:
    return RequestContext(
        correlation_id=f"phase2-{tenant_id}",
        trace_id=uuid4().hex,
        tenant=TenantContext(
            installation_id=uuid4(),
            tenant_id=tenant_id,
            principal_id=principal_id or uuid4(),
            authentication_strength="mfa",
        ),
    )


def _raw(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _seed_tenant(url: str, tenant_id: UUID, slug: str) -> None:
    with psycopg.connect(_raw(url)) as connection:
        connection.execute(
            "INSERT INTO platform_tenant.tenants "
            "(id, tenant_id, slug, name, status, deployment_mode, region) "
            "VALUES (%s, %s, %s, %s, 'requested', 'shared_schema', 'global')",
            (tenant_id, tenant_id, slug, slug.title()),
        )
        connection.execute(
            "INSERT INTO platform_tenant.tenant_status_history "
            "(id, tenant_id, to_status, reason) VALUES (%s, %s, 'requested', 'test seed')",
            (uuid4(), tenant_id),
        )
        connection.commit()


async def _dispatch(app: Any, message: object, context: RequestContext) -> object:
    assert app.runtime is not None
    async with app.container.request_scope() as dependencies:
        return await app.runtime.messages.command(message, context, dependencies)


async def _query(app: Any, message: object, context: RequestContext) -> object:
    assert app.runtime is not None
    async with app.container.request_scope() as dependencies:
        return await app.runtime.messages.query(message, context, dependencies)


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_multinational_tenant_identity_and_organization_exit_criterion(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    modules = _modules()
    app = create_application(
        _settings(postgres_database.runtime_url),
        modules=modules,
        authorizer=Authorizer(AllowAllPolicy()),
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    tenant_id = uuid4()
    admin_id = uuid4()
    context = _context(tenant_id, admin_id)
    await app.startup()
    assert [entry.state for entry in app.runtime.modules.ordered()] == [
        ModuleState.ENABLED,
        ModuleState.ENABLED,
        ModuleState.ENABLED,
    ]

    await _dispatch(
        app,
        ProvisionTenant(
            tenant_id=tenant_id,
            slug="global-holdings",
            name="Global Holdings",
            deployment_mode="shared_schema",
            region="global",
        ),
        context,
    )

    await _dispatch(
        app,
        TransitionTenant(
            tenant_id=tenant_id, target=TenantStatus.PROVISIONING, reason="resources ready"
        ),
        context,
    )
    await _dispatch(
        app,
        TransitionTenant(tenant_id=tenant_id, target=TenantStatus.ACTIVE),
        context,
    )
    await _dispatch(
        app,
        SetTenantEntitlement(tenant_id=tenant_id, capability="businessos.sales", enabled=True),
        context,
    )
    await _dispatch(
        app,
        SetTenantQuota(tenant_id=tenant_id, quota="users", limit_value=5000, unit="count"),
        context,
    )
    boundary = datetime.now(UTC)
    with pytest.raises(BusinessOSError) as invalid_entitlement_period:
        await _dispatch(
            app,
            SetTenantEntitlement(
                tenant_id=tenant_id,
                capability="businessos.invalid",
                enabled=True,
                effective_from=boundary,
                effective_until=boundary,
            ),
            context,
        )
    assert invalid_entitlement_period.value.code == "invalid_effective_dates"
    await _dispatch(
        app,
        SetTenantEntitlement(
            tenant_id=tenant_id,
            capability="businessos.sales",
            enabled=True,
            reference="plan-enterprise",
        ),
        context,
    )
    await _dispatch(
        app,
        SetTenantQuota(tenant_id=tenant_id, quota="users", limit_value=6000, unit="count"),
        context,
    )

    await _dispatch(
        app,
        CreateUser(
            user_id=admin_id,
            tenant_id=tenant_id,
            email="admin@example.test",
            display_name="Global Administrator",
        ),
        context,
    )
    await _dispatch(
        app,
        MapExternalIdentity(
            tenant_id=tenant_id,
            user_id=admin_id,
            issuer="https://identity.example.test",
            subject="admin-subject",
        ),
        context,
    )
    await _dispatch(
        app,
        GrantMembership(
            tenant_id=tenant_id,
            principal_id=admin_id,
            principal_type="user",
            scopes=({"type": "tenant", "id": str(tenant_id)},),
        ),
        context,
    )
    break_glass_id = uuid4()
    await _dispatch(
        app,
        CreateUser(
            user_id=break_glass_id,
            tenant_id=tenant_id,
            email="emergency@example.test",
            display_name="Emergency",
            break_glass=True,
            credential_secret_reference="secret://break-glass",
        ),
        context,
    )
    with pytest.raises(BusinessOSError) as break_glass_mapping:
        await _dispatch(
            app,
            MapExternalIdentity(
                tenant_id=tenant_id,
                user_id=break_glass_id,
                issuer="https://identity.example.test",
                subject="emergency-subject",
            ),
            context,
        )
    assert break_glass_mapping.value.code == "invalid_break_glass"
    await _dispatch(
        app,
        GrantMembership(
            tenant_id=tenant_id,
            principal_id=break_glass_id,
            principal_type="user",
        ),
        context,
    )
    with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
        connection.execute(
            "INSERT INTO platform_identity.external_identities "
            "(id, tenant_id, user_id, issuer, subject) VALUES (%s, %s, %s, %s, %s)",
            (
                uuid4(),
                tenant_id,
                break_glass_id,
                "https://identity.example.test",
                "legacy-emergency-subject",
            ),
        )
        connection.commit()
    device_id = uuid4()
    await _dispatch(
        app,
        RegisterDevice(
            device_id=device_id,
            tenant_id=tenant_id,
            principal_id=admin_id,
            principal_type="user",
            name="Admin Device",
            device_type="workstation",
            credential_secret_reference="secret://device/admin",
        ),
        context,
    )
    with pytest.raises(BusinessOSError) as unknown_device_principal:
        await _dispatch(
            app,
            RegisterDevice(
                tenant_id=tenant_id,
                principal_id=uuid4(),
                principal_type="user",
                name="Unknown Device",
                device_type="workstation",
                credential_secret_reference="secret://device/unknown",
            ),
            context,
        )
    assert unknown_device_principal.value.code == "not_found"
    other_tenant_id, other_user_id = uuid4(), uuid4()
    other_context = _context(other_tenant_id, other_user_id)
    await _dispatch(
        app,
        ProvisionTenant(
            tenant_id=other_tenant_id,
            slug="other-tenant",
            name="Other Tenant",
            deployment_mode="shared_schema",
            region="global",
        ),
        other_context,
    )
    await _dispatch(
        app,
        CreateUser(
            user_id=other_user_id,
            tenant_id=other_tenant_id,
            email="other@example.test",
            display_name="Other User",
        ),
        other_context,
    )
    with pytest.raises(BusinessOSError) as cross_tenant_device:
        await _dispatch(
            app,
            RegisterDevice(
                tenant_id=tenant_id,
                principal_id=other_user_id,
                principal_type="user",
                name="Cross Tenant Device",
                device_type="workstation",
                credential_secret_reference="secret://device/cross",
            ),
            context,
        )
    assert cross_tenant_device.value.code == "not_found"
    service_account_id = uuid4()
    await _dispatch(
        app,
        RegisterServiceAccount(
            service_account_id=service_account_id,
            tenant_id=tenant_id,
            name="Integration Agent",
            credential_secret_reference="secret://service/integration",
        ),
        context,
    )
    for principal_id, principal_type in (
        (service_account_id, "service_account"),
        (device_id, "device"),
    ):
        await _dispatch(
            app,
            GrantMembership(
                tenant_id=tenant_id,
                principal_id=principal_id,
                principal_type=principal_type,
            ),
            context,
        )
    future_group_id, expired_group_id, inactive_group_id = uuid4(), uuid4(), uuid4()
    today = datetime.now(UTC).date()
    await _dispatch(
        app,
        CreateEnterpriseGroup(
            id=future_group_id,
            tenant_id=tenant_id,
            code="FUTURE",
            name="Future",
            effective_from=today + timedelta(days=1),
        ),
        context,
    )
    await _dispatch(
        app,
        CreateEnterpriseGroup(
            id=expired_group_id,
            tenant_id=tenant_id,
            code="EXPIRED",
            name="Expired",
            effective_from=today - timedelta(days=2),
            effective_until=today,
        ),
        context,
    )
    await _dispatch(
        app,
        CreateEnterpriseGroup(
            id=inactive_group_id,
            tenant_id=tenant_id,
            code="INACTIVE",
            name="Inactive",
        ),
        context,
    )
    with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
        connection.execute(
            "UPDATE platform_org.enterprise_groups SET active = false "
            "WHERE tenant_id = %s AND id = %s",
            (tenant_id, inactive_group_id),
        )
        connection.commit()
    for invalid_scope_id in (future_group_id, expired_group_id, inactive_group_id):
        with pytest.raises(BusinessOSError) as invalid_effective_scope:
            await _dispatch(
                app,
                AssignPrincipal(
                    tenant_id=tenant_id,
                    principal_id=admin_id,
                    scope_type=OrganizationScopeType.ENTERPRISE_GROUP,
                    scope_id=invalid_scope_id,
                ),
                context,
            )
        assert invalid_effective_scope.value.code == "inactive_organization_scope"

    group_id, other_group_id = uuid4(), uuid4()
    legal_us_id, legal_uk_id, other_legal_id = uuid4(), uuid4(), uuid4()
    company_us_id, company_uk_id, other_company_id = uuid4(), uuid4(), uuid4()
    region_id, site_type_id, site_id, other_site_id = uuid4(), uuid4(), uuid4(), uuid4()
    business_unit_id, department_id, other_department_id, other_team_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    cost_center_id, warehouse_id, location_id = uuid4(), uuid4(), uuid4()

    await _dispatch(
        app,
        CreateEnterpriseGroup(
            id=group_id, tenant_id=tenant_id, code="GLOBAL", name="Global Holdings"
        ),
        context,
    )
    await _dispatch(
        app,
        CreateEnterpriseGroup(
            id=other_group_id,
            tenant_id=tenant_id,
            code="OTHER",
            name="Other Holdings",
        ),
        context,
    )
    for legal_id, code, country in (
        (legal_us_id, "US-LEGAL", "US"),
        (legal_uk_id, "UK-LEGAL", "GB"),
    ):
        await _dispatch(
            app,
            CreateLegalEntity(
                id=legal_id,
                tenant_id=tenant_id,
                code=code,
                name=code,
                enterprise_group_id=group_id,
                country_code=country,
            ),
            context,
        )
    await _dispatch(
        app,
        CreateLegalEntity(
            id=other_legal_id,
            tenant_id=tenant_id,
            code="OTHER-LEGAL",
            name="Other Legal",
            enterprise_group_id=other_group_id,
            country_code="CA",
        ),
        context,
    )
    for company_id, legal_id, code, currency, timezone in (
        (company_us_id, legal_us_id, "US-CO", "USD", "America/New_York"),
        (company_uk_id, legal_uk_id, "UK-CO", "GBP", "Europe/London"),
    ):
        await _dispatch(
            app,
            CreateCompany(
                id=company_id,
                tenant_id=tenant_id,
                code=code,
                name=code,
                legal_entity_id=legal_id,
                base_currency=currency,
                timezone=timezone,
            ),
            context,
        )
    await _dispatch(
        app,
        CreateCompany(
            id=other_company_id,
            tenant_id=tenant_id,
            code="OTHER-CO",
            name="Other Company",
            legal_entity_id=other_legal_id,
            base_currency="CAD",
            timezone="America/Toronto",
        ),
        context,
    )
    await _dispatch(
        app,
        CreateOrgUnit(
            id=business_unit_id,
            tenant_id=tenant_id,
            code="OPS",
            name="Operations",
            company_id=company_us_id,
            unit_type=OrganizationUnitType.BUSINESS_UNIT,
        ),
        context,
    )
    await _dispatch(
        app,
        CreateOrgUnit(
            id=other_department_id,
            tenant_id=tenant_id,
            code="FINANCE",
            name="Finance",
            company_id=company_us_id,
            parent_id=business_unit_id,
            unit_type=OrganizationUnitType.DEPARTMENT,
        ),
        context,
    )
    await _dispatch(
        app,
        CreateOrgUnit(
            id=other_team_id,
            tenant_id=tenant_id,
            code="FINANCE-AP",
            name="Accounts Payable",
            company_id=company_us_id,
            parent_id=other_department_id,
            unit_type=OrganizationUnitType.TEAM,
        ),
        context,
    )
    await _dispatch(
        app,
        CreateOrgUnit(
            id=department_id,
            tenant_id=tenant_id,
            code="OPS-WEST",
            name="West Operations",
            company_id=company_us_id,
            parent_id=business_unit_id,
            unit_type=OrganizationUnitType.DEPARTMENT,
        ),
        context,
    )
    await _dispatch(
        app,
        CreateRegion(
            id=region_id,
            tenant_id=tenant_id,
            code="US-WEST",
            name="US West",
            company_id=company_us_id,
        ),
        context,
    )
    await _dispatch(
        app,
        RegisterSiteType(
            id=site_type_id,
            tenant_id=tenant_id,
            code="branch",
            name="Branch",
            profile_contract="organization.branch.v1",
        ),
        context,
    )
    await _dispatch(
        app,
        CreateOperatingSite(
            id=site_id,
            tenant_id=tenant_id,
            code="SFO",
            name="San Francisco Branch",
            company_id=company_us_id,
            region_id=region_id,
            site_type_id=site_type_id,
            timezone="America/Los_Angeles",
        ),
        context,
    )
    await _dispatch(
        app,
        CreateOperatingSite(
            id=other_site_id,
            tenant_id=tenant_id,
            code="OTHER-SITE",
            name="Other Site",
            company_id=other_company_id,
            site_type_id=site_type_id,
            timezone="America/Toronto",
        ),
        context,
    )
    await _dispatch(
        app,
        CreateFinancialDimension(
            id=cost_center_id,
            tenant_id=tenant_id,
            code="CC-WEST",
            name="West Cost Center",
            company_id=company_us_id,
            dimension_type=FinancialDimensionType.COST_CENTER,
        ),
        context,
    )
    await _dispatch(
        app,
        CreateWarehouse(
            id=warehouse_id,
            tenant_id=tenant_id,
            code="WH-SFO",
            name="SFO Warehouse",
            company_id=company_us_id,
            operating_site_id=site_id,
        ),
        context,
    )
    await _dispatch(
        app,
        CreateWarehouseLocation(
            id=location_id,
            tenant_id=tenant_id,
            code="RECEIVING",
            name="Receiving",
            warehouse_id=warehouse_id,
        ),
        context,
    )
    await _dispatch(
        app,
        AssignPrincipal(
            tenant_id=tenant_id,
            principal_id=admin_id,
            scope_type=OrganizationScopeType.COMPANY,
            scope_id=company_us_id,
            title="Country Director",
        ),
        context,
    )
    await _dispatch(
        app,
        AssignPrincipal(
            tenant_id=tenant_id,
            principal_id=admin_id,
            scope_type=OrganizationScopeType.ENTERPRISE_GROUP,
            scope_id=group_id,
            title="Group Director",
        ),
        context,
    )
    for principal_id, principal_type in (
        (service_account_id, "service_account"),
        (device_id, "device"),
    ):
        await _dispatch(
            app,
            AssignPrincipal(
                tenant_id=tenant_id,
                principal_id=principal_id,
                principal_type=principal_type,
                scope_type=OrganizationScopeType.COMPANY,
                scope_id=company_us_id,
            ),
            context,
        )
    delegation_id = uuid4()
    group_delegation_id = uuid4()
    with pytest.raises(BusinessOSError) as zero_length_delegation:
        await _dispatch(
            app,
            DelegateScope(
                tenant_id=tenant_id,
                recipient_principal_id=admin_id,
                scope_type=OrganizationScopeType.OPERATING_SITE,
                scope_id=site_id,
                allowed_actions=("organization.read",),
                valid_from=boundary,
                valid_until=boundary,
                reason="invalid zero length",
            ),
            context,
        )
    assert zero_length_delegation.value.code == "invalid_effective_dates"
    await _dispatch(
        app,
        DelegateScope(
            id=delegation_id,
            tenant_id=tenant_id,
            recipient_principal_id=admin_id,
            scope_type=OrganizationScopeType.OPERATING_SITE,
            scope_id=site_id,
            allowed_actions=("organization.read",),
            valid_from=datetime.now(UTC),
            valid_until=datetime.now(UTC) + timedelta(hours=1),
            reason="regional coverage",
        ),
        context,
    )
    await _dispatch(
        app,
        DelegateScope(
            id=group_delegation_id,
            tenant_id=tenant_id,
            recipient_principal_id=admin_id,
            scope_type=OrganizationScopeType.ENTERPRISE_GROUP,
            scope_id=group_id,
            allowed_actions=("organization.read",),
            valid_from=datetime.now(UTC),
            valid_until=datetime.now(UTC) + timedelta(hours=1),
            reason="group coverage",
        ),
        context,
    )

    tenant = await _query(app, GetTenant(tenant_id=tenant_id), context)
    entitlements = cast(
        tuple[TenantEntitlementRecord, ...],
        await _query(app, GetTenantEntitlements(tenant_id=tenant_id), context),
    )
    quotas = cast(
        tuple[TenantQuotaRecord, ...],
        await _query(app, GetTenantQuotas(tenant_id=tenant_id), context),
    )
    with pytest.raises(BusinessOSError) as isolated_entitlement_read:
        await _query(
            app,
            GetTenantEntitlements(tenant_id=tenant_id),
            other_context,
        )
    assert isolated_entitlement_read.value.code == "forbidden"
    membership = await _query(
        app, GetMembership(tenant_id=tenant_id, principal_id=admin_id), context
    )
    snapshot = await _query(app, ReadOrganization(tenant_id=tenant_id), context)
    selected = await _query(
        app,
        SelectActiveScope(
            tenant_id=tenant_id,
            enterprise_group_id=group_id,
            legal_entity_id=legal_us_id,
            company_id=company_us_id,
            business_unit_id=business_unit_id,
            department_id=department_id,
            region_id=region_id,
            operating_site_id=site_id,
            warehouse_id=warehouse_id,
            cost_center_id=cost_center_id,
        ),
        context,
    )
    delegated = await _query(
        app,
        SelectActiveScope(
            tenant_id=tenant_id,
            operating_site_id=site_id,
            warehouse_id=warehouse_id,
            delegation_id=delegation_id,
        ),
        context,
    )
    for principal_id, principal_type in (
        (service_account_id, "service_account"),
        (device_id, "device"),
    ):
        principal_selection = await _query(
            app,
            SelectActiveScope(
                tenant_id=tenant_id,
                principal_type=principal_type,
                company_id=company_us_id,
            ),
            _context(tenant_id, principal_id),
        )
        assert isinstance(principal_selection, TenantContext)
        assert principal_selection.active_company_id == company_us_id
    assert isinstance(tenant, TenantRecord) and tenant.status is TenantStatus.ACTIVE
    assert entitlements[0].capability == "businessos.sales"
    assert entitlements[0].enabled is True
    assert quotas[0].quota == "users"
    assert entitlements[0].reference == "plan-enterprise"
    assert quotas[0].limit_value == 6000
    assert isinstance(membership, MembershipRecord) and membership.principal_id == admin_id
    assert isinstance(snapshot, OrganizationSnapshot)
    assert len(snapshot.legal_entities) == 3
    assert len(snapshot.companies) == 3
    assert (
        next(item for item in snapshot.org_units if item.id == department_id).parent_id
        == business_unit_id
    )
    assert snapshot.operating_sites[0].site_type_id == site_type_id
    assert snapshot.warehouse_locations[0].warehouse_id == warehouse_id
    assert snapshot.assignments[0].principal_type == "user"
    assert isinstance(selected, TenantContext)
    assert selected.active_company_id == company_us_id
    assert selected.operating_site_id == site_id
    assert selected.delegation_id is None
    assert isinstance(delegated, TenantContext)
    assert delegated.delegation_id == delegation_id
    with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
        audit_count = connection.execute(
            "SELECT count(*) FROM eventing.outbox_messages "
            "WHERE tenant_id = %s AND event_type = 'organization.active_scope.selected.v1'",
            (tenant_id,),
        ).fetchone()
    assert audit_count is not None and audit_count[0] >= 2
    with pytest.raises(BusinessOSError) as inconsistent_scope:
        await _query(
            app,
            SelectActiveScope(
                tenant_id=tenant_id,
                legal_entity_id=legal_uk_id,
                company_id=company_us_id,
            ),
            context,
        )
    assert inconsistent_scope.value.code == "invalid_organization_hierarchy"
    with pytest.raises(BusinessOSError) as unrelated_child:
        await _query(
            app,
            SelectActiveScope(
                tenant_id=tenant_id,
                enterprise_group_id=group_id,
                company_id=other_company_id,
            ),
            context,
        )
    assert unrelated_child.value.code == "invalid_organization_hierarchy"
    with pytest.raises(BusinessOSError) as parent_assignment_escape:
        await _query(
            app,
            SelectActiveScope(tenant_id=tenant_id, company_id=other_company_id),
            context,
        )
    assert parent_assignment_escape.value.code == "forbidden"
    with pytest.raises(BusinessOSError) as legal_site_escape:
        await _query(
            app,
            SelectActiveScope(
                tenant_id=tenant_id,
                legal_entity_id=legal_us_id,
                operating_site_id=other_site_id,
            ),
            context,
        )
    assert legal_site_escape.value.code == "invalid_organization_hierarchy"
    with pytest.raises(BusinessOSError) as delegation_escape:
        await _query(
            app,
            SelectActiveScope(
                tenant_id=tenant_id,
                company_id=other_company_id,
                delegation_id=group_delegation_id,
            ),
            context,
        )
    assert delegation_escape.value.code == "forbidden"
    with pytest.raises(BusinessOSError) as unrelated_org_unit:
        await _query(
            app,
            SelectActiveScope(
                tenant_id=tenant_id,
                department_id=department_id,
                team_id=other_team_id,
            ),
            context,
        )
    assert unrelated_org_unit.value.code == "invalid_organization_hierarchy"

    unassigned_context = _context(tenant_id, uuid4())
    with pytest.raises(BusinessOSError) as unassigned_scope:
        await _query(
            app,
            SelectActiveScope(tenant_id=tenant_id, company_id=company_us_id),
            unassigned_context,
        )
    assert unassigned_scope.value.code == "forbidden"

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    await _dispatch(
        app,
        ConfigureOIDCProvider(
            tenant_id=tenant_id,
            issuer="https://identity.example.test",
            audience="businessos",
            jwks_uri="https://identity.example.test/jwks",
            algorithms=("RS256",),
        ),
        context,
    )
    verifier = OIDCTokenVerifier(
        OIDCConfiguration(
            issuer="https://identity.example.test",
            audience="businessos",
            jwks_uri="https://identity.example.test/jwks",
        ),
        StaticKeyResolver(private_key.public_key()),
    )
    async with app.container.request_scope() as dependencies:
        factory = await dependencies.resolve(UNIT_OF_WORK_FACTORY)
    resolver = OIDCContextResolver(
        installation_id=uuid4(),
        verifier=verifier,
        unit_of_work_factory=factory,
        tenant_access=DatabaseTenantAccessValidator(uuid4(), factory),
    )
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": "https://identity.example.test",
            "sub": "admin-subject",
            "aud": "businessos",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "businessos_tenant_id": str(tenant_id),
            "amr": ["pwd", "mfa"],
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "integration"},
    )
    trusted = await resolver.resolve(
        RequestIdentity(
            method="GET",
            path="/",
            headers={"authorization": f"Bearer {token}", "x-tenant-id": str(uuid4())},
            correlation_id="oidc-integration",
            trace_id=uuid4().hex,
        )
    )
    assert trusted.tenant is not None
    assert trusted.tenant.tenant_id == tenant_id
    assert trusted.tenant.principal_id == admin_id
    assert trusted.tenant.authentication_strength == "mfa"
    wrong_tenant_token = jwt.encode(
        {
            "iss": "https://identity.example.test",
            "sub": "admin-subject",
            "aud": "businessos",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "businessos_tenant_id": str(other_tenant_id),
            "amr": ["pwd", "mfa"],
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "integration"},
    )
    with pytest.raises(BusinessOSError) as wrong_tenant_provider:
        await resolver.resolve(
            RequestIdentity(
                method="GET",
                path="/",
                headers={"authorization": f"Bearer {wrong_tenant_token}"},
                correlation_id="oidc-wrong-tenant-provider",
                trace_id=uuid4().hex,
            )
        )
    assert wrong_tenant_provider.value.code == "invalid_token"
    break_glass_token = jwt.encode(
        {
            "iss": "https://identity.example.test",
            "sub": "legacy-emergency-subject",
            "aud": "businessos",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "businessos_tenant_id": str(tenant_id),
            "amr": ["pwd", "mfa"],
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "integration"},
    )
    with pytest.raises(BusinessOSError) as federated_break_glass:
        await resolver.resolve(
            RequestIdentity(
                method="GET",
                path="/",
                headers={"authorization": f"Bearer {break_glass_token}"},
                correlation_id="oidc-break-glass",
                trace_id=uuid4().hex,
            )
        )
    assert federated_break_glass.value.code == "invalid_membership"
    await _dispatch(
        app,
        SetMFAPolicy(
            tenant_id=tenant_id,
            minimum_strength="mfa",
            required_methods=("mfa",),
        ),
        context,
    )
    password_token = jwt.encode(
        {
            "iss": "https://identity.example.test",
            "sub": "admin-subject",
            "aud": "businessos",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "businessos_tenant_id": str(tenant_id),
            "amr": ["pwd"],
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "integration"},
    )
    with pytest.raises(BusinessOSError) as insufficient_mfa:
        await resolver.resolve(
            RequestIdentity(
                method="GET",
                path="/",
                headers={"authorization": f"Bearer {password_token}"},
                correlation_id="oidc-password-only",
                trace_id=uuid4().hex,
            )
        )
    assert insufficient_mfa.value.code == "invalid_token"
    await _dispatch(
        app,
        ConfigureOIDCProvider(
            tenant_id=tenant_id,
            issuer="https://identity.example.test",
            audience="businessos",
            jwks_uri="https://identity.example.test/jwks",
            algorithms=("RS256",),
            active=False,
        ),
        context,
    )
    with pytest.raises(BusinessOSError) as inactive_provider:
        await resolver.resolve(
            RequestIdentity(
                method="GET",
                path="/",
                headers={"authorization": f"Bearer {token}"},
                correlation_id="oidc-inactive-provider",
                trace_id=uuid4().hex,
            )
        )
    assert inactive_provider.value.code == "invalid_token"
    await _dispatch(
        app,
        ConfigureOIDCProvider(
            tenant_id=tenant_id,
            issuer="https://identity.example.test",
            audience="businessos",
            jwks_uri="https://identity.example.test/jwks",
            algorithms=("ES256",),
            active=True,
        ),
        context,
    )
    with pytest.raises(BusinessOSError) as stale_configuration:
        await resolver.resolve(
            RequestIdentity(
                method="GET",
                path="/",
                headers={"authorization": f"Bearer {token}"},
                correlation_id="oidc-stale-configuration",
                trace_id=uuid4().hex,
            )
        )
    assert stale_configuration.value.code == "invalid_token"
    await _dispatch(
        app,
        ConfigureOIDCProvider(
            tenant_id=tenant_id,
            issuer="https://identity.example.test",
            audience="businessos",
            jwks_uri="https://identity.example.test/jwks",
            algorithms=("RS256",),
            active=True,
        ),
        context,
    )
    restored = await resolver.resolve(
        RequestIdentity(
            method="GET",
            path="/",
            headers={"authorization": f"Bearer {token}"},
            correlation_id="oidc-current-configuration",
            trace_id=uuid4().hex,
        )
    )
    assert restored.tenant is not None
    await _dispatch(
        app,
        TransitionTenant(tenant_id=tenant_id, target=TenantStatus.SUSPENDED),
        context,
    )
    with pytest.raises(BusinessOSError) as suspended_authentication:
        await resolver.resolve(
            RequestIdentity(
                method="GET",
                path="/",
                headers={"authorization": f"Bearer {token}"},
                correlation_id="suspended-tenant",
                trace_id=uuid4().hex,
            )
        )
    assert suspended_authentication.value.code == "tenant_unavailable"

    with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
        event_types = {
            row[0]
            for row in connection.execute(
                "SELECT event_type FROM eventing.outbox_messages WHERE tenant_id = %s",
                (tenant_id,),
            ).fetchall()
        }
    assert {
        "tenant.activated.v1",
        "identity.membership.granted.v1",
        "organization.legal_entity.created.v1",
        "organization.company.created.v1",
        "organization.site.created.v1",
    } <= event_types

    await app.shutdown()
    app.runtime.migrations.downgrade(postgres_database.migration_url)


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_phase2_rls_cross_tenant_writes_and_missing_context_fail_closed(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    modules = _modules()
    app = create_application(
        _settings(postgres_database.runtime_url),
        modules=modules,
        authorizer=Authorizer(AllowAllPolicy()),
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    tenant_a, tenant_b = uuid4(), uuid4()
    context_a, context_b = _context(tenant_a), _context(tenant_b)
    group_a, group_b = uuid4(), uuid4()
    await app.startup()
    await _dispatch(
        app,
        ProvisionTenant(
            tenant_id=tenant_a,
            slug="tenant-a",
            name="Tenant A",
            deployment_mode="shared_schema",
            region="global",
        ),
        context_a,
    )
    await _dispatch(
        app,
        ProvisionTenant(
            tenant_id=tenant_b,
            slug="tenant-b",
            name="Tenant B",
            deployment_mode="shared_schema",
            region="global",
        ),
        context_b,
    )
    await _dispatch(
        app,
        CreateEnterpriseGroup(id=group_a, tenant_id=tenant_a, code="GROUP", name="A"),
        context_a,
    )
    await _dispatch(
        app,
        CreateEnterpriseGroup(id=group_b, tenant_id=tenant_b, code="GROUP", name="B"),
        context_b,
    )
    with pytest.raises(BusinessOSError) as cross_tenant_parent:
        await _dispatch(
            app,
            CreateLegalEntity(
                tenant_id=tenant_a,
                code="CROSS",
                name="Cross Tenant",
                enterprise_group_id=group_b,
                country_code="US",
            ),
            context_a,
        )
    assert cross_tenant_parent.value.code == "invalid_organization_scope"
    with pytest.raises(IntegrityError):
        await _dispatch(
            app,
            CreateEnterpriseGroup(tenant_id=tenant_a, code="GROUP", name="Duplicate Code"),
            context_a,
        )

    runtime = Database(_settings(postgres_database.runtime_url))
    factory = SQLAlchemyUnitOfWorkFactory(runtime.sessions)
    async with factory.for_tenant(context_a.tenant) as unit_of_work:  # type: ignore[arg-type]
        rows = (
            (await unit_of_work.persistence.execute(select(ENTERPRISE_GROUPS.c.id))).scalars().all()
        )
        assert rows == [group_a]
        with pytest.raises(DBAPIError):
            await unit_of_work.persistence.execute(
                insert(ENTERPRISE_GROUPS).values(
                    id=uuid4(), tenant_id=tenant_b, code="FORGED", name="Forged"
                )
            )
            await unit_of_work.commit()

    async with runtime.sessions() as session:
        assert (await session.execute(select(ENTERPRISE_GROUPS.c.id))).all() == []
        with pytest.raises(DBAPIError):
            await session.execute(
                insert(ENTERPRISE_GROUPS).values(
                    id=uuid4(), tenant_id=tenant_a, code="NOCTX", name="No Context"
                )
            )
            await session.commit()
        await session.rollback()

    with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
        rls = connection.execute(
            "SELECT n.nspname, c.relname, c.relrowsecurity, c.relforcerowsecurity, "
            "pg_get_userbyid(c.relowner) "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname IN ('platform_tenant','platform_identity','platform_org') "
            "AND c.relkind = 'r' ORDER BY n.nspname, c.relname"
        ).fetchall()
        app_role = connection.execute(
            "SELECT rolsuper, rolbypassrls, rolinherit FROM pg_roles WHERE rolname='businessos_app'"
        ).fetchone()
    assert len(rls) == 25
    assert all(row[2] and row[3] and row[4] == "businessos_migrator" for row in rls)
    assert app_role == (False, False, False)

    await runtime.close()
    await app.shutdown()
    app.runtime.migrations.downgrade(postgres_database.migration_url)


@pytest.mark.integration
@pytest.mark.postgres
def test_phase2_migration_upgrade_downgrade_replay_and_constraints(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = create_application(_settings(postgres_database.runtime_url), modules=_modules())
    assert app.runtime is not None
    plan = app.runtime.migrations.plan()
    assert plan.heads == ("organization_0002",)
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    tenant_id = uuid4()
    _seed_tenant(postgres_database.migration_url, tenant_id, "constraint-tenant")
    with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(
                "INSERT INTO platform_org.enterprise_groups "
                "(id, tenant_id, code, name) VALUES (%s, %s, 'BAD', 'Missing Tenant')",
                (uuid4(), uuid4()),
            )
        connection.rollback()
        heads = {row[0] for row in connection.execute("SELECT version_num FROM alembic_version")}
        inventory = {
            row[0]
            for row in connection.execute(
                "SELECT module_id FROM platform_module.installed_module_migrations"
            )
        }
    assert heads == {"organization_0002"}
    assert inventory == {
        "foundation.tenant",
        "foundation.identity",
        "foundation.organization",
    }
    app.runtime.migrations.downgrade(postgres_database.migration_url)
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    app.runtime.migrations.downgrade(postgres_database.migration_url)


@pytest.mark.integration
@pytest.mark.postgres
def test_identity_migration_rejects_existing_cross_tenant_device_principal(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = create_application(_settings(postgres_database.runtime_url), modules=_modules())
    assert app.runtime is not None
    migrations = app.runtime.migrations
    migrations.upgrade(postgres_database.migration_url, "identity_0001")

    principal_tenant_id = uuid4()
    device_tenant_id = uuid4()
    principal_id = uuid4()
    device_id = uuid4()
    _seed_tenant(postgres_database.migration_url, principal_tenant_id, "principal-tenant")
    _seed_tenant(postgres_database.migration_url, device_tenant_id, "device-tenant")
    with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
        connection.execute(
            "INSERT INTO platform_identity.users "
            "(id, tenant_id, email, display_name) VALUES (%s, %s, %s, %s)",
            (principal_id, principal_tenant_id, "principal@example.test", "Principal"),
        )
        connection.execute(
            "INSERT INTO platform_identity.devices "
            "(id, tenant_id, principal_id, name, device_type, credential_secret_reference) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                device_id,
                device_tenant_id,
                principal_id,
                "Cross-tenant device",
                "workstation",
                "secret://device/cross-tenant",
            ),
        )
        connection.commit()

    with pytest.raises(IntegrityError, match="same tenant") as invalid_upgrade:
        migrations.upgrade(postgres_database.migration_url)
    assert isinstance(invalid_upgrade.value.orig, psycopg.errors.ForeignKeyViolation)

    with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
        heads = {row[0] for row in connection.execute("SELECT version_num FROM alembic_version")}
        principal_type_column = connection.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'platform_identity' "
            "AND table_name = 'devices' AND column_name = 'principal_type'"
        ).fetchone()
        persisted_device = connection.execute(
            "SELECT tenant_id, principal_id FROM platform_identity.devices WHERE id = %s",
            (device_id,),
        ).fetchone()
        connection.execute(
            "UPDATE platform_identity.devices SET tenant_id = %s WHERE id = %s",
            (principal_tenant_id, device_id),
        )
        connection.commit()

    assert heads == {"identity_0001"}
    assert principal_type_column is None
    assert persisted_device == (device_tenant_id, principal_id)

    migrations.upgrade(postgres_database.migration_url)
    with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
        heads = {row[0] for row in connection.execute("SELECT version_num FROM alembic_version")}
        migrated_device = connection.execute(
            "SELECT tenant_id, principal_id, principal_type "
            "FROM platform_identity.devices WHERE id = %s",
            (device_id,),
        ).fetchone()
    assert heads == {"organization_0002"}
    assert migrated_device == (principal_tenant_id, principal_id, "user")
    migrations.downgrade(postgres_database.migration_url)
