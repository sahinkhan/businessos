import asyncio
from collections.abc import Iterator, Mapping
from typing import ClassVar
from uuid import uuid4

import pytest
from sqlalchemy import column, select, table

from businessos.config import Settings
from businessos.context import RequestContext, TenantContext
from businessos.di import Container
from businessos.eventing import DurableEventConsumer, Inbox, OutboxPublisher
from businessos.messages import DomainEvent, EventBus, EventHandlingContext
from businessos.persistence import (
    Database,
    InboxReceipt,
    OutboxMessage,
    PendingOutboxMessage,
    SQLAlchemyUnitOfWorkFactory,
)
from tests.conftest import TenantSessions

EFFECTS = table("effects", column("id"), schema="mod_test_projection")


class RecordingPublisher:
    def __init__(self, *, failing: bool = False) -> None:
        self.failing = failing
        self.messages: list[tuple[str, bytes, Mapping[str, str]]] = []

    async def publish(self, subject: str, payload: bytes, headers: Mapping[str, str]) -> None:
        if self.failing:
            raise RuntimeError("broker unavailable")
        self.messages.append((subject, payload, headers))

    async def readiness(self) -> None:
        if self.failing:
            raise RuntimeError("broker unavailable")


class ProbeEvent(DomainEvent):
    event_type: ClassVar[str] = "test.probe.completed"
    value: str


