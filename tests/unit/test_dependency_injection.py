import asyncio
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import pytest

from businessos.activation import ContributionGate
from businessos.di import Container, DependencyKey, DependencyResolver, DependencyScope
from businessos.errors import ConfigurationError


@pytest.mark.asyncio
async def test_request_dependency_is_cached_and_torn_down() -> None:
    key = DependencyKey[str]("request-value")
    lifecycle: list[str] = []

    @asynccontextmanager
    async def resource() -> AsyncGenerator[str]:
        lifecycle.append("enter")
        yield "value"
        lifecycle.append("exit")

    container = Container()
    container.register(key, lambda _: resource(), scope=DependencyScope.REQUEST)

    async with container.request_scope() as scope:
        assert await scope.resolve(key) == "value"
        assert await scope.resolve(key) == "value"
        assert lifecycle == ["enter"]

    assert lifecycle == ["enter", "exit"]


@pytest.mark.asyncio
async def test_scope_must_be_entered() -> None:
    key = DependencyKey[str]("value")
    container = Container()
    container.register(key, lambda _: "value")
    scope = container.request_scope()

    with pytest.raises(ConfigurationError, match="must be entered"):
        await scope.resolve(key)


@pytest.mark.asyncio
async def test_singleton_initialization_is_single_flight_for_concurrent_callers() -> None:
    key = DependencyKey[object]("shared")
    calls = 0
    entered = 0
    exited = 0

    @asynccontextmanager
    async def provider(_: DependencyResolver) -> AsyncGenerator[object]:
        nonlocal calls, entered, exited
        calls += 1
        await asyncio.sleep(0)
        entered += 1
        value = object()
        try:
            yield value
        finally:
            exited += 1

    container = Container()
    container.register(key, provider, scope=DependencyScope.SINGLETON)
    async with container.request_scope() as scope:
        values = await asyncio.gather(*(scope.resolve(key) for _ in range(500)))

    assert calls == 1
    assert entered == 1
    assert all(value is values[0] for value in values)
    await container.close()
    assert exited == 1


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_cancel_shared_singleton_initialization() -> None:
    key = DependencyKey[object]("shared")
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def provider(_: DependencyResolver) -> object:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return object()

    container = Container()
    container.register(key, provider, scope=DependencyScope.SINGLETON)
    async with container.request_scope() as scope:
        cancelled_waiter = asyncio.create_task(scope.resolve(key))
        surviving_waiters = [asyncio.create_task(scope.resolve(key)) for _ in range(10)]
        await started.wait()
        cancelled_waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled_waiter
        release.set()
        values = await asyncio.gather(*surviving_waiters)
        retried = await scope.resolve(key)

    assert calls == 1
    assert all(value is values[0] for value in values)
    assert retried is values[0]
    await container.close()


@pytest.mark.asyncio
async def test_failed_singleton_is_shared_then_retryable() -> None:
    key = DependencyKey[str]("retryable")
    started = asyncio.Event()
    release = asyncio.Event()
    failure = RuntimeError("initialization failed")
    calls = 0

    async def provider(_: DependencyResolver) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await release.wait()
            raise failure
        return "ready"

    container = Container()
    container.register(key, provider, scope=DependencyScope.SINGLETON)
    async with container.request_scope() as scope:
        waiters = [asyncio.create_task(scope.resolve(key)) for _ in range(20)]
        await started.wait()
        release.set()
        failures = await asyncio.gather(*waiters, return_exceptions=True)
        assert all(item is failure for item in failures)
        assert await scope.resolve(key) == "ready"

    assert calls == 2
    await container.close()


@pytest.mark.asyncio
async def test_cancelled_initializer_does_not_poison_retry() -> None:
    key = DependencyKey[str]("cancelled-initializer")
    calls = 0

    async def provider(_: DependencyResolver) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise asyncio.CancelledError
        return "recovered"

    container = Container()
    container.register(key, provider, scope=DependencyScope.SINGLETON)
    async with container.request_scope() as scope:
        with pytest.raises(asyncio.CancelledError):
            await scope.resolve(key)
        assert await scope.resolve(key) == "recovered"

    assert calls == 2
    await container.close()


