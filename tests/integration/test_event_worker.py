import asyncio
import json
import os
from typing import ClassVar
from uuid import uuid4

import boto3
import psycopg
import pytest
from businessos_proof.module import PROOF_RECORDS, ProofModule, ProofStored, StoreProof
from sqlalchemy import select, text

from businessos.config import Settings
from businessos.context import RequestContext, TenantContext
from businessos.errors import DeliveryUnavailableError
from businessos.event_worker import EventWorkerSettings, create_event_worker
from businessos.messages import DomainEvent, EventHandlingContext
from businessos.migrations import MigrationCoordinator
from businessos.modules import ModuleManifest, ModuleRegistration, ModuleRegistry
from businessos.persistence import (
    Database,
    EventSubscriberObligation,
    InboxReceipt,
    OutboxMessage,
    SQLAlchemyUnitOfWorkFactory,
)
from businessos.providers import NatsJetStreamPublisher, S3ObjectStorageProvider
from tests.conftest import PostgreSQLTestDatabase


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        pytest.skip(f"{name} is not configured")
    return value


class _RetryingProofModule(ProofModule):
    def __init__(self) -> None:
        super().__init__()
        self.delivery_attempts = 0
        self.projected = asyncio.Event()

    async def _project(self, event: ProofStored, context: EventHandlingContext) -> None:
        self.delivery_attempts += 1
        if self.delivery_attempts == 1:
            raise RuntimeError("deterministic first delivery failure")
        await super()._project(event, context)
        self.projected.set()


class _ObligationEvent(DomainEvent):
    event_type: ClassVar[str] = "test.durable-obligation"


class _SubscriberModule:
    def __init__(self, module_id: str, calls: list[str], completed: asyncio.Event) -> None:
        self.manifest = ModuleManifest(
            module_id=module_id,
            name=module_id,
            publisher="businessos-tests",
            version="1.0.0",
            platform=">=0.1,<1",
            sdk=">=0.1,<1",
            entry_point="tests.integration.test_event_worker:_SubscriberModule",
        )
        self._calls = calls
        self._completed = completed

    async def register(self, registration: ModuleRegistration) -> None:
        registration.event(_ObligationEvent, "projection", self._consume)

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def _consume(
        self,
        event: _ObligationEvent,
        context: EventHandlingContext,
    ) -> None:
        self._calls.append(self.manifest.module_id)
        if len(self._calls) == 2:
            self._completed.set()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.providers
