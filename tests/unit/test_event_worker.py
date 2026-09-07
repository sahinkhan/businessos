import asyncio
import json
import logging
from typing import Any, ClassVar, cast
from uuid import uuid4

import pytest
from pydantic import ValidationError

import businessos.__main__ as cli
from businessos.errors import BusinessOSError, DeliveryUnavailableError
from businessos.event_worker import EventWorkerSettings, create_event_worker
from businessos.messages import DomainEvent
from businessos.providers import BrokerEvent, PermanentDeliveryError


class _Broker:
    async def publish(self, subject: str, payload: bytes, headers: object) -> None:
        return None

    async def readiness(self) -> None:
        return None

    async def subscribe(self, subject: str, durable_name: str, handler: object) -> object:
        raise AssertionError("invalid envelope must not subscribe")


class _UnknownEvent(DomainEvent):
    event_type: ClassVar[str] = "future.event"


def _settings() -> EventWorkerSettings:
    return EventWorkerSettings(
        runtime_database_url="postgresql+psycopg://businessos_app:runtime-secret@db/app",
        operations_database_url="postgresql+psycopg://businessos_ops:ops-secret@db/app",
        installation_id=uuid4(),
        principal_id=uuid4(),
    )


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
