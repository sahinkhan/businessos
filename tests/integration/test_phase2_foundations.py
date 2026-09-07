from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
import psycopg
import pytest
from businessos_identity import (
    CreateUser,
    GetMembership,
    GrantMembership,
    IdentityModule,
    MapExternalIdentity,
    MembershipRecord,
    OIDCConfiguration,
    OIDCContextResolver,
    OIDCTokenVerifier,
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
    ProvisionTenant,
    SetTenantEntitlement,
    SetTenantQuota,
    TenantModule,
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

    group_id, legal_us_id, legal_uk_id = uuid4(), uuid4(), uuid4()
    company_us_id, company_uk_id = uuid4(), uuid4()
    region_id, site_type_id, site_id = uuid4(), uuid4(), uuid4()
    business_unit_id, department_id = uuid4(), uuid4()
    cost_center_id, warehouse_id, location_id = uuid4(), uuid4(), uuid4()

    await _dispatch(
        app,
        CreateEnterpriseGroup(
            id=group_id, tenant_id=tenant_id, code="GLOBAL", name="Global Holdings"
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
    delegation_id = uuid4()
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

    tenant = await _query(app, GetTenant(tenant_id=tenant_id), context)
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
            delegation_id=delegation_id,
        ),
        context,
    )
    assert isinstance(tenant, TenantRecord) and tenant.status is TenantStatus.ACTIVE
    assert isinstance(membership, MembershipRecord) and membership.principal_id == admin_id
    assert isinstance(snapshot, OrganizationSnapshot)
    assert len(snapshot.legal_entities) == 2
    assert len(snapshot.companies) == 2
    assert isinstance(selected, TenantContext)
    assert selected.active_company_id == company_us_id
    assert selected.operating_site_id == site_id
    assert selected.delegation_id == delegation_id
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

    unassigned_context = _context(tenant_id, uuid4())
    with pytest.raises(BusinessOSError) as unassigned_scope:
        await _query(
            app,
            SelectActiveScope(tenant_id=tenant_id, company_id=company_us_id),
            unassigned_context,
        )
    assert unassigned_scope.value.code == "forbidden"

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
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
    assert plan.heads == ("organization_0001",)
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
    assert heads == {"organization_0001"}
    assert inventory == {
        "foundation.tenant",
        "foundation.identity",
        "foundation.organization",
    }
    app.runtime.migrations.downgrade(postgres_database.migration_url)
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    app.runtime.migrations.downgrade(postgres_database.migration_url)
