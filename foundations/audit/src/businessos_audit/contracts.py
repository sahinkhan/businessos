"""Public contracts, events, and audit log interfaces."""

from __future__ import annotations

from typing import ClassVar
from uuid import UUID

from businessos.sdk import DomainEvent


class AuditEventRecorded(DomainEvent):
    event_type: ClassVar[str] = "audit.event.recorded.v1"
    audit_id: UUID
    tenant_id: UUID
    actor_id: str
    action: str
    resource_type: str
    resource_id: str | None
    status: str
