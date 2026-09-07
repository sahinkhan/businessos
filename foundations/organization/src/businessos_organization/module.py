"""Organization module registration and tenant-consistent hierarchy handlers."""

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from importlib.resources import files
from typing import ClassVar
from uuid import UUID, uuid4

from businessos_identity import GetMembership, MembershipRecord
from pydantic import Field
from sqlalchemy import insert, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.sql.schema import Table

from businessos.sdk import (
    MESSAGE_DISPATCHER,
    BusinessOSError,
    Command,
    DomainEvent,
    HandlingContext,
    ModuleManifest,
    ModuleRegistration,
    PermissionDeclaration,
    Query,
    RequestContext,
    TenantContext,
)

from .contracts import (
    FinancialDimensionType,
    OrganizationContract,
    OrganizationNode,
    OrganizationScopeType,
    OrganizationSnapshot,
    OrganizationUnitType,
)
from .models import (
    ASSIGNMENTS,
    COMPANIES,
    DELEGATED_SCOPES,
    ENTERPRISE_GROUPS,
    FINANCIAL_DIMENSIONS,
    LEGAL_ENTITIES,
    OPERATING_SITES,
    ORG_UNITS,
    REGIONS,
    RELATIONSHIPS,
    SITE_TYPES,
    WAREHOUSE_LOCATIONS,
    WAREHOUSES,
)


class _NamedCommand(Command):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    code: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
    name: str = Field(min_length=1, max_length=200)
    effective_from: date | None = None
    effective_until: date | None = None


class CreateEnterpriseGroup(_NamedCommand):
    pass


class CreateLegalEntity(_NamedCommand):
    enterprise_group_id: UUID
    registration_number: str | None = Field(default=None, max_length=200)
    country_code: str = Field(pattern=r"^[A-Z]{2}$")


class CreateCompany(_NamedCommand):
    legal_entity_id: UUID
    base_currency: str = Field(pattern=r"^[A-Z]{3}$")
    timezone: str = Field(min_length=1, max_length=100)


class CreateOrgUnit(_NamedCommand):
    company_id: UUID
    parent_id: UUID | None = None
    unit_type: OrganizationUnitType


class CreateRegion(_NamedCommand):
    company_id: UUID
    parent_id: UUID | None = None


class RegisterSiteType(Command):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    code: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,99}$")
    name: str = Field(min_length=1, max_length=200)
    profile_contract: str | None = Field(default=None, max_length=300)


class CreateOperatingSite(_NamedCommand):
    company_id: UUID
    region_id: UUID | None = None
    site_type_id: UUID
    timezone: str = Field(min_length=1, max_length=100)


class CreateFinancialDimension(_NamedCommand):
    company_id: UUID
    dimension_type: FinancialDimensionType


class CreateWarehouse(_NamedCommand):
    company_id: UUID
    operating_site_id: UUID | None = None


class CreateWarehouseLocation(_NamedCommand):
    warehouse_id: UUID
    parent_id: UUID | None = None


class CreateRelationship(Command):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    source_type: OrganizationScopeType
    source_id: UUID
    target_type: OrganizationScopeType
    target_id: UUID
    relationship_type: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,99}$")
    effective_from: date | None = None
    effective_until: date | None = None


class AssignPrincipal(Command):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    principal_id: UUID
    scope_type: OrganizationScopeType
    scope_id: UUID
    title: str | None = Field(default=None, max_length=200)
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class DelegateScope(Command):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    recipient_principal_id: UUID
    scope_type: OrganizationScopeType
    scope_id: UUID
    allowed_actions: tuple[str, ...]
    valid_from: datetime
    valid_until: datetime
    reason: str = Field(min_length=1, max_length=1000)


class ReadOrganization(Query):
    tenant_id: UUID


class SelectActiveScope(Query):
    tenant_id: UUID
    enterprise_group_id: UUID | None = None
    legal_entity_id: UUID | None = None
    company_id: UUID | None = None
    business_unit_id: UUID | None = None
    division_id: UUID | None = None
    department_id: UUID | None = None
    team_id: UUID | None = None
    region_id: UUID | None = None
    operating_site_id: UUID | None = None
    warehouse_id: UUID | None = None
    cost_center_id: UUID | None = None
    profit_center_id: UUID | None = None
    project_id: UUID | None = None
    delegation_id: UUID | None = None


