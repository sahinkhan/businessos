import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import psycopg
import pytest
from businessos_proof.module import PROOF_RECORDS
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from businessos.config import Settings
from businessos.context import RequestContext, TenantContext
from businessos.di import Container, RequestDependencyScope
from businessos.errors import ConfigurationError
from businessos.messages import Command, DomainEvent, EventBus, HandlingContext, MessageDispatcher
from businessos.migrations import MigrationCoordinator
from businessos.modules import ModuleRegistry
from businessos.persistence import Database, SQLAlchemyUnitOfWorkFactory
from tests.conftest import TenantSessions


class AtomicProbe(Command):
    record_id: UUID
    event_id: UUID
    value: str


class AtomicProbeStored(DomainEvent):
    event_type = "example.phase1_proof.atomic_probe_stored"
    record_id: UUID
    value: str


class FailingCommitSession(AsyncSession):
    async def commit(self) -> None:
        await self.flush()
        await self.rollback()
        raise RuntimeError("forced commit failure")


def _settings(database_url: str) -> Settings:
    return Settings(environment="test", database_url=database_url, database_pool_size=2)


def _tenant() -> TenantContext:
    return TenantContext(uuid4(), uuid4(), uuid4(), authentication_strength="test")


@asynccontextmanager
async def _migrated_proof_database(
    runtime_url: str,
    migration_url: str,
) -> AsyncGenerator[Database]:
    from businessos_proof import ProofModule

    modules = ModuleRegistry(platform_version="0.1.0", sdk_version="0.2.0")
    modules.add(ProofModule())
    migrations = MigrationCoordinator(modules)
    await migrations.upgrade_async(migration_url)
    database = Database(_settings(runtime_url))
    try:
        yield database
    finally:
        await database.close()
        await migrations.downgrade_async(migration_url)


def _stored_counts(
    migration_url: str,
    record_id: UUID,
    event_id: UUID,
) -> tuple[int, int]:
    connection_url = migration_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(connection_url) as connection:
        row = connection.execute(
            "SELECT "
            "(SELECT count(*) FROM mod_example_phase1_proof.proof_records WHERE id = %s), "
            "(SELECT count(*) FROM eventing.outbox_messages WHERE id = %s)",
            (record_id, event_id),
        ).fetchone()
    assert row is not None
    return int(row[0]), int(row[1])


def _handler(
    *,
    after_write: Callable[[], Awaitable[None]] | None = None,
    state_tenant: UUID | None = None,
    correlation_id: str = "atomic-probe",
) -> Callable[[AtomicProbe, HandlingContext], Awaitable[object]]:
    async def handle(command: AtomicProbe, context: HandlingContext) -> object:
        assert context.request.tenant is not None
        await context.persistence.insert(
            "proof_records",
            {
                "id": command.record_id,
                "tenant_id": state_tenant or context.request.tenant.tenant_id,
                "command_id": uuid4(),
                "value": command.value,
            },
        )
        context.emit(
            AtomicProbeStored(
                event_id=command.event_id,
                tenant_id=context.request.tenant.tenant_id,
                correlation_id=correlation_id,
                record_id=command.record_id,
                value=command.value,
            )
        )
        if after_write is not None:
            await after_write()
        return {"stored": True}

    return handle


