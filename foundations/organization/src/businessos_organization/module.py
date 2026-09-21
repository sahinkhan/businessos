"""Organization module registration and tenant-consistent hierarchy handlers."""

import json
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from importlib.resources import files
from typing import ClassVar, Literal, cast
from uuid import UUID, uuid4

from businessos_identity import GetMembership, MembershipRecord, lock_membership_for_authority
from businessos_tenant import effective_at, validate_effective_period
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
    CompanyRecord,
    DelegatedScopeRecord,
    EffectiveAssignment,
    EnterpriseGroupRecord,
    FinancialDimensionRecord,
    FinancialDimensionType,
    LegalEntityRecord,
    OperatingSiteRecord,
    OrganizationContract,
    OrganizationRelationshipRecord,
    OrganizationScopeType,
    OrganizationSnapshot,
    OrganizationUnitType,
    OrgUnitRecord,
    RegionRecord,
    SiteTypeRecord,
    WarehouseLocationRecord,
    WarehouseRecord,
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
    principal_type: Literal["user", "service_account", "device"] = "user"
    scope_type: OrganizationScopeType
    scope_id: UUID
    title: str | None = Field(default=None, max_length=200)
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class DelegateScope(Command):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    grantor_principal_type: Literal["user", "service_account", "device"] = "user"
    recipient_principal_id: UUID
    recipient_principal_type: Literal["user", "service_account", "device"] = "user"
    scope_type: OrganizationScopeType
    scope_id: UUID
    allowed_actions: tuple[str, ...]
    valid_from: datetime
    valid_until: datetime
    reason: str = Field(min_length=1, max_length=1000)


class ReadOrganization(Query):
    tenant_id: UUID


class SelectActiveScope(Command):
    tenant_id: UUID
    principal_type: Literal["user", "service_account", "device"] = "user"
    action: str = Field(default="organization.read", pattern=r"^[a-z][a-z0-9_.:-]+$")
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