@pytest.mark.asyncio
async def test_event_worker_delivers_outbox_with_nats_redelivery_and_restart_idempotency(
    postgres_database: PostgreSQLTestDatabase,
    request: pytest.FixtureRequest,
) -> None:
    runtime_url = postgres_database.runtime_url
    operations_url = postgres_database.operations_url
    migration_modules = ModuleRegistry(platform_version="0.1.0", sdk_version="0.1.0")
    migration_modules.add(ProofModule())
    migrations = MigrationCoordinator(migration_modules)
    await migrations.upgrade_async(postgres_database.migration_url)
    endpoint = _required_env("BOS_TEST_S3_ENDPOINT")
    access_key = _required_env("BOS_TEST_S3_ACCESS_KEY")
    secret_key = _required_env("BOS_TEST_S3_SECRET_KEY")
    bucket = f"businessos-event-worker-{uuid4().hex}"
    s3_client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
    )
    s3_client.create_bucket(Bucket=bucket)

    def remove_bucket() -> None:
        listed = s3_client.list_objects_v2(Bucket=bucket)
        for item in listed.get("Contents", []):
            s3_client.delete_object(Bucket=bucket, Key=item["Key"])
        s3_client.delete_bucket(Bucket=bucket)

    request.addfinalizer(remove_bucket)
    tenant = TenantContext(uuid4(), uuid4(), uuid4(), authentication_strength="test")
    durable_name = f"businessos-test-{uuid4().hex}"
    worker_settings = EventWorkerSettings(
        runtime_database_url=runtime_url,
        operations_database_url=operations_url,
        nats_url=_required_env("BOS_TEST_NATS_URL"),
        installation_id=tenant.installation_id,
        principal_id=tenant.principal_id,
        permissions="example.phase1-proof.write,example.phase1-proof.read",
        durable_name=durable_name,
        publish_interval_seconds=0.02,
    )

    def storage() -> S3ObjectStorageProvider:
        return S3ObjectStorageProvider(
            bucket=bucket,
            endpoint_url=endpoint,
            region_name="us-east-1",
            access_key=access_key,
            secret_key=secret_key,
        )

    first_module = _RetryingProofModule()
    first_broker = NatsJetStreamPublisher((worker_settings.nats_url,))
    first_worker = create_event_worker(
        worker_settings,
        modules=(first_module,),
        broker=first_broker,
        object_storage=storage(),
    )
    await first_worker.start()
    await first_worker.readiness()
    assert first_worker.application.runtime is not None
    context = RequestContext(correlation_id="event-worker-e2e", tenant=tenant)
    command_id = uuid4()
    async with first_worker.application.container.request_scope() as dependencies:
        result = await first_worker.application.runtime.messages.command(
            StoreProof(command_id=command_id, value="durable"),
            context,
            dependencies,
        )
    assert result == {"stored": True}
    await asyncio.wait_for(first_module.projected.wait(), timeout=10.0)
    assert first_module.delivery_attempts == 2

    inspection_database = Database(
        first_worker.application.settings.model_copy(update={"database_url": runtime_url})
    )
    inspection_factory = SQLAlchemyUnitOfWorkFactory(inspection_database.sessions)
    async with inspection_factory.for_tenant(tenant) as unit_of_work:
        assert unit_of_work.session is not None
        outbox = (
            await unit_of_work.session.execute(
                select(
                    OutboxMessage.id,
                    OutboxMessage.tenant_id,
                    OutboxMessage.event_type,
                    OutboxMessage.schema_version,
                    OutboxMessage.correlation_id,
                    OutboxMessage.payload,
                    OutboxMessage.published_at,
                ).where(OutboxMessage.correlation_id == "event-worker-e2e")
            )
        ).one()
        receipts = (
            await unit_of_work.session.scalars(
                select(InboxReceipt).where(InboxReceipt.event_id == outbox.id)
            )
        ).all()
        description = await unit_of_work.session.scalar(
            select(PROOF_RECORDS.c.description).where(PROOF_RECORDS.c.command_id == command_id)
        )
    assert outbox.published_at is not None
    assert len(receipts) == 1
    assert description == "object-storage-projection"
    await first_worker.stop()

    second_module = _RetryingProofModule()
    second_broker = NatsJetStreamPublisher((worker_settings.nats_url,))
    second_worker = create_event_worker(
        worker_settings,
        modules=(second_module,),
        broker=second_broker,
        object_storage=storage(),
    )
    await second_worker.start()
    await second_broker.publish(
        f"businessos.events.tenant.{outbox.tenant_id}.{outbox.event_type}",
        json.dumps(outbox.payload, separators=(",", ":")).encode(),
        {
            "event-id": str(outbox.id),
            "event-type": outbox.event_type,
            "tenant-id": str(outbox.tenant_id),
            "schema-version": str(outbox.schema_version),
            "correlation-id": outbox.correlation_id,
        },
    )
    await asyncio.sleep(0.5)
    assert second_module.delivery_attempts == 0
    async with inspection_factory.for_tenant(tenant) as unit_of_work:
        assert unit_of_work.session is not None
        receipts_after_restart = (
            await unit_of_work.session.scalars(
                select(InboxReceipt).where(InboxReceipt.event_id == outbox.id)
            )
        ).all()
    assert len(receipts_after_restart) == 1

    assert second_worker.application.runtime is not None
    await second_worker.application.runtime.lifecycle.disable(second_module.manifest.module_id)
    deferred_event = ProofStored(
        tenant_id=tenant.tenant_id,
        correlation_id="event-worker-disabled-module",
        record_id=uuid4(),
        command_id=uuid4(),
        value="deliver-after-reenable",
    )
    async with inspection_factory.for_tenant(tenant) as unit_of_work:
        unit_of_work.add_outbox(deferred_event.to_outbox())
        await unit_of_work.commit()
    await asyncio.sleep(0.5)
    assert second_module.delivery_attempts == 0
    async with inspection_factory.for_tenant(tenant) as unit_of_work:
        assert unit_of_work.session is not None
        receipts_while_disabled = (
            await unit_of_work.session.scalars(
                select(InboxReceipt).where(InboxReceipt.event_id == deferred_event.event_id)
            )
        ).all()
    assert receipts_while_disabled == []

    await second_worker.application.runtime.lifecycle.enable(second_module.manifest.module_id)
    await asyncio.wait_for(second_module.projected.wait(), timeout=10.0)
    assert second_module.delivery_attempts == 2
    async with inspection_factory.for_tenant(tenant) as unit_of_work:
        assert unit_of_work.session is not None
        deferred_receipts = (
            await unit_of_work.session.scalars(
                select(InboxReceipt).where(InboxReceipt.event_id == deferred_event.event_id)
            )
        ).all()
    assert len(deferred_receipts) == 1
    await second_worker.stop()
    await inspection_database.close()

    await migrations.downgrade_async(postgres_database.migration_url)


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.providers
@pytest.mark.asyncio
async def test_subscriber_obligations_survive_worker_recreation(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    migrations = MigrationCoordinator(ModuleRegistry(platform_version="0.1.0", sdk_version="0.1.0"))
    await migrations.upgrade_async(postgres_database.migration_url)
    tenant = TenantContext(uuid4(), uuid4(), uuid4(), authentication_strength="test")
    durable_name = f"businessos-obligations-{uuid4().hex}"
    settings = EventWorkerSettings(
        runtime_database_url=postgres_database.runtime_url,
        operations_database_url=postgres_database.operations_url,
        nats_url=_required_env("BOS_TEST_NATS_URL"),
        installation_id=tenant.installation_id,
        principal_id=tenant.principal_id,
        durable_name=durable_name,
        publish_interval_seconds=0.02,
    )
    calls: list[str] = []
    completed = asyncio.Event()

    first_worker = create_event_worker(
        settings,
        modules=(
            _SubscriberModule("example.obligation-a", calls, completed),
            _SubscriberModule("example.obligation-b", calls, completed),
        ),
        broker=NatsJetStreamPublisher((settings.nats_url,)),
    )
    await first_worker.start()
    await first_worker.stop()

    second_broker = NatsJetStreamPublisher((settings.nats_url,))
    second_worker = create_event_worker(
        settings,
        modules=(_SubscriberModule("example.obligation-a", calls, completed),),
        broker=second_broker,
    )
    await second_worker.start()
    assert second_worker.application.runtime is not None
    event = _ObligationEvent(
        tenant_id=tenant.tenant_id,
        correlation_id="durable-obligation-restart",
    )
    with pytest.raises(DeliveryUnavailableError):
        second_worker.application.runtime.events.delivery_subscribers(event)
    await second_broker.publish(
        f"businessos.events.tenant.{tenant.tenant_id}.{event.event_type}",
        event.model_dump_json().encode(),
        {
            "event-id": str(event.event_id),
            "event-type": event.event_type,
            "tenant-id": str(event.tenant_id),
            "schema-version": str(event.schema_version),
            "correlation-id": event.correlation_id,
        },
    )
    await asyncio.sleep(0.3)
    assert calls == []
    await second_worker.stop()

    third_worker = create_event_worker(
        settings,
        modules=(
            _SubscriberModule("example.obligation-a", calls, completed),
            _SubscriberModule("example.obligation-b", calls, completed),
        ),
        broker=NatsJetStreamPublisher((settings.nats_url,)),
    )
    await third_worker.start()
    await asyncio.wait_for(completed.wait(), timeout=10.0)
    assert calls == ["example.obligation-a", "example.obligation-b"]

    inspection = Database(Settings(database_url=postgres_database.operations_url))
    inspection_factory = SQLAlchemyUnitOfWorkFactory(
        inspection.sessions,
        system_sessions=inspection.sessions,
    )
    async with inspection_factory.system() as unit_of_work:
        assert unit_of_work.session is not None
        obligations = (
            await unit_of_work.session.scalars(
                select(EventSubscriberObligation).where(
                    EventSubscriberObligation.event_type == event.event_type
                )
            )
        ).all()
        obligation_identities = {(item.subscriber, item.owner) for item in obligations}
    assert obligation_identities == {
        ("example.obligation-a.projection", "example.obligation-a"),
        ("example.obligation-b.projection", "example.obligation-b"),
    }
    runtime_inspection = Database(Settings(database_url=postgres_database.runtime_url))
    runtime_factory = SQLAlchemyUnitOfWorkFactory(runtime_inspection.sessions)
    async with runtime_factory.for_tenant(tenant) as unit_of_work:
        assert unit_of_work.session is not None
        receipts = (
            await unit_of_work.session.scalars(
                select(InboxReceipt).where(InboxReceipt.event_id == event.event_id)
            )
        ).all()
    assert len(receipts) == 2
    await third_worker.stop()
    await inspection.close()
    await runtime_inspection.close()
    await migrations.downgrade_async(postgres_database.migration_url)


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_worker_stop_retains_real_uow_cleanup_until_backend_closes(
    postgres_database: PostgreSQLTestDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = EventWorkerSettings(
        runtime_database_url=postgres_database.runtime_url,
        operations_database_url=postgres_database.operations_url,
        installation_id=uuid4(),
        principal_id=uuid4(),
        shutdown_timeout_seconds=0.02,
    )
    worker = create_event_worker(
        settings,
        modules=(),
        broker=NatsJetStreamPublisher(("nats://unused",)),
    )
    session = worker._operations_database.sessions()
    original_rollback = session.rollback
    publisher_entered = asyncio.Event()
    rollback_entered = asyncio.Event()
    rollback_release = asyncio.Event()
    backend_pid: int | None = None

    async def delayed_rollback() -> None:
        rollback_entered.set()
        await rollback_release.wait()
        await original_rollback()

    monkeypatch.setattr(session, "rollback", delayed_rollback)
    factory = SQLAlchemyUnitOfWorkFactory(
        lambda: session,
        system_sessions=lambda: session,
    )

    async def publisher_with_transaction() -> None:
        nonlocal backend_pid
        async with factory.system() as unit_of_work:
            assert unit_of_work.session is not None
            backend_pid = await unit_of_work.session.scalar(text("SELECT pg_backend_pid()"))
            publisher_entered.set()
            await asyncio.Event().wait()

    publisher = asyncio.create_task(
        publisher_with_transaction(),
        name="real-uow-publisher",
    )
    worker._publisher_task = publisher
    worker._started = True
    await publisher_entered.wait()
    stopping = asyncio.create_task(worker.stop())
    await rollback_entered.wait()
    for _ in range(3):
        stopping.cancel()
        await asyncio.sleep(0)
    try:
        await asyncio.sleep(0.05)
        assert not stopping.done()
        assert not publisher.done()
        assert backend_pid is not None
        with psycopg.connect(postgres_database.administrator_url) as connection:
            backend_state = connection.execute(
                "SELECT state FROM pg_stat_activity WHERE pid = %s",
                (backend_pid,),
            ).fetchone()
        assert backend_state == ("idle in transaction",)
    finally:
        rollback_release.set()

    with pytest.raises(BaseExceptionGroup, match="Event worker cleanup failed"):
        await asyncio.wait_for(stopping, timeout=1.0)
    assert stopping.cancelling() == 0
    assert not stopping.cancelled()
    assert publisher.done()
    assert worker._publisher_task is None
    with psycopg.connect(postgres_database.administrator_url) as connection:
        backend_count = connection.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE pid = %s",
            (backend_pid,),
        ).fetchone()
    assert backend_count == (0,)
