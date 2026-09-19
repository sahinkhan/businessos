import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from contextvars import ContextVar

import anyio
import pytest

from businessos.di import Container, DependencyKey, DependencyResolver, DependencyScope
from businessos.errors import ConfigurationError


@pytest.mark.asyncio
async def test_request_cycle_crossing_transient_fails_without_deadlock() -> None:
    first = DependencyKey[str]("cycle-request-a")
    transient = DependencyKey[str]("cycle-transient")
    second = DependencyKey[str]("cycle-request-b")
    first_started = asyncio.Event()
    second_started = asyncio.Event()

    async def first_provider(resolver: DependencyResolver) -> str:
        first_started.set()
        await second_started.wait()
        return await resolver.resolve(transient)

    async def transient_provider(resolver: DependencyResolver) -> str:
        return await resolver.resolve(second)

    async def second_provider(resolver: DependencyResolver) -> str:
        second_started.set()
        await first_started.wait()
        return await resolver.resolve(first)

    container = Container()
    container.register(first, first_provider, scope=DependencyScope.REQUEST)
    container.register(transient, transient_provider, scope=DependencyScope.TRANSIENT)
    container.register(second, second_provider, scope=DependencyScope.REQUEST)
    async with container.request_scope() as scope:
        results = await asyncio.wait_for(
            asyncio.gather(scope.resolve(first), scope.resolve(second), return_exceptions=True),
            timeout=1,
        )
    assert all(isinstance(result, ConfigurationError) for result in results)
    assert all("Dependency cycle detected" in str(result) for result in results)
    assert any("cycle-transient" in str(result) for result in results)
    await container.close()


@pytest.mark.asyncio
async def test_request_cycle_crossing_multiple_transients_fails_without_deadlock() -> None:
    first = DependencyKey[str]("multi-request-a")
    outer = DependencyKey[str]("multi-transient-outer")
    inner = DependencyKey[str]("multi-transient-inner")
    second = DependencyKey[str]("multi-request-b")
    first_started = asyncio.Event()
    second_started = asyncio.Event()

    async def first_provider(resolver: DependencyResolver) -> str:
        first_started.set()
        await second_started.wait()
        return await resolver.resolve(outer)

    async def outer_provider(resolver: DependencyResolver) -> str:
        return await resolver.resolve(inner)

    async def inner_provider(resolver: DependencyResolver) -> str:
        return await resolver.resolve(second)

    async def second_provider(resolver: DependencyResolver) -> str:
        second_started.set()
        await first_started.wait()
        return await resolver.resolve(first)

    container = Container()
    container.register(first, first_provider, scope=DependencyScope.REQUEST)
    container.register(outer, outer_provider, scope=DependencyScope.TRANSIENT)
    container.register(inner, inner_provider, scope=DependencyScope.TRANSIENT)
    container.register(second, second_provider, scope=DependencyScope.REQUEST)
    async with container.request_scope() as scope:
        results = await asyncio.wait_for(
            asyncio.gather(scope.resolve(first), scope.resolve(second), return_exceptions=True),
            timeout=1,
        )
    assert all(isinstance(result, ConfigurationError) for result in results)
    assert any("multi-transient-outer" in str(result) for result in results)
    assert any("multi-transient-inner" in str(result) for result in results)
    await container.close()


@pytest.mark.asyncio
async def test_independent_concurrent_requests_do_not_report_false_cycle() -> None:
    first = DependencyKey[str]("independent-a")
    second = DependencyKey[str]("independent-b")
    container = Container()
    container.register(first, lambda _: "a", scope=DependencyScope.REQUEST)
    container.register(second, lambda _: "b", scope=DependencyScope.REQUEST)
    async with container.request_scope() as scope:
        values = await asyncio.gather(scope.resolve(first), scope.resolve(second))
        assert list(values) == ["a", "b"]
    await container.close()


