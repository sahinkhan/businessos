"""Public tenant-management contracts."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from businessos.sdk import TenantContext, UnitOfWorkFactory

from .models import TENANTS


class TenantStatus(StrEnum):
    REQUESTED = "requested"
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    RETENTION_HOLD = "retention_hold"
    TERMINATING = "terminating"
    DELETED = "deleted"


class DeploymentMode(StrEnum):
    DEDICATED = "dedicated"
    DATABASE_PER_TENANT = "database_per_tenant"
    SHARED_SCHEMA = "shared_schema"


class TenantRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: UUID
    slug: str
    name: str
    status: TenantStatus
    deployment_mode: DeploymentMode
    region: str
    residency: dict[str, str] = Field(default_factory=dict)
    configuration_defaults: dict[str, object] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class TenantLifecycleHook(Protocol):
    async def export(self, tenant_id: UUID) -> None: ...

    async def delete(self, tenant_id: UUID) -> None: ...

    async def restore(self, tenant_id: UUID) -> None: ...


class TenantAccessValidator(Protocol):
    async def require_active(self, tenant_id: UUID) -> None: ...


class DatabaseTenantAccessValidator:
    """Fail closed unless the tenant exists and is active in its own RLS scope."""

    def __init__(self, installation_id: UUID, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._installation_id = installation_id
        self._unit_of_work_factory = unit_of_work_factory

    async def require_active(self, tenant_id: UUID) -> None:
        from sqlalchemy import select

        provisional = TenantContext(
            installation_id=self._installation_id,
            tenant_id=tenant_id,
            principal_id=UUID(int=0),
            authentication_strength="tenant-status-validation",
        )
        async with self._unit_of_work_factory.for_tenant(provisional) as unit_of_work:
            result = await unit_of_work.persistence.execute(
                select(TENANTS.c.status).where(TENANTS.c.tenant_id == tenant_id)
            )
            status = result.scalar_one_or_none()
        if status != TenantStatus.ACTIVE:
            from businessos.sdk import BusinessOSError

            raise BusinessOSError("tenant_unavailable", "Tenant is not active", status_code=403)


LifecycleCallback = Callable[[UUID], Awaitable[None]]


class TenantLifecycleHooks:
    """Ordered foundation-owned lifecycle hooks for later module participation."""

    version = "1.0"

    def __init__(self) -> None:
        self._hooks: dict[str, TenantLifecycleHook] = {}

    def register(self, owner: str, hook: TenantLifecycleHook) -> None:
        if owner in self._hooks:
            raise ValueError(f"Tenant lifecycle hook already registered: {owner}")
        self._hooks[owner] = hook

    async def export(self, tenant_id: UUID) -> None:
        for owner in sorted(self._hooks):
            await self._hooks[owner].export(tenant_id)

    async def delete(self, tenant_id: UUID) -> None:
        for owner in reversed(sorted(self._hooks)):
            await self._hooks[owner].delete(tenant_id)

    async def restore(self, tenant_id: UUID) -> None:
        for owner in sorted(self._hooks):
            await self._hooks[owner].restore(tenant_id)


@dataclass(frozen=True, slots=True)
class TenantManagementContract:
    version: str = "1.0"
    provisioning_command: str = "businessos_tenant.ProvisionTenant"
    status_command: str = "businessos_tenant.TransitionTenant"
    read_query: str = "businessos_tenant.GetTenant"
