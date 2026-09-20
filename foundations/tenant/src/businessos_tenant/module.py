"""Tenant-management module registration and application handlers."""

import json
from datetime import datetime
from importlib.resources import files
from typing import ClassVar, Literal
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from businessos.sdk import (
    BusinessOSError,
    Command,
    DomainEvent,
    EventHandlingContext,
    HandlingContext,
    ModuleManifest,
    ModuleRegistration,
    PermissionDeclaration,
    Query,
    RequestContext,
    TenantContext,
)

from .contracts import (
    DeploymentMode,
    TenantEntitlementRecord,
    TenantLifecycleHooks,
    TenantManagementContract,
    TenantQuotaRecord,
    TenantRecord,
    TenantStatus,
    validate_effective_period,
)
from .models import TENANT_ENTITLEMENTS, TENANT_QUOTAS, TENANT_STATUS_HISTORY, TENANTS


class ProvisionTenant(Command):
    tenant_id: UUID = Field(default_factory=uuid4)
    slug: str = Field(pattern=r"^[a-z][a-z0-9-]{2,99}$")
    name: str = Field(min_length=1, max_length=200)
    deployment_mode: DeploymentMode
    region: str = Field(min_length=1, max_length=100)
    residency: dict[str, str] = Field(default_factory=dict)
    configuration_defaults: dict[str, object] = Field(default_factory=dict)


class TransitionTenant(Command):
    tenant_id: UUID
    target: TenantStatus
    reason: str | None = Field(default=None, max_length=1000)


class SetTenantEntitlement(Command):
    tenant_id: UUID
    capability: str = Field(pattern=r"^[a-z][a-z0-9_.:-]+$")
    enabled: bool
    reference: str | None = Field(default=None, max_length=200)
    effective_from: datetime | None = None
    effective_until: datetime | None = None


class SetTenantQuota(Command):
    tenant_id: UUID
    quota: str = Field(pattern=r"^[a-z][a-z0-9_.:-]+$")
    limit_value: int = Field(ge=0)
    unit: str = Field(min_length=1, max_length=50)


class GetTenant(Query):
    tenant_id: UUID


class GetTenantEntitlements(Query):
    tenant_id: UUID


class GetTenantQuotas(Query):
    tenant_id: UUID


class TenantCreated(DomainEvent):
    event_type: ClassVar[str] = "tenant.created.v1"
    slug: str


class TenantActivated(DomainEvent):
    event_type: ClassVar[str] = "tenant.activated.v1"


class TenantSuspended(DomainEvent):
    event_type: ClassVar[str] = "tenant.suspended.v1"


class TenantLifecycleWorkRequested(DomainEvent):
    """Durable, retryable lifecycle work; event_id is the idempotency key."""

    event_type: ClassVar[str] = "tenant.lifecycle.work-requested.v1"
    operation: Literal["export", "delete", "restore"]


_TRANSITIONS: dict[TenantStatus, frozenset[TenantStatus]] = {
    TenantStatus.REQUESTED: frozenset({TenantStatus.PROVISIONING}),
    TenantStatus.PROVISIONING: frozenset({TenantStatus.ACTIVE, TenantStatus.TERMINATING}),
    TenantStatus.ACTIVE: frozenset(
        {TenantStatus.SUSPENDED, TenantStatus.RETENTION_HOLD, TenantStatus.TERMINATING}
    ),
    TenantStatus.SUSPENDED: frozenset(
        {TenantStatus.ACTIVE, TenantStatus.RETENTION_HOLD, TenantStatus.TERMINATING}
    ),
    TenantStatus.RETENTION_HOLD: frozenset({TenantStatus.ACTIVE, TenantStatus.TERMINATING}),
    TenantStatus.TERMINATING: frozenset({TenantStatus.DELETED}),
    TenantStatus.DELETED: frozenset(),
}


