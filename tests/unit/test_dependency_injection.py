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
async def test_concurrent_cross_key_singleton_cycle_fails_without_deadlock() -> None:
    first = DependencyKey[str]("cross-cycle-first")
    second = DependencyKey[str]("cross-cycle-second")
    first_started = asyncio.Event()
    second_started = asyncio.Event()
    container = Container()

    async def first_provider(resolver: DependencyResolver) -> str:
        first_started.set()
        await second_started.wait()
        return await resolver.resolve(second)

    async def second_provider(resolver: DependencyResolver) -> str:
        second_started.set()
        await first_started.wait()
        return await resolver.resolve(first)

    container.register(first, first_provider, scope=DependencyScope.SINGLETON)
    container.register(second, second_provider, scope=DependencyScope.SINGLETON)
    async with container.request_scope() as scope:
        results = await asyncio.wait_for(
            asyncio.gather(
                scope.resolve(first),
                scope.resolve(second),
                return_exceptions=True,
            ),
            timeout=1,
        )

    assert all(isinstance(result, ConfigurationError) for result in results)
    assert all("Dependency cycle detected" in str(result) for result in results)
    await container.close()


@pytest.mark.asyncio
async def test_unobserved_singleton_failure_is_consumed_and_retryable() -> None:
    key = DependencyKey[str]("abandoned-failure")
    release = asyncio.Event()
    calls = 0

    async def provider(_: DependencyResolver) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            await release.wait()
            raise RuntimeError("expected provider failure")
        return "recovered"

    container = Container()
    container.register(key, provider, scope=DependencyScope.SINGLETON)
    async with container.request_scope() as scope:
        abandoned = asyncio.create_task(scope.resolve(key))
        await asyncio.sleep(0)
        abandoned.cancel()
        with pytest.raises(asyncio.CancelledError):
            await abandoned
        release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert await scope.resolve(key) == "recovered"

    assert calls == 2
    await container.close()


def test_closed_container_rejects_new_registrations() -> None:
    async def scenario() -> None:
        container = Container()
        await container.close()
        with pytest.raises(ConfigurationError, match="closed"):
            container.register(DependencyKey[str]("late"), lambda _: "late")

    asyncio.run(scenario())


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


@pytest.mark.asyncio
@pytest.mark.parametrize("indirect", [False, True])
async def test_singleton_cannot_capture_request_lifetime(indirect: bool) -> None:
    request_key = DependencyKey[str]("captured-request")
    transient_key = DependencyKey[str]("capturing-transient")
    singleton_key = DependencyKey[str]("capturing-singleton")
    container = Container()
    container.register(request_key, lambda _: "request", scope=DependencyScope.REQUEST)

    async def transient(resolver: DependencyResolver) -> str:
        return await resolver.resolve(request_key)

    async def singleton(resolver: DependencyResolver) -> str:
        return await resolver.resolve(transient_key if indirect else request_key)

    container.register(transient_key, transient, scope=DependencyScope.TRANSIENT)
    container.register(singleton_key, singleton, scope=DependencyScope.SINGLETON)
    async with container.request_scope() as scope:
        with pytest.raises(
            ConfigurationError,
            match=r"capturing-singleton.*captured-request",
        ):
            await scope.resolve(singleton_key)
    await container.close()


@pytest.mark.asyncio
async def test_singleton_cannot_capture_request_through_arbitrary_transient_chain() -> None:
    request_key = DependencyKey[str]("deep-request")
    inner_key = DependencyKey[str]("deep-inner-transient")
    outer_key = DependencyKey[str]("deep-outer-transient")
    singleton_key = DependencyKey[str]("deep-singleton")

    async def resolve_dependency(
        resolver: DependencyResolver,
        dependency: DependencyKey[str],
    ) -> str:
        return await resolver.resolve(dependency)

    container = Container()
    container.register(request_key, lambda _: "request", scope=DependencyScope.REQUEST)
    container.register(
        inner_key,
        lambda resolver: resolve_dependency(resolver, request_key),
        scope=DependencyScope.TRANSIENT,
    )
    container.register(
        outer_key,
        lambda resolver: resolve_dependency(resolver, inner_key),
        scope=DependencyScope.TRANSIENT,
    )
    container.register(
        singleton_key,
        lambda resolver: resolve_dependency(resolver, outer_key),
        scope=DependencyScope.SINGLETON,
    )
    async with container.request_scope() as scope:
        with pytest.raises(ConfigurationError, match=r"deep-singleton.*deep-request"):
            await scope.resolve(singleton_key)
    await container.close()


