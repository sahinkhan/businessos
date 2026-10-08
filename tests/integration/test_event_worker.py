import asyncio
import hashlib
import json
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import ClassVar, Protocol
from uuid import UUID, uuid4

import boto3
import psycopg
import pytest
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from businessos_data_governance import (
    DestructiveCleanupRequestedV2,
    ExecuteDestructiveLifecycleV2,
    ExpiryAction,
    RecordDestructiveCleanupResultV2,
    RetentionSubjectKey,
    SetRetentionPolicyV2,
)
from businessos_identity import IdentityModule, PrincipalIdentity
from businessos_identity.principal_binding import bind_authenticated_principal
from businessos_proof.module import PROOF_RECORDS, ProofModule, ProofStored, StoreProof
from businessos_tenant import TenantModule
from sqlalchemy import insert, select, text

from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.context import RequestContext, TenantContext, bind_request_context
from businessos.errors import BusinessOSError, DeliveryUnavailableError
from businessos.event_worker import EventWorkerSettings, create_event_worker
from businessos.messages import Command, DomainEvent, EventHandlingContext
from businessos.migrations import MigrationCoordinator
from businessos.modules import ModuleManifest, ModuleRegistration, ModuleRegistry, discover_modules
from businessos.modules.installation_inventory import approved_artifacts_from_operator_inventory
from businessos.permissions import PermissionDeclaration
from businessos.persistence import (
    Database,
    EventSubscriberObligation,
    InboxReceipt,
    OutboxMessage,
    SQLAlchemyUnitOfWorkFactory,
)
from businessos.providers import BrokerEvent, NatsJetStreamPublisher, S3ObjectStorageProvider
from businessos.security import Authorizer
from tests.conftest import PostgreSQLTestDatabase


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None:
        pytest.skip(f"{name} is not configured")
    return value


async def _provision_workload(database_url: str, installation_id: UUID, secret_path: Path) -> UUID:
    credential = os.urandom(48)
    await asyncio.to_thread(secret_path.write_bytes, credential)
    workload_id = uuid4()
    database = Database(Settings(database_url=database_url))
    factory = SQLAlchemyUnitOfWorkFactory(database.sessions, system_sessions=database.sessions)
    try:
        async with factory.system() as unit:
            await unit.persistence.execute(
                text(
                    "INSERT INTO platform_identity.installation_workloads "
                    "(installation_id, workload_id, name, process_class, allowed_purposes, "
                    "credential_reference, credential_digest, credential_generation) "
                    "VALUES (:installation, :workload, 'integration-worker', 'event-worker', "
                    "ARRAY['worker-startup','subscriber-sync','event-publisher','event-delivery'], "
                    "'integration-file-v1', :digest, 1)"
                ),
                {
                    "installation": installation_id,
                    "workload": workload_id,
                    "digest": hashlib.sha256(credential).digest(),
                },
            )
            await unit.commit()
    finally:
        await database.close()
    return workload_id


async def _remove_workload(database_url: str, installation_id: UUID, workload_id: UUID) -> None:
    database = Database(Settings(database_url=database_url))
    factory = SQLAlchemyUnitOfWorkFactory(database.sessions, system_sessions=database.sessions)
    try:
        async with factory.system() as unit:
            await unit.persistence.execute(
                text(
                    "DELETE FROM platform_identity.installation_workloads "
                    "WHERE installation_id=:installation AND workload_id=:workload"
                ),
                {"installation": installation_id, "workload": workload_id},
            )
            await unit.commit()
    finally:
        await database.close()


