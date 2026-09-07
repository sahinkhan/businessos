"""Transactional outbox publication and durable inbox idempotency."""

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from businessos.context import RequestContext
from businessos.di import RequestDependencyScope
from businessos.messages import DomainEvent, EventBus, EventHandlingContext
from businessos.persistence import (
    InboxReceipt,
    OutboxMessage,
    SQLAlchemyUnitOfWorkFactory,
    TransactionalPersistence,
    UnitOfWork,
    UnitOfWorkFactory,
)
from businessos.persistence.repository import TenantRepository
from businessos.providers import EventPublisher
from businessos.telemetry import consumer_span


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
                trace_value = message.payload.get("trace_context")
                trace_headers = (
                    {
                        key: value
                        for key, value in cast(Mapping[str, object], trace_value).items()
                        if key in {"traceparent", "tracestate"} and isinstance(value, str)
                    }
                    if isinstance(trace_value, dict)
                    else {}
                )
                try:
                    await self._publisher.publish(
                        (f"{self._subject_prefix}.tenant.{message.tenant_id}.{message.event_type}"),
                        json.dumps(message.payload, separators=(",", ":")).encode(),
                        {
                            "event-id": str(message.id),
                            "event-type": message.event_type,
                            "tenant-id": str(message.tenant_id),
                            "schema-version": str(message.schema_version),
                            "correlation-id": message.correlation_id,
                            **trace_headers,
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


class DurableEventConsumer:
    """Deliver each subscriber once under its inbox and tenant transaction."""

    def __init__(self, unit_of_work_factory: UnitOfWorkFactory, events: EventBus) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._events = events

    async def consume(
        self,
        event: DomainEvent,
        context: RequestContext,
        dependencies: RequestDependencyScope,
    ) -> int:
        tenant = context.tenant
        if tenant is None:
            raise RuntimeError("Durable event delivery requires authoritative tenant context")
        if event.tenant_id != tenant.tenant_id:
            raise RuntimeError("Event tenant does not match authoritative tenant context")
        with consumer_span(event.event_type, event.trace_context) as trace_id:
            traced_context = replace(context, trace_id=trace_id)
            processed = 0
            async with self._events.admit_delivery(event) as subscribers:
                for subscriber in subscribers:
                    await self._events.authorize(traced_context, subscriber.permission)
                    unit_of_work = self._unit_of_work_factory.for_tenant(tenant)
                    async with unit_of_work:
                        claimed = await unit_of_work.claim_inbox(
                            consumer=subscriber.subscriber,
                            event_id=event.event_id,
                            tenant_id=tenant.tenant_id,
                        )
                        if not claimed:
                            continue
                        from businessos.module_access import module_dependencies

                        public_dependencies = module_dependencies(dependencies, traced_context)

                        def persistence(
                            current: UnitOfWork = unit_of_work,
                        ) -> TransactionalPersistence:
                            return current.persistence

                        try:
                            await self._events.invoke_registered(
                                subscriber,
                                event,
                                EventHandlingContext(
                                    traced_context,
                                    public_dependencies,
                                    TenantRepository(
                                        persistence,
                                        subscriber.owner,
                                        tenant.tenant_id,
                                        public_dependencies.check,
                                    ),
                                ),
                            )
                        finally:
                            public_dependencies.close()
                        await unit_of_work.commit()
                        processed += 1
            return processed
