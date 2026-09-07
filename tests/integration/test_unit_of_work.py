import asyncio
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from businessos.config import Settings
from businessos.context import TenantContext
from businessos.persistence import (
    Database,
    OutboxMessage,
    PendingOutboxMessage,
    SQLAlchemyUnitOfWork,
    SQLAlchemyUnitOfWorkFactory,
)
from tests.conftest import TenantSessions


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
async def test_unit_of_work_commits_outbox_with_trusted_tenant_context(
    migrated_database_url: str,
    tenant_sessions: TenantSessions,
) -> None:
    database = Database(_settings(migrated_database_url))
    factory = SQLAlchemyUnitOfWorkFactory(
        database.sessions, tenant_sessions=tenant_sessions(database)
    )
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
            text("SELECT platform_security.current_tenant_id()")
        )
        assert configured_tenant == tenant.tenant_id
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
    tenant_sessions: TenantSessions,
) -> None:
    database = Database(_settings(migrated_database_url))
    factory = SQLAlchemyUnitOfWorkFactory(
        database.sessions, tenant_sessions=tenant_sessions(database)
    )
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


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_unit_of_work_entry_cancellation_closes_real_pooled_session(
    migrated_database_url: str,
    tenant_sessions: TenantSessions,
) -> None:
    database = Database(_settings(migrated_database_url))
    tenant = TenantContext(uuid4(), uuid4(), uuid4())
    session = tenant_sessions(database)(tenant)()
    execute_entered = asyncio.Event()
    hold_tenant_setup = asyncio.Event()
    cleanup_entered = asyncio.Event()
    release_cleanup = asyncio.Event()
    real_execute = session.scalar
    real_rollback = session.rollback

    async def held_execute(*args: object, **kwargs: object) -> object:
        result = await cast(Any, real_execute)(*args, **kwargs)
        execute_entered.set()
        await hold_tenant_setup.wait()
        return result

    async def held_rollback() -> None:
        cleanup_entered.set()
        await release_cleanup.wait()
        await real_rollback()

    cast(Any, session).scalar = held_execute
    cast(Any, session).rollback = held_rollback
    unit_of_work = SQLAlchemyUnitOfWork(lambda: session, tenant)
    task = asyncio.create_task(unit_of_work.__aenter__())
    await execute_entered.wait()
    task.cancel()
    await cleanup_entered.wait()
    task.cancel()
    task.cancel()
    release_cleanup.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert task.cancelling() == 0
    assert unit_of_work.session is None
    assert cast(Any, database.engine.pool).checkedout() == 0
    await database.close()
