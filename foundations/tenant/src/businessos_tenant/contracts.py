"""Public tenant-management contracts."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from businessos.sdk import (
    BusinessOSError,
    TenantContext,
    TransactionalPersistence,
    UnitOfWorkFactory,
)

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


class TenantEntitlementRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: UUID
    capability: str
    enabled: bool
    reference: str | None = None
    effective_from: datetime | None = None
    effective_until: datetime | None = None

    def is_effective(self, at: datetime) -> bool:
        return self.enabled and effective_at(self.effective_from, self.effective_until, at)


class TenantQuotaRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: UUID
    quota: str
    limit_value: int
    unit: str


TemporalValue = date | datetime


def validate_effective_period(
    start: TemporalValue | None,
    end: TemporalValue | None,
) -> None:
    """Validate a strict half-open effective period before persistence."""

    datetimes = [value for value in (start, end) if isinstance(value, datetime)]
    dates = [
        value for value in (start, end) if value is not None and not isinstance(value, datetime)
    ]
    if datetimes and dates:
        raise _invalid_effective_period()
    if any(value.tzinfo is None or value.utcoffset() is None for value in datetimes):
        raise _invalid_effective_period()
    if start is None or end is None:
        return
    if isinstance(start, datetime) and isinstance(end, datetime):
        invalid = end <= start
    elif not isinstance(start, datetime) and not isinstance(end, datetime):
        invalid = end <= start
    else:
        invalid = True
    if invalid:
        raise _invalid_effective_period()


def effective_at(
    start: TemporalValue | None,
    end: TemporalValue | None,
    instant: TemporalValue,
) -> bool:
    """Return whether *instant* belongs to the validated half-open period."""

    validate_effective_period(start, end)
    validate_effective_period(start, None)
    if isinstance(instant, datetime):
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise _invalid_effective_period()
        if start is not None and not isinstance(start, datetime):
            raise _invalid_effective_period()
        if end is not None and not isinstance(end, datetime):
            raise _invalid_effective_period()
    elif isinstance(start, datetime) or isinstance(end, datetime):
        raise _invalid_effective_period()
    return (start is None or start <= instant) and (end is None or instant < end)


def _invalid_effective_period() -> BusinessOSError:
    return BusinessOSError(
        "invalid_effective_dates",
        "Effective period must use compatible, timezone-aware values with end after start",
        status_code=422,
    )


class TenantLifecycleHook(Protocol):
    async def export(self, tenant_id: UUID) -> None: ...

    async def delete(self, tenant_id: UUID) -> None: ...

    async def restore(self, tenant_id: UUID) -> None: ...


class TenantAccessValidator(Protocol):
    async def require_active(self, tenant_id: UUID) -> None: ...

    async def require_active_in(
        self,
        tenant_id: UUID,
        persistence: TransactionalPersistence,
        *,
        lock: bool = False,
    ) -> None: ...


class DatabaseTenantAccessValidator:
    """Fail closed unless the tenant exists and is active in its own RLS scope."""

    def __init__(self, installation_id: UUID, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._installation_id = installation_id
        self._unit_of_work_factory = unit_of_work_factory

    async def require_active(self, tenant_id: UUID) -> None:
        provisional = TenantContext(
            installation_id=self._installation_id,
            tenant_id=tenant_id,
            principal_id=UUID(int=0),
            authentication_strength="tenant-status-validation",
        )
        async with self._unit_of_work_factory.for_tenant(provisional) as unit_of_work:
            await self.require_active_in(tenant_id, unit_of_work.persistence)

    async def require_active_in(
        self,
        tenant_id: UUID,
        persistence: TransactionalPersistence,
        *,
        lock: bool = False,
    ) -> None:
        from sqlalchemy import select

        statement = select(TENANTS.c.status).where(TENANTS.c.tenant_id == tenant_id)
        if lock:
            statement = statement.with_for_update(read=True)
        result = await persistence.execute(statement)
        status = result.scalar_one_or_none()
        if status != TenantStatus.ACTIVE:
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
    version: str = "1.1"
    provisioning_command: str = "businessos_tenant.ProvisionTenant"
    status_command: str = "businessos_tenant.TransitionTenant"
    read_query: str = "businessos_tenant.GetTenant"
    entitlements_query: str = "businessos_tenant.GetTenantEntitlements"
    quotas_query: str = "businessos_tenant.GetTenantQuotas"
    lifecycle_hooks: str = "foundation.tenant.lifecycle-hooks.v1"
