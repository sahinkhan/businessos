"""Public multinational organization contracts."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


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


class OrganizationNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    kind: str
    code: str
    name: str
    effective_from: date | None = None
    effective_until: date | None = None


class OrganizationSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: UUID
    enterprise_groups: tuple[OrganizationNode, ...]
    legal_entities: tuple[OrganizationNode, ...]
    companies: tuple[OrganizationNode, ...]
    org_units: tuple[OrganizationNode, ...]
    regions: tuple[OrganizationNode, ...]
    operating_sites: tuple[OrganizationNode, ...]
    warehouses: tuple[OrganizationNode, ...]


class EffectiveAssignment(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    principal_id: UUID
    scope_type: OrganizationScopeType
    scope_id: UUID
    valid_from: datetime | None = None
    valid_until: datetime | None = None


@dataclass(frozen=True, slots=True)
class OrganizationContract:
    version: str = "1.0"
    read_query: str = "businessos_organization.ReadOrganization"
    active_scope_query: str = "businessos_organization.SelectActiveScope"
    assignment_command: str = "businessos_organization.AssignPrincipal"