async def _dispatch(
    dispatcher: MessageDispatcher,
    command: AtomicProbe,
    tenant: TenantContext,
    dependencies: RequestDependencyScope,
) -> object:
    return await dispatcher.command(
        command,
        RequestContext(correlation_id="atomic-probe", tenant=tenant),
        dependencies,
    )


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_handler_exception_and_cancellation_roll_back_state_and_outbox(
    postgres_database_url: str,
    postgres_migration_database_url: str,
    tenant_sessions: TenantSessions,
) -> None:
    async with _migrated_proof_database(
        postgres_database_url, postgres_migration_database_url
    ) as database:
        factory = SQLAlchemyUnitOfWorkFactory(
            database.sessions, tenant_sessions=tenant_sessions(database)
        )
        dispatcher = MessageDispatcher(factory, EventBus())
        tenant = _tenant()
        container = Container()

        async def fail_after_write() -> None:
            raise RuntimeError("handler failed")

        dispatcher.commands.register(
            AtomicProbe,
            "example.phase1-proof",
            _handler(after_write=fail_after_write),
        )
        failed = AtomicProbe(record_id=uuid4(), event_id=uuid4(), value="handler-failure")
        async with container.request_scope() as dependencies:
            with pytest.raises(RuntimeError, match="handler failed"):
                await _dispatch(dispatcher, failed, tenant, dependencies)
        assert await asyncio.to_thread(
            _stored_counts,
            postgres_migration_database_url,
            failed.record_id,
            failed.event_id,
        ) == (0, 0)

        cancellation_started = asyncio.Event()
        never_finish = asyncio.Event()

        async def wait_for_cancellation() -> None:
            cancellation_started.set()
            await never_finish.wait()

        cancellation_dispatcher = MessageDispatcher(factory, EventBus())
        cancellation_dispatcher.commands.register(
            AtomicProbe,
            "example.phase1-proof",
            _handler(after_write=wait_for_cancellation),
        )
        cancelled = AtomicProbe(record_id=uuid4(), event_id=uuid4(), value="cancelled")
        async with container.request_scope() as dependencies:
            task = asyncio.create_task(
                _dispatch(cancellation_dispatcher, cancelled, tenant, dependencies)
            )
            await cancellation_started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert await asyncio.to_thread(
            _stored_counts,
            postgres_migration_database_url,
            cancelled.record_id,
            cancelled.event_id,
        ) == (0, 0)


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_state_outbox_and_commit_failures_are_atomic(
    postgres_database_url: str,
    postgres_migration_database_url: str,
    tenant_sessions: TenantSessions,
) -> None:
    async with _migrated_proof_database(
        postgres_database_url, postgres_migration_database_url
    ) as database:
        tenant = _tenant()
        container = Container()
        factory = SQLAlchemyUnitOfWorkFactory(
            database.sessions, tenant_sessions=tenant_sessions(database)
        )

        outbox_failure = AtomicProbe(record_id=uuid4(), event_id=uuid4(), value="outbox-failure")
        dispatcher = MessageDispatcher(factory, EventBus())
        dispatcher.commands.register(
            AtomicProbe,
            "example.phase1-proof",
            _handler(correlation_id="x" * 101),
        )
        async with container.request_scope() as dependencies:
            with pytest.raises(DBAPIError):
                await _dispatch(dispatcher, outbox_failure, tenant, dependencies)
        assert await asyncio.to_thread(
            _stored_counts,
            postgres_migration_database_url,
            outbox_failure.record_id,
            outbox_failure.event_id,
        ) == (0, 0)

        state_failure = AtomicProbe(record_id=uuid4(), event_id=uuid4(), value="state-failure")
        state_dispatcher = MessageDispatcher(factory, EventBus())
        state_dispatcher.commands.register(
            AtomicProbe,
            "example.phase1-proof",
            _handler(state_tenant=uuid4()),
        )
        async with container.request_scope() as dependencies:
            with pytest.raises(ConfigurationError):
                await _dispatch(state_dispatcher, state_failure, tenant, dependencies)
        assert await asyncio.to_thread(
            _stored_counts,
            postgres_migration_database_url,
            state_failure.record_id,
            state_failure.event_id,
        ) == (0, 0)

        failing_sessions = async_sessionmaker(
            bind=tenant_sessions(database)(tenant).kw["bind"],
            class_=FailingCommitSession,
            autoflush=False,
            expire_on_commit=False,
        )
        commit_dispatcher = MessageDispatcher(
            SQLAlchemyUnitOfWorkFactory(failing_sessions), EventBus()
        )
        commit_dispatcher.commands.register(
            AtomicProbe,
            "example.phase1-proof",
            _handler(),
        )
        commit_failure = AtomicProbe(record_id=uuid4(), event_id=uuid4(), value="commit-failure")
        async with container.request_scope() as dependencies:
            with pytest.raises(RuntimeError, match="forced commit failure"):
                await _dispatch(commit_dispatcher, commit_failure, tenant, dependencies)
        assert await asyncio.to_thread(
            _stored_counts,
            postgres_migration_database_url,
            commit_failure.record_id,
            commit_failure.event_id,
        ) == (0, 0)


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_runtime_rls_blocks_cross_tenant_proof_mutations(
    postgres_database_url: str,
    postgres_migration_database_url: str,
    tenant_sessions: TenantSessions,
) -> None:
    async with _migrated_proof_database(
        postgres_database_url, postgres_migration_database_url
    ) as database:
        factory = SQLAlchemyUnitOfWorkFactory(
            database.sessions, tenant_sessions=tenant_sessions(database)
        )
        tenant_a = _tenant()
        tenant_b = _tenant()
        record_a = uuid4()
        record_b = uuid4()

        for tenant, record_id, value in (
            (tenant_a, record_a, "tenant-a"),
            (tenant_b, record_b, "tenant-b"),
        ):
            async with factory.for_tenant(tenant) as unit_of_work:
                await unit_of_work.persistence.execute(
                    insert(PROOF_RECORDS).values(
                        id=record_id,
                        tenant_id=tenant.tenant_id,
                        command_id=uuid4(),
                        value=value,
                    )
                )
                await unit_of_work.commit()

        async with factory.for_tenant(tenant_a) as unit_of_work:
            visible = (
                (await unit_of_work.persistence.execute(select(PROOF_RECORDS.c.id))).scalars().all()
            )
            updated = await unit_of_work.persistence.execute(
                update(PROOF_RECORDS)
                .where(PROOF_RECORDS.c.id == record_b)
                .values(value="forged")
                .returning(PROOF_RECORDS.c.id)
            )
            deleted = await unit_of_work.persistence.execute(
                delete(PROOF_RECORDS)
                .where(PROOF_RECORDS.c.id == record_b)
                .returning(PROOF_RECORDS.c.id)
            )
            await unit_of_work.commit()

        assert visible == [record_a]
        assert updated.scalar_one_or_none() is None
        assert deleted.scalar_one_or_none() is None

        async with factory.for_tenant(tenant_a) as unit_of_work:
            with pytest.raises(DBAPIError):
                await unit_of_work.persistence.execute(
                    insert(PROOF_RECORDS).values(
                        id=uuid4(),
                        tenant_id=tenant_b.tenant_id,
                        command_id=uuid4(),
                        value="forged",
                    )
                )