@pytest.mark.asyncio
async def test_valid_dependency_lifetime_relationships_resolve() -> None:
    singleton_key = DependencyKey[object]("valid-singleton")
    singleton_parent = DependencyKey[object]("valid-singleton-parent")
    request_key = DependencyKey[object]("valid-request")
    transient_key = DependencyKey[object]("valid-transient")
    request_parent = DependencyKey[tuple[object, object, object]]("valid-request-parent")
    singleton_value = object()
    request_value = object()

    async def singleton_provider(resolver: DependencyResolver) -> object:
        return await resolver.resolve(singleton_key)

    async def request_provider(
        resolver: DependencyResolver,
    ) -> tuple[object, object, object]:
        singleton, request, transient = await asyncio.gather(
            resolver.resolve(singleton_key),
            resolver.resolve(request_key),
            resolver.resolve(transient_key),
        )
        return singleton, request, transient

    container = Container()
    container.register(singleton_key, lambda _: singleton_value, scope=DependencyScope.SINGLETON)
    container.register(singleton_parent, singleton_provider, scope=DependencyScope.SINGLETON)
    container.register(request_key, lambda _: request_value, scope=DependencyScope.REQUEST)
    container.register(transient_key, lambda _: object(), scope=DependencyScope.TRANSIENT)
    container.register(request_parent, request_provider, scope=DependencyScope.REQUEST)
    async with container.request_scope() as scope:
        assert await scope.resolve(singleton_parent) is singleton_value
        singleton, request, transient = await scope.resolve(request_parent)
        assert singleton is singleton_value
        assert request is request_value
        assert transient is not singleton_value
        assert transient is not request_value
    await container.close()


@pytest.mark.asyncio
async def test_singleton_owns_safe_transient_resource_until_container_close() -> None:
    transient_key = DependencyKey[str]("singleton-safe-transient")
    singleton_key = DependencyKey[str]("singleton-with-transient")
    timeline: list[str] = []

    @asynccontextmanager
    async def transient(_: DependencyResolver) -> AsyncGenerator[str]:
        timeline.append("enter")
        try:
            yield "safe"
        finally:
            timeline.append("exit")

    async def singleton(resolver: DependencyResolver) -> str:
        return await resolver.resolve(transient_key)

    container = Container()
    container.register(transient_key, transient, scope=DependencyScope.TRANSIENT)
    container.register(singleton_key, singleton, scope=DependencyScope.SINGLETON)
    async with container.request_scope() as scope:
        assert await scope.resolve(singleton_key) == "safe"
    assert timeline == ["enter"]
    await container.close()
    assert timeline == ["enter", "exit"]


@pytest.mark.asyncio
async def test_request_initialization_is_single_flight_and_resource_exits_once() -> None:
    key = DependencyKey[object]("request-single-flight")
    calls = 0
    exits = 0

    @asynccontextmanager
    async def provider(_: DependencyResolver) -> AsyncGenerator[object]:
        nonlocal calls, exits
        calls += 1
        await asyncio.sleep(0)
        value = object()
        try:
            yield value
        finally:
            exits += 1

    container = Container()
    container.register(key, provider, scope=DependencyScope.REQUEST)
    async with container.request_scope() as scope:
        values = await asyncio.gather(*(scope.resolve(key) for _ in range(500)))
        assert all(value is values[0] for value in values)
    assert calls == 1
    assert exits == 1
    await container.close()


@pytest.mark.asyncio
async def test_cancelled_request_waiter_does_not_cancel_shared_initialization() -> None:
    key = DependencyKey[object]("request-cancelled-waiter")
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
    container.register(key, provider, scope=DependencyScope.REQUEST)
    async with container.request_scope() as scope:
        cancelled = asyncio.create_task(scope.resolve(key))
        survivor = asyncio.create_task(scope.resolve(key))
        await started.wait()
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        release.set()
        value = await survivor
        assert await scope.resolve(key) is value
    assert calls == 1
    await container.close()


