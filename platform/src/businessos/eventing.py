"""Transactional outbox publication and durable inbox idempotency."""

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from businessos.persistence import (
    InboxReceipt,
    OutboxMessage,
    SQLAlchemyUnitOfWorkFactory,
)
from businessos.providers import EventPublisher


class OutboxPublisher:
    def __init__(
        self,
        unit_of_work_factory: SQLAlchemyUnitOfWorkFactory,
        publisher: EventPublisher,
        *,
        subject_prefix: str = "businessos.events",
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._publisher = publisher
        self._subject_prefix = subject_prefix

    async def publish_batch(self, limit: int = 100) -> int:
        published = 0
        async with self._unit_of_work_factory.system() as unit_of_work:
            if unit_of_work.session is None:
                raise RuntimeError("Unit of Work did not create a session")
            result = await unit_of_work.session.scalars(
                select(OutboxMessage)
                .where(OutboxMessage.published_at.is_(None))
                .order_by(OutboxMessage.occurred_at, OutboxMessage.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            for message in result:
                try:
                    await self._publisher.publish(
                        f"{self._subject_prefix}.{message.event_type}",
                        json.dumps(message.payload, separators=(",", ":")).encode(),
                        {
                            "event-id": str(message.id),
                            "tenant-id": str(message.tenant_id),
                            "schema-version": str(message.schema_version),
                            "correlation-id": message.correlation_id,
                        },
                    )
                except Exception as exc:
                    message.attempts += 1
                    message.last_error = type(exc).__name__
                else:
                    message.published_at = datetime.now(UTC)
                    message.attempts += 1
                    message.last_error = None
                    published += 1
            await unit_of_work.commit()
        return published


class Inbox:
    """Claim a consumer/event pair once inside the caller's active transaction."""

    async def claim(
        self,
        session: AsyncSession,
        *,
        consumer: str,
        event_id: UUID,
        tenant_id: UUID,
    ) -> bool:
        statement = (
            insert(InboxReceipt)
            .values(consumer=consumer, event_id=event_id, tenant_id=tenant_id)
            .on_conflict_do_nothing(index_elements=["tenant_id", "consumer", "event_id"])
            .returning(InboxReceipt.event_id)
        )
        claimed = await session.scalar(statement)
        return claimed is not None