@pytest.mark.asyncio
async def test_request_dependency_diamond_is_not_a_cycle() -> None:
    leaf = DependencyKey[object]("diamond-leaf")
    left = DependencyKey[object]("diamond-left")
    right = DependencyKey[object]("diamond-right")
    root = DependencyKey[tuple[object, object]]("diamond-root")
    value = object()
    container = Container()
    container.register(leaf, lambda _: value, scope=DependencyScope.REQUEST)
    container.register(left, lambda resolver: resolver.resolve(leaf), scope=DependencyScope.REQUEST)
    container.register(
        right, lambda resolver: resolver.resolve(leaf), scope=DependencyScope.REQUEST
    )

    async def root_provider(resolver: DependencyResolver) -> tuple[object, object]:
        return await asyncio.gather(resolver.resolve(left), resolver.resolve(right))

    container.register(root, root_provider, scope=DependencyScope.REQUEST)
    async with container.request_scope() as scope:
        left_value, right_value = await scope.resolve(root)
        assert left_value is value
        assert right_value is value
    await container.close()


@pytest.mark.asyncio
async def test_concurrent_request_resource_uses_one_lifecycle_context() -> None:
    key = DependencyKey[object]("context-owned-request")
    marker: ContextVar[str] = ContextVar("request-resource-marker", default="outside")
    value = object()
    entered = 0
    exited = 0

    @asynccontextmanager
    async def resource(_: DependencyResolver) -> AsyncGenerator[object]:
        nonlocal entered, exited
        entered += 1
        token = marker.set("inside")
        try:
            yield value
        finally:
            assert marker.get() == "inside"
            marker.reset(token)
            exited += 1

    container = Container()
    container.register(key, resource, scope=DependencyScope.REQUEST)
    async with container.request_scope() as scope:
        values = await asyncio.gather(*(scope.resolve(key) for _ in range(60)))
        assert all(item is value for item in values)
    assert entered == 1
    assert exited == 1
    await container.close()


@pytest.mark.asyncio
async def test_task_affine_request_resource_enters_and_exits_in_owner_task() -> None:
    key = DependencyKey[object]("task-affine-request")
    enter_task: asyncio.Task[object] | None = None
    exit_task: asyncio.Task[object] | None = None
    exited = asyncio.Event()

    @asynccontextmanager
    async def resource(_: DependencyResolver) -> AsyncGenerator[object]:
        nonlocal enter_task, exit_task
        enter_task = asyncio.current_task()
        async with anyio.create_task_group() as task_group:
            try:
                yield task_group
            finally:
                exit_task = asyncio.current_task()
        exited.set()

    container = Container()
    container.register(key, resource, scope=DependencyScope.REQUEST)
    async with container.request_scope() as scope:
        task_group = await scope.resolve(key)
        assert task_group is not None
    assert exited.is_set()
    assert enter_task is not None
    assert enter_task is exit_task
    await container.close()


@pytest.mark.asyncio
async def test_inflight_owner_cleanup_failure_is_reported_by_scope_close() -> None:
    key = DependencyKey[object]("late-critical-close-failure")
    started = asyncio.Event()
    cancellation_observed = asyncio.Event()

    @asynccontextmanager
    async def failing_resource() -> AsyncGenerator[object]:
        try:
            yield object()
        finally:
            raise RuntimeError("critical-close-failure")

    async def provider(_: DependencyResolver) -> object:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancellation_observed.set()
        return failing_resource()

    container = Container()
    container.register(key, provider, scope=DependencyScope.REQUEST)
    scope = container.request_scope()
    await scope.__aenter__()
    waiter = asyncio.create_task(scope.resolve(key))
    await started.wait()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    with pytest.raises(BaseExceptionGroup, match="Dependency cleanup failed") as raised:
        await scope.__aexit__(None, None, None)
    assert cancellation_observed.is_set()
    assert "critical-close-failure" in str(raised.value.exceptions[0])
    with pytest.raises(ConfigurationError, match="must be entered"):
        await scope.resolve(key)
    await container.close()


