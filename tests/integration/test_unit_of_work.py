from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from businessos.config import Settings
from businessos.context import TenantContext
from businessos.persistence import (
    Database,
    OutboxMessage,
    PendingOutboxMessage,
    SQLAlchemyUnitOfWorkFactory,
)


def _settings(database_url: str) -> Settings:
    return Settings(
        environment="test",
        database_url=database_url,
        database_pool_size=2,
        database_readiness_enabled=True,
    )


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_unit_of_work_commits_state_and_outbox_atomically(
    migrated_database_url: str,
) -> None:
    database = Database(_settings(migrated_database_url))
    factory = SQLAlchemyUnitOfWorkFactory(database.sessions)
    tenant = TenantContext(
        installation_id=uuid4(),
        tenant_id=uuid4(),
        principal_id=uuid4(),
        authentication_strength="test",
    )
    message = PendingOutboxMessage(
        tenant_id=tenant.tenant_id,
        event_type="proof.changed",
        schema_version=1,
        correlation_id="correlation-1",
        payload={"value": "committed"},
    )

    await database.readiness()
    async with factory.for_tenant(tenant) as unit_of_work:
        assert unit_of_work.session is not None
        configured_tenant = await unit_of_work.session.scalar(
            text("SELECT current_setting('app.tenant_id', true)")
        )
        assert configured_tenant == str(tenant.tenant_id)
        unit_of_work.add_outbox(message)
        await unit_of_work.commit()

    async with factory.for_tenant(tenant) as unit_of_work:
        assert unit_of_work.session is not None
        count = await unit_of_work.session.scalar(select(func.count()).select_from(OutboxMessage))
    await database.close()

    assert count == 1


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_unit_of_work_rolls_back_without_explicit_commit(
    migrated_database_url: str,
) -> None:
    database = Database(_settings(migrated_database_url))
    factory = SQLAlchemyUnitOfWorkFactory(database.sessions)
    tenant = TenantContext(
        installation_id=uuid4(),
        tenant_id=uuid4(),
        principal_id=uuid4(),
    )
    message = PendingOutboxMessage(
        tenant_id=tenant.tenant_id,
        event_type="proof.rolled_back",
        schema_version=1,
        correlation_id="correlation-2",
        payload={"value": "rolled-back"},
    )

    async with factory.for_tenant(tenant) as unit_of_work:
        unit_of_work.add_outbox(message)

    async with factory.for_tenant(tenant) as unit_of_work:
        assert unit_of_work.session is not None
        count = await unit_of_work.session.scalar(
            select(func.count())
            .select_from(OutboxMessage)
            .where(OutboxMessage.id == message.event_id)
        )
    await database.close()

    assert count == 0
