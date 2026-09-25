"""Public contracts, domain events, and extension hooks for data governance."""

from __future__ import annotations

from typing import Any, ClassVar, Protocol
from uuid import UUID

from businessos.sdk import DomainEvent


class LegalHoldPlaced(DomainEvent):
    event_type: ClassVar[str] = "governance.legal_hold.placed.v1"
    tenant_id: UUID
    hold_id: UUID
    code: str
    entity_type: str
    entity_id: str | None


class LegalHoldReleased(DomainEvent):
    event_type: ClassVar[str] = "governance.legal_hold.released.v1"
    tenant_id: UUID
    hold_id: UUID
    code: str
    released_by: str


class RetentionPolicyChanged(DomainEvent):
    event_type: ClassVar[str] = "governance.retention_policy.changed.v1"
    tenant_id: UUID
    policy_id: UUID
    code: str
    entity_type: str


class ConsentRecorded(DomainEvent):
    event_type: ClassVar[str] = "governance.consent.recorded.v1"
    tenant_id: UUID
    consent_id: UUID
    subject_id: UUID
    purpose_code: str


class ConsentRevoked(DomainEvent):
    event_type: ClassVar[str] = "governance.consent.revoked.v1"
    tenant_id: UUID
    consent_id: UUID
    subject_id: UUID
    purpose_code: str


class TenantExportHook(Protocol):
    """Extension hook called during tenant data extraction / portability flows."""

    async def export_tenant_data(self, tenant_id: UUID) -> dict[str, Any]: ...


class AnonymizationHook(Protocol):
    """Extension hook called when subject erasure or record anonymization executes."""

    async def anonymize_subject(self, tenant_id: UUID, subject_id: UUID) -> None: ...


class DataGovernanceHooks:
    """Ordered public extension hooks for tenant export and subject anonymization."""

    version: str = "1"

    def __init__(self) -> None:
        self._export_hooks: dict[str, TenantExportHook] = {}
        self._anonymization_hooks: dict[str, AnonymizationHook] = {}

    def register_export_hook(self, owner: str, hook: TenantExportHook) -> None:
        if owner in self._export_hooks:
            raise ValueError(f"Export hook already registered for {owner}")
        self._export_hooks[owner] = hook

    def register_anonymization_hook(self, owner: str, hook: AnonymizationHook) -> None:
        if owner in self._anonymization_hooks:
            raise ValueError(f"Anonymization hook already registered for {owner}")
        self._anonymization_hooks[owner] = hook

    async def export_tenant_data(self, tenant_id: UUID) -> dict[str, dict[str, Any]]:
        return {
            owner: await hook.export_tenant_data(tenant_id)
            for owner, hook in sorted(self._export_hooks.items())
        }

    async def anonymize_subject(self, tenant_id: UUID, subject_id: UUID) -> None:
        raise PermissionError(
            "V1 destructive hooks cannot authorize anonymization; "
            "use foundation.governance.destructive-lifecycle.v2"
        )