def _settings(database_url: str) -> Settings:
    return Settings(environment="test", database_url=database_url, database_pool_size=2)


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_outbox_survives_publish_failure_and_retries(
    migrated_database_url: str,
    postgres_operations_database_url: str,
    tenant_sessions: TenantSessions,
) -> None:
    database = Database(_settings(migrated_database_url))
    operations_database = Database(_settings(postgres_operations_database_url))
    factory = SQLAlchemyUnitOfWorkFactory(
        database.sessions,
        tenant_sessions=tenant_sessions(database),
        system_sessions=operations_database.sessions,
    )
    tenant = TenantContext(uuid4(), uuid4(), uuid4())
    pending = PendingOutboxMessage(
        tenant_id=tenant.tenant_id,
        event_type="proof.changed",
        schema_version=1,
        correlation_id="correlation",
        payload={
            "value": "saved",
            "trace_context": {
                "traceparent": "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"
            },
        },
    )
    async with factory.for_tenant(tenant) as unit_of_work:
        unit_of_work.add_outbox(pending)
        await unit_of_work.commit()

    provider = RecordingPublisher(failing=True)
    publisher = OutboxPublisher(factory, provider)
    assert await publisher.publish_batch() == 0

    async with factory.for_tenant(tenant) as unit_of_work:
        assert unit_of_work.session is not None
        stored = await unit_of_work.session.scalar(
            select(OutboxMessage).where(OutboxMessage.id == pending.event_id)
        )
        assert stored is not None
        assert stored.published_at is None
        assert stored.attempts == 1
        assert stored.last_error == "RuntimeError"

    provider.failing = False
    assert await publisher.publish_batch() == 1
    async with factory.for_tenant(tenant) as unit_of_work:
        assert unit_of_work.session is not None
        stored = await unit_of_work.session.scalar(
            select(OutboxMessage).where(OutboxMessage.id == pending.event_id)
        )
        assert stored is not None
        assert stored.published_at is not None
        assert stored.attempts == 2
    await database.close()
    await operations_database.close()

    assert provider.messages[0][0] == (f"businessos.events.tenant.{tenant.tenant_id}.proof.changed")
    assert provider.messages[0][2]["tenant-id"] == str(tenant.tenant_id)
    assert provider.messages[0][2]["traceparent"].startswith("00-0123456789abcdef")


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_inbox_claim_is_durable_and_idempotent(
    migrated_database_url: str,
    tenant_sessions: TenantSessions,
) -> None:
    database = Database(_settings(migrated_database_url))
    factory = SQLAlchemyUnitOfWorkFactory(
        database.sessions, tenant_sessions=tenant_sessions(database)
    )
    tenant = TenantContext(uuid4(), uuid4(), uuid4())
    event_id = uuid4()
    inbox = Inbox()

    async with factory.for_tenant(tenant) as unit_of_work:
        assert unit_of_work.session is not None
        assert await inbox.claim(
            unit_of_work.session,
            consumer="proof.consumer",
            event_id=event_id,
            tenant_id=tenant.tenant_id,
        )
        await unit_of_work.commit()

    async with factory.for_tenant(tenant) as unit_of_work:
        assert unit_of_work.session is not None
        assert not await inbox.claim(
            unit_of_work.session,
            consumer="proof.consumer",
            event_id=event_id,
            tenant_id=tenant.tenant_id,
        )

    async with factory.for_tenant(tenant) as unit_of_work:
        assert unit_of_work.session is not None
        receipts = (await unit_of_work.session.scalars(select(InboxReceipt))).all()
    await database.close()
    assert len(receipts) == 1


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_durable_consumer_serializes_concurrent_redelivery(
    subscriber_effects: None,
    migrated_database_url: str,
    postgres_operations_database_url: str,
    tenant_sessions: TenantSessions,
) -> None:
    database = Database(_settings(migrated_database_url))
    operations_database = Database(_settings(postgres_operations_database_url))
    factory = SQLAlchemyUnitOfWorkFactory(
        database.sessions,
        tenant_sessions=tenant_sessions(database),
        system_sessions=operations_database.sessions,
    )
    events = EventBus()
    consumer = DurableEventConsumer(factory, events)
    tenant = TenantContext(uuid4(), uuid4(), uuid4())
    event = ProbeEvent(
        tenant_id=tenant.tenant_id,
        correlation_id="concurrent-redelivery",
        value="saved",
    )
    side_effect_id = uuid4()
    handler_calls = 0

    async def handle(_: ProbeEvent, handling: EventHandlingContext) -> None:
        nonlocal handler_calls
        handler_calls += 1
        await handling.persistence.insert("effects", {"id": side_effect_id})
        await asyncio.sleep(0.05)

    events.subscribe(ProbeEvent, "test.projection", handle, owner="test.projection")
    container = Container()

    async def deliver() -> int:
        async with container.request_scope() as dependencies:
            return await consumer.consume(
                event,
                RequestContext(correlation_id=event.correlation_id, tenant=tenant),
                dependencies,
            )

    outcomes = await asyncio.gather(deliver(), deliver())
    assert sorted(outcomes) == [0, 1]
    assert handler_calls == 1

    async with factory.for_tenant(tenant) as unit_of_work:
        assert unit_of_work.session is not None
        receipt_count = len((await unit_of_work.session.scalars(select(InboxReceipt))).all())
        side_effect = await unit_of_work.session.scalar(
            select(EFFECTS.c.id).where(EFFECTS.c.id == side_effect_id)
        )
    assert receipt_count == 1
    assert side_effect is not None
    await container.close()
    await database.close()
    await operations_database.close()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_durable_consumer_rolls_back_receipt_and_side_effect_then_retries(
    subscriber_effects: None,
    migrated_database_url: str,
    tenant_sessions: TenantSessions,
) -> None:
    database = Database(_settings(migrated_database_url))
    factory = SQLAlchemyUnitOfWorkFactory(
        database.sessions, tenant_sessions=tenant_sessions(database)
    )
    events = EventBus()
    consumer = DurableEventConsumer(factory, events)
    tenant = TenantContext(uuid4(), uuid4(), uuid4())
    event = ProbeEvent(
        tenant_id=tenant.tenant_id,
        correlation_id="rollback-redelivery",
        value="saved",
    )
    side_effect_id = uuid4()
    should_fail = True

    async def handle(_: ProbeEvent, handling: EventHandlingContext) -> None:
        await handling.persistence.insert("effects", {"id": side_effect_id})
        if should_fail:
            raise RuntimeError("projection failed")

    events.subscribe(ProbeEvent, "test.retryable-projection", handle, owner="test.projection")
    container = Container()

    async def deliver() -> int:
        async with container.request_scope() as dependencies:
            return await consumer.consume(
                event,
                RequestContext(correlation_id=event.correlation_id, tenant=tenant),
                dependencies,
            )

    with pytest.raises(RuntimeError, match="projection failed"):
        await deliver()
    async with factory.for_tenant(tenant) as unit_of_work:
        assert unit_of_work.session is not None
        assert (await unit_of_work.session.scalars(select(InboxReceipt))).all() == []
        assert (
            await unit_of_work.session.scalar(
                select(EFFECTS.c.id).where(EFFECTS.c.id == side_effect_id)
            )
            is None
        )

    should_fail = False
    assert await deliver() == 1
    assert await deliver() == 0
    async with factory.for_tenant(tenant) as unit_of_work:
        assert unit_of_work.session is not None
        assert len((await unit_of_work.session.scalars(select(InboxReceipt))).all()) == 1
        assert (
            await unit_of_work.session.scalar(
                select(EFFECTS.c.id).where(EFFECTS.c.id == side_effect_id)
            )
            is not None
        )
    await container.close()
    await database.close()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_durable_consumer_cancellation_rolls_back_and_remains_retryable(
    subscriber_effects: None,
    migrated_database_url: str,
    tenant_sessions: TenantSessions,
) -> None:
    database = Database(_settings(migrated_database_url))
    factory = SQLAlchemyUnitOfWorkFactory(
        database.sessions, tenant_sessions=tenant_sessions(database)
    )
    events = EventBus()
    consumer = DurableEventConsumer(factory, events)
    tenant = TenantContext(uuid4(), uuid4(), uuid4())
    event = ProbeEvent(
        tenant_id=tenant.tenant_id,
        correlation_id="cancelled-redelivery",
        value="saved",
    )
    side_effect_id = uuid4()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def handle(_: ProbeEvent, handling: EventHandlingContext) -> None:
        await handling.persistence.insert("effects", {"id": side_effect_id})
        entered.set()
        await release.wait()

    events.subscribe(ProbeEvent, "test.cancelled-projection", handle, owner="test.projection")
    container = Container()

    async def deliver() -> int:
        async with container.request_scope() as dependencies:
            return await consumer.consume(
                event,
                RequestContext(correlation_id=event.correlation_id, tenant=tenant),
                dependencies,
            )

    task = asyncio.create_task(deliver())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with factory.for_tenant(tenant) as unit_of_work:
        assert unit_of_work.session is not None
        assert (await unit_of_work.session.scalars(select(InboxReceipt))).all() == []
        assert (
            await unit_of_work.session.scalar(
                select(EFFECTS.c.id).where(EFFECTS.c.id == side_effect_id)
            )
            is None
        )

    release.set()
    assert await deliver() == 1
    await container.close()
    await database.close()