@pytest.mark.asyncio
async def test_failed_request_initialization_is_shared_then_retryable() -> None:
    key = DependencyKey[str]("request-retry")
    failure = RuntimeError("request initialization failed")
    started = asyncio.Event()
    release = asyncio.Event()
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
    container.register(key, provider, scope=DependencyScope.REQUEST)
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
async def test_request_single_flight_is_isolated_between_scopes() -> None:
    key = DependencyKey[object]("request-scope-isolation")
    calls = 0

    async def provider(_: DependencyResolver) -> object:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return object()

    container = Container()
    container.register(key, provider, scope=DependencyScope.REQUEST)

    async def resolve_scope() -> tuple[object, object]:
        async with container.request_scope() as scope:
            first, second = await asyncio.gather(scope.resolve(key), scope.resolve(key))
            return first, second

    first_scope, second_scope = await asyncio.gather(resolve_scope(), resolve_scope())
    assert first_scope[0] is first_scope[1]
    assert second_scope[0] is second_scope[1]
    assert first_scope[0] is not second_scope[0]
    assert calls == 2
    await container.close()


@pytest.mark.asyncio
async def test_request_scope_close_cancels_initialization_without_publishing() -> None:
    key = DependencyKey[str]("request-close-race")
    started = asyncio.Event()
    cleaned = asyncio.Event()

    async def provider(_: DependencyResolver) -> str:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()
        return "never"

    container = Container()
    container.register(key, provider, scope=DependencyScope.REQUEST)
    scope = container.request_scope()
    await scope.__aenter__()
    resolving = asyncio.create_task(scope.resolve(key))
    await started.wait()
    await scope.__aexit__(None, None, None)
    with pytest.raises(asyncio.CancelledError):
        await resolving
    assert cleaned.is_set()
    with pytest.raises(ConfigurationError, match="must be entered"):
        await scope.resolve(key)
    await container.close()


@pytest.mark.asyncio
async def test_nested_concurrent_request_dependencies_do_not_deadlock() -> None:
    child = DependencyKey[str]("request-child")
    parent = DependencyKey[tuple[str, str]]("request-parent")
    child_calls = 0

    async def child_provider(_: DependencyResolver) -> str:
        nonlocal child_calls
        child_calls += 1
        await asyncio.sleep(0)
        return "child"

    async def parent_provider(resolver: DependencyResolver) -> tuple[str, str]:
        first, second = await asyncio.gather(resolver.resolve(child), resolver.resolve(child))
        return first, second

    container = Container()
    container.register(child, child_provider, scope=DependencyScope.REQUEST)
    container.register(parent, parent_provider, scope=DependencyScope.REQUEST)
    async with container.request_scope() as scope:
        assert await asyncio.wait_for(scope.resolve(parent), timeout=1) == ("child", "child")
    assert child_calls == 1
    await container.close()


@pytest.mark.asyncio
async def test_concurrent_cross_key_request_cycle_fails_without_deadlock() -> None:
    first = DependencyKey[str]("request-cross-cycle-first")
    second = DependencyKey[str]("request-cross-cycle-second")
    first_started = asyncio.Event()
    second_started = asyncio.Event()

    async def first_provider(resolver: DependencyResolver) -> str:
        first_started.set()
        await second_started.wait()
        return await resolver.resolve(second)

    async def second_provider(resolver: DependencyResolver) -> str:
        second_started.set()
        await first_started.wait()
        return await resolver.resolve(first)

    container = Container()
    container.register(first, first_provider, scope=DependencyScope.REQUEST)
    container.register(second, second_provider, scope=DependencyScope.REQUEST)
    async with container.request_scope() as scope:
        results = await asyncio.wait_for(
            asyncio.gather(
                scope.resolve(first),
                scope.resolve(second),
                return_exceptions=True,
            ),
            timeout=1,
        )
    assert all(isinstance(result, ConfigurationError) for result in results)
    assert all("Dependency cycle detected" in str(result) for result in results)
    await container.close()