class LegalEntityCreated(DomainEvent):
    event_type: ClassVar[str] = "organization.legal_entity.created.v1"
    legal_entity_id: UUID


class CompanyCreated(DomainEvent):
    event_type: ClassVar[str] = "organization.company.created.v1"
    company_id: UUID


class OperatingSiteCreated(DomainEvent):
    event_type: ClassVar[str] = "organization.site.created.v1"
    operating_site_id: UUID


_SCOPE_TABLES = {
    OrganizationScopeType.ENTERPRISE_GROUP: ENTERPRISE_GROUPS,
    OrganizationScopeType.LEGAL_ENTITY: LEGAL_ENTITIES,
    OrganizationScopeType.COMPANY: COMPANIES,
    OrganizationScopeType.ORG_UNIT: ORG_UNITS,
    OrganizationScopeType.REGION: REGIONS,
    OrganizationScopeType.OPERATING_SITE: OPERATING_SITES,
    OrganizationScopeType.WAREHOUSE: WAREHOUSES,
    OrganizationScopeType.FINANCIAL_DIMENSION: FINANCIAL_DIMENSIONS,
}


class OrganizationModule:
    def __init__(self) -> None:
        data = json.loads(
            files("businessos_organization").joinpath("manifest.json").read_text(encoding="utf-8")
        )
        self.manifest = ModuleManifest.model_validate(data)

    async def register(self, registration: ModuleRegistration) -> None:
        registration.permission(
            PermissionDeclaration(
                key="foundation.organization.read", description="Read tenant organization structure"
            )
        )
        registration.permission(
            PermissionDeclaration(
                key="foundation.organization.manage",
                description="Manage tenant organization structure",
            )
        )
        registration.contract("foundation.organization.v1", OrganizationContract())
        registration.command(
            CreateEnterpriseGroup,
            self._enterprise_group,
            permission="foundation.organization.manage",
        )
        registration.command(
            CreateLegalEntity, self._legal_entity, permission="foundation.organization.manage"
        )
        registration.command(
            CreateCompany, self._company, permission="foundation.organization.manage"
        )
        registration.command(
            CreateOrgUnit, self._org_unit, permission="foundation.organization.manage"
        )
        registration.command(
            CreateRegion, self._region, permission="foundation.organization.manage"
        )
        registration.command(
            RegisterSiteType, self._site_type, permission="foundation.organization.manage"
        )
        registration.command(
            CreateOperatingSite,
            self._operating_site,
            permission="foundation.organization.manage",
        )
        registration.command(
            CreateFinancialDimension,
            self._financial_dimension,
            permission="foundation.organization.manage",
        )
        registration.command(
            CreateWarehouse, self._warehouse, permission="foundation.organization.manage"
        )
        registration.command(
            CreateWarehouseLocation,
            self._warehouse_location,
            permission="foundation.organization.manage",
        )
        registration.command(
            CreateRelationship,
            self._relationship,
            permission="foundation.organization.manage",
        )
        registration.command(
            AssignPrincipal, self._assignment, permission="foundation.organization.manage"
        )
        registration.command(
            DelegateScope, self._delegation, permission="foundation.organization.manage"
        )
        registration.query(ReadOrganization, self._read, permission="foundation.organization.read")
        registration.query(
            SelectActiveScope, self._select_scope, permission="foundation.organization.read"
        )

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def _enterprise_group(
        self, command: CreateEnterpriseGroup, context: HandlingContext
    ) -> object:
        tenant = _tenant(context.request, command.tenant_id)
        _valid_dates(command.effective_from, command.effective_until)
        await _insert_named(context, ENTERPRISE_GROUPS, command, tenant)
        return {"enterprise_group_id": command.id}

    async def _legal_entity(self, command: CreateLegalEntity, context: HandlingContext) -> object:
        tenant = _tenant(context.request, command.tenant_id)
        await _require_owned(context, ENTERPRISE_GROUPS, command.enterprise_group_id, tenant)
        await _insert_named(
            context,
            LEGAL_ENTITIES,
            command,
            tenant,
            enterprise_group_id=command.enterprise_group_id,
            registration_number=command.registration_number,
            country_code=command.country_code,
        )
        context.emit(
            LegalEntityCreated(
                tenant_id=tenant.tenant_id,
                correlation_id=context.request.correlation_id,
                legal_entity_id=command.id,
            )
        )
        return {"legal_entity_id": command.id}

    async def _company(self, command: CreateCompany, context: HandlingContext) -> object:
        tenant = _tenant(context.request, command.tenant_id)
        await _require_owned(context, LEGAL_ENTITIES, command.legal_entity_id, tenant)
        await _insert_named(
            context,
            COMPANIES,
            command,
            tenant,
            legal_entity_id=command.legal_entity_id,
            base_currency=command.base_currency,
            timezone=command.timezone,
        )
        context.emit(
            CompanyCreated(
                tenant_id=tenant.tenant_id,
                correlation_id=context.request.correlation_id,
                company_id=command.id,
            )
        )
        return {"company_id": command.id}

    async def _org_unit(self, command: CreateOrgUnit, context: HandlingContext) -> object:
        tenant = _tenant(context.request, command.tenant_id)
        await _require_owned(context, COMPANIES, command.company_id, tenant)
        if command.parent_id is not None:
            parent = await _require_owned(context, ORG_UNITS, command.parent_id, tenant)
            if parent["company_id"] != command.company_id:
                raise _hierarchy_error()
        await _insert_named(
            context,
            ORG_UNITS,
            command,
            tenant,
            company_id=command.company_id,
            parent_id=command.parent_id,
            unit_type=command.unit_type,
        )
        return {"org_unit_id": command.id, "unit_type": command.unit_type}

    async def _region(self, command: CreateRegion, context: HandlingContext) -> object:
        tenant = _tenant(context.request, command.tenant_id)
        await _require_owned(context, COMPANIES, command.company_id, tenant)
        if command.parent_id is not None:
            parent = await _require_owned(context, REGIONS, command.parent_id, tenant)
            if parent["company_id"] != command.company_id:
                raise _hierarchy_error()
        await _insert_named(
            context,
            REGIONS,
            command,
            tenant,
            company_id=command.company_id,
            parent_id=command.parent_id,
        )
        return {"region_id": command.id}

    async def _site_type(self, command: RegisterSiteType, context: HandlingContext) -> object:
        tenant = _tenant(context.request, command.tenant_id)
        await context.unit_of_work.persistence.execute(
            insert(SITE_TYPES).values(
                id=command.id,
                tenant_id=tenant.tenant_id,
                code=command.code,
                name=command.name,
                profile_contract=command.profile_contract,
            )
        )
        return {"site_type_id": command.id}

    async def _operating_site(
        self, command: CreateOperatingSite, context: HandlingContext
    ) -> object:
        tenant = _tenant(context.request, command.tenant_id)
        await _require_owned(context, COMPANIES, command.company_id, tenant)
        await _require_owned(context, SITE_TYPES, command.site_type_id, tenant)
        if command.region_id is not None:
            region = await _require_owned(context, REGIONS, command.region_id, tenant)
            if region["company_id"] != command.company_id:
                raise _hierarchy_error()
        await _insert_named(
            context,
            OPERATING_SITES,
            command,
            tenant,
            company_id=command.company_id,
            region_id=command.region_id,
            site_type_id=command.site_type_id,
            timezone=command.timezone,
        )
        context.emit(
            OperatingSiteCreated(
                tenant_id=tenant.tenant_id,
                correlation_id=context.request.correlation_id,
                operating_site_id=command.id,
            )
        )
        return {"operating_site_id": command.id}

    async def _financial_dimension(
        self, command: CreateFinancialDimension, context: HandlingContext
    ) -> object:
        tenant = _tenant(context.request, command.tenant_id)
        await _require_owned(context, COMPANIES, command.company_id, tenant)
        await _insert_named(
            context,
            FINANCIAL_DIMENSIONS,
            command,
            tenant,
            company_id=command.company_id,
            dimension_type=command.dimension_type,
        )
        return {"financial_dimension_id": command.id}

    async def _warehouse(self, command: CreateWarehouse, context: HandlingContext) -> object:
        tenant = _tenant(context.request, command.tenant_id)
        await _require_owned(context, COMPANIES, command.company_id, tenant)
        if command.operating_site_id is not None:
            site = await _require_owned(context, OPERATING_SITES, command.operating_site_id, tenant)
            if site["company_id"] != command.company_id:
                raise _hierarchy_error()
        await _insert_named(
            context,
            WAREHOUSES,
            command,
            tenant,
            company_id=command.company_id,
            operating_site_id=command.operating_site_id,
        )
        return {"warehouse_id": command.id}

    async def _warehouse_location(
        self, command: CreateWarehouseLocation, context: HandlingContext
    ) -> object:
        tenant = _tenant(context.request, command.tenant_id)
        await _require_owned(context, WAREHOUSES, command.warehouse_id, tenant)
        if command.parent_id is not None:
            parent = await _require_owned(context, WAREHOUSE_LOCATIONS, command.parent_id, tenant)
            if parent["warehouse_id"] != command.warehouse_id:
                raise _hierarchy_error()
        await _insert_named(
            context,
            WAREHOUSE_LOCATIONS,
            command,
            tenant,
            warehouse_id=command.warehouse_id,
            parent_id=command.parent_id,
        )
        return {"warehouse_location_id": command.id}

    async def _relationship(self, command: CreateRelationship, context: HandlingContext) -> object:
        tenant = _tenant(context.request, command.tenant_id)
        _valid_dates(command.effective_from, command.effective_until)
        await _require_owned(context, _SCOPE_TABLES[command.source_type], command.source_id, tenant)
        await _require_owned(context, _SCOPE_TABLES[command.target_type], command.target_id, tenant)
        await context.unit_of_work.persistence.execute(
            insert(RELATIONSHIPS).values(**command.model_dump())
        )
        return {"relationship_id": command.id}

    async def _assignment(self, command: AssignPrincipal, context: HandlingContext) -> object:
        tenant = _tenant(context.request, command.tenant_id)
        _valid_datetimes(command.valid_from, command.valid_until)
        membership = await self._membership(command.principal_id, context)
        if not membership.is_effective():
            raise BusinessOSError(
                "inactive_membership", "Active membership is required", status_code=409
            )
        await _require_owned(context, _SCOPE_TABLES[command.scope_type], command.scope_id, tenant)
        await context.unit_of_work.persistence.execute(
            insert(ASSIGNMENTS).values(**command.model_dump())
        )
        return {"assignment_id": command.id}

    async def _delegation(self, command: DelegateScope, context: HandlingContext) -> object:
        tenant = _tenant(context.request, command.tenant_id)
        _valid_datetimes(command.valid_from, command.valid_until)
        if not command.allowed_actions:
            raise BusinessOSError(
                "invalid_delegation", "Delegation actions are required", status_code=422
            )
        membership = await self._membership(command.recipient_principal_id, context)
        if not membership.is_effective():
            raise BusinessOSError(
                "inactive_membership", "Active membership is required", status_code=409
            )
        await _require_owned(context, _SCOPE_TABLES[command.scope_type], command.scope_id, tenant)
        await context.unit_of_work.persistence.execute(
            insert(DELEGATED_SCOPES).values(
                **command.model_dump(), grantor_principal_id=tenant.principal_id
            )
        )
        return {"delegation_id": command.id}

    async def _membership(self, principal_id: UUID, context: HandlingContext) -> MembershipRecord:
        tenant = context.request.tenant
        assert tenant is not None
        dispatcher = await context.dependencies.resolve(MESSAGE_DISPATCHER)
        result = await dispatcher.query(
            GetMembership(tenant_id=tenant.tenant_id, principal_id=principal_id),
            context.request,
            context.dependencies,
        )
        if not isinstance(result, MembershipRecord):
            raise RuntimeError("Identity membership contract returned an invalid result")
        return result

    async def _read(self, query: ReadOrganization, context: HandlingContext) -> object:
        tenant = _tenant(context.request, query.tenant_id)
        results: list[tuple[RowMapping, ...]] = []
        for table in (
            ENTERPRISE_GROUPS,
            LEGAL_ENTITIES,
            COMPANIES,
            ORG_UNITS,
            REGIONS,
            OPERATING_SITES,
            WAREHOUSES,
        ):
            result = await context.unit_of_work.persistence.execute(
                select(table).where(table.c.tenant_id == tenant.tenant_id).order_by(table.c.code)
            )
            results.append(tuple(result.mappings()))
        kinds = (
            "enterprise_group",
            "legal_entity",
            "company",
            "org_unit",
            "region",
            "operating_site",
            "warehouse",
        )
        groups = tuple(
            tuple(
                OrganizationNode(
                    id=row["id"],
                    tenant_id=row["tenant_id"],
                    kind=kind,
                    code=row["code"],
                    name=row["name"],
                    effective_from=row.get("effective_from"),
                    effective_until=row.get("effective_until"),
                )
                for row in rows
            )
            for kind, rows in zip(kinds, results, strict=True)
        )
        return OrganizationSnapshot(
            tenant_id=tenant.tenant_id,
            enterprise_groups=groups[0],
            legal_entities=groups[1],
            companies=groups[2],
            org_units=groups[3],
            regions=groups[4],
            operating_sites=groups[5],
            warehouses=groups[6],
        )

    async def _select_scope(self, query: SelectActiveScope, context: HandlingContext) -> object:
        tenant = _tenant(context.request, query.tenant_id)
        checks = (
            ("enterprise_group", query.enterprise_group_id, ENTERPRISE_GROUPS),
            ("legal_entity", query.legal_entity_id, LEGAL_ENTITIES),
            ("company", query.company_id, COMPANIES),
            ("business_unit", query.business_unit_id, ORG_UNITS),
            ("division", query.division_id, ORG_UNITS),
            ("department", query.department_id, ORG_UNITS),
            ("team", query.team_id, ORG_UNITS),
            ("region", query.region_id, REGIONS),
            ("operating_site", query.operating_site_id, OPERATING_SITES),
            ("warehouse", query.warehouse_id, WAREHOUSES),
            ("cost_center", query.cost_center_id, FINANCIAL_DIMENSIONS),
            ("profit_center", query.profit_center_id, FINANCIAL_DIMENSIONS),
            ("project", query.project_id, FINANCIAL_DIMENSIONS),
        )
        resolved: dict[str, RowMapping] = {}
        selected_scopes: set[tuple[str, UUID]] = set()
        for kind, identifier, table in checks:
            if identifier is not None:
                row = await _require_owned(context, table, identifier, tenant)
                resolved[kind] = row
                scope_kind = (
                    OrganizationScopeType.ORG_UNIT.value
                    if kind in {"business_unit", "division", "department", "team"}
                    else OrganizationScopeType.FINANCIAL_DIMENSION.value
                    if kind in {"cost_center", "profit_center", "project"}
                    else kind
                )
                selected_scopes.add((scope_kind, identifier))
        _validate_selected_hierarchy(resolved)
        now = datetime.now(UTC)
        authorized_by_delegation = False
        if query.delegation_id is not None:
            delegation = await _require_owned(
                context, DELEGATED_SCOPES, query.delegation_id, tenant
            )
            if (
                delegation["recipient_principal_id"] != tenant.principal_id
                or delegation["valid_from"] > now
                or delegation["valid_until"] < now
                or (delegation["scope_type"], delegation["scope_id"]) not in selected_scopes
            ):
                raise BusinessOSError(
                    "forbidden", "Delegation does not authorize the selected scope", status_code=403
                )
            authorized_by_delegation = True
        if selected_scopes and not authorized_by_delegation:
            assignments = await context.unit_of_work.persistence.execute(
                select(ASSIGNMENTS.c.scope_type, ASSIGNMENTS.c.scope_id).where(
                    ASSIGNMENTS.c.tenant_id == tenant.tenant_id,
                    ASSIGNMENTS.c.principal_id == tenant.principal_id,
                    (ASSIGNMENTS.c.valid_from.is_(None) | (ASSIGNMENTS.c.valid_from <= now)),
                    (ASSIGNMENTS.c.valid_until.is_(None) | (ASSIGNMENTS.c.valid_until >= now)),
                )
            )
            if selected_scopes.isdisjoint(set(assignments.tuples())):
                raise BusinessOSError(
                    "forbidden", "Principal is not assigned to the selected scope", status_code=403
                )
        return replace(
            tenant,
            enterprise_group_id=query.enterprise_group_id,
            legal_entity_id=query.legal_entity_id,
            active_company_id=query.company_id,
            business_unit_id=query.business_unit_id,
            division_id=query.division_id,
            department_id=query.department_id,
            team_id=query.team_id,
            region_id=query.region_id,
            operating_site_id=query.operating_site_id,
            warehouse_id=query.warehouse_id,
            cost_center_id=query.cost_center_id,
            profit_center_id=query.profit_center_id,
            project_id=query.project_id,
            delegation_id=query.delegation_id,
        )


