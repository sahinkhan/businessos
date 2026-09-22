"""Public multinational organization contracts."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from businessos.sdk import DependencyKey, TransactionalPersistence


class OrganizationUnitType(StrEnum):
    BUSINESS_UNIT = "business_unit"
    DIVISION = "division"
    DEPARTMENT = "department"
    TEAM = "team"


class FinancialDimensionType(StrEnum):
    COST_CENTER = "cost_center"
    PROFIT_CENTER = "profit_center"
    PROJECT = "project"
    CHANNEL = "channel"
    RESPONSIBILITY_CENTER = "responsibility_center"


class OrganizationScopeType(StrEnum):
    ENTERPRISE_GROUP = "enterprise_group"
    LEGAL_ENTITY = "legal_entity"
    COMPANY = "company"
    ORG_UNIT = "org_unit"
    REGION = "region"
    OPERATING_SITE = "operating_site"
    WAREHOUSE = "warehouse"
    FINANCIAL_DIMENSION = "financial_dimension"


@dataclass(frozen=True, slots=True)
class DelegationAuthorityRequest:
    """Trusted, transaction-bound action and target submitted by Organization."""

    tenant_id: UUID
    grantor_principal_id: UUID
    scope_type: OrganizationScopeType
    scope_id: UUID
    action: str
    evaluated_at: datetime
    valid_from: datetime
    valid_until: datetime


class DelegationActionAuthority(Protocol):
    """Organization-owned authority port; implementations own their policy data."""

    async def acquire(self, tenant_id: UUID, persistence: TransactionalPersistence) -> None: ...

    async def allows(
        self, request: DelegationAuthorityRequest, persistence: TransactionalPersistence
    ) -> bool: ...


DELEGATION_ACTION_AUTHORITY = DependencyKey[DelegationActionAuthority](
    "businessos.organization.delegation_action_authority"
)


class OrganizationNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    kind: str
    code: str
    name: str
    active: bool = True
    effective_from: date | None = None
    effective_until: date | None = None


class EnterpriseGroupRecord(OrganizationNode):
    kind: str = "enterprise_group"


class LegalEntityRecord(OrganizationNode):
    kind: str = "legal_entity"
    enterprise_group_id: UUID
    registration_number: str | None = None
    country_code: str


class CompanyRecord(OrganizationNode):
    kind: str = "company"
    legal_entity_id: UUID
    base_currency: str
    timezone: str


class OrgUnitRecord(OrganizationNode):
    kind: str = "org_unit"
    company_id: UUID
    parent_id: UUID | None = None
    unit_type: OrganizationUnitType


class RegionRecord(OrganizationNode):
    kind: str = "region"
    company_id: UUID
    parent_id: UUID | None = None


class SiteTypeRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    code: str
    name: str
    profile_contract: str | None = None
    active: bool


class OperatingSiteRecord(OrganizationNode):
    kind: str = "operating_site"
    company_id: UUID
    region_id: UUID | None = None
    site_type_id: UUID
    timezone: str


class FinancialDimensionRecord(OrganizationNode):
    kind: str = "financial_dimension"
    company_id: UUID
    dimension_type: FinancialDimensionType


class WarehouseRecord(OrganizationNode):
    kind: str = "warehouse"
    company_id: UUID
    operating_site_id: UUID | None = None


class WarehouseLocationRecord(OrganizationNode):
    kind: str = "warehouse_location"
    warehouse_id: UUID
    parent_id: UUID | None = None


class OrganizationRelationshipRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    source_type: OrganizationScopeType
    source_id: UUID
    target_type: OrganizationScopeType
    target_id: UUID
    relationship_type: str
    effective_from: date | None = None
    effective_until: date | None = None


class EffectiveAssignment(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    principal_id: UUID
    principal_type: Literal["user", "service_account", "device"] = "user"
    scope_type: OrganizationScopeType
    scope_id: UUID
    title: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class DelegatedScopeRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    grantor_principal_id: UUID
    grantor_principal_type: Literal["user", "service_account", "device"] = "user"
    recipient_principal_id: UUID
    recipient_principal_type: Literal["user", "service_account", "device"] = "user"
    scope_type: OrganizationScopeType
    scope_id: UUID
    allowed_actions: tuple[str, ...]
    valid_from: datetime
    valid_until: datetime
    reason: str


class OrganizationSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: UUID
    enterprise_groups: tuple[EnterpriseGroupRecord | OrganizationNode, ...] = ()
    legal_entities: tuple[LegalEntityRecord | OrganizationNode, ...] = ()
    companies: tuple[CompanyRecord | OrganizationNode, ...] = ()
    org_units: tuple[OrgUnitRecord | OrganizationNode, ...] = ()
    regions: tuple[RegionRecord | OrganizationNode, ...] = ()
    site_types: tuple[SiteTypeRecord, ...] = ()
    operating_sites: tuple[OperatingSiteRecord | OrganizationNode, ...] = ()
    financial_dimensions: tuple[FinancialDimensionRecord, ...] = ()
    warehouses: tuple[WarehouseRecord | OrganizationNode, ...] = ()
    warehouse_locations: tuple[WarehouseLocationRecord, ...] = ()
    relationships: tuple[OrganizationRelationshipRecord, ...] = ()
    assignments: tuple[EffectiveAssignment, ...] = ()
    delegations: tuple[DelegatedScopeRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class OrganizationContract:
    version: str = "1.2"
    read_query: str = "businessos_organization.ReadOrganization"
    active_scope_command: str = "businessos_organization.SelectActiveScope"
    assignment_command: str = "businessos_organization.AssignPrincipal"