@pytest.mark.asyncio
async def test_multiple_owner_cleanup_failures_are_aggregated_once() -> None:
    first = DependencyKey[str]("multiple-cleanup-first")
    second = DependencyKey[str]("multiple-cleanup-second")
    exits: list[str] = []

    def managed(name: str) -> Callable[[DependencyResolver], AbstractAsyncContextManager[str]]:
        @asynccontextmanager
        async def resource(_: DependencyResolver) -> AsyncGenerator[str]:
            try:
                yield name
            finally:
                exits.append(name)
                raise RuntimeError(f"{name}-close-failure")

        return resource

    container = Container()
    container.register(first, managed("first"), scope=DependencyScope.REQUEST)
    container.register(second, managed("second"), scope=DependencyScope.REQUEST)
    with pytest.raises(BaseExceptionGroup, match="Dependency cleanup failed") as raised:
        async with container.request_scope() as scope:
            await scope.resolve(first)
            await scope.resolve(second)
    assert exits == ["second", "first"]
    assert len(raised.value.exceptions) == 2
    assert {str(error) for error in raised.value.exceptions} == {
        "first-close-failure",
        "second-close-failure",
    }
    await container.close()


@pytest.mark.asyncio
async def test_published_cleanup_cancelled_error_is_aggregated() -> None:
    cancelled = DependencyKey[str]("cancelled-cleanup")
    failed = DependencyKey[str]("runtime-cleanup")
    exits: list[str] = []

    def managed(
        name: str, error: BaseException
    ) -> Callable[[DependencyResolver], AbstractAsyncContextManager[str]]:
        @asynccontextmanager
        async def resource(_: DependencyResolver) -> AsyncGenerator[str]:
            try:
                yield name
            finally:
                exits.append(name)
                raise error

        return resource

    container = Container()
    container.register(
        cancelled,
        managed("cancelled", asyncio.CancelledError("cancel-cleanup-marker")),
        scope=DependencyScope.REQUEST,
    )
    container.register(
        failed,
        managed("runtime", RuntimeError("runtime-cleanup-marker")),
        scope=DependencyScope.REQUEST,
    )
    with pytest.raises(BaseExceptionGroup, match="Dependency cleanup failed") as raised:
        async with container.request_scope() as scope:
            await scope.resolve(cancelled)
            await scope.resolve(failed)

    group: BaseExceptionGroup[BaseException] = raised.value
    observed = {(type(error).__name__, str(error)) for error in group.exceptions}
    assert exits == ["runtime", "cancelled"]
    assert observed == {
        ("CancelledError", "cancel-cleanup-marker"),
        ("RuntimeError", "runtime-cleanup-marker"),
    }
    await container.close()


@pytest.mark.asyncio
async def test_failed_published_owner_invalidates_cached_resource() -> None:
    key = DependencyKey[object]("failed-background-owner")
    trigger = asyncio.Event()
    closed = asyncio.Event()

    class Resource:
        open = False

        def use(self) -> str:
            if not self.open:
                raise RuntimeError("resource already closed")
            return "usable"

    value = Resource()

    async def child() -> None:
        await trigger.wait()
        raise RuntimeError("background-worker-failed")

    @asynccontextmanager
    async def resource(_: DependencyResolver) -> AsyncGenerator[object]:
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(child)
            value.open = True
            try:
                yield value
            finally:
                value.open = False
                closed.set()

    container = Container()
    container.register(key, resource, scope=DependencyScope.REQUEST)
    scope = container.request_scope()
    await scope.__aenter__()
    resolved = await scope.resolve(key)
    assert resolved is value
    assert value.use() == "usable"
    trigger.set()
    await closed.wait()

    with pytest.raises(ConfigurationError, match="terminated after publication"):
        await scope.resolve(key)
    with pytest.raises(BaseExceptionGroup, match="Dependency cleanup failed") as raised:
        await scope.__aexit__(None, None, None)
    assert "background-worker-failed" in repr(raised.value)
    await container.close()