def _validate_selected_hierarchy(rows: dict[str, RowMapping]) -> None:
    group = rows.get("enterprise_group")
    legal = rows.get("legal_entity")
    company = rows.get("company")
    if group is not None and legal is not None and legal["enterprise_group_id"] != group["id"]:
        raise _hierarchy_error()
    if legal is not None and company is not None and company["legal_entity_id"] != legal["id"]:
        raise _hierarchy_error()
    for kind in ("business_unit", "division", "department", "team"):
        row = rows.get(kind)
        if row is not None:
            if row["unit_type"] != kind:
                raise _hierarchy_error()
            if company is not None and row["company_id"] != company["id"]:
                raise _hierarchy_error()
    region = rows.get("region")
    if region is not None and company is not None and region["company_id"] != company["id"]:
        raise _hierarchy_error()
    site = rows.get("operating_site")
    if site is not None:
        if company is not None and site["company_id"] != company["id"]:
            raise _hierarchy_error()
        if region is not None and site["region_id"] != region["id"]:
            raise _hierarchy_error()
    warehouse = rows.get("warehouse")
    if warehouse is not None:
        if company is not None and warehouse["company_id"] != company["id"]:
            raise _hierarchy_error()
        if site is not None and warehouse["operating_site_id"] != site["id"]:
            raise _hierarchy_error()
    for kind in ("cost_center", "profit_center", "project"):
        row = rows.get(kind)
        if row is not None:
            if row["dimension_type"] != kind:
                raise _hierarchy_error()
            if company is not None and row["company_id"] != company["id"]:
                raise _hierarchy_error()


