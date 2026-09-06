from collections.abc import Mapping
from uuid import uuid4

import pytest
from sqlalchemy import select

from businessos.config import Settings
from businessos.context import TenantContext
from businessos.eventing import Inbox, OutboxPublisher
from businessos.persistence import (
    Database,
    InboxReceipt,
    OutboxMessage,
    PendingOutboxMessage,
    SQLAlchemyUnitOfWorkFactory,
)


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


def _settings(database_url: str) -> Settings:
    return Settings(environment="test", database_url=database_url, database_pool_size=2)


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_outbox_survives_publish_failure_and_retries(migrated_database_url: str) -> None:
    database = Database(_settings(migrated_database_url))
    factory = SQLAlchemyUnitOfWorkFactory(database.sessions)
    tenant = TenantContext(uuid4(), uuid4(), uuid4())
    pending = PendingOutboxMessage(
        tenant_id=tenant.tenant_id,
        event_type="proof.changed",
        schema_version=1,
        correlation_id="correlation",
        payload={"value": "saved"},
    )
    async with factory.for_tenant(tenant) as unit_of_work:
        unit_of_work.add_outbox(pending)
        await unit_of_work.commit()

    provider = RecordingPublisher(failing=True)
    publisher = OutboxPublisher(factory, provider)
    assert await publisher.publish_batch() == 0

    async with database.sessions() as session:
        stored = await session.scalar(
            select(OutboxMessage).where(OutboxMessage.id == pending.event_id)
        )
        assert stored is not None
        assert stored.published_at is None
        assert stored.attempts == 1
        assert stored.last_error == "RuntimeError"

    provider.failing = False
    assert await publisher.publish_batch() == 1
    async with database.sessions() as session:
        stored = await session.scalar(
            select(OutboxMessage).where(OutboxMessage.id == pending.event_id)
        )
        assert stored is not None
        assert stored.published_at is not None
        assert stored.attempts == 2
    await database.close()

    assert provider.messages[0][0] == "businessos.events.proof.changed"
    assert provider.messages[0][2]["tenant-id"] == str(tenant.tenant_id)


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_inbox_claim_is_durable_and_idempotent(migrated_database_url: str) -> None:
    database = Database(_settings(migrated_database_url))
    factory = SQLAlchemyUnitOfWorkFactory(database.sessions)
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

    async with database.sessions() as session:
        receipts = (await session.scalars(select(InboxReceipt))).all()
    await database.close()
    assert len(receipts) == 1