class TenantModule:
    def __init__(self) -> None:
        data = json.loads(
            files("businessos_tenant").joinpath("manifest.json").read_text(encoding="utf-8")
        )
        self.manifest = ModuleManifest.model_validate(data)
        self.lifecycle_hooks = TenantLifecycleHooks()

    async def register(self, registration: ModuleRegistration) -> None:
        for key, description in (
            ("foundation.tenant.read", "Read the active tenant boundary"),
            ("foundation.tenant.manage", "Manage tenant lifecycle and limits"),
            ("foundation.tenant.provision", "Provision a new tenant boundary"),
        ):
            registration.permission(PermissionDeclaration(key=key, description=description))
        registration.contract("foundation.tenant.management.v1", TenantManagementContract())
        registration.contract("foundation.tenant.lifecycle-hooks.v1", self.lifecycle_hooks)
        registration.command(
            ProvisionTenant, self._provision, permission="foundation.tenant.provision"
        )
        registration.command(
            TransitionTenant, self._transition, permission="foundation.tenant.manage"
        )
        registration.command(
            SetTenantEntitlement, self._set_entitlement, permission="foundation.tenant.manage"
        )
        registration.command(SetTenantQuota, self._set_quota, permission="foundation.tenant.manage")
        registration.query(GetTenant, self._get, permission="foundation.tenant.read")
        registration.query(
            GetTenantEntitlements, self._get_entitlements, permission="foundation.tenant.read"
        )
        registration.query(GetTenantQuotas, self._get_quotas, permission="foundation.tenant.read")
        registration.event(
            TenantLifecycleWorkRequested,
            "lifecycle-hooks",
            self._run_lifecycle_hooks,
        )

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def _provision(self, command: ProvisionTenant, context: HandlingContext) -> object:
        tenant = _require_tenant(context.request, command.tenant_id)
        await context.unit_of_work.persistence.execute(
            insert(TENANTS).values(
                id=tenant.tenant_id,
                tenant_id=tenant.tenant_id,
                slug=command.slug,
                name=command.name,
                status=TenantStatus.REQUESTED,
                deployment_mode=command.deployment_mode,
                region=command.region,
                residency=command.residency,
                configuration_defaults=command.configuration_defaults,
            )
        )
        await context.unit_of_work.persistence.execute(
            insert(TENANT_STATUS_HISTORY).values(
                id=uuid4(),
                tenant_id=command.tenant_id,
                from_status=None,
                to_status=TenantStatus.REQUESTED,
                reason="provisioning requested",
                changed_by=tenant.principal_id,
            )
        )
        context.emit(
            TenantCreated(
                tenant_id=command.tenant_id,
                correlation_id=context.request.correlation_id,
                slug=command.slug,
            )
        )
        return {"tenant_id": command.tenant_id, "status": TenantStatus.REQUESTED}

    async def _transition(self, command: TransitionTenant, context: HandlingContext) -> object:
        tenant = _require_tenant(context.request, command.tenant_id)
        current = await context.unit_of_work.persistence.execute(
            select(TENANTS.c.status)
            .where(TENANTS.c.tenant_id == tenant.tenant_id)
            .with_for_update()
        )
        value = current.scalar_one_or_none()
        if value is None:
            raise BusinessOSError("not_found", "Tenant not found", status_code=404)
        current_status = TenantStatus(value)
        if command.target not in _TRANSITIONS[current_status]:
            raise BusinessOSError(
                "invalid_transition",
                "Tenant lifecycle transition is not allowed",
                status_code=409,
            )
        operation: Literal["export", "delete", "restore"] | None = None
        if command.target is TenantStatus.TERMINATING:
            operation = "export"
        elif command.target is TenantStatus.DELETED:
            operation = "delete"
        elif (
            current_status is TenantStatus.RETENTION_HOLD and command.target is TenantStatus.ACTIVE
        ):
            operation = "restore"
        await context.unit_of_work.persistence.execute(
            update(TENANTS)
            .where(TENANTS.c.tenant_id == tenant.tenant_id)
            .values(status=command.target, updated_at=datetime.now().astimezone())
        )
        await context.unit_of_work.persistence.execute(
            insert(TENANT_STATUS_HISTORY).values(
                id=uuid4(),
                tenant_id=tenant.tenant_id,
                from_status=current_status,
                to_status=command.target,
                reason=command.reason,
                changed_by=tenant.principal_id,
            )
        )
        if command.target is TenantStatus.ACTIVE:
            context.emit(
                TenantActivated(
                    tenant_id=tenant.tenant_id,
                    correlation_id=context.request.correlation_id,
                )
            )
        elif command.target is TenantStatus.SUSPENDED:
            context.emit(
                TenantSuspended(
                    tenant_id=tenant.tenant_id,
                    correlation_id=context.request.correlation_id,
                )
            )
        if operation is not None:
            context.emit(
                TenantLifecycleWorkRequested(
                    tenant_id=tenant.tenant_id,
                    correlation_id=context.request.correlation_id,
                    operation=operation,
                )
            )
        return {"tenant_id": tenant.tenant_id, "status": command.target}

    async def _run_lifecycle_hooks(
        self,
        event: TenantLifecycleWorkRequested,
        context: EventHandlingContext,
    ) -> None:
        del context
        operation = getattr(self.lifecycle_hooks, event.operation)
        await operation(event.tenant_id, event.event_id)

    async def _set_entitlement(
        self, command: SetTenantEntitlement, context: HandlingContext
    ) -> object:
        tenant = _require_tenant(context.request, command.tenant_id)
        validate_effective_period(command.effective_from, command.effective_until)
        await self._require_existing(tenant.tenant_id, context)
        statement = (
            pg_insert(TENANT_ENTITLEMENTS)
            .values(
                id=uuid4(),
                tenant_id=tenant.tenant_id,
                capability=command.capability,
                enabled=command.enabled,
                reference=command.reference,
                effective_from=command.effective_from,
                effective_until=command.effective_until,
            )
            .on_conflict_do_update(
                constraint="tenant_entitlement_capability",
                set_={
                    "enabled": command.enabled,
                    "reference": command.reference,
                    "effective_from": command.effective_from,
                    "effective_until": command.effective_until,
                },
            )
        )
        await context.unit_of_work.persistence.execute(statement)
        return {"capability": command.capability, "enabled": command.enabled}

    async def _set_quota(self, command: SetTenantQuota, context: HandlingContext) -> object:
        tenant = _require_tenant(context.request, command.tenant_id)
        await self._require_existing(tenant.tenant_id, context)
        statement = (
            pg_insert(TENANT_QUOTAS)
            .values(
                id=uuid4(),
                tenant_id=tenant.tenant_id,
                quota=command.quota,
                limit_value=command.limit_value,
                unit=command.unit,
            )
            .on_conflict_do_update(
                constraint="tenant_quota_name",
                set_={"limit_value": command.limit_value, "unit": command.unit},
            )
        )
        await context.unit_of_work.persistence.execute(statement)
        return {"quota": command.quota, "limit": command.limit_value, "unit": command.unit}

    async def _get(self, query: GetTenant, context: HandlingContext) -> object:
        _require_tenant(context.request, query.tenant_id)
        result = await context.unit_of_work.persistence.execute(
            select(TENANTS).where(TENANTS.c.tenant_id == query.tenant_id)
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise BusinessOSError("not_found", "Tenant not found", status_code=404)
        return TenantRecord.model_validate(dict(row))

    async def _get_entitlements(
        self, query: GetTenantEntitlements, context: HandlingContext
    ) -> object:
        _require_tenant(context.request, query.tenant_id)
        await self._require_existing(query.tenant_id, context)
        result = await context.unit_of_work.persistence.execute(
            select(TENANT_ENTITLEMENTS)
            .where(TENANT_ENTITLEMENTS.c.tenant_id == query.tenant_id)
            .order_by(TENANT_ENTITLEMENTS.c.capability)
        )
        return tuple(TenantEntitlementRecord.model_validate(dict(row)) for row in result.mappings())

    async def _get_quotas(self, query: GetTenantQuotas, context: HandlingContext) -> object:
        _require_tenant(context.request, query.tenant_id)
        await self._require_existing(query.tenant_id, context)
        result = await context.unit_of_work.persistence.execute(
            select(TENANT_QUOTAS)
            .where(TENANT_QUOTAS.c.tenant_id == query.tenant_id)
            .order_by(TENANT_QUOTAS.c.quota)
        )
        return tuple(TenantQuotaRecord.model_validate(dict(row)) for row in result.mappings())

    async def _require_existing(self, tenant_id: UUID, context: HandlingContext) -> None:
        result = await context.unit_of_work.persistence.execute(
            select(TENANTS.c.tenant_id).where(TENANTS.c.tenant_id == tenant_id)
        )
        if result.scalar_one_or_none() is None:
            raise BusinessOSError("not_found", "Tenant not found", status_code=404)


def _require_tenant(context: RequestContext, expected: UUID) -> TenantContext:
    tenant = context.tenant
    if tenant is None:
        raise BusinessOSError("unauthenticated", "Authentication required", status_code=401)
    if tenant.tenant_id != expected:
        raise BusinessOSError("forbidden", "Tenant scope mismatch", status_code=403)
    return tenant