async def _insert_named(
    context: HandlingContext,
    table: Table,
    command: _NamedCommand,
    tenant: TenantContext,
    **extra: object,
) -> None:
    _valid_dates(command.effective_from, command.effective_until)
    await context.unit_of_work.persistence.execute(
        insert(table).values(
            id=command.id,
            tenant_id=tenant.tenant_id,
            code=command.code,
            name=command.name,
            effective_from=command.effective_from,
            effective_until=command.effective_until,
            **extra,
        )
    )


async def _require_owned(
    context: HandlingContext, table: Table, identifier: UUID, tenant: TenantContext
) -> RowMapping:
    result = await context.unit_of_work.persistence.execute(
        select(table).where(table.c.id == identifier, table.c.tenant_id == tenant.tenant_id)
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise BusinessOSError(
            "invalid_organization_scope", "Organization scope is invalid", status_code=422
        )
    return row


def _tenant(context: RequestContext, expected: UUID) -> TenantContext:
    tenant = context.tenant
    if tenant is None:
        raise BusinessOSError("unauthenticated", "Authentication required", status_code=401)
    if tenant.tenant_id != expected:
        raise BusinessOSError("forbidden", "Tenant scope mismatch", status_code=403)
    return tenant


def _valid_dates(start: date | None, end: date | None) -> None:
    if start is not None and end is not None and end < start:
        raise BusinessOSError(
            "invalid_effective_dates", "Effective dates are invalid", status_code=422
        )


def _valid_datetimes(start: datetime | None, end: datetime | None) -> None:
    if start is not None and end is not None and end < start:
        raise BusinessOSError(
            "invalid_effective_dates", "Effective dates are invalid", status_code=422
        )


def _hierarchy_error() -> BusinessOSError:
    return BusinessOSError(
        "invalid_organization_hierarchy", "Organization hierarchy is inconsistent", status_code=422
    )
