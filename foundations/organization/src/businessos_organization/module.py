"""Organization module registration and tenant-consistent hierarchy handlers."""

import json
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from importlib.resources import files
from typing import ClassVar, Literal, cast
from uuid import UUID, uuid4

from businessos_identity import (
    AUTHENTICATED_PRINCIPAL,
    MEMBERSHIP_AUTHORITY,
    GetMembership,
    MembershipRecord,
    PrincipalReference,
    PrincipalType,
)
from businessos_tenant import (
    DatabaseTenantAccessValidator,
    effective_at,
    validate_effective_period,
)
from pydantic import Field
from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.sql.schema import Table

from businessos.sdk import (
    MESSAGE_DISPATCHER,
    UNIT_OF_WORK_FACTORY,
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
    DELEGATION_ACTION_AUTHORITY,
    CompanyRecord,
    DelegatedScopeRecord,
    DelegationAuthorityRequest,
    DelegationDecisionAuthority,
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


class RevokePrincipalAssignment(Command):
    tenant_id: UUID
    assignment_id: UUID
    reason: str = Field(min_length=1, max_length=1000)


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


class RevokeOrganizationDelegation(Command):
    tenant_id: UUID
    delegation_id: UUID
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
    action: str | None = None
    authority_path: tuple[UUID, ...] = ()
    root_assignment_ids: tuple[UUID, ...] = ()
    policy_decision_references: tuple[str, ...] = ()


class OrganizationDelegationRevoked(DomainEvent):
    event_type: ClassVar[str] = "organization.delegation.revoked.v1"
    delegation_id: UUID
    actor_principal_id: UUID
    actor_principal_type: str
    reason: str


class OrganizationDelegationGranted(DomainEvent):
    event_type: ClassVar[str] = "organization.delegation.granted.v1"
    delegation_id: UUID
    actor_principal_id: UUID
    actor_principal_type: str
    root_principal_id: UUID
    root_principal_type: str
    root_assignment_id: UUID
    parent_delegation_id: UUID | None
    source_path: tuple[UUID, ...]
    scope_type: str
    scope_id: UUID
    actions: tuple[str, ...]
    policy_decision_references: tuple[str, ...]


class PrincipalAssignmentRevoked(DomainEvent):
    event_type: ClassVar[str] = "organization.assignment.revoked.v1"
    assignment_id: UUID
    actor_principal_id: UUID
    actor_principal_type: str
    reason: str


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
            RevokePrincipalAssignment,
            self._revoke_assignment,
            permission="foundation.organization.manage",
        )
        registration.command(
            DelegateScope, self._delegation, permission="foundation.organization.manage"
        )
        registration.command(
            RevokeOrganizationDelegation,
            self._revoke_delegation,
            permission="foundation.organization.manage",
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

    async def _revoke_assignment(
        self, command: RevokePrincipalAssignment, context: HandlingContext
    ) -> object:
        tenant = _tenant(context.request, command.tenant_id)
        actor = await _trusted_principal(context, tenant)
        authority = await context.dependencies.resolve(DELEGATION_ACTION_AUTHORITY)
        await authority.acquire(tenant.tenant_id, context.unit_of_work.persistence)
        await _verify_active_tenant(context, tenant)
        result = await context.unit_of_work.persistence.execute(
            delete(ASSIGNMENTS)
            .where(
                ASSIGNMENTS.c.tenant_id == tenant.tenant_id,
                ASSIGNMENTS.c.id == command.assignment_id,
            )
            .returning(ASSIGNMENTS.c.id)
        )
        if result.scalar_one_or_none() is None:
            raise BusinessOSError("not_found", "Assignment not found", status_code=404)
        await context.dependencies.resolve(DELEGATION_ACTION_AUTHORITY)
        context.emit(
            PrincipalAssignmentRevoked(
                tenant_id=tenant.tenant_id,
                correlation_id=context.request.correlation_id,
                assignment_id=command.assignment_id,
                actor_principal_id=actor.principal_id,
                actor_principal_type=actor.principal_type,
                reason=command.reason,
            )
        )
        return {"assignment_id": command.assignment_id, "revoked": True}

    async def _delegation(self, command: DelegateScope, context: HandlingContext) -> object:
        tenant = _tenant(context.request, command.tenant_id)
        actor = await _trusted_principal(context, tenant)
        if actor.principal_type != command.grantor_principal_type:
            raise BusinessOSError("forbidden", "Caller principal type mismatch", status_code=403)
        validate_effective_period(command.valid_from, command.valid_until)
        now = datetime.now(UTC)
        if command.valid_until <= now:
            raise BusinessOSError("invalid_delegation", "Delegation has expired", status_code=422)
        recipient = PrincipalReference(
            command.recipient_principal_type, command.recipient_principal_id
        )
        proof = await _validate_delegation_path(
            context,
            tenant,
            actor,
            tenant.delegation_id,
            command.scope_type,
            command.scope_id,
            frozenset(command.allowed_actions),
            command.valid_from,
            command.valid_until,
            now,
            new_recipient=recipient,
        )
        target = await _require_effective_scope_lineage(
            context, command.scope_type, command.scope_id, tenant, now
        )
        lineage = await _scope_lineage(context, tenant, command.scope_type.value, target)
        if not _selected_scope_covers(tenant, lineage):
            raise BusinessOSError(
                "forbidden", "Selected scope does not cover delegation", status_code=403
            )
        # Re-resolve the provider so a disabled generation cannot be held through
        # the final insert after its last authority decision.
        await context.dependencies.resolve(DELEGATION_ACTION_AUTHORITY)
        await context.unit_of_work.persistence.execute(
            insert(DELEGATED_SCOPES).values(
                **command.model_dump(),
                grantor_principal_id=actor.principal_id,
                authority_source_kind="delegation" if tenant.delegation_id else "direct",
                parent_delegation_id=tenant.delegation_id,
            )
        )
        context.emit(
            OrganizationDelegationGranted(
                tenant_id=tenant.tenant_id,
                correlation_id=context.request.correlation_id,
                delegation_id=command.id,
                actor_principal_id=actor.principal_id,
                actor_principal_type=actor.principal_type,
                root_principal_id=proof.root.principal_id,
                root_principal_type=proof.root.principal_type,
                root_assignment_id=proof.assignment_id,
                parent_delegation_id=tenant.delegation_id,
                source_path=proof.path,
                scope_type=command.scope_type.value,
                scope_id=command.scope_id,
                actions=command.allowed_actions,
                policy_decision_references=proof.policy_references,
            )
        )
        return {"delegation_id": command.id}

    async def _revoke_delegation(
        self, command: RevokeOrganizationDelegation, context: HandlingContext
    ) -> object:
        tenant = _tenant(context.request, command.tenant_id)
        actor = await _trusted_principal(context, tenant)
        authority = await context.dependencies.resolve(DELEGATION_ACTION_AUTHORITY)
        await authority.acquire(tenant.tenant_id, context.unit_of_work.persistence)
        await _verify_active_tenant(context, tenant)
        result = await context.unit_of_work.persistence.execute(
            update(DELEGATED_SCOPES)
            .where(
                DELEGATED_SCOPES.c.tenant_id == tenant.tenant_id,
                DELEGATED_SCOPES.c.id == command.delegation_id,
                DELEGATED_SCOPES.c.authority_source_kind.is_not(None),
                DELEGATED_SCOPES.c.revoked_at.is_(None),
            )
            .values(
                revoked_at=datetime.now(UTC),
                revoked_by_principal_id=actor.principal_id,
                revoked_by_principal_type=actor.principal_type,
                revocation_reason=command.reason,
                revocation_correlation_id=context.request.correlation_id,
            )
            .returning(DELEGATED_SCOPES.c.id)
        )
        if result.scalar_one_or_none() is None:
            raise BusinessOSError("not_found", "Active delegation not found", status_code=404)
        await context.dependencies.resolve(DELEGATION_ACTION_AUTHORITY)
        context.emit(
            OrganizationDelegationRevoked(
                tenant_id=tenant.tenant_id,
                correlation_id=context.request.correlation_id,
                delegation_id=command.delegation_id,
                actor_principal_id=actor.principal_id,
                actor_principal_type=actor.principal_type,
                reason=command.reason,
            )
        )
        return {"delegation_id": command.delegation_id, "revoked": True}

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
        actor = await _trusted_principal(context, tenant)
        if actor.principal_type != query.principal_type:
            raise BusinessOSError("forbidden", "Caller principal type mismatch", status_code=403)
        if query.delegation_id is not None:
            # Consumption must observe Policy revocations as well as Organization
            # scope revocations. Keep the authority read in this same transaction.
            authority = await context.dependencies.resolve(DELEGATION_ACTION_AUTHORITY)
            await authority.acquire(tenant.tenant_id, context.unit_of_work.persistence)
        if query.delegation_id is None:
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
        delegated_selection = query.delegation_id is not None
        for kind, identifier, table in checks:
            if identifier is not None:
                row = await _require_effective_row(
                    context,
                    table,
                    identifier,
                    tenant,
                    datetime.now(UTC),
                    lock=not delegated_selection,
                )
                resolved[kind] = row
        selection = await _canonical_scope_selection(
            context, tenant, resolved, lock=not delegated_selection
        )
        now = datetime.now(UTC)
        authorized_by_delegation = False
        delegation_proofs: list[_DelegationProof] = []
        if query.delegation_id is not None:
            if not selection.leaves:
                raise BusinessOSError("forbidden", "Delegation needs a target", status_code=403)
            for kind, identifier in sorted(selection.leaves):
                try:
                    target_type = OrganizationScopeType(kind)
                except ValueError:
                    raise BusinessOSError(
                        "forbidden", "Unsupported delegation target", status_code=403
                    ) from None
                proof = await _validate_delegation_path(
                    context,
                    tenant,
                    actor,
                    query.delegation_id,
                    target_type,
                    identifier,
                    frozenset((query.action,)),
                    now,
                    now + timedelta(microseconds=1),
                    now,
                )
                if proof.selected_scope is None or not selection.authorized_by(
                    proof.selected_scope
                ):
                    raise BusinessOSError(
                        "forbidden", "Delegation cannot widen selected scope", status_code=403
                    )
                delegation_proofs.append(proof)
            # The initial hierarchy read took no row locks, preserving the
            # ADR-011 membership -> assignment -> delegation lock order.
            # Recheck the exact selection under locks before publishing it.
            locked_rows: dict[str, RowMapping] = {}
            for kind, identifier, table in checks:
                if identifier is not None:
                    locked_rows[kind] = await _require_effective_row(
                        context, table, identifier, tenant, now, lock=True
                    )
            locked_selection = await _canonical_scope_selection(context, tenant, locked_rows)
            if locked_selection.lineages != selection.lineages:
                raise BusinessOSError(
                    "forbidden", "Selected hierarchy changed during authorization", status_code=403
                )
            await context.dependencies.resolve(DELEGATION_ACTION_AUTHORITY)
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
        if not authorized_by_delegation:
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
                action=query.action if authorized_by_delegation else None,
                authority_path=delegation_proofs[0].path if delegation_proofs else (),
                root_assignment_ids=tuple(
                    sorted(
                        {proof.assignment_id for proof in delegation_proofs},
                        key=lambda value: value.bytes,
                    )
                ),
                policy_decision_references=tuple(
                    sorted(
                        {
                            reference
                            for proof in delegation_proofs
                            for reference in proof.policy_references
                        }
                    )
                ),
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
    *,
    lock: bool = True,
) -> _ScopeSelection:
    lineages: dict[tuple[str, UUID], frozenset[tuple[str, UUID]]] = {}
    for kind, row in rows.items():
        pair = (_canonical_kind(kind), cast(UUID, row["id"]))
        lineages[pair] = await _scope_lineage(context, tenant, kind, row, lock=lock)
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
    *,
    lock: bool = True,
) -> frozenset[tuple[str, UUID]]:
    now = datetime.now(UTC)
    lineage: set[tuple[str, UUID]] = {(_canonical_kind(selected_kind), cast(UUID, selected["id"]))}

    async def company_lineage(company_id: UUID) -> None:
        company = await _require_effective_row(
            context, COMPANIES, company_id, tenant, now, lock=lock
        )
        legal = await _require_effective_row(
            context, LEGAL_ENTITIES, company["legal_entity_id"], tenant, now, lock=lock
        )
        group = await _require_effective_row(
            context,
            ENTERPRISE_GROUPS,
            legal["enterprise_group_id"],
            tenant,
            now,
            lock=lock,
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
            lock=lock,
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
            context,
            tenant,
            ORG_UNITS,
            selected,
            OrganizationScopeType.ORG_UNIT.value,
            lineage,
            lock=lock,
        )
    elif selected_kind == "region":
        await _append_parent_chain(
            context,
            tenant,
            REGIONS,
            selected,
            OrganizationScopeType.REGION.value,
            lineage,
            lock=lock,
        )
    elif selected_kind == "operating_site":
        site_type = await _require_owned(
            context, SITE_TYPES, selected["site_type_id"], tenant, lock=lock
        )
        if not site_type["active"]:
            raise _hierarchy_error()
        if selected["region_id"] is not None:
            region = await _require_effective_row(
                context, REGIONS, selected["region_id"], tenant, now, lock=lock
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
                lock=lock,
            )
    elif selected_kind == "warehouse" and selected["operating_site_id"] is not None:
        site = await _require_effective_row(
            context, OPERATING_SITES, selected["operating_site_id"], tenant, now, lock=lock
        )
        if site["company_id"] != company_id:
            raise _hierarchy_error()
        lineage.update(await _scope_lineage(context, tenant, "operating_site", site, lock=lock))
    return frozenset(lineage)


