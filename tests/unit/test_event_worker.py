import asyncio
from typing import Any, cast
from uuid import uuid4

import pytest
from pydantic import ValidationError

from businessos.event_worker import EventWorkerSettings, create_event_worker
from businessos.providers import BrokerEvent, PermanentDeliveryError


class _Broker:
    async def publish(self, subject: str, payload: bytes, headers: object) -> None:
        return None

    async def readiness(self) -> None:
        return None

    async def subscribe(self, subject: str, durable_name: str, handler: object) -> object:
        raise AssertionError("invalid envelope must not subscribe")


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
