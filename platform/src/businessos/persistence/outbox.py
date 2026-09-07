"""Transport-neutral outbox write contract."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class PendingOutboxMessage:
    tenant_id: UUID
    event_type: str
    schema_version: int
    correlation_id: str
    payload: dict[str, object]
    causation_id: str | None = None
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