async def _append_parent_chain(
    context: HandlingContext,
    tenant: TenantContext,
    table: Table,
    first: RowMapping,
    scope_type: str,
    lineage: set[tuple[str, UUID]],
    *,
    lock: bool = True,
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
            context, table, parent_id, tenant, datetime.now(UTC), lock=lock
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


@dataclass(frozen=True, slots=True)
class _DelegationProof:
    root: PrincipalReference
    assignment_id: UUID
    path: tuple[UUID, ...]
    selected_scope: tuple[str, UUID] | None
    policy_references: tuple[str, ...]


async def _trusted_principal(context: HandlingContext, tenant: TenantContext) -> PrincipalReference:
    binding = await context.dependencies.resolve(AUTHENTICATED_PRINCIPAL)
    principal = binding.principal
    if (
        binding.request is not context.request
        or principal.tenant_id != tenant.tenant_id
        or principal.principal_id != tenant.principal_id
        or principal.principal_type not in {"user", "service_account", "device"}
    ):
        raise BusinessOSError("forbidden", "Trusted principal mismatch", status_code=403)
    return PrincipalReference(cast(PrincipalType, principal.principal_type), principal.principal_id)


async def _verify_active_tenant(context: HandlingContext, tenant: TenantContext) -> None:
    factory = await context.dependencies.resolve(UNIT_OF_WORK_FACTORY)
    validator = DatabaseTenantAccessValidator(tenant.installation_id, factory)
    await validator.require_active_in(tenant.tenant_id, context.unit_of_work.persistence, lock=True)


async def _validate_delegation_path(
    context: HandlingContext,
    tenant: TenantContext,
    consumer: PrincipalReference,
    source_id: UUID | None,
    target_type: OrganizationScopeType,
    target_id: UUID,
    actions: frozenset[str],
    start: datetime,
    end: datetime,
    now: datetime,
    *,
    new_recipient: PrincipalReference | None = None,
) -> _DelegationProof:
    """One live, locked source path for both creation and consumption."""
    authority = await context.dependencies.resolve(DELEGATION_ACTION_AUTHORITY)
    if not isinstance(authority, DelegationDecisionAuthority):
        raise BusinessOSError("forbidden", "Typed Policy decision unavailable", status_code=403)
    await authority.acquire(tenant.tenant_id, context.unit_of_work.persistence)
    await _verify_active_tenant(context, tenant)
    if not actions or end <= start:
        raise BusinessOSError("forbidden", "Invalid delegation authority", status_code=403)

    # Discover immutable parent IDs before taking row locks. Re-read after the
    # canonical lock sequence; no alternative parent is ever considered.
    candidates: list[RowMapping] = []
    seen_ids: set[UUID] = set()
    current_id = source_id
    while current_id is not None:
        if current_id in seen_ids or len(candidates) >= 16:
            raise BusinessOSError("forbidden", "Invalid delegation chain", status_code=403)
        seen_ids.add(current_id)
        result = await context.unit_of_work.persistence.execute(
            select(DELEGATED_SCOPES).where(
                DELEGATED_SCOPES.c.tenant_id == tenant.tenant_id,
                DELEGATED_SCOPES.c.id == current_id,
            )
        )
        row = result.mappings().one_or_none()
        if row is None or row["authority_source_kind"] not in {"direct", "delegation"}:
            raise BusinessOSError("forbidden", "Unverified delegation source", status_code=403)
        candidates.append(row)
        if row["authority_source_kind"] == "direct":
            if row["parent_delegation_id"] is not None:
                raise BusinessOSError("forbidden", "Invalid direct source", status_code=403)
            current_id = None
        else:
            current_id = row["parent_delegation_id"]
            if current_id is None:
                raise BusinessOSError("forbidden", "Missing delegation parent", status_code=403)
    path = list(reversed(candidates))
    if new_recipient is not None and len(path) >= 16:
        raise BusinessOSError("forbidden", "Delegation depth exceeded", status_code=403)

    root = (
        PrincipalReference(path[0]["grantor_principal_type"], path[0]["grantor_principal_id"])
        if path
        else consumer
    )
    principals = [root]
    seen_principals = {root}
    preceding = root
    previous_id: UUID | None = None
    for index, row in enumerate(path):
        grantor = PrincipalReference(row["grantor_principal_type"], row["grantor_principal_id"])
        recipient = PrincipalReference(
            row["recipient_principal_type"], row["recipient_principal_id"]
        )
        if (
            grantor != preceding
            or recipient in seen_principals
            or (index == 0 and row["authority_source_kind"] != "direct")
            or (index > 0 and row["authority_source_kind"] != "delegation")
            or row["parent_delegation_id"] != previous_id
        ):
            raise BusinessOSError("forbidden", "Invalid delegation chain", status_code=403)
        principals.append(recipient)
        seen_principals.add(recipient)
        preceding = recipient
        previous_id = row["id"]
    if preceding != consumer or (new_recipient is not None and new_recipient in seen_principals):
        raise BusinessOSError("forbidden", "Delegation principal cycle", status_code=403)
    if new_recipient is not None:
        principals.append(new_recipient)

    memberships = await context.dependencies.resolve(MEMBERSHIP_AUTHORITY)
    await memberships.lock_many(
        context.unit_of_work.persistence,
        tenant.tenant_id,
        tuple(principals),
        now,
        start,
        end,
    )

    assignment_ids = await context.unit_of_work.persistence.execute(
        select(ASSIGNMENTS.c.id)
        .where(
            ASSIGNMENTS.c.tenant_id == tenant.tenant_id,
            ASSIGNMENTS.c.principal_type == root.principal_type,
            ASSIGNMENTS.c.principal_id == root.principal_id,
        )
        .order_by(ASSIGNMENTS.c.id)
    )
    assignments: list[RowMapping] = []
    for assignment_id in assignment_ids.scalars():
        result = await context.unit_of_work.persistence.execute(
            select(ASSIGNMENTS)
            .where(ASSIGNMENTS.c.tenant_id == tenant.tenant_id, ASSIGNMENTS.c.id == assignment_id)
            .with_for_update(read=True)
        )
        row = result.mappings().one_or_none()
        if row is not None:
            assignments.append(row)
    locked: dict[UUID, RowMapping] = {}
    for identifier in sorted(seen_ids, key=lambda value: value.bytes):
        result = await context.unit_of_work.persistence.execute(
            select(DELEGATED_SCOPES)
            .where(
                DELEGATED_SCOPES.c.tenant_id == tenant.tenant_id,
                DELEGATED_SCOPES.c.id == identifier,
            )
            .with_for_update(read=True)
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise BusinessOSError("forbidden", "Delegation source changed", status_code=403)
        locked[identifier] = row
    for candidate in path:
        current = locked[candidate["id"]]
        if (
            current["authority_source_kind"] != candidate["authority_source_kind"]
            or current["parent_delegation_id"] != candidate["parent_delegation_id"]
            or current["revoked_at"] is not None
            or (current["grantor_principal_type"], current["grantor_principal_id"])
            != (candidate["grantor_principal_type"], candidate["grantor_principal_id"])
            or (current["recipient_principal_type"], current["recipient_principal_id"])
            != (candidate["recipient_principal_type"], candidate["recipient_principal_id"])
        ):
            raise BusinessOSError("forbidden", "Delegation source changed", status_code=403)

    target = await _require_effective_scope_lineage(context, target_type, target_id, tenant, now)
    lineage = await _scope_lineage(context, tenant, target_type.value, target)
    roots = [
        row
        for row in assignments
        if (row["scope_type"], row["scope_id"]) in lineage
        and _period_covers(row["valid_from"], row["valid_until"], start, end, now)
    ]
    if not roots:
        raise BusinessOSError("forbidden", "Root assignment unavailable", status_code=403)
    root_assignment = min(roots, key=lambda row: row["id"].bytes)
    for candidate in path:
        row = locked[candidate["id"]]
        if (
            (row["scope_type"], row["scope_id"]) not in lineage
            or not actions.issubset(row["allowed_actions"])
            or not _period_covers(row["valid_from"], row["valid_until"], start, end, now)
        ):
            raise BusinessOSError("forbidden", "Delegation authority expired", status_code=403)
    policy_references: list[str] = []
    for action in sorted(actions):
        decision = await authority.evaluate(
            DelegationAuthorityRequest(
                tenant_id=tenant.tenant_id,
                grantor_principal_id=root.principal_id,
                grantor_principal_type=root.principal_type,
                scope_type=target_type,
                scope_id=target_id,
                action=action,
                evaluated_at=now,
                valid_from=start,
                valid_until=end,
            ),
            context.unit_of_work.persistence,
        )
        if not decision.allowed or decision.policy_reference is None:
            raise BusinessOSError("forbidden", "Root action authority denied", status_code=403)
        policy_references.append(decision.policy_reference)
    selected_scope = None
    if path:
        last = locked[path[-1]["id"]]
        selected_scope = (last["scope_type"], last["scope_id"])
    return _DelegationProof(
        root,
        root_assignment["id"],
        tuple(row["id"] for row in path),
        selected_scope,
        tuple(policy_references),
    )


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