@pytest.mark.asyncio
async def test_inflight_resolution_rejects_owner_that_failed_after_publication() -> None:
    key = DependencyKey[object]("failed-started-child-owner")
    closed = asyncio.Event()

    class Resource:
        open = True

    value = Resource()

    async def child(*, task_status: anyio.abc.TaskStatus[None]) -> None:
        task_status.started()
        raise RuntimeError("child-failed-after-started")

    @asynccontextmanager
    async def resource(_: DependencyResolver) -> AsyncGenerator[object]:
        async with anyio.create_task_group() as task_group:
            await task_group.start(child)
            try:
                yield value
            finally:
                value.open = False
                closed.set()

    container = Container()
    container.register(key, resource, scope=DependencyScope.REQUEST)
    scope = container.request_scope()
    await scope.__aenter__()

    with pytest.raises(ConfigurationError, match="terminated after publication"):
        await scope.resolve(key)
    assert closed.is_set()
    assert not value.open
    with pytest.raises(ConfigurationError, match="terminated after publication"):
        await scope.resolve(key)
    with pytest.raises(BaseExceptionGroup, match="Dependency cleanup failed") as raised:
        await scope.__aexit__(None, None, None)
    assert "child-failed-after-started" in repr(raised.value)
    await container.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("nested", [False, True])
async def test_failed_transient_owner_is_rejected_before_delivery(nested: bool) -> None:
    class Resource:
        def __init__(self) -> None:
            self.open = True
            self.closed = asyncio.Event()

        def use(self) -> str:
            if not self.open:
                raise RuntimeError("resource already finalized")
            return "usable"

    transient = DependencyKey[Resource]("failed-transient-owner")
    parent = DependencyKey[Resource]("request-parent-with-transient")
    values: list[Resource] = []
    entries = 0
    exits = 0

    async def child(*, task_status: anyio.abc.TaskStatus[None]) -> None:
        task_status.started()
        raise RuntimeError("transient-child-failed-after-started")

    @asynccontextmanager
    async def resource(_: DependencyResolver) -> AsyncGenerator[Resource]:
        nonlocal entries, exits
        value = Resource()
        values.append(value)
        entries += 1
        try:
            if entries == 1:
                async with anyio.create_task_group() as task_group:
                    await task_group.start(child)
                    yield value
            else:
                yield value
        finally:
            value.open = False
            value.closed.set()
            exits += 1

    container = Container()
    container.register(transient, resource)
    container.register(
        parent,
        lambda resolver: resolver.resolve(transient),
        scope=DependencyScope.REQUEST,
    )
    scope = container.request_scope()
    await scope.__aenter__()
    key = parent if nested else transient

    with pytest.raises(ConfigurationError, match="terminated after publication"):
        await scope.resolve(key)
    await values[0].closed.wait()
    assert not values[0].open

    resolved = await scope.resolve(key)
    assert resolved is values[1]
    assert resolved.use() == "usable"
    if nested:
        assert await scope.resolve(parent) is resolved
    else:
        another = await scope.resolve(transient)
        assert another is values[2]
        assert another.use() == "usable"

    with pytest.raises(BaseExceptionGroup, match="Dependency cleanup failed") as raised:
        await scope.__aexit__(None, None, None)
    assert "transient-child-failed-after-started" in repr(raised.value)
    assert entries == exits
    assert all(not value.open for value in values)
    await container.close()


@pytest.mark.asyncio
async def test_cancelled_initializers_preserve_unwinding_failures() -> None:
    keys = [DependencyKey[object](f"initializer-cleanup-{index}") for index in range(3)]
    started = [asyncio.Event() for _ in keys]
    cleanup: list[int] = []

    def provider(index: int) -> Callable[[DependencyResolver], object]:
        async def initialize(_: DependencyResolver) -> object:
            started[index].set()
            try:
                await asyncio.Event().wait()
            finally:
                cleanup.append(index)
                raise RuntimeError(f"initializer-cleanup-{index}")

        return initialize

    container = Container()
    for index, key in enumerate(keys):
        container.register(key, provider(index), scope=DependencyScope.REQUEST)
    scope = container.request_scope()
    await scope.__aenter__()
    waiters = [asyncio.create_task(scope.resolve(key)) for key in keys]
    await asyncio.gather(*(event.wait() for event in started))
    for waiter in waiters:
        waiter.cancel()
    await asyncio.gather(*waiters, return_exceptions=True)

    with pytest.raises(BaseExceptionGroup, match="Dependency cleanup failed") as raised:
        await scope.__aexit__(None, None, None)
    assert sorted(cleanup) == [0, 1, 2]
    assert {str(error) for error in raised.value.exceptions} == {
        "initializer-cleanup-0",
        "initializer-cleanup-1",
        "initializer-cleanup-2",
    }
    await container.close()