class _WorkerLifecycle(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...


@asynccontextmanager
async def _running_worker(worker: _WorkerLifecycle) -> AsyncGenerator[None]:
    await worker.start()
    try:
        yield
    finally:
        await worker.stop()


async def _inbox_receipts(
    factory: SQLAlchemyUnitOfWorkFactory,
    tenant: TenantContext,
    event_id: UUID,
) -> list[InboxReceipt]:
    async with factory.for_tenant(tenant) as unit_of_work:
        assert unit_of_work.session is not None
        return list(
            (
                await unit_of_work.session.scalars(
                    select(InboxReceipt).where(InboxReceipt.event_id == event_id)
                )
            ).all()
        )


async def _wait_for_inbox_receipt_count(
    factory: SQLAlchemyUnitOfWorkFactory,
    tenant: TenantContext,
    event_id: UUID,
    *,
    expected: int,
    timeout_seconds: float = 10.0,
    poll_interval: float = 0.02,
) -> list[InboxReceipt]:
    deadline = monotonic() + timeout_seconds
    while True:
        receipts = await _inbox_receipts(factory, tenant, event_id)
        actual = len(receipts)
        if actual == expected:
            return receipts
        if actual > expected:
            raise AssertionError(
                f"inbox receipt count exceeded expected state: expected={expected}, actual={actual}"
            )
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise AssertionError(
                "timed out waiting for committed inbox receipts: "
                f"event_id={event_id}, expected={expected}, actual={actual}"
            )
        await asyncio.sleep(min(poll_interval, remaining))


@pytest.mark.asyncio
async def test_running_worker_stops_when_test_body_raises() -> None:
    class LifecycleProbe:
        def __init__(self) -> None:
            self.started = 0
            self.stopped = 0

        async def start(self) -> None:
            self.started += 1

        async def stop(self) -> None:
            self.stopped += 1

    worker = LifecycleProbe()
    with pytest.raises(AssertionError, match="forced test-body failure"):
        async with _running_worker(worker):
            assert worker.started == 1
            raise AssertionError("forced test-body failure")
    assert worker.stopped == 1


class _AllowEveryPermission:
    async def is_allowed(self, principal_id: UUID, tenant: TenantContext, permission: str) -> bool:
        return True


class _ObligationEvent(DomainEvent):
    event_type: ClassVar[str] = "test.durable-obligation"


class _SubscriberModule:
    def __init__(
        self, module_id: str, calls: list[str], completed: asyncio.Event, event_id: UUID
    ) -> None:
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
        self._event_id = event_id

    async def register(self, registration: ModuleRegistration) -> None:
        permission = f"{self.manifest.module_id}.consume"
        registration.permission(
            PermissionDeclaration(key=permission, description="Consume obligation")
        )
        registration.event(_ObligationEvent, "projection", self._consume, permission=permission)

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def _consume(
        self,
        event: _ObligationEvent,
        context: EventHandlingContext,
    ) -> None:
        if event.event_id != self._event_id:
            return
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
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delivery_attempts: dict[ProofModule, int] = {}
    projected: dict[ProofModule, asyncio.Event] = {}
    original_project = ProofModule._project

    async def retry_project(
        self: ProofModule, event: ProofStored, context: EventHandlingContext
    ) -> None:
        delivery_attempts[self] += 1
        if delivery_attempts[self] == 1:
            raise RuntimeError("deterministic first delivery failure")
        await original_project(self, event, context)
        projected[self].set()

    monkeypatch.setattr(ProofModule, "_project", retry_project)
    runtime_url = postgres_database.worker_url
    operations_url = postgres_database.operations_url
    migration_candidates = (TenantModule(), IdentityModule(), ProofModule())
    migration_modules = ModuleRegistry(
        platform_version="0.1.0",
        sdk_version="0.1.0",
        approved_artifacts=approved_artifacts_from_operator_inventory(migration_candidates),
    )
    for module in migration_candidates:
        migration_modules.add(module)
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
    credential_file = tmp_path / "workload-secret"
    workload_id = await _provision_workload(operations_url, tenant.installation_id, credential_file)
    durable_name = f"businessos-test-{uuid4().hex}"
    worker_settings = EventWorkerSettings(
        runtime_database_url=runtime_url,
        operations_database_url=operations_url,
        nats_url=_required_env("BOS_TEST_NATS_URL"),
        installation_id=tenant.installation_id,
        principal_id=tenant.principal_id,
        workload_id=workload_id,
        workload_credential_reference="integration-file-v1",
        workload_credential_file=credential_file,
        permissions="example.phase1-proof.write,example.phase1-proof.read,example.obligation-a.consume,example.obligation-b.consume,foundation.tenant.manage",
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

    first_module = ProofModule()
    delivery_attempts[first_module] = 0
    projected[first_module] = asyncio.Event()
    first_broker = NatsJetStreamPublisher((worker_settings.nats_url,))
    first_worker = create_event_worker(
        worker_settings,
        modules=(TenantModule(), IdentityModule(), first_module),
        broker=first_broker,
        object_storage=storage(),
    )
    await first_worker.start()
    await first_worker.readiness()
    assert first_worker.application.runtime is not None
    command_id = uuid4()
    record_id = uuid4()
    source_database = Database(Settings(database_url=runtime_url))
    source_factory = SQLAlchemyUnitOfWorkFactory(source_database.sessions)
    async with source_factory.for_tenant(tenant) as unit_of_work:
        await unit_of_work.persistence.execute(
            insert(PROOF_RECORDS).values(
                id=record_id,
                tenant_id=tenant.tenant_id,
                command_id=command_id,
                value="durable",
            )
        )
        unit_of_work.add_outbox(
            ProofStored(
                tenant_id=tenant.tenant_id,
                correlation_id="event-worker-e2e",
                record_id=record_id,
                command_id=command_id,
                value="durable",
            ).to_outbox()
        )
        await unit_of_work.commit()
    await source_database.close()
    await asyncio.wait_for(projected[first_module].wait(), timeout=10.0)
    assert delivery_attempts[first_module] == 2

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
    assert outbox.published_at is not None
    receipts = await _wait_for_inbox_receipt_count(
        inspection_factory, tenant, outbox.id, expected=1
    )
    assert len(receipts) == 1
    async with inspection_factory.for_tenant(tenant) as unit_of_work:
        assert unit_of_work.session is not None
        description = await unit_of_work.session.scalar(
            select(PROOF_RECORDS.c.description).where(PROOF_RECORDS.c.command_id == command_id)
        )
    assert description == "object-storage-projection"

    # One verified installation worker also processes another tenant through
    # a separate event, binding, inbox receipt and RLS-scoped transaction.
    tenant_b = TenantContext(
        tenant.installation_id, uuid4(), tenant.principal_id, authentication_strength="test"
    )
    command_b, record_b = uuid4(), uuid4()
    event_b = ProofStored(
        tenant_id=tenant_b.tenant_id,
        correlation_id="event-worker-tenant-b",
        record_id=record_b,
        command_id=command_b,
        value="tenant-b",
    )
    async with inspection_factory.for_tenant(tenant_b) as unit_of_work:
        await unit_of_work.persistence.execute(
            insert(PROOF_RECORDS).values(
                id=record_b,
                tenant_id=tenant_b.tenant_id,
                command_id=command_b,
                value="tenant-b",
            )
        )
        unit_of_work.add_outbox(event_b.to_outbox())
        await unit_of_work.commit()
    assert (
        len(
            await _wait_for_inbox_receipt_count(
                inspection_factory, tenant_b, event_b.event_id, expected=1
            )
        )
        == 1
    )
    async with inspection_factory.for_tenant(tenant_b) as unit_of_work:
        result = await unit_of_work.persistence.execute(
            select(PROOF_RECORDS.c.description).where(PROOF_RECORDS.c.command_id == command_b)
        )
        assert result.scalar_one() == "object-storage-projection"
        result = await unit_of_work.persistence.execute(
            select(PROOF_RECORDS.c.id).where(PROOF_RECORDS.c.command_id == command_id)
        )
        assert result.scalar_one_or_none() is None
    async with inspection_factory.for_tenant(tenant) as unit_of_work:
        result = await unit_of_work.persistence.execute(
            select(PROOF_RECORDS.c.id).where(PROOF_RECORDS.c.command_id == command_b)
        )
        assert result.scalar_one_or_none() is None
    await first_worker.stop()

    second_module = ProofModule()
    delivery_attempts[second_module] = 0
    projected[second_module] = asyncio.Event()
    second_broker = NatsJetStreamPublisher((worker_settings.nats_url,))
    second_worker = create_event_worker(
        worker_settings,
        modules=(TenantModule(), IdentityModule(), second_module),
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
    assert delivery_attempts[second_module] == 0
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
    assert delivery_attempts[second_module] == 0
    async with inspection_factory.for_tenant(tenant) as unit_of_work:
        assert unit_of_work.session is not None
        receipts_while_disabled = (
            await unit_of_work.session.scalars(
                select(InboxReceipt).where(InboxReceipt.event_id == deferred_event.event_id)
            )
        ).all()
    assert receipts_while_disabled == []

    await second_worker.application.runtime.lifecycle.enable(second_module.manifest.module_id)
    await asyncio.wait_for(projected[second_module].wait(), timeout=10.0)
    assert delivery_attempts[second_module] == 2
    deferred_receipts = await _wait_for_inbox_receipt_count(
        inspection_factory, tenant, deferred_event.event_id, expected=1
    )
    assert len(deferred_receipts) == 1
    await second_worker.stop()
    await inspection_database.close()

    await _remove_workload(postgres_database.migration_url, tenant.installation_id, workload_id)
    with pytest.raises(RuntimeError, match="proof_0004 downgrade refused"):
        await migrations.downgrade_async(postgres_database.migration_url)


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.providers
@pytest.mark.asyncio
async def test_subscriber_obligations_survive_worker_recreation(
    postgres_database: PostgreSQLTestDatabase,
    tmp_path: Path,
) -> None:
    migration_modules = ModuleRegistry(platform_version="0.1.0", sdk_version="0.1.0")
    migration_modules.add(TenantModule())
    migration_modules.add(IdentityModule())
    migrations = MigrationCoordinator(migration_modules)
    await migrations.upgrade_async(postgres_database.migration_url)
    inspection: Database | None = None
    runtime_inspection: Database | None = None
    try:
        tenant = TenantContext(uuid4(), uuid4(), uuid4(), authentication_strength="test")
        credential_file = tmp_path / "workload-secret"
        workload_id = await _provision_workload(
            postgres_database.operations_url, tenant.installation_id, credential_file
        )
        durable_name = f"businessos-obligations-{uuid4().hex}"
        settings = EventWorkerSettings(
            runtime_database_url=postgres_database.worker_url,
            operations_database_url=postgres_database.operations_url,
            nats_url=_required_env("BOS_TEST_NATS_URL"),
            installation_id=tenant.installation_id,
            principal_id=tenant.principal_id,
            workload_id=workload_id,
            workload_credential_reference="integration-file-v1",
            workload_credential_file=credential_file,
            permissions="example.obligation-a.consume,example.obligation-b.consume,foundation.tenant.manage",
            durable_name=durable_name,
            publish_interval_seconds=0.02,
        )
        calls: list[str] = []
        completed = asyncio.Event()
        event = _ObligationEvent(
            tenant_id=tenant.tenant_id,
            correlation_id="durable-obligation-restart",
        )

        first_worker = create_event_worker(
            settings,
            modules=(
                TenantModule(),
                IdentityModule(),
                _SubscriberModule("example.obligation-a", calls, completed, event.event_id),
                _SubscriberModule("example.obligation-b", calls, completed, event.event_id),
            ),
            broker=NatsJetStreamPublisher((settings.nats_url,)),
        )
        async with _running_worker(first_worker):
            pass

        source_database = Database(Settings(database_url=postgres_database.runtime_url))
        try:
            source_factory = SQLAlchemyUnitOfWorkFactory(source_database.sessions)
            async with source_factory.for_tenant(tenant) as unit:
                unit.add_outbox(event.to_outbox())
                await unit.commit()
        finally:
            await source_database.close()

        second_broker = NatsJetStreamPublisher((settings.nats_url,))
        second_worker = create_event_worker(
            settings,
            modules=(
                TenantModule(),
                IdentityModule(),
                _SubscriberModule("example.obligation-a", calls, completed, event.event_id),
            ),
            broker=second_broker,
        )
        subject = f"businessos.events.tenant.{tenant.tenant_id}.{event.event_type}"
        headers = {
            "event-id": str(event.event_id),
            "event-type": event.event_type,
            "tenant-id": str(event.tenant_id),
            "schema-version": str(event.schema_version),
            "correlation-id": event.correlation_id,
        }
        async with _running_worker(second_worker):
            assert second_worker.application.runtime is not None
            with pytest.raises(DeliveryUnavailableError):
                second_worker.application.runtime.events.delivery_subscribers(event)
            await second_broker.publish(subject, event.model_dump_json().encode(), headers)
            await asyncio.sleep(0.3)
            assert calls == []

        inspection = Database(Settings(database_url=postgres_database.operations_url))
        inspection_factory = SQLAlchemyUnitOfWorkFactory(
            inspection.sessions,
            system_sessions=inspection.sessions,
        )
        runtime_inspection = Database(Settings(database_url=postgres_database.runtime_url))
        runtime_factory = SQLAlchemyUnitOfWorkFactory(runtime_inspection.sessions)
        third_broker = NatsJetStreamPublisher((settings.nats_url,))
        third_worker = create_event_worker(
            settings,
            modules=(
                TenantModule(),
                IdentityModule(),
                _SubscriberModule("example.obligation-a", calls, completed, event.event_id),
                _SubscriberModule("example.obligation-b", calls, completed, event.event_id),
            ),
            broker=third_broker,
        )
        async with _running_worker(third_worker):
            await asyncio.wait_for(completed.wait(), timeout=10.0)
            assert calls == ["example.obligation-a", "example.obligation-b"]

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

            receipts = await _wait_for_inbox_receipt_count(
                runtime_factory,
                tenant,
                event.event_id,
                expected=2,
            )
            assert len(receipts) == 2
            await third_broker.publish(subject, event.model_dump_json().encode(), headers)

        assert calls == ["example.obligation-a", "example.obligation-b"]
        assert len(await _inbox_receipts(runtime_factory, tenant, event.event_id)) == 2
    finally:
        if runtime_inspection is not None:
            await runtime_inspection.close()
        if inspection is not None:
            await inspection.close()
        await _remove_workload(postgres_database.migration_url, tenant.installation_id, workload_id)
        await migrations.downgrade_async(postgres_database.migration_url)


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_worker_stop_retains_real_uow_cleanup_until_backend_closes(
    postgres_database: PostgreSQLTestDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = EventWorkerSettings(
        runtime_database_url=postgres_database.worker_url,
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


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.providers
@pytest.mark.asyncio
@pytest.mark.parametrize("survivor", (False, True))
@pytest.mark.parametrize("versioned", (False, True))
async def test_adr017_committed_cleanup_retries_and_marks_completed_after_s3_erasure(
    postgres_database: PostgreSQLTestDatabase,
    request: pytest.FixtureRequest,
    tmp_path: Path,
    survivor: bool,
    versioned: bool,
) -> None:
    endpoint = _required_env("BOS_TEST_S3_ENDPOINT")
    access_key = _required_env("BOS_TEST_S3_ACCESS_KEY")
    secret_key = _required_env("BOS_TEST_S3_SECRET_KEY")
    nats_url = _required_env("BOS_TEST_NATS_URL")
    bucket = f"businessos-adr017-cleanup-{uuid4().hex}"
    s3_client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="us-east-1",
    )
    s3_client.create_bucket(Bucket=bucket)
    if versioned:
        s3_client.put_bucket_versioning(
            Bucket=bucket, VersioningConfiguration={"Status": "Enabled"}
        )

    def remove_bucket() -> None:
        listed = s3_client.list_object_versions(Bucket=bucket)
        for group in ("Versions", "DeleteMarkers"):
            for item in listed.get(group, []):
                s3_client.delete_object(Bucket=bucket, Key=item["Key"], VersionId=item["VersionId"])
        s3_client.delete_bucket(Bucket=bucket)

    request.addfinalizer(remove_bucket)
    tenant = TenantContext(uuid4(), uuid4(), uuid4(), authentication_strength="mfa")
    credential_file = tmp_path / "adr017-workload-secret"
    modules = tuple(discover_modules())
    source_app = create_application(
        Settings(
            environment="test",
            database_url=postgres_database.runtime_url,
            governance_database_url=postgres_database.governance_url,
            metadata_database_url=postgres_database.metadata_url,
            ui_publication_database_url=postgres_database.ui_publication_url,
        ),
        modules=modules,
        approved_module_artifacts=approved_artifacts_from_operator_inventory(modules),
        resource_coordinator_ids=frozenset({"foundation.data_governance"}),
        authorizer=Authorizer(_AllowEveryPermission()),
        infrastructure_providers={
            "object-storage": S3ObjectStorageProvider(
                bucket=bucket,
                endpoint_url=endpoint,
                access_key=access_key,
                secret_key=secret_key,
                region_name="us-east-1",
            )
        },
    )
    assert source_app.runtime is not None
    source_app.runtime.migrations.upgrade(postgres_database.migration_url)
    await source_app.startup()
    workload_id = await _provision_workload(
        postgres_database.operations_url, tenant.installation_id, credential_file
    )
    settings = EventWorkerSettings(
        runtime_database_url=postgres_database.worker_url,
        operations_database_url=postgres_database.operations_url,
        governance_database_url=postgres_database.governance_url,
        metadata_database_url=postgres_database.metadata_url,
        nats_url=nats_url,
        installation_id=tenant.installation_id,
        principal_id=tenant.principal_id,
        workload_id=workload_id,
        workload_credential_reference="integration-file-v1",
        workload_credential_file=credential_file,
        permissions=(
            "example.phase1-proof.write,example.phase1-proof.cleanup,"
            "foundation.governance.cleanup.report"
        ),
        durable_name=f"businessos-adr017-{uuid4().hex}",
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

    async def dispatch(command: Command, context: RequestContext) -> object:
        assert source_app.runtime is not None
        async with source_app.container.request_scope() as dependencies:
            return await source_app.runtime.messages.command(command, context, dependencies)

    context = RequestContext(tenant=tenant)
    bind_authenticated_principal(
        context,
        PrincipalIdentity(
            tenant_id=tenant.tenant_id,
            principal_id=tenant.principal_id,
            principal_type="user",
            authentication_strength="mfa",
        ),
    )
    first_worker = create_event_worker(settings, modules=modules, object_storage=storage())
    try:
        await first_worker.start()
        command_id = uuid4()
        assert await dispatch(StoreProof(command_id=command_id, value="erase-me"), context) == {
            "stored": True
        }
        with psycopg.connect(postgres_database.administrator_url) as admin:
            record_row = admin.execute(
                "SELECT id FROM mod_example_phase1_proof.proof_records WHERE command_id = %s",
                (command_id,),
            ).fetchone()
            assert record_row is not None
            record_id = record_row[0]
        record_key = f"tenant/{tenant.tenant_id}/phase1-proof/records/{record_id}.txt"
        shared_key = f"tenant/{tenant.tenant_id}/phase1-proof/value.txt"

        async def wait_for_object() -> None:
            deadline = monotonic() + 15
            while monotonic() < deadline:
                if any(
                    item["Key"] == record_key
                    for item in s3_client.list_objects_v2(Bucket=bucket).get("Contents", [])
                ):
                    return
                await asyncio.sleep(0.05)
            raise AssertionError("proof record projection was not delivered")

        await wait_for_object()
        surviving_key: str | None = None
        if survivor:
            surviving_command_id = uuid4()
            assert await dispatch(
                StoreProof(command_id=surviving_command_id, value="keep-me"), context
            ) == {"stored": True}
            with psycopg.connect(postgres_database.administrator_url) as admin:
                surviving_row = admin.execute(
                    "SELECT id FROM mod_example_phase1_proof.proof_records WHERE command_id = %s",
                    (surviving_command_id,),
                ).fetchone()
                assert surviving_row is not None
                surviving_record_id = surviving_row[0]
            surviving_key = (
                f"tenant/{tenant.tenant_id}/phase1-proof/records/{surviving_record_id}.txt"
            )
            deadline = monotonic() + 15
            while True:
                keys = {
                    item["Key"]
                    for item in s3_client.list_objects_v2(Bucket=bucket).get("Contents", [])
                }
                if surviving_key in keys:
                    break
                if monotonic() >= deadline:
                    raise AssertionError("surviving proof projection was not delivered")
                await asyncio.sleep(0.05)
        await first_worker.stop()
        old_versions: dict[str, list[str]] = {}
        if versioned:
            for key in (record_key, shared_key):
                # Multiple prior plaintext generations must be physically erased.
                body = b"keep-me" if key == shared_key and survivor else b"erase-me"
                s3_client.put_object(Bucket=bucket, Key=key, Body=body)
                s3_client.put_object(Bucket=bucket, Key=key, Body=body)
                old_versions[key] = [
                    item["VersionId"]
                    for item in s3_client.list_object_versions(Bucket=bucket, Prefix=key)[
                        "Versions"
                    ]
                    if item["Key"] == key
                ]
        with psycopg.connect(postgres_database.administrator_url) as admin:
            admin.execute(
                "UPDATE mod_example_phase1_proof.proof_records "
                "SET retention_anchor_at = %s WHERE id = %s",
                (datetime.now(UTC) - timedelta(days=2), record_id),
            )
            admin.commit()
        await dispatch(
            SetRetentionPolicyV2(
                tenant_id=tenant.tenant_id,
                owner_module_id="example.phase1-proof",
                resource_namespace="example.phase1-proof.proof-record",
                contract_version="1",
                entity_type="proof_record",
                retention_category="proof",
                retention_period_days=1,
                action_on_expiry=ExpiryAction.PURGE,
                valid_from=datetime.now(UTC) - timedelta(days=1),
            ),
            context,
        )
        decision_id = await dispatch(
            ExecuteDestructiveLifecycleV2(
                subject=RetentionSubjectKey(
                    tenant_id=tenant.tenant_id,
                    owner_module_id="example.phase1-proof",
                    resource_namespace="example.phase1-proof.proof-record",
                    contract_version="1",
                    entity_type="proof_record",
                    record_id=record_id,
                ),
                action=ExpiryAction.PURGE,
            ),
            context,
        )
        with psycopg.connect(postgres_database.administrator_url) as admin:
            assert admin.execute(
                "SELECT external_cleanup_status FROM platform_gov.destructive_decisions_v2 "
                "WHERE id = %s",
                (decision_id,),
            ).fetchone() == ("pending",)
        with bind_request_context(context):
            assert (
                await storage().get(tenant.tenant_id, ProofModule.record_object_key(record_id))
                == b"erase-me"
            )
            assert await storage().get(tenant.tenant_id, "phase1-proof/value.txt") == (
                b"keep-me" if survivor else b"erase-me"
            )
        with psycopg.connect(
            postgres_database.worker_url.replace("postgresql+psycopg://", "postgresql://", 1)
        ) as worker_connection:
            worker_connection.execute(
                "SELECT set_config('app.tenant_id', %s, true)", (str(tenant.tenant_id),)
            )
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                worker_connection.execute(
                    "UPDATE platform_gov.destructive_decisions_v2 "
                    "SET external_cleanup_status = 'completed' WHERE id = %s",
                    (decision_id,),
                )
        # A same-tenant caller can commit an outbox event. Its existence must
        # not grant authority over another record or this protected decision.
        forged_record = uuid4()
        forged_key = f"tenant/{tenant.tenant_id}/phase1-proof/records/{forged_record}.txt"
        with psycopg.connect(postgres_database.administrator_url) as admin:
            admin.execute(
                "INSERT INTO mod_example_phase1_proof.proof_records "
                "(id, tenant_id, command_id, value, lifecycle) "
                "VALUES (%s, %s, %s, '', 'purged')",
                (forged_record, tenant.tenant_id, uuid4()),
            )
            admin.commit()
        s3_client.put_object(Bucket=bucket, Key=forged_key, Body=b"unrelated-secret")
        forged = DestructiveCleanupRequestedV2(
            tenant_id=tenant.tenant_id,
            correlation_id="committed-forgery",
            decision_id=decision_id,
            owner_module_id="example.phase1-proof",
            resource_namespace="example.phase1-proof.proof-record",
            contract_version="1",
            entity_type="proof_record",
            record_id=forged_record,
            action=ExpiryAction.PURGE,
        )
        forged_database = Database(Settings(database_url=postgres_database.runtime_url))
        try:
            forged_factory = SQLAlchemyUnitOfWorkFactory(forged_database.sessions)
            async with forged_factory.for_tenant(tenant) as unit:
                unit.add_outbox(forged.to_outbox())
                await unit.commit()
        finally:
            await forged_database.close()
        with psycopg.connect(postgres_database.administrator_url) as admin:
            admin.execute(
                "UPDATE eventing.outbox_messages SET published_at = now() WHERE id = %s",
                (forged.event_id,),
            )
            admin.commit()

        failed = asyncio.Event()
        retry_started = asyncio.Event()
        permit_retry = asyncio.Event()

        class FlakyDeleteStorage(S3ObjectStorageProvider):
            attempts = 0

            async def compare_and_reconcile(
                self,
                tenant_id: UUID,
                key: str,
                expected_version: str | None,
                content: bytes | None,
            ) -> bool:
                if (
                    not versioned
                    and key == ProofModule.record_object_key(record_id)
                    and content is None
                ):
                    self.attempts += 1
                    if self.attempts == 1:
                        failed.set()
                        raise RuntimeError("deterministic S3 deletion failure")
                    retry_started.set()
                    await permit_retry.wait()
                return await super().compare_and_reconcile(
                    tenant_id, key, expected_version, content
                )

            async def erase_prior_versions(
                self, tenant_id: UUID, key: str, expected_version: str
            ) -> None:
                if versioned and key == ProofModule.record_object_key(record_id):
                    self.attempts += 1
                    if self.attempts == 1:
                        # One real version is erased, then a later deletion fails.
                        versions = self._client.list_object_versions(
                            Bucket=bucket, Prefix=self._key(tenant_id, key)
                        )["Versions"]
                        older = next(item for item in versions if not item["IsLatest"])
                        self._client.delete_object(
                            Bucket=bucket, Key=older["Key"], VersionId=older["VersionId"]
                        )
                        failed.set()
                        raise RuntimeError("deterministic historical version deletion failure")
                    retry_started.set()
                    await permit_retry.wait()
                await super().erase_prior_versions(tenant_id, key, expected_version)

        flaky_storage = FlakyDeleteStorage(
            bucket=bucket,
            endpoint_url=endpoint,
            region_name="us-east-1",
            access_key=access_key,
            secret_key=secret_key,
        )
        retry_worker = create_event_worker(
            settings, modules=tuple(discover_modules()), object_storage=flaky_storage
        )
        try:
            await retry_worker.start()
            with pytest.raises(BusinessOSError) as rejected:
                await retry_worker._consume_delivery(
                    BrokerEvent(
                        subject=(
                            f"businessos.events.tenant.{tenant.tenant_id}.{forged.event_type}"
                        ),
                        payload=json.dumps(
                            forged.model_dump(mode="json"), separators=(",", ":")
                        ).encode(),
                        headers={
                            "event-id": str(forged.event_id),
                            "event-type": forged.event_type,
                            "tenant-id": str(tenant.tenant_id),
                            "schema-version": str(forged.schema_version),
                            "correlation-id": forged.correlation_id,
                        },
                    )
                )
            assert rejected.value.code == "proof_cleanup_decision_invalid"
            assert s3_client.get_object(Bucket=bucket, Key=forged_key)["Body"].read() == (
                b"unrelated-secret"
            )
            await asyncio.wait_for(failed.wait(), timeout=15)
            await asyncio.wait_for(retry_started.wait(), timeout=15)
            with psycopg.connect(postgres_database.administrator_url) as admin:
                assert admin.execute(
                    "SELECT external_cleanup_status "
                    "FROM platform_gov.destructive_decisions_v2 WHERE id = %s",
                    (decision_id,),
                ).fetchone() == ("pending",)
            permit_retry.set()
            deadline = monotonic() + 15
            while True:
                with psycopg.connect(postgres_database.administrator_url) as admin:
                    status = admin.execute(
                        "SELECT external_cleanup_status "
                        "FROM platform_gov.destructive_decisions_v2 WHERE id = %s",
                        (decision_id,),
                    ).fetchone()
                if status == ("completed",):
                    break
                if monotonic() >= deadline:
                    raise AssertionError(f"cleanup completion did not commit: {status}")
                await asyncio.sleep(0.05)
            assert flaky_storage.attempts == 2
            if versioned:
                for key, version_ids in old_versions.items():
                    remaining = s3_client.list_object_versions(Bucket=bucket, Prefix=key)
                    assert (
                        len([item for item in remaining.get("Versions", []) if item["Key"] == key])
                        == 1
                    )
                    for version_id in version_ids:
                        with pytest.raises(ClientError):
                            s3_client.get_object(Bucket=bucket, Key=key, VersionId=version_id)
            keys = {
                item["Key"] for item in s3_client.list_objects_v2(Bucket=bucket).get("Contents", [])
            }
            assert record_key in keys  # persistent fence, with no retained plaintext
            record_tombstone = s3_client.get_object(Bucket=bucket, Key=record_key)["Body"].read()
            assert record_tombstone.startswith(S3ObjectStorageProvider._FENCE_PREFIX)
            assert b"erase-me" not in record_tombstone
            with bind_request_context(context):
                with pytest.raises(FileNotFoundError):
                    await flaky_storage.get(
                        tenant.tenant_id, ProofModule.record_object_key(record_id)
                    )
            if survivor:
                assert surviving_key in keys
                with bind_request_context(context):
                    assert (
                        await flaky_storage.get(tenant.tenant_id, "phase1-proof/value.txt")
                        == b"keep-me"
                    )
            else:
                assert shared_key in keys
                assert (
                    b"erase-me"
                    not in s3_client.get_object(Bucket=bucket, Key=shared_key)["Body"].read()
                )
                with bind_request_context(context):
                    with pytest.raises(FileNotFoundError):
                        await flaky_storage.get(tenant.tenant_id, "phase1-proof/value.txt")
            bind_authenticated_principal(
                context,
                PrincipalIdentity(
                    tenant_id=tenant.tenant_id,
                    principal_id=tenant.principal_id,
                    principal_type="service_account",
                    authentication_strength="verified-workload",
                ),
            )
            with pytest.raises(BusinessOSError) as rejected_completion:
                await dispatch(
                    RecordDestructiveCleanupResultV2(
                        tenant_id=tenant.tenant_id, decision_id=decision_id, completed=True
                    ),
                    context,
                )
            assert rejected_completion.value.code == "cleanup_delivery_invalid"
        finally:
            permit_retry.set()
            await retry_worker.stop()
    finally:
        await first_worker.stop()
        await source_app.shutdown()
        await _remove_workload(postgres_database.migration_url, tenant.installation_id, workload_id)