@pytest.fixture
def subscriber_effects(
    migrated_database_url: str, postgres_migration_database_url: str
) -> Iterator[None]:
    import psycopg

    with psycopg.connect(
        postgres_migration_database_url.replace("postgresql+psycopg", "postgresql")
    ) as connection:
        connection.execute("CREATE SCHEMA mod_test_projection")
        connection.execute(
            "CREATE TABLE mod_test_projection.effects "
            "(id UUID PRIMARY KEY, tenant_id UUID NOT NULL)"
        )
        connection.execute("ALTER TABLE mod_test_projection.effects ENABLE ROW LEVEL SECURITY")
        connection.execute("ALTER TABLE mod_test_projection.effects FORCE ROW LEVEL SECURITY")
        connection.execute(
            "CREATE POLICY tenant_isolation ON mod_test_projection.effects TO businessos_app "
            "USING (tenant_id = platform_security.current_tenant_id()) "
            "WITH CHECK (tenant_id = platform_security.current_tenant_id())"
        )
        connection.execute("GRANT USAGE ON SCHEMA mod_test_projection TO businessos_app")
        connection.execute("GRANT SELECT, INSERT ON mod_test_projection.effects TO businessos_app")
    yield
    with psycopg.connect(
        postgres_migration_database_url.replace("postgresql+psycopg", "postgresql")
    ) as connection:
        connection.execute("DROP SCHEMA mod_test_projection CASCADE")