@pytest.mark.asyncio
async def test_task_affine_cleanup_survives_repeated_cancellation() -> None:
    key = DependencyKey[object]("task-affine-cancelled-cleanup")
    enter_task: asyncio.Task[object] | None = None
    exit_task: asyncio.Task[object] | None = None
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()
    cleanup_finished = asyncio.Event()

    @asynccontextmanager
    async def resource(_: DependencyResolver) -> AsyncGenerator[object]:
        nonlocal enter_task, exit_task
        enter_task = asyncio.current_task()
        async with anyio.create_task_group() as task_group:
            try:
                yield task_group
            finally:
                exit_task = asyncio.current_task()
                cleanup_started.set()
                await release_cleanup.wait()
        cleanup_finished.set()

    container = Container()
    container.register(key, resource, scope=DependencyScope.REQUEST)
    scope = container.request_scope()
    await scope.__aenter__()
    await scope.resolve(key)
    closing = asyncio.create_task(scope.__aexit__(None, None, None))
    await cleanup_started.wait()
    for _ in range(5):
        closing.cancel()
        await asyncio.sleep(0)
    release_cleanup.set()
    with pytest.raises(asyncio.CancelledError):
        await closing
    assert cleanup_finished.is_set()
    assert enter_task is exit_task
    await container.close()


@pytest.mark.asyncio
async def test_nested_request_resources_exit_in_reverse_order_in_their_contexts() -> None:
    child = DependencyKey[str]("context-child")
    parent = DependencyKey[str]("context-parent")
    marker: ContextVar[str] = ContextVar("nested-resource-marker", default="outside")
    timeline: list[str] = []

    @asynccontextmanager
    async def child_resource(_: DependencyResolver) -> AsyncGenerator[str]:
        token = marker.set("child")
        timeline.append("enter-child")
        try:
            yield "child"
        finally:
            assert marker.get() == "child"
            timeline.append("exit-child")
            marker.reset(token)

    @asynccontextmanager
    async def parent_resource(resolver: DependencyResolver) -> AsyncGenerator[str]:
        assert await resolver.resolve(child) == "child"
        token = marker.set("parent")
        timeline.append("enter-parent")
        try:
            yield "parent"
        finally:
            assert marker.get() == "parent"
            timeline.append("exit-parent")
            marker.reset(token)

    container = Container()
    container.register(child, child_resource, scope=DependencyScope.REQUEST)
    container.register(parent, parent_resource, scope=DependencyScope.REQUEST)
    async with container.request_scope() as scope:
        assert await scope.resolve(parent) == "parent"
    assert timeline == ["enter-child", "enter-parent", "exit-parent", "exit-child"]
    await container.close()


@pytest.mark.asyncio
async def test_request_provider_failure_cleans_partially_acquired_resource() -> None:
    resource_key = DependencyKey[str]("partial-resource")
    failing_key = DependencyKey[str]("partial-failure")
    marker: ContextVar[str] = ContextVar("partial-marker", default="outside")
    timeline: list[str] = []

    @asynccontextmanager
    async def resource(_: DependencyResolver) -> AsyncGenerator[str]:
        token = marker.set("resource")
        timeline.append("enter")
        try:
            yield "resource"
        finally:
            assert marker.get() == "resource"
            timeline.append("exit")
            marker.reset(token)

    async def failing(resolver: DependencyResolver) -> str:
        await resolver.resolve(resource_key)
        raise RuntimeError("provider failed")

    container = Container()
    container.register(resource_key, resource, scope=DependencyScope.TRANSIENT)
    container.register(failing_key, failing, scope=DependencyScope.REQUEST)
    with pytest.raises(RuntimeError, match="provider failed"):
        async with container.request_scope() as scope:
            await scope.resolve(failing_key)
    assert timeline == ["enter", "exit"]
    await container.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancellations", [1, 2, 5])
