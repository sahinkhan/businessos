"""Version 1 governed custom-entity boundary values; no persistence authority."""

from datetime import datetime
from enum import StrEnum
from typing import Final, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from businessos.sdk import BusinessOSError, CustomFieldValue, TenantContext

from .contracts import ReferenceResolution

CUSTOM_ENTITY_NAMESPACE: Final = "foundation.metadata.custom_entity"
CUSTOM_ENTITY_OWNER_VERSION = "1"


class _Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CustomEntityScopeKind(StrEnum):
    TENANT = "tenant"
    COMPANY = "company"
    ENTERPRISE_GROUP = "enterprise_group"
    LEGAL_ENTITY = "legal_entity"
    BUSINESS_UNIT = "business_unit"
    DIVISION = "division"
    DEPARTMENT = "department"
    TEAM = "team"
    REGION = "region"
    OPERATING_SITE = "operating_site"
    WAREHOUSE = "warehouse"
    COST_CENTER = "cost_center"
    PROFIT_CENTER = "profit_center"
    PROJECT = "project"

    def trusted_id(self, tenant: TenantContext) -> UUID:
        attribute = (
            "tenant_id"
            if self is self.TENANT
            else "active_company_id"
            if self is self.COMPANY
            else f"{self.value}_id"
        )
        identity = getattr(tenant, attribute, None)
        if type(identity) is not UUID:
            raise BusinessOSError("scope_unavailable", "Trusted scope required", status_code=403)
        return identity


class CustomEntityLifecycle(StrEnum):
    CURRENT = "current"
    ARCHIVED = "archived"


class CustomEntityLimits(_Contract):
    max_instances_per_tenant: int = Field(default=100000, ge=1, le=10000000, strict=True)
    max_instances_per_type: int = Field(default=10000, ge=1, le=10000000, strict=True)
    max_page_size: int = Field(default=100, ge=1, le=1000, strict=True)
    max_references: int = Field(default=100, ge=0, le=1000, strict=True)


class CustomEntityIdentity(_Contract):
    contract_version: Literal["1.0"] = "1.0"
    resource_namespace: Literal["foundation.metadata.custom_entity"] = CUSTOM_ENTITY_NAMESPACE
    resource_contract_version: Literal["1"] = "1"
    tenant_id: UUID
    entity_type_id: UUID
    instance_id: UUID


class CustomEntityRecord(_Contract):
    contract_version: Literal["1.0"] = "1.0"
    identity: CustomEntityIdentity
    revision_id: UUID
    revision_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    lifecycle: CustomEntityLifecycle
    scope_kind: CustomEntityScopeKind
    scope_id: UUID
    value_version: int = Field(ge=1, lt=2**63, strict=True)
    values: tuple[CustomFieldValue, ...]
    created_by: UUID
    updated_by: UUID
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    references: tuple[ReferenceResolution, ...] = ()

    @model_validator(mode="after")
    def envelope(self) -> Self:
        if (self.lifecycle is CustomEntityLifecycle.ARCHIVED) != (self.archived_at is not None):
            raise ValueError("Archive timestamp must match lifecycle")
        if (
            self.scope_kind is CustomEntityScopeKind.TENANT
            and self.scope_id != self.identity.tenant_id
        ):
            raise ValueError("Tenant scope must be the exact tenant")
        if len({v.field_id for v in self.values}) != len(self.values):
            raise ValueError("Duplicate stable field IDs")
        return self


class CustomEntityPage(_Contract):
    contract_version: Literal["1.0"] = "1.0"
    records: tuple[CustomEntityRecord, ...]
    next_after: UUID | None = None


class CustomEntityExport(_Contract):
    contract_version: Literal["1.0"] = "1.0"
    owner_module_id: Literal["foundation.metadata"] = "foundation.metadata"
    record: CustomEntityRecord


class CustomEntityQueryCapabilities(_Contract):
    version: Literal["1.0"] = "1.0"
    contract_version: Literal["1.0"] = "1.0"
    direct_read: Literal[True] = True
    type_scoped_list: Literal[True] = True
    scope_scoped_list: Literal[True] = True
    custom_field_filter: Literal[False] = False
    custom_field_sort: Literal[False] = False
    search: Literal[False] = False
    uniqueness: Literal[False] = False
    analytics: Literal[False] = False

    def require(self, operation: str) -> None:
        if operation not in {"read", "list"}:
            raise BusinessOSError("custom_query_unsupported", "Custom field query unsupported")
