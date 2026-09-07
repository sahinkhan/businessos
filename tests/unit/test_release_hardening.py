"""Adversarial SDK capability and secret regressions for release hardening."""

import asyncio
import logging
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.context import RequestContext, TenantContext
from businessos.dependencies import DATABASE, OBJECT_STORAGE
from businessos.di import Container, DependencyKey, DependencyResolver, DependencyScope
from businessos.errors import ConfigurationError
from businessos.event_worker import EventWorkerSettings
from businessos.logging import JsonFormatter
from businessos.module_access import module_dependencies
from businessos.sdk import OBJECT_STORAGE as PUBLIC_STORAGE


@pytest.mark.parametrize("surface", ["constructor", "model", "json", "strings"])
def test_configuration_canary_never_survives_error_boundary(surface: str) -> None:
    canary = "secret-canary-9182"
    with pytest.raises(ValidationError) as caught:
        if surface == "constructor":
            Settings(database_url=canary)
        elif surface == "model":
            Settings.model_validate({"database_url": canary})
        elif surface == "json":
            Settings.model_validate_json('{"database_url":"' + canary)
        else:
            Settings.model_validate_strings({"database_url": canary})
    error = caught.value
    assert error.__context__ is None
    assert error.__cause__ is None
    representations = (
        str(error),
        repr(error),
        str(error.errors()),
        error.json(),
        "".join(traceback.format_exception(error)),
    )
    assert all(canary not in value for value in representations)
    record = logging.LogRecord("test", logging.ERROR, "test", 1, "%s", (error,), None)
    assert canary not in JsonFormatter().format(record)


def test_worker_credentials_are_redacted_in_repr_serialization_and_logs() -> None:
    canary = "secret-canary-9182"
    settings = EventWorkerSettings(
        runtime_database_url=f"postgresql+psycopg://app:{canary}@db/test",
        operations_database_url=f"postgresql+psycopg://ops:{canary}@db/test",
        nats_url=f"nats://user:{canary}@broker",
        s3_endpoint_url=f"http://user:{canary}@storage",
        s3_bucket="test",
        s3_access_key=canary,
        s3_secret_key=canary,
        installation_id=uuid4(),
        principal_id=uuid4(),
    )
    assert canary not in repr(settings)
    assert canary not in str(settings.model_dump())
    assert canary not in settings.model_dump_json()
    record = logging.LogRecord("test", logging.INFO, "test", 1, "%s", (settings,), None)
    assert canary not in JsonFormatter().format(record)


@pytest.mark.asyncio
async def test_sdk_cannot_forge_internal_keys_or_resolve_actual_internal_authority() -> None:
    app = create_application(Settings(environment="test", database_readiness_enabled=False))
    assert DependencyKey[object]("businessos.database") != DATABASE
    async with app.container.request_scope() as scope:
        public = module_dependencies(scope, RequestContext())
        for key in (DependencyKey[object]("businessos.database"), DATABASE):
            with pytest.raises(ConfigurationError):
                await public.resolve(key)
        public.close()
    await app.shutdown()


@pytest.mark.asyncio
async def test_storage_capability_is_tenant_bound_and_expires() -> None:
    calls: list[tuple[UUID, str]] = []

    class Storage:
        async def put(self, tenant_id: UUID, key: str, content: bytes) -> None:
            calls.append((tenant_id, key))

        async def get(self, tenant_id: UUID, key: str) -> bytes:
            calls.append((tenant_id, key))
            return b"value"

        async def readiness(self) -> None:
            pass

    container = Container()
    container.register(OBJECT_STORAGE, lambda _: Storage())
    tenant = TenantContext(uuid4(), uuid4(), uuid4())
    async with container.request_scope() as scope:
        public = module_dependencies(scope, RequestContext(tenant=tenant))
        storage = await public.resolve(PUBLIC_STORAGE)
        await storage.put("key", b"value")
        assert calls == [(tenant.tenant_id, "key")]
        public.close()
        with pytest.raises(ConfigurationError, match="expired"):
            await storage.get("key")
    await container.close()


@pytest.mark.asyncio
async def test_singleton_cannot_capture_request_scoped_resource() -> None:
    container = Container()
    request_key = DependencyKey[object]("request")
    singleton_key = DependencyKey[object]("singleton")
    container.register(request_key, lambda _: object(), scope=DependencyScope.REQUEST)

    async def singleton(resolver: "DependencyResolver") -> object:
        return await resolver.resolve(request_key)

    container.register(singleton_key, singleton, scope=DependencyScope.SINGLETON)
    async with container.request_scope() as scope:
        with pytest.raises(ConfigurationError, match="request-scoped"):
            await scope.resolve(singleton_key)
    await container.close()


@pytest.mark.asyncio
async def test_concurrent_close_and_cancellation_join_one_cleanup() -> None:
    container = Container()
    key = DependencyKey[object]("resource")
    entered = asyncio.Event()
    release = asyncio.Event()
    completions = []

    @asynccontextmanager
    async def resource(_: "DependencyResolver") -> AsyncIterator[object]:
        yield object()
        entered.set()
        await release.wait()
        completions.append("closed")

    container.register(key, resource, scope=DependencyScope.SINGLETON)
    async with container.request_scope() as scope:
        await scope.resolve(key)
    first = asyncio.create_task(container.close())
    await entered.wait()
    second = asyncio.create_task(container.close())
    first.cancel()
    await asyncio.sleep(0)
    assert not first.done()
    assert not second.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await first
    await second
    assert completions == ["closed"]