async def test_request_teardown_survives_repeated_cancellation(cancellations: int) -> None:
    key = DependencyKey[str](f"cancelled-cleanup-{cancellations}")
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()
    cleanup_finished = asyncio.Event()

    @asynccontextmanager
    async def resource(_: DependencyResolver) -> AsyncGenerator[str]:
        try:
            yield "resource"
        finally:
            cleanup_started.set()
            await release_cleanup.wait()
            cleanup_finished.set()

    container = Container()
    container.register(key, resource, scope=DependencyScope.REQUEST)
    scope = container.request_scope()
    await scope.__aenter__()
    assert await scope.resolve(key) == "resource"
    closing = asyncio.create_task(scope.__aexit__(None, None, None))
    await cleanup_started.wait()
    for _ in range(cancellations):
        closing.cancel()
        await asyncio.sleep(0)
    release_cleanup.set()
    with pytest.raises(asyncio.CancelledError):
        await closing
    assert cleanup_finished.is_set()
    await container.close()


@pytest.mark.asyncio
async def test_request_teardown_closes_every_resource_when_one_exit_fails() -> None:
    first = DependencyKey[str]("cleanup-first")
    second = DependencyKey[str]("cleanup-second")
    timeline: list[str] = []

    def managed(
        name: str, *, fail: bool = False
    ) -> Callable[[DependencyResolver], AbstractAsyncContextManager[str]]:
        @asynccontextmanager
        async def resource(_: DependencyResolver) -> AsyncGenerator[str]:
            timeline.append(f"enter-{name}")
            try:
                yield name
            finally:
                timeline.append(f"exit-{name}")
                if fail:
                    raise RuntimeError(f"{name} cleanup failed")

        return resource

    container = Container()
    container.register(first, managed("first"), scope=DependencyScope.REQUEST)
    container.register(second, managed("second", fail=True), scope=DependencyScope.REQUEST)
    with pytest.raises(BaseExceptionGroup, match="Dependency cleanup failed"):
        async with container.request_scope() as scope:
            await scope.resolve(first)
            await scope.resolve(second)
    assert timeline == ["enter-first", "enter-second", "exit-second", "exit-first"]
    await container.close()


@pytest.mark.asyncio
async def test_cancelled_request_teardown_closes_multiple_resources_in_reverse_order() -> None:
    first = DependencyKey[str]("cancel-order-first")
    second = DependencyKey[str]("cancel-order-second")
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()
    timeline: list[str] = []

    def managed(
        name: str, *, wait: bool = False
    ) -> Callable[[DependencyResolver], AbstractAsyncContextManager[str]]:
        @asynccontextmanager
        async def resource(_: DependencyResolver) -> AsyncGenerator[str]:
            timeline.append(f"enter-{name}")
            try:
                yield name
            finally:
                timeline.append(f"exit-{name}-start")
                if wait:
                    cleanup_started.set()
                    await release_cleanup.wait()
                timeline.append(f"exit-{name}-done")

        return resource

    container = Container()
    container.register(first, managed("first"), scope=DependencyScope.REQUEST)
    container.register(second, managed("second", wait=True), scope=DependencyScope.REQUEST)
    scope = container.request_scope()
    await scope.__aenter__()
    await scope.resolve(first)
    await scope.resolve(second)
    closing = asyncio.create_task(scope.__aexit__(None, None, None))
    await cleanup_started.wait()
    closing.cancel()
    release_cleanup.set()
    with pytest.raises(asyncio.CancelledError):
        await closing
    assert timeline == [
        "enter-first",
        "enter-second",
        "exit-second-start",
        "exit-second-done",
        "exit-first-start",
        "exit-first-done",
    ]
    await container.close()


@pytest.mark.asyncio
async def test_close_during_request_initialization_prevents_late_publication() -> None:
    key = DependencyKey[str]("close-in-flight")
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def provider(_: DependencyResolver) -> str:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return "late"

    container = Container()
    container.register(key, provider, scope=DependencyScope.REQUEST)
    scope = container.request_scope()
    await scope.__aenter__()
    resolving = asyncio.create_task(scope.resolve(key))
    await started.wait()
    await scope.__aexit__(None, None, None)
    with pytest.raises(asyncio.CancelledError):
        await resolving
    assert cancelled.is_set()
    with pytest.raises(ConfigurationError, match="must be entered"):
        await scope.resolve(key)
    await container.close()