class ActiveScopeSelected(DomainEvent):
    event_type: ClassVar[str] = "organization.active_scope.selected.v1"
    principal_id: UUID
    principal_type: str
    previous_scope: dict[str, str | None]
    selected_scope: dict[str, str | None]


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
        registration.command(
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
        validate_effective_period(command.effective_from, command.effective_until)
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
        validate_effective_period(command.effective_from, command.effective_until)
        await _require_owned(context, _SCOPE_TABLES[command.source_type], command.source_id, tenant)
        await _require_owned(context, _SCOPE_TABLES[command.target_type], command.target_id, tenant)
        await context.unit_of_work.persistence.execute(
            insert(RELATIONSHIPS).values(**command.model_dump())
        )
        return {"relationship_id": command.id}

    async def _assignment(self, command: AssignPrincipal, context: HandlingContext) -> object:
        tenant = _tenant(context.request, command.tenant_id)
        validate_effective_period(command.valid_from, command.valid_until)
        membership = await self._membership(command.principal_id, command.principal_type, context)
        if not _membership_is_current(membership):
            raise BusinessOSError(
                "inactive_membership", "Active membership is required", status_code=409
            )
        await _require_effective_scope_lineage(
            context, command.scope_type, command.scope_id, tenant, datetime.now(UTC)
        )
        await self._require_effective_membership(
            command.principal_id, command.principal_type, context
        )
        await context.unit_of_work.persistence.execute(
            insert(ASSIGNMENTS).values(**command.model_dump())
        )
        return {"assignment_id": command.id}

    async def _delegation(self, command: DelegateScope, context: HandlingContext) -> object:
        tenant = _tenant(context.request, command.tenant_id)
        validate_effective_period(command.valid_from, command.valid_until)
        if not command.allowed_actions:
            raise BusinessOSError(
                "invalid_delegation", "Delegation actions are required", status_code=422
            )
        now = datetime.now(UTC)
        if command.valid_until <= now:
            raise BusinessOSError("invalid_delegation", "Delegation has expired", status_code=422)
        await self._require_actor_membership(
            tenant.principal_id, command.grantor_principal_type, context
        )
        recipient = await lock_membership_for_authority(
            context.unit_of_work.persistence,
            tenant.tenant_id,
            command.recipient_principal_id,
            command.recipient_principal_type,
        )
        if not _membership_covers(recipient, now, command.valid_from, command.valid_until):
            raise BusinessOSError(
                "inactive_membership", "Active membership is required", status_code=409
            )
        target = await _require_effective_scope_lineage(
            context, command.scope_type, command.scope_id, tenant, now
        )
        lineage = await _scope_lineage(context, tenant, command.scope_type.value, target)
        if not _selected_scope_covers(tenant, lineage):
            raise BusinessOSError(
                "forbidden", "Selected scope does not cover delegation", status_code=403
            )
        authority_principal_id = tenant.principal_id
        authority_principal_type = command.grantor_principal_type
        visited: frozenset[UUID] = frozenset()
        if tenant.delegation_id is not None:
            selected_grant = await _require_owned(
                context, DELEGATED_SCOPES, tenant.delegation_id, tenant, lock=True
            )
            if (
                selected_grant["recipient_principal_id"] != tenant.principal_id
                or selected_grant["recipient_principal_type"] != command.grantor_principal_type
                or (selected_grant["scope_type"], selected_grant["scope_id"]) not in lineage
                or not frozenset(command.allowed_actions).issubset(
                    selected_grant["allowed_actions"]
                )
                or not _period_covers(
                    selected_grant["valid_from"],
                    selected_grant["valid_until"],
                    command.valid_from,
                    command.valid_until,
                    now,
                )
            ):
                raise BusinessOSError(
                    "forbidden",
                    "Selected delegation cannot grant requested authority",
                    status_code=403,
                )
            authority_principal_id = selected_grant["grantor_principal_id"]
            authority_principal_type = selected_grant["grantor_principal_type"]
            visited = frozenset((selected_grant["id"],))
        if not await _grantor_has_authority(
            context,
            tenant,
            authority_principal_id,
            authority_principal_type,
            lineage,
            frozenset(command.allowed_actions),
            command.valid_from,
            command.valid_until,
            now,
            visited,
        ):
            raise BusinessOSError("forbidden", "Grantor lacks delegated authority", status_code=403)
        await context.unit_of_work.persistence.execute(
            insert(DELEGATED_SCOPES).values(
                **command.model_dump(), grantor_principal_id=tenant.principal_id
            )
        )
        return {"delegation_id": command.id}

    async def _membership(
        self,
        principal_id: UUID,
        principal_type: Literal["user", "service_account", "device"],
        context: HandlingContext,
    ) -> MembershipRecord:
        tenant = context.request.tenant
        assert tenant is not None
        dispatcher = await context.dependencies.resolve(MESSAGE_DISPATCHER)
        result = await dispatcher.query(
            GetMembership(
                tenant_id=tenant.tenant_id,
                principal_id=principal_id,
                principal_type=principal_type,
            ),
            context.request,
            context.dependencies,
        )
        if not isinstance(result, MembershipRecord):
            raise RuntimeError("Identity membership contract returned an invalid result")
        return result

    async def _require_effective_membership(
        self,
        principal_id: UUID,
        principal_type: Literal["user", "service_account", "device"],
        context: HandlingContext,
    ) -> MembershipRecord:
        membership = await self._membership(principal_id, principal_type, context)
        if not _membership_is_current(membership):
            raise BusinessOSError(
                "inactive_membership", "Active membership is required", status_code=409
            )
        return membership

    async def _require_actor_membership(
        self,
        principal_id: UUID,
        expected_type: Literal["user", "service_account", "device"],
        context: HandlingContext,
    ) -> MembershipRecord:
        effective: list[MembershipRecord] = []
        for principal_type in ("user", "service_account", "device"):
            try:
                membership = await self._membership(
                    principal_id,
                    principal_type,
                    context,
                )
            except BusinessOSError as error:
                if error.code == "not_found":
                    continue
                raise
            if _membership_is_current(membership):
                effective.append(membership)
        if len(effective) != 1 or effective[0].principal_type != expected_type:
            raise BusinessOSError("forbidden", "Active membership is required", status_code=403)
        return effective[0]

    async def _read(self, query: ReadOrganization, context: HandlingContext) -> object:
        tenant = _tenant(context.request, query.tenant_id)

        async def rows(table: Table, *, order_by_code: bool = True) -> tuple[RowMapping, ...]:
            statement = select(table).where(table.c.tenant_id == tenant.tenant_id)
            if order_by_code:
                statement = statement.order_by(table.c.code)
            result = await context.unit_of_work.persistence.execute(statement)
            return tuple(result.mappings())

        groups = await rows(ENTERPRISE_GROUPS)
        legal_entities = await rows(LEGAL_ENTITIES)
        companies = await rows(COMPANIES)
        org_units = await rows(ORG_UNITS)
        regions = await rows(REGIONS)
        site_types = await rows(SITE_TYPES)
        sites = await rows(OPERATING_SITES)
        dimensions = await rows(FINANCIAL_DIMENSIONS)
        warehouses = await rows(WAREHOUSES)
        locations = await rows(WAREHOUSE_LOCATIONS)
        relationships = await rows(RELATIONSHIPS, order_by_code=False)
        assignments = await rows(ASSIGNMENTS, order_by_code=False)
        delegations = await rows(DELEGATED_SCOPES, order_by_code=False)

        def payload(row: RowMapping, kind: str | None = None) -> dict[str, object]:
            value = dict(row)
            if kind is not None:
                value["kind"] = kind
            return value

        return OrganizationSnapshot(
            tenant_id=tenant.tenant_id,
            enterprise_groups=tuple(
                EnterpriseGroupRecord.model_validate(payload(row, "enterprise_group"))
                for row in groups
            ),
            legal_entities=tuple(
                LegalEntityRecord.model_validate(payload(row, "legal_entity"))
                for row in legal_entities
            ),
            companies=tuple(
                CompanyRecord.model_validate(payload(row, "company")) for row in companies
            ),
            org_units=tuple(
                OrgUnitRecord.model_validate(payload(row, "org_unit")) for row in org_units
            ),
            regions=tuple(RegionRecord.model_validate(payload(row, "region")) for row in regions),
            site_types=tuple(SiteTypeRecord.model_validate(dict(row)) for row in site_types),
            operating_sites=tuple(
                OperatingSiteRecord.model_validate(payload(row, "operating_site")) for row in sites
            ),
            financial_dimensions=tuple(
                FinancialDimensionRecord.model_validate(payload(row, "financial_dimension"))
                for row in dimensions
            ),
            warehouses=tuple(
                WarehouseRecord.model_validate(payload(row, "warehouse")) for row in warehouses
            ),
            warehouse_locations=tuple(
                WarehouseLocationRecord.model_validate(payload(row, "warehouse_location"))
                for row in locations
            ),
            relationships=tuple(
                OrganizationRelationshipRecord.model_validate(dict(row)) for row in relationships
            ),
            assignments=tuple(EffectiveAssignment.model_validate(dict(row)) for row in assignments),
            delegations=tuple(
                DelegatedScopeRecord.model_validate(dict(row)) for row in delegations
            ),
        )

    async def _select_scope(self, query: SelectActiveScope, context: HandlingContext) -> object:
        tenant = _tenant(context.request, query.tenant_id)
        await self._require_actor_membership(tenant.principal_id, query.principal_type, context)
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
        for kind, identifier, table in checks:
            if identifier is not None:
                row = await _require_effective_row(
                    context, table, identifier, tenant, datetime.now(UTC), lock=True
                )
                resolved[kind] = row
        selection = await _canonical_scope_selection(context, tenant, resolved)
        now = datetime.now(UTC)
        authorized_by_delegation = False
        if query.delegation_id is not None:
            delegation = await _require_owned(
                context, DELEGATED_SCOPES, query.delegation_id, tenant, lock=True
            )
            if (
                delegation["recipient_principal_id"] != tenant.principal_id
                or delegation["recipient_principal_type"] != query.principal_type
                or delegation["valid_from"] > now
                or delegation["valid_until"] <= now
                or query.action not in delegation["allowed_actions"]
                or not selection.authorized_by((delegation["scope_type"], delegation["scope_id"]))
            ):
                raise BusinessOSError(
                    "forbidden", "Delegation does not authorize the selected scope", status_code=403
                )
            source = await _require_effective_scope_lineage(
                context,
                OrganizationScopeType(delegation["scope_type"]),
                delegation["scope_id"],
                tenant,
                now,
            )
            lineage = await _scope_lineage(context, tenant, delegation["scope_type"], source)
            if not await _grantor_has_authority(
                context,
                tenant,
                delegation["grantor_principal_id"],
                delegation["grantor_principal_type"],
                lineage,
                frozenset((query.action,)),
                now,
                now + timedelta(microseconds=1),
                now,
                frozenset((delegation["id"],)),
            ):
                raise BusinessOSError(
                    "forbidden", "Delegation source is no longer authorized", status_code=403
                )
            authorized_by_delegation = True
        if selection.leaves and not authorized_by_delegation:
            assignments = await context.unit_of_work.persistence.execute(
                select(ASSIGNMENTS.c.scope_type, ASSIGNMENTS.c.scope_id)
                .where(
                    ASSIGNMENTS.c.tenant_id == tenant.tenant_id,
                    ASSIGNMENTS.c.principal_id == tenant.principal_id,
                    ASSIGNMENTS.c.principal_type == query.principal_type,
                    (ASSIGNMENTS.c.valid_from.is_(None) | (ASSIGNMENTS.c.valid_from <= now)),
                    (ASSIGNMENTS.c.valid_until.is_(None) | (ASSIGNMENTS.c.valid_until > now)),
                )
                .with_for_update(read=True)
            )
            valid_assignments: set[tuple[str, UUID]] = set()
            for scope_type, scope_id in assignments.tuples():
                try:
                    await _require_effective_scope_lineage(
                        context,
                        OrganizationScopeType(scope_type),
                        scope_id,
                        tenant,
                        now,
                    )
                except (BusinessOSError, ValueError):
                    continue
                valid_assignments.add((scope_type, scope_id))
            if not selection.authorized_by_any(valid_assignments):
                raise BusinessOSError(
                    "forbidden", "Principal is not assigned to the selected scope", status_code=403
                )
        await self._require_actor_membership(tenant.principal_id, query.principal_type, context)
        selected = replace(
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
        context.emit(
            ActiveScopeSelected(
                tenant_id=tenant.tenant_id,
                correlation_id=context.request.correlation_id,
                principal_id=tenant.principal_id,
                principal_type=query.principal_type,
                previous_scope=_scope_projection(tenant),
                selected_scope=_scope_projection(selected),
            )
        )
        return selected


@dataclass(frozen=True, slots=True)
class _ScopeSelection:
    lineages: dict[tuple[str, UUID], frozenset[tuple[str, UUID]]]
    leaves: frozenset[tuple[str, UUID]]

    def authorized_by(self, grant: tuple[str, UUID]) -> bool:
        return bool(self.lineages) and all(grant in lineage for lineage in self.lineages.values())

    def authorized_by_any(self, grants: set[tuple[str, UUID]]) -> bool:
        return all(any(grant in lineage for grant in grants) for lineage in self.lineages.values())


async def _canonical_scope_selection(
    context: HandlingContext,
    tenant: TenantContext,
    rows: dict[str, RowMapping],
) -> _ScopeSelection:
    lineages: dict[tuple[str, UUID], frozenset[tuple[str, UUID]]] = {}
    for kind, row in rows.items():
        pair = (_canonical_kind(kind), cast(UUID, row["id"]))
        lineages[pair] = await _scope_lineage(context, tenant, kind, row)
        if kind in {"business_unit", "division", "department", "team"}:
            if row["unit_type"] != kind:
                raise _hierarchy_error()
        if kind in {"cost_center", "profit_center", "project"}:
            if row["dimension_type"] != kind:
                raise _hierarchy_error()

    for scope_type in (
        OrganizationScopeType.ENTERPRISE_GROUP.value,
        OrganizationScopeType.LEGAL_ENTITY.value,
        OrganizationScopeType.COMPANY.value,
    ):
        identifiers = {
            identifier
            for lineage in lineages.values()
            for kind, identifier in lineage
            if kind == scope_type
        }
        if len(identifiers) > 1:
            raise _hierarchy_error()

    for pair in lineages:
        if pair[0] == OrganizationScopeType.FINANCIAL_DIMENSION.value:
            continue
        for other, other_lineage in lineages.items():
            if pair == other:
                continue
            if pair[0] == other[0]:
                continue
            if any(kind == pair[0] for kind, _identifier in other_lineage):
                if pair not in other_lineage:
                    raise _hierarchy_error()

    _require_single_chain(lineages, OrganizationScopeType.ORG_UNIT.value)
    _require_single_chain(lineages, OrganizationScopeType.REGION.value)
    selected = set(lineages)
    leaves = frozenset(
        pair
        for pair in selected
        if not any(pair != other and pair in lineages[other] for other in selected)
    )
    return _ScopeSelection(lineages, leaves)


def _require_single_chain(
    lineages: dict[tuple[str, UUID], frozenset[tuple[str, UUID]]],
    scope_type: str,
) -> None:
    selected = [pair for pair in lineages if pair[0] == scope_type]
    for index, left in enumerate(selected):
        for right in selected[index + 1 :]:
            if left not in lineages[right] and right not in lineages[left]:
                raise _hierarchy_error()


async def _scope_lineage(
    context: HandlingContext,
    tenant: TenantContext,
    selected_kind: str,
    selected: RowMapping,
) -> frozenset[tuple[str, UUID]]:
    now = datetime.now(UTC)
    lineage: set[tuple[str, UUID]] = {(_canonical_kind(selected_kind), cast(UUID, selected["id"]))}

    async def company_lineage(company_id: UUID) -> None:
        company = await _require_effective_row(
            context, COMPANIES, company_id, tenant, now, lock=True
        )
        legal = await _require_effective_row(
            context, LEGAL_ENTITIES, company["legal_entity_id"], tenant, now, lock=True
        )
        group = await _require_effective_row(
            context,
            ENTERPRISE_GROUPS,
            legal["enterprise_group_id"],
            tenant,
            now,
            lock=True,
        )
        lineage.update(
            {
                (OrganizationScopeType.COMPANY.value, cast(UUID, company["id"])),
                (OrganizationScopeType.LEGAL_ENTITY.value, cast(UUID, legal["id"])),
                (OrganizationScopeType.ENTERPRISE_GROUP.value, cast(UUID, group["id"])),
            }
        )

    if selected_kind == "enterprise_group":
        return frozenset(lineage)
    if selected_kind == "legal_entity":
        group = await _require_effective_row(
            context,
            ENTERPRISE_GROUPS,
            selected["enterprise_group_id"],
            tenant,
            now,
            lock=True,
        )
        lineage.add((OrganizationScopeType.ENTERPRISE_GROUP.value, cast(UUID, group["id"])))
        return frozenset(lineage)
    if selected_kind == "company":
        await company_lineage(cast(UUID, selected["id"]))
        return frozenset(lineage)

    company_id = cast(UUID, selected["company_id"])
    await company_lineage(company_id)
    if selected_kind in {"business_unit", "division", "department", "team"}:
        await _append_parent_chain(
            context, tenant, ORG_UNITS, selected, OrganizationScopeType.ORG_UNIT.value, lineage
        )
    elif selected_kind == "region":
        await _append_parent_chain(
            context, tenant, REGIONS, selected, OrganizationScopeType.REGION.value, lineage
        )
    elif selected_kind == "operating_site":
        site_type = await _require_owned(
            context, SITE_TYPES, selected["site_type_id"], tenant, lock=True
        )
        if not site_type["active"]:
            raise _hierarchy_error()
        if selected["region_id"] is not None:
            region = await _require_effective_row(
                context, REGIONS, selected["region_id"], tenant, now, lock=True
            )
            if region["company_id"] != company_id:
                raise _hierarchy_error()
            await _append_parent_chain(
                context,
                tenant,
                REGIONS,
                region,
                OrganizationScopeType.REGION.value,
                lineage,
            )
    elif selected_kind == "warehouse" and selected["operating_site_id"] is not None:
        site = await _require_effective_row(
            context, OPERATING_SITES, selected["operating_site_id"], tenant, now, lock=True
        )
        if site["company_id"] != company_id:
            raise _hierarchy_error()
        lineage.update(await _scope_lineage(context, tenant, "operating_site", site))
    return frozenset(lineage)


async def _append_parent_chain(
    context: HandlingContext,
    tenant: TenantContext,
    table: Table,
    first: RowMapping,
    scope_type: str,
    lineage: set[tuple[str, UUID]],
) -> None:
    current = first
    visited: set[UUID] = set()
    company_id = current["company_id"]
    while True:
        identifier = cast(UUID, current["id"])
        if identifier in visited:
            raise _hierarchy_error()
        visited.add(identifier)
        lineage.add((scope_type, identifier))
        parent_id = current["parent_id"]
        if parent_id is None:
            return
        current = await _require_effective_row(
            context, table, parent_id, tenant, datetime.now(UTC), lock=True
        )
        if current["company_id"] != company_id:
            raise _hierarchy_error()


def _canonical_kind(kind: str) -> str:
    if kind in {"business_unit", "division", "department", "team"}:
        return OrganizationScopeType.ORG_UNIT.value
    if kind in {"cost_center", "profit_center", "project"}:
        return OrganizationScopeType.FINANCIAL_DIMENSION.value
    return kind


def _scope_projection(tenant: TenantContext) -> dict[str, str | None]:
    fields = (
        "enterprise_group_id",
        "legal_entity_id",
        "active_company_id",
        "business_unit_id",
        "division_id",
        "department_id",
        "team_id",
        "region_id",
        "operating_site_id",
        "warehouse_id",
        "cost_center_id",
        "profit_center_id",
        "project_id",
        "delegation_id",
    )
    return {
        field: str(value) if (value := getattr(tenant, field)) is not None else None
        for field in fields
    }


async def _insert_named(
    context: HandlingContext,
    table: Table,
    command: _NamedCommand,
    tenant: TenantContext,
    **extra: object,
) -> None:
    validate_effective_period(command.effective_from, command.effective_until)
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
    context: HandlingContext,
    table: Table,
    identifier: UUID,
    tenant: TenantContext,
    *,
    lock: bool = False,
) -> RowMapping:
    statement = select(table).where(table.c.id == identifier, table.c.tenant_id == tenant.tenant_id)
    if lock:
        statement = statement.with_for_update(read=True)
    result = await context.unit_of_work.persistence.execute(statement)
    row = result.mappings().one_or_none()
    if row is None:
        raise BusinessOSError(
            "invalid_organization_scope", "Organization scope is invalid", status_code=422
        )
    return row


async def _require_effective_row(
    context: HandlingContext,
    table: Table,
    identifier: UUID,
    tenant: TenantContext,
    instant: datetime,
    *,
    lock: bool = False,
) -> RowMapping:
    row = await _require_owned(context, table, identifier, tenant, lock=lock)
    if not row["active"] or not effective_at(
        row["effective_from"], row["effective_until"], instant.date()
    ):
        raise BusinessOSError(
            "inactive_organization_scope",
            "Organization scope is not currently effective",
            status_code=422,
        )
    return row


async def _require_effective_scope(
    context: HandlingContext,
    scope_type: OrganizationScopeType,
    identifier: UUID,
    tenant: TenantContext,
    instant: datetime,
) -> RowMapping:
    return await _require_effective_row(
        context,
        _SCOPE_TABLES[scope_type],
        identifier,
        tenant,
        instant,
        lock=True,
    )


async def _require_effective_scope_lineage(
    context: HandlingContext,
    scope_type: OrganizationScopeType,
    identifier: UUID,
    tenant: TenantContext,
    instant: datetime,
) -> RowMapping:
    row = await _require_effective_scope(context, scope_type, identifier, tenant, instant)
    kind = scope_type.value
    if scope_type is OrganizationScopeType.ORG_UNIT:
        kind = str(row["unit_type"])
    elif scope_type is OrganizationScopeType.FINANCIAL_DIMENSION:
        kind = str(row["dimension_type"])
    await _scope_lineage(context, tenant, kind, row)
    return row


def _membership_covers(
    membership: MembershipRecord, now: datetime, start: datetime, end: datetime
) -> bool:
    return (
        membership.is_effective(now)
        and (membership.valid_from is None or membership.valid_from <= start)
        and (membership.valid_until is None or end <= membership.valid_until)
    )


def _period_covers(
    valid_from: datetime | None,
    valid_until: datetime | None,
    start: datetime,
    end: datetime,
    now: datetime,
) -> bool:
    return (
        (valid_from is None or valid_from <= start)
        and (valid_until is None or end <= valid_until)
        and (valid_from is None or valid_from <= now)
        and (valid_until is None or now < valid_until)
    )


def _selected_scope_covers(
    tenant: TenantContext, target_lineage: frozenset[tuple[str, UUID]]
) -> bool:
    selected = (
        ("enterprise_group", tenant.enterprise_group_id),
        ("legal_entity", tenant.legal_entity_id),
        ("company", tenant.active_company_id),
        ("org_unit", tenant.business_unit_id),
        ("org_unit", tenant.division_id),
        ("org_unit", tenant.department_id),
        ("org_unit", tenant.team_id),
        ("region", tenant.region_id),
        ("operating_site", tenant.operating_site_id),
        ("warehouse", tenant.warehouse_id),
        ("financial_dimension", tenant.cost_center_id),
        ("financial_dimension", tenant.profit_center_id),
        ("financial_dimension", tenant.project_id),
    )
    return all(
        identifier is None or (kind, identifier) in target_lineage for kind, identifier in selected
    )


async def _grantor_has_authority(
    context: HandlingContext,
    tenant: TenantContext,
    principal_id: UUID,
    principal_type: Literal["user", "service_account", "device"],
    target_lineage: frozenset[tuple[str, UUID]],
    actions: frozenset[str],
    start: datetime,
    end: datetime,
    now: datetime,
    visited: frozenset[UUID],
) -> bool:
    """Trace a locked authority chain to a current assignment in this transaction."""
    if len(visited) >= 16:
        return False
    try:
        membership = await lock_membership_for_authority(
            context.unit_of_work.persistence, tenant.tenant_id, principal_id, principal_type
        )
    except BusinessOSError as error:
        if error.code == "not_found":
            return False
        raise
    if not _membership_covers(membership, now, start, end):
        return False

    assignments = await context.unit_of_work.persistence.execute(
        select(ASSIGNMENTS)
        .where(
            ASSIGNMENTS.c.tenant_id == tenant.tenant_id,
            ASSIGNMENTS.c.principal_id == principal_id,
            ASSIGNMENTS.c.principal_type == principal_type,
        )
        .with_for_update(read=True)
    )
    for assignment in assignments.mappings():
        if (assignment["scope_type"], assignment["scope_id"]) in target_lineage and _period_covers(
            assignment["valid_from"], assignment["valid_until"], start, end, now
        ):
            # Assignments are the Phase 2 root organizational grant. Action-specific
            # restrictions live on delegations and the framework permission check.
            return True

    delegations = await context.unit_of_work.persistence.execute(
        select(DELEGATED_SCOPES)
        .where(
            DELEGATED_SCOPES.c.tenant_id == tenant.tenant_id,
            DELEGATED_SCOPES.c.recipient_principal_id == principal_id,
            DELEGATED_SCOPES.c.recipient_principal_type == principal_type,
        )
        .with_for_update(read=True)
    )
    for delegation in delegations.mappings():
        identifier = cast(UUID, delegation["id"])
        if (
            identifier in visited
            or (delegation["scope_type"], delegation["scope_id"]) not in target_lineage
            or not actions.issubset(delegation["allowed_actions"])
            or not _period_covers(
                delegation["valid_from"], delegation["valid_until"], start, end, now
            )
        ):
            continue
        if await _grantor_has_authority(
            context,
            tenant,
            delegation["grantor_principal_id"],
            delegation["grantor_principal_type"],
            target_lineage,
            actions,
            start,
            end,
            now,
            visited | {identifier},
        ):
            return True
    return False


def _membership_is_current(membership: MembershipRecord) -> bool:
    return membership.status.value == "active" and effective_at(
        membership.valid_from, membership.valid_until, datetime.now(UTC)
    )


def _tenant(context: RequestContext, expected: UUID) -> TenantContext:
    tenant = context.tenant
    if tenant is None:
        raise BusinessOSError("unauthenticated", "Authentication required", status_code=401)
    if tenant.tenant_id != expected:
        raise BusinessOSError("forbidden", "Tenant scope mismatch", status_code=403)
    return tenant


def _hierarchy_error() -> BusinessOSError:
    return BusinessOSError(
        "invalid_organization_hierarchy", "Organization hierarchy is inconsistent", status_code=422
    )
