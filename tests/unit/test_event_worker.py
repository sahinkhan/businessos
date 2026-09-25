import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, ClassVar, cast
from uuid import uuid4

import pytest
from pydantic import ValidationError

import businessos.__main__ as cli
from businessos.context import RequestContext, TenantContext, current_request_context
from businessos.errors import BusinessOSError, DeliveryUnavailableError
from businessos.event_source import CommittedOutboxSourceVerifier
from businessos.event_worker import (
    EventWorker,
    EventWorkerSettings,
    create_event_worker,
)
from businessos.eventing import OutboxPublisher
from businessos.logging import JsonFormatter
from businessos.messages import DomainEvent
from businessos.providers import BrokerEvent, PermanentDeliveryError
from businessos.workload import WorkloadAdmissionDenied


class _Broker:
    async def publish(self, subject: str, payload: bytes, headers: object) -> None:
        return None

    async def readiness(self) -> None:
        return None

    async def subscribe(self, subject: str, durable_name: str, handler: object) -> object:
        raise AssertionError("invalid envelope must not subscribe")


class _UnknownEvent(DomainEvent):
    event_type: ClassVar[str] = "future.event"


@pytest.fixture(autouse=True)
def transport_only_worker_harness(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep legacy envelope tests focused on transport after trusted admission."""

    async def verified(_: EventWorker, __: object, ___: str) -> object:
        return SimpleNamespace(valid_until=datetime.now(UTC) + timedelta(minutes=1))

    async def source_verified(_: object, **__: object) -> None:
        return None

    monkeypatch.setattr(EventWorker, "_verify_workload", verified)
    monkeypatch.setattr(CommittedOutboxSourceVerifier, "verify", source_verified)


def _settings() -> EventWorkerSettings:
    return EventWorkerSettings(
        runtime_database_url="postgresql+psycopg://businessos_app:runtime-secret@db/app",
        operations_database_url="postgresql+psycopg://businessos_ops:ops-secret@db/app",
        installation_id=uuid4(),
        principal_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_worker_delivery_logs_bind_correlation_tenant_and_restore_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = create_event_worker(_settings(), modules=(), broker=cast(Any, _Broker()))
    assert worker.application.runtime is not None
    runtime = worker.application.runtime
    runtime.events.subscribe(_UnknownEvent, "test.log-projection", cast(Any, lambda *_: None))
    observed: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            observed.append(JsonFormatter().format(record))

    logger = logging.getLogger("businessos.event-worker")
    handler = Capture()
    logger.addHandler(handler)
    old_level = logger.level
    logger.setLevel(logging.INFO)

    async def synchronize() -> None:
        return None

    async def consume(
        event: _UnknownEvent, context: object, dependencies: object, **_: object
    ) -> None:
        logging.getLogger("businessos.event-worker").info("handler log")
        if event.correlation_id == "first-delivery":
            raise RuntimeError("delivery failed")

    monkeypatch.setattr(worker, "_synchronize_subscriber_obligations", synchronize)
    monkeypatch.setattr(runtime.event_consumer, "consume", consume)

    tenant_id = uuid4()

    def delivery(correlation: str) -> BrokerEvent:
        event = _UnknownEvent(tenant_id=tenant_id, correlation_id=correlation)
        return BrokerEvent(
            subject=f"businessos.events.tenant.{tenant_id}.future.event",
            payload=event.model_dump_json().encode(),
            headers={
                "event-id": str(event.event_id),
                "event-type": event.event_type,
                "tenant-id": str(tenant_id),
                "schema-version": "1",
                "correlation-id": correlation,
            },
        )

    try:
        with pytest.raises(RuntimeError, match="delivery failed"):
            await worker._consume_delivery(delivery("first-delivery"))
        assert current_request_context() is None
        await worker._consume_delivery(delivery("second-delivery"))
        assert current_request_context() is None
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        await worker.stop()

    entries = [json.loads(line) for line in observed]
    assert [entry["correlation_id"] for entry in entries] == [
        "first-delivery",
        "first-delivery",
        "second-delivery",
    ]
    assert all(entry["tenant_id"] == str(tenant_id) for entry in entries)
    assert entries[1]["message"] == "Event delivery failed"


def test_event_worker_configuration_redacts_role_credentials() -> None:
    settings = _settings()

    assert "runtime-secret" not in repr(settings)
    assert "ops-secret" not in repr(settings)
    assert "runtime_database_url" not in settings.model_dump()
    assert "operations_database_url" not in settings.model_dump()


def test_event_worker_requires_separate_runtime_and_operations_roles() -> None:
    runtime_url = "postgresql+psycopg://same:runtime-secret@db/app"
    operations_url = "postgresql+psycopg://same:operations-secret@db/app?application_name=ops"
    with pytest.raises(ValidationError, match="roles must be separate"):
        EventWorkerSettings(
            runtime_database_url=runtime_url,
            operations_database_url=operations_url,
            installation_id=uuid4(),
            principal_id=uuid4(),
        )


def test_event_worker_requires_one_source_database() -> None:
    with pytest.raises(ValidationError, match="same source database"):
        EventWorkerSettings(
            runtime_database_url="postgresql+psycopg://businessos_app:a@db/installation_a",
            operations_database_url="postgresql+psycopg://businessos_ops:b@db/installation_b",
            installation_id=uuid4(),
            principal_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_worker_permission_is_only_for_registered_subscriber_check() -> None:
    principal_id, tenant_id = uuid4(), uuid4()
    settings = _settings().model_copy(
        update={"principal_id": principal_id, "permissions": "test.consume"}
    )
    worker = create_event_worker(settings, modules=(), broker=cast(Any, _Broker()))
    runtime = worker.application.runtime
    assert runtime is not None
    context = RequestContext(
        correlation_id="permission-separation",
        tenant=TenantContext(settings.installation_id, tenant_id, principal_id),
    )
    with pytest.raises(BusinessOSError, match="Permission denied"):
        await runtime.events.authorize(context, "test.consume")
    await cast(Any, runtime.event_consumer)._subscriber_authorizer.require(context, "test.consume")
    with pytest.raises(BusinessOSError, match="Permission denied"):
        await cast(Any, runtime.event_consumer)._subscriber_authorizer.require(
            context, "test.manage"
        )
    await worker.stop()


@pytest.mark.asyncio
async def test_quarantine_closes_subscription() -> None:
    worker = create_event_worker(_settings(), modules=(), broker=cast(Any, _Broker()))
    closed = asyncio.Event()

    class Subscription:
        async def close(self) -> None:
            closed.set()

    worker._subscription = cast(Any, Subscription())
    worker._quarantine()
    await asyncio.wait_for(closed.wait(), timeout=1)
    assert worker._quarantined
    assert worker._subscription is None
    assert worker._stop_publisher.is_set()
    await worker.stop()


@pytest.mark.asyncio
async def test_invalid_workload_blocks_startup_sync_and_publisher_without_secret_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    canary = "raw-workload-credential-canary"
    worker = create_event_worker(
        _settings(),
        modules=(),
        broker=cast(Any, _Broker()),
        workload_authority=cast(Any, object()),
    )
    calls: list[str] = []

    class Unit:
        persistence: Any = object()

        async def commit(self) -> None:
            calls.append("commit")

    @asynccontextmanager
    async def system() -> Any:
        yield Unit()

    async def noop() -> None:
        return None

    async def invalid(_: EventWorker, __: object, purpose: str) -> object:
        calls.append(purpose)
        raise WorkloadAdmissionDenied(canary)

    monkeypatch.setattr(worker._operations_uow, "system", system)
    monkeypatch.setattr(worker._operations_database, "readiness", noop)
    monkeypatch.setattr(worker._operations_database, "close", noop)
    monkeypatch.setattr(worker.application, "startup", noop)
    monkeypatch.setattr(worker.application, "shutdown", noop)
    monkeypatch.setattr(EventWorker, "_verify_workload", invalid)

    with pytest.raises(WorkloadAdmissionDenied):
        await worker.start()
    assert calls == ["worker-startup"]

    with pytest.raises(WorkloadAdmissionDenied):
        await worker._synchronize_subscriber_obligations()
    assert calls[-1] == "subscriber-sync"

    with pytest.raises(WorkloadAdmissionDenied):
        async with worker._admit_publisher(cast(Any, Unit())):
            pytest.fail("publisher bypassed workload verification")
    assert calls[-1] == "event-publisher"
    assert "commit" not in calls

    worker._stop_publisher.clear()
    with caplog.at_level(logging.WARNING, logger="businessos.event-worker"):
        await worker._publish_loop()
    assert worker._quarantined
    assert canary not in caplog.text


@pytest.mark.asyncio
async def test_raw_workload_secret_stays_out_of_context_event_outbox_and_broker(
    tmp_path: Any,
) -> None:
    secret = b"raw-workload-credential-canary-1234567890"
    secret_file = tmp_path / "workload-secret"
    secret_file.write_bytes(secret)
    settings = _settings().model_copy(
        update={
            "workload_id": uuid4(),
            "workload_credential_reference": "test-file-v1",
            "workload_credential_file": secret_file,
        }
    )

    class Authority:
        async def verify(self, _: object, **kwargs: object) -> object:
            assert kwargs.pop("credential") == secret
            return SimpleNamespace(valid_until=datetime.now(UTC) + timedelta(seconds=60))

    worker = create_event_worker(
        settings,
        modules=(),
        broker=cast(Any, _Broker()),
        workload_authority=cast(Any, Authority()),
    )
    await worker._verify_workload(
        cast(Any, SimpleNamespace(persistence=object())), "event-delivery"
    )
    tenant_id = uuid4()
    event = _UnknownEvent(tenant_id=tenant_id, correlation_id="canary")
    context = worker._context_resolver.resolve(
        BrokerEvent(subject="test", payload=b"{}", headers={}), tenant_id, "canary"
    )
    pending = event.to_outbox()
    row = SimpleNamespace(
        id=pending.event_id,
        tenant_id=pending.tenant_id,
        event_type=pending.event_type,
        schema_version=pending.schema_version,
        occurred_at=pending.occurred_at,
        correlation_id=pending.correlation_id,
        causation_id=pending.causation_id,
        payload=pending.payload,
        published_at=None,
        attempts=0,
        last_error=None,
    )

    class Session:
        async def scalars(self, _: object) -> list[object]:
            return [row]

    published: list[tuple[bytes, object]] = []

    class CaptureBroker:
        async def publish(self, _: str, payload: bytes, headers: object) -> None:
            published.append((payload, headers))

    @asynccontextmanager
    async def test_admission(_: object) -> AsyncGenerator[None]:
        yield

    publisher = OutboxPublisher(
        cast(Any, None), cast(Any, CaptureBroker()), admission=test_admission
    )
    assert (
        await publisher._publish_locked_batch(cast(Any, SimpleNamespace(session=Session())), 1) == 1
    )
    assert secret not in repr(settings).encode()
    assert secret not in repr(context).encode()
    assert secret not in repr(event).encode()
    assert secret not in repr(pending).encode()
    assert secret not in repr(row.payload).encode()
    assert all(secret not in repr(item).encode() for item in published)
    await worker.stop()


@pytest.mark.asyncio
async def test_invalid_event_envelope_is_rejected_before_tenant_transaction() -> None:
    settings = _settings()
    worker = create_event_worker(settings, modules=(), broker=cast(Any, _Broker()))
    tenant_id = uuid4()
    delivery = BrokerEvent(
        subject=f"businessos.events.tenant.{tenant_id}.wrong.type",
        payload=b"{}",
        headers={
            "event-id": str(uuid4()),
            "event-type": "expected.type",
            "tenant-id": str(tenant_id),
            "schema-version": "1",
            "correlation-id": "invalid-envelope",
        },
    )

    with pytest.raises(PermanentDeliveryError, match="Invalid event envelope"):
        await worker._consume_delivery(delivery)

    assert worker.application.settings.database_url.startswith(
        "postgresql+psycopg://businessos_app:"
    )
    assert "ops-secret" not in repr(worker.application.settings)
    await worker.stop()


@pytest.mark.asyncio
async def test_unknown_well_formed_event_is_retryable_for_rolling_deployments() -> None:
    settings = _settings()
    worker = create_event_worker(settings, modules=(), broker=cast(Any, _Broker()))
    tenant_id = uuid4()
    event_id = uuid4()
    event = _UnknownEvent(
        event_id=event_id,
        tenant_id=tenant_id,
        correlation_id="rolling-deployment",
    )
    delivery = BrokerEvent(
        subject=f"businessos.events.tenant.{tenant_id}.future.event",
        payload=event.model_dump_json().encode(),
        headers={
            "event-id": str(event_id),
            "event-type": "future.event",
            "tenant-id": str(tenant_id),
            "schema-version": "1",
            "correlation-id": "rolling-deployment",
        },
    )

    with pytest.raises(BusinessOSError) as raised:
        await worker._consume_delivery(delivery)

    assert raised.value.code == "not_found"
    await worker.stop()


@pytest.mark.asyncio
async def test_malformed_unknown_event_is_permanently_rejected() -> None:
    settings = _settings()
    worker = create_event_worker(settings, modules=(), broker=cast(Any, _Broker()))
    tenant_id = uuid4()
    delivery = BrokerEvent(
        subject=f"businessos.events.tenant.{tenant_id}.future.event",
        payload=b"not-json",
        headers={
            "event-id": str(uuid4()),
            "event-type": "future.event",
            "tenant-id": str(tenant_id),
            "schema-version": "1",
            "correlation-id": "malformed-unknown",
        },
    )

    with pytest.raises(PermanentDeliveryError, match="Invalid event envelope"):
        await worker._consume_delivery(delivery)

    await worker.stop()


@pytest.mark.asyncio
async def test_unknown_event_missing_required_common_timestamp_is_permanently_rejected() -> None:
    settings = _settings()
    worker = create_event_worker(settings, modules=(), broker=cast(Any, _Broker()))
    tenant_id = uuid4()
    event_id = uuid4()
    delivery = BrokerEvent(
        subject=f"businessos.events.tenant.{tenant_id}.future.event",
        payload=json.dumps(
            {
                "event_id": str(event_id),
                "tenant_id": str(tenant_id),
                "correlation_id": "missing-timestamp",
            }
        ).encode(),
        headers={
            "event-id": str(event_id),
            "event-type": "future.event",
            "tenant-id": str(tenant_id),
            "schema-version": "1",
            "correlation-id": "missing-timestamp",
        },
    )

    with pytest.raises(PermanentDeliveryError, match="Invalid event envelope"):
        await worker._consume_delivery(delivery)

    await worker.stop()


@pytest.mark.asyncio
async def test_known_future_event_schema_version_is_retryable() -> None:
    settings = _settings()
    worker = create_event_worker(settings, modules=(), broker=cast(Any, _Broker()))
    assert worker.application.runtime is not None

    async def consume(_: _UnknownEvent, __: object) -> None:
        return None

    worker.application.runtime.events.subscribe(_UnknownEvent, "projection", cast(Any, consume))
    tenant_id = uuid4()
    event = _UnknownEvent(tenant_id=tenant_id, correlation_id="future-schema")
    delivery = BrokerEvent(
        subject=f"businessos.events.tenant.{tenant_id}.{event.event_type}",
        payload=event.model_dump_json().encode(),
        headers={
            "event-id": str(event.event_id),
            "event-type": event.event_type,
            "tenant-id": str(tenant_id),
            "schema-version": "2",
            "correlation-id": event.correlation_id,
        },
    )

    with pytest.raises(DeliveryUnavailableError, match="Unsupported event schema version"):
        await worker._consume_delivery(delivery)

    await worker.stop()


def test_event_worker_child_redacts_unexpected_exception_details(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "postgresql://probe:PROBE_CREDENTIAL_CANARY@localhost/db"

    async def fail() -> None:
        raise RuntimeError(secret)

    monkeypatch.setattr(cli, "_serve_event_worker", fail)
    caplog.set_level(logging.ERROR, logger="businessos.event-worker")

    with pytest.raises(SystemExit) as raised:
        cli._event_worker_child()

    captured = capsys.readouterr()
    visible_output = captured.out + captured.err + caplog.text
    assert raised.value.code == 1
    assert secret not in visible_output
    assert "PROBE_CREDENTIAL_CANARY" not in visible_output
    assert "Traceback" not in visible_output
    assert "Event worker child failed" in visible_output


@pytest.mark.asyncio
async def test_worker_stop_survives_repeated_cancellation_until_cleanup_finishes() -> None:
    settings = _settings()
    worker = create_event_worker(settings, modules=(), broker=cast(Any, _Broker()))
    entered = asyncio.Event()
    release = asyncio.Event()
    application_stopped = False

    class Subscription:
        async def close(self) -> None:
            entered.set()
            await release.wait()

    async def shutdown() -> None:
        nonlocal application_stopped
        application_stopped = True

    async def publisher_wait() -> None:
        await worker._stop_publisher.wait()

    cast(Any, worker.application).shutdown = shutdown
    worker._subscription = Subscription()
    worker._publisher_task = asyncio.create_task(publisher_wait())
    worker._started = True
    task = asyncio.create_task(worker.stop())
    await entered.wait()
    task.cancel()
    task.cancel()
    task.cancel()
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert task.cancelling() == 0
    assert application_stopped
    assert worker._subscription is None
    assert worker._publisher_task is None


@pytest.mark.asyncio
async def test_worker_stop_bounds_stalled_publisher_and_runs_finalizers() -> None:
    settings = _settings().model_copy(update={"shutdown_timeout_seconds": 0.02})
    worker = create_event_worker(settings, modules=(), broker=cast(Any, _Broker()))
    publisher_entered = asyncio.Event()
    application_stopped = False
    database_closed = False

    async def stalled_publisher() -> None:
        publisher_entered.set()
        await asyncio.Event().wait()

    async def shutdown() -> None:
        nonlocal application_stopped
        application_stopped = True

    async def close_database() -> None:
        nonlocal database_closed
        database_closed = True

    cast(Any, worker.application).shutdown = shutdown
    cast(Any, worker._operations_database).close = close_database
    worker._publisher_task = asyncio.create_task(stalled_publisher())
    worker._started = True
    await publisher_entered.wait()
    task = asyncio.create_task(worker.stop())
    await asyncio.sleep(0)
    task.cancel()
    task.cancel()
    task.cancel()

    with pytest.raises(BaseExceptionGroup, match="Event worker cleanup failed") as raised:
        await asyncio.wait_for(task, timeout=0.5)

    assert any(isinstance(error, TimeoutError) for error in raised.value.exceptions)
    assert task.cancelling() == 0
    assert not task.cancelled()
    assert application_stopped
    assert database_closed
    assert worker._publisher_task is None


@pytest.mark.asyncio
async def test_worker_retains_cleanup_ownership_until_resistant_publisher_finishes() -> None:
    settings = _settings().model_copy(update={"shutdown_timeout_seconds": 0.01})
    worker = create_event_worker(settings, modules=(), broker=cast(Any, _Broker()))
    publisher_entered = asyncio.Event()
    cleanup_entered = asyncio.Event()
    cleanup_release = asyncio.Event()
    application_stopped = False
    database_closed = False

    async def resistant_publisher() -> None:
        publisher_entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleanup_entered.set()
            current = asyncio.current_task()
            while not cleanup_release.is_set():
                try:
                    await asyncio.shield(cleanup_release.wait())
                except asyncio.CancelledError:
                    if current is not None:
                        while current.cancelling():
                            current.uncancel()

    async def shutdown() -> None:
        nonlocal application_stopped
        application_stopped = True

    async def close_database() -> None:
        nonlocal database_closed
        database_closed = True

    cast(Any, worker.application).shutdown = shutdown
    cast(Any, worker._operations_database).close = close_database
    publisher = asyncio.create_task(resistant_publisher(), name="resistant-publisher")
    worker._publisher_task = publisher
    worker._started = True
    await publisher_entered.wait()
    stopping = asyncio.create_task(worker.stop())
    await cleanup_entered.wait()
    await asyncio.sleep(0.03)

    assert not stopping.done()
    assert not publisher.done()
    assert worker._publisher_task is publisher
    assert application_stopped
    assert not database_closed

    cleanup_release.set()
    with pytest.raises(BaseExceptionGroup, match="Event worker cleanup failed"):
        await asyncio.wait_for(stopping, timeout=0.5)

    assert publisher.done()
    assert worker._publisher_task is None
    assert database_closed
