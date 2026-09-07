import asyncio
import json
import os
from uuid import uuid4

import boto3
import pytest
from businessos_proof.module import PROOF_RECORDS, ProofModule, ProofStored, StoreProof
from sqlalchemy import select

from businessos.context import RequestContext, TenantContext
from businessos.event_worker import EventWorkerSettings, create_event_worker
from businessos.messages import EventHandlingContext
from businessos.migrations import MigrationCoordinator
from businessos.modules import ModuleRegistry
from businessos.persistence import (
    Database,
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