@pytest.mark.asyncio
async def test_dependency_cycles_are_deterministic() -> None:
    direct = DependencyKey[str]("direct")
    first = DependencyKey[str]("first")
    second = DependencyKey[str]("second")
    container = Container()

    async def direct_provider(resolver: DependencyResolver) -> str:
        return await resolver.resolve(direct)

    async def first_provider(resolver: DependencyResolver) -> str:
        return await resolver.resolve(second)

    async def second_provider(resolver: DependencyResolver) -> str:
        return await resolver.resolve(first)

    container.register(direct, direct_provider, scope=DependencyScope.SINGLETON)
    container.register(first, first_provider, scope=DependencyScope.SINGLETON)
    container.register(second, second_provider, scope=DependencyScope.SINGLETON)
    async with container.request_scope() as scope:
        with pytest.raises(ConfigurationError, match="direct -> direct"):
            await scope.resolve(direct)
        with pytest.raises(ConfigurationError, match="first -> second -> first"):
            await scope.resolve(first)
    await container.close()


@pytest.mark.asyncio
async def test_unrelated_singletons_initialize_in_parallel() -> None:
    first = DependencyKey[str]("parallel-first")
    second = DependencyKey[str]("parallel-second")
    both_started = asyncio.Event()
    started: set[str] = set()

    async def provider(name: str) -> str:
        started.add(name)
        if len(started) == 2:
            both_started.set()
        await both_started.wait()
        return name

    container = Container()
    container.register(first, lambda _: provider("first"), scope=DependencyScope.SINGLETON)
    container.register(second, lambda _: provider("second"), scope=DependencyScope.SINGLETON)
    async with container.request_scope() as scope:
        assert tuple(await asyncio.gather(scope.resolve(first), scope.resolve(second))) == (
            "first",
            "second",
        )
    await container.close()


@pytest.mark.asyncio
async def test_module_singletons_are_cleaned_in_reverse_order_and_removed() -> None:
    first = DependencyKey[str]("owned-first")
    second = DependencyKey[str]("owned-second")
    timeline: list[str] = []
    gate = ContributionGate()
    generation = gate.reserve("example.owner")

    def resource(name: str) -> AbstractAsyncContextManager[str]:
        @asynccontextmanager
        async def managed() -> AsyncGenerator[str]:
            timeline.append(f"enter:{name}")
            yield name
            timeline.append(f"exit:{name}")

        return managed()

    container = Container()
    container.register(
        first,
        lambda _: resource("first"),
        scope=DependencyScope.SINGLETON,
        owner="example.owner",
        generation=generation,
        gate=gate,
    )
    container.register(
        second,
        lambda _: resource("second"),
        scope=DependencyScope.SINGLETON,
        owner="example.owner",
        generation=generation,
        gate=gate,
    )
    gate.publish(generation)
    async with container.request_scope() as scope:
        assert await scope.resolve(first) == "first"
        assert await scope.resolve(second) == "second"
    await gate.close_and_drain(generation, timeout_seconds=1)
    await container.remove_owner_generation(generation)

    assert timeline == ["enter:first", "enter:second", "exit:second", "exit:first"]
    async with container.request_scope() as scope:
        with pytest.raises(ConfigurationError, match="not registered"):
            await scope.resolve(first)
    await container.close()


@pytest.mark.asyncio
async def test_failed_resource_initialization_cleans_partial_resource_and_retries() -> None:
    key = DependencyKey[str]("partial-resource")
    timeline: list[str] = []
    calls = 0

    @asynccontextmanager
    async def resource(_: DependencyResolver) -> AsyncGenerator[str]:
        nonlocal calls
        calls += 1
        timeline.append(f"enter:{calls}")
        try:
            if calls == 1:
                raise RuntimeError("partial failure")
            yield "ready"
        finally:
            timeline.append(f"exit:{calls}")

    container = Container()
    container.register(key, resource, scope=DependencyScope.SINGLETON)
    async with container.request_scope() as scope:
        with pytest.raises(RuntimeError, match="partial failure"):
            await scope.resolve(key)
        assert await scope.resolve(key) == "ready"
    await container.close()

    assert timeline == ["enter:1", "exit:1", "enter:2", "exit:2"]


@pytest.mark.asyncio
async def test_container_close_cancels_initializer_and_rejects_new_resolution() -> None:
    key = DependencyKey[str]("shutdown-race")
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def provider(_: DependencyResolver) -> str:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return "never"

    container = Container()
    container.register(key, provider, scope=DependencyScope.SINGLETON)
    async with container.request_scope() as scope:
        resolving = asyncio.create_task(scope.resolve(key))
        await started.wait()
        await container.close()
        with pytest.raises(asyncio.CancelledError):
            await resolving
        assert cancelled.is_set()
        with pytest.raises(ConfigurationError, match="closed"):
            await scope.resolve(key)
