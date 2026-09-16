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

    async def export_tenant_data(self, tenant_id: UUID) -> dict[str, Any]:
        ...


class AnonymizationHook(Protocol):
    """Extension hook called when subject erasure or record anonymization executes."""

    async def anonymize_subject(self, tenant_id: UUID, subject_id: UUID) -> None:
        ...
