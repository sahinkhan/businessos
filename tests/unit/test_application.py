import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, cast

import httpx
import pytest

from businessos.application import ApplicationState, BusinessOSApplication
from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.di import Container
from businessos.http import Request, Response, Router
from businessos.http.middleware import CallNext


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://test:test@db/test",
        database_readiness_enabled=False,
    )


def _recording_lifecycle_hooks(
    index: int,
    failure_position: int,
    timeline: list[str],
) -> tuple[Callable[[], Awaitable[None]], Callable[[], Awaitable[None]]]:
    async def start() -> None:
        timeline.append(f"start:{index}")
        if index == failure_position:
            raise RuntimeError(f"failure:{index}")

    async def stop() -> None:
        timeline.append(f"stop:{index}")

    return start, stop


@pytest.mark.asyncio
async def test_diagnostic_endpoints_are_available_through_custom_asgi_app() -> None:
    app = create_application(_settings())
    transport = httpx.ASGITransport(app=cast(Any, app))
    await app.startup()

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        liveness = await client.get("/livez")
        readiness = await client.get("/readyz")
        version = await client.get("/version")
        modules = await client.get("/diagnostics/modules")
    await app.shutdown()

    assert liveness.status_code == 200
    assert liveness.json() == {"status": "live"}
    assert readiness.status_code == 200
    assert readiness.json() == {
        "status": "ready",
        "checks": [{"name": "application", "ready": True, "detail": None}],
    }
    assert version.status_code == 200
    assert "version" in version.json()
    assert modules.status_code == 200
    assert modules.json() == {"modules": []}
    assert liveness.headers["x-correlation-id"]


@pytest.mark.asyncio
async def test_middleware_order_and_lifecycle_are_deterministic() -> None:
    app = create_application(_settings())
    events: list[str] = []

    class RecordingMiddleware:
        def __init__(self, name: str) -> None:
            self.name = name

        async def __call__(self, request: Request, call_next: CallNext) -> Response:
            events.append(f"{self.name}:before")
            response = await call_next(request)
            events.append(f"{self.name}:after")
            return response

    async def route(request: Request, _: object) -> Response:
        events.append("handler")
        return Response.json({"path": request.path})

    async def startup() -> None:
        events.append("startup")

    async def shutdown() -> None:
        events.append("shutdown")

    app.add_middleware(RecordingMiddleware("first"))
    app.add_middleware(RecordingMiddleware("second"))
    app.router.add_route("GET", "/ordered", route)
    app.on_startup(startup)
    app.on_shutdown(shutdown)

    await app.startup()
    assert app.state is ApplicationState.RUNNING

    transport = httpx.ASGITransport(app=cast(Any, app))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ordered")
    await app.shutdown()

    assert response.status_code == 200
    assert events == [
        "startup",
        "first:before",
        "second:before",
        "handler",
        "second:after",
        "first:after",
        "shutdown",
    ]
    assert app.state.value == ApplicationState.STOPPED.value


@pytest.mark.asyncio
async def test_framework_serializes_expected_and_unexpected_errors() -> None:
    app = create_application(_settings())

    async def failure(_: Request, __: object) -> Response:
        raise RuntimeError("secret detail")

    app.router.add_route("GET", "/failure", failure)
    await app.startup()
    transport = httpx.ASGITransport(app=cast(Any, app))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.get("/missing")
        failed = await client.get("/failure")
    await app.shutdown()

    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"
    assert failed.status_code == 500
    assert failed.json() == {"code": "internal_error", "message": "Internal server error"}


@pytest.mark.asyncio
async def test_startup_failure_rolls_back_completed_components_in_reverse_order() -> None:
    app = create_application(_settings())
    timeline: list[str] = []

    async def start_first() -> None:
        timeline.append("start:first")

    async def stop_first() -> None:
        timeline.append("stop:first")

    async def start_second() -> None:
        timeline.append("start:second")

    async def stop_second() -> None:
        timeline.append("stop:second")

    async def fail() -> None:
        timeline.append("start:failure")
        raise RuntimeError("failed")

    app.add_lifecycle("first", start_first, stop_first)
    app.add_lifecycle("second", start_second, stop_second)
    app.add_lifecycle("failure", fail, lambda: asyncio.sleep(0))

    with pytest.raises(RuntimeError, match="failed"):
        await app.startup()

    assert timeline == [
        "start:first",
        "start:second",
        "start:failure",
        "stop:second",
        "stop:first",
    ]
    assert app.state is ApplicationState.FAILED


@pytest.mark.parametrize("failure_position", [0, 1, 2])
@pytest.mark.asyncio
async def test_startup_failure_at_each_position_rolls_back_only_completed_work(
    failure_position: int,
) -> None:
    app = BusinessOSApplication(_settings(), router=Router(), container=Container())
    timeline: list[str] = []
    for index in range(3):
        start, stop = _recording_lifecycle_hooks(index, failure_position, timeline)
        app.add_lifecycle(f"component-{index}", start, stop)

    with pytest.raises(RuntimeError, match=f"failure:{failure_position}"):
        await app.startup()

    expected = [f"start:{index}" for index in range(failure_position + 1)]
    expected.extend(f"stop:{index}" for index in reversed(range(failure_position)))
    assert timeline == expected
    assert app.state is ApplicationState.FAILED


@pytest.mark.asyncio
async def test_startup_cancellation_rolls_back_completed_components() -> None:
    app = create_application(_settings())
    timeline: list[str] = []
    blocked = asyncio.Event()
    blocked_entered = asyncio.Event()

    async def started() -> None:
        timeline.append("start")

    async def rolled_back() -> None:
        timeline.append("rollback")

    async def wait_forever() -> None:
        blocked_entered.set()
        await blocked.wait()

    app.add_lifecycle("completed", started, rolled_back)
    app.add_lifecycle("blocked", wait_forever, lambda: asyncio.sleep(0))
    task = asyncio.create_task(app.startup())
    await blocked_entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert timeline == ["start", "rollback"]
    assert app.state is ApplicationState.FAILED


@pytest.mark.asyncio
async def test_startup_timeout_rolls_back_completed_components() -> None:
    settings = Settings(
        environment="test",
        database_url="postgresql+psycopg://test:test@db/test",
        database_readiness_enabled=False,
        startup_timeout_seconds=0.01,
    )
    app = create_application(settings)
    timeline: list[str] = []

    async def start_first() -> None:
        timeline.append("start:first")

    async def stop_first() -> None:
        timeline.append("stop:first")

    async def stuck() -> None:
        await asyncio.Event().wait()

    app.add_lifecycle("first", start_first, stop_first)
    app.add_lifecycle("stuck", stuck, lambda: asyncio.sleep(0))
    with pytest.raises(TimeoutError):
        await app.startup()

    assert timeline == ["start:first", "stop:first"]
    assert app.state is ApplicationState.FAILED


@pytest.mark.asyncio
async def test_startup_timeout_repeatedly_cancels_resistant_hook_and_rolls_back() -> None:
    settings = Settings(
        environment="test",
        database_url="postgresql+psycopg://test:test@db/test",
        database_readiness_enabled=False,
        startup_timeout_seconds=0.01,
    )
    app = BusinessOSApplication(settings, router=Router(), container=Container())
    timeline: list[str] = []

    async def start_first() -> None:
        timeline.append("start:first")

    async def stop_first() -> None:
        timeline.append("stop:first")

    async def resistant_start() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            timeline.append("start:cancel-once")
            await asyncio.sleep(1)

    app.add_lifecycle("first", start_first, stop_first)
    app.add_lifecycle("resistant", resistant_start, lambda: asyncio.sleep(0))
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        await app.startup()

    assert time.monotonic() - started < 0.2
    assert timeline == ["start:first", "start:cancel-once", "stop:first"]
    assert app.state is ApplicationState.FAILED


@pytest.mark.asyncio
async def test_simultaneous_startup_is_serialized_and_idempotent() -> None:
    app = create_application(_settings())
    startup_calls = 0
    shutdown_calls = 0

    async def start() -> None:
        nonlocal startup_calls
        startup_calls += 1
        await asyncio.sleep(0)

    async def stop() -> None:
        nonlocal shutdown_calls
        shutdown_calls += 1

    app.add_lifecycle("counted", start, stop)
    await asyncio.gather(*(app.startup() for _ in range(50)))
    assert startup_calls == 1
    assert app.state is ApplicationState.RUNNING
    await asyncio.gather(*(app.shutdown() for _ in range(50)))
    assert shutdown_calls == 1
    assert app.state.value == ApplicationState.STOPPED.value


@pytest.mark.asyncio
async def test_repeated_shutdown_cancellation_cannot_interrupt_cleanup() -> None:
    app = create_application(_settings())
    timeline: list[str] = []
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()

    async def start() -> None:
        return None

    async def stop_first() -> None:
        timeline.append("stop:first")

    async def stop_second() -> None:
        timeline.append("stop:second:begin")
        cleanup_started.set()
        await release_cleanup.wait()
        timeline.append("stop:second:end")

    app.add_lifecycle("first", start, stop_first)
    app.add_lifecycle("second", start, stop_second)
    await app.startup()
    task = asyncio.create_task(app.shutdown())
    await cleanup_started.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    release_cleanup.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert timeline == ["stop:second:begin", "stop:second:end", "stop:first"]
    assert app.state.value == ApplicationState.STOPPED.value
    assert task.cancelling() == 0
    await app.shutdown()


@pytest.mark.asyncio
async def test_shutdown_timeout_continues_cleanup_and_reports_failure() -> None:
    settings = Settings(
        environment="test",
        database_url="postgresql+psycopg://test:test@db/test",
        database_readiness_enabled=False,
        shutdown_timeout_seconds=0.01,
    )
    app = create_application(settings)
    timeline: list[str] = []

    async def start() -> None:
        return None

    async def stuck() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            timeline.append("stuck:cancelled")

    async def still_runs() -> None:
        timeline.append("next:ran")

    app.add_lifecycle("next", start, still_runs)
    app.add_lifecycle("stuck", start, stuck)
    await app.startup()
    with pytest.raises(BaseExceptionGroup) as raised:
        await app.shutdown()

    assert any(isinstance(error, TimeoutError) for error in raised.value.exceptions)
    assert timeline == ["stuck:cancelled", "next:ran"]
    assert app.state is ApplicationState.FAILED


@pytest.mark.asyncio
async def test_shutdown_timeout_repeatedly_cancels_resistant_hook_within_bound() -> None:
    settings = Settings(
        environment="test",
        database_url="postgresql+psycopg://test:test@db/test",
        database_readiness_enabled=False,
        shutdown_timeout_seconds=0.01,
    )
    app = BusinessOSApplication(settings, router=Router(), container=Container())
    timeline: list[str] = []

    async def start() -> None:
        return None

    async def still_runs() -> None:
        timeline.append("next:ran")

    async def resistant_stop() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            timeline.append("stop:cancel-once")
            await asyncio.sleep(1)

    app.add_lifecycle("next", start, still_runs)
    app.add_lifecycle("resistant", start, resistant_stop)
    await app.startup()
    started = time.monotonic()
    with pytest.raises(BaseExceptionGroup) as raised:
        await app.shutdown()

    assert time.monotonic() - started < 0.2
    assert any(isinstance(error, TimeoutError) for error in raised.value.exceptions)
    assert timeline == ["stop:cancel-once", "next:ran"]
    assert app.state is ApplicationState.FAILED
    active_names = {task.get_name() for task in asyncio.all_tasks() if not task.done()}
    assert "businessos-lifecycle-startup-hook" not in active_names
    assert "businessos-lifecycle-hook-cancellation" not in active_names


@pytest.mark.asyncio
async def test_readiness_and_request_admission_follow_lifecycle_state() -> None:
    app = create_application(_settings())
    stopping = asyncio.Event()
    release = asyncio.Event()

    async def route(_: Request, __: object) -> Response:
        return Response.text("ok")

    async def stop() -> None:
        stopping.set()
        await release.wait()

    app.router.add_route("GET", "/work", route)
    app.add_lifecycle("blocking-stop", lambda: asyncio.sleep(0), stop)
    transport = httpx.ASGITransport(app=cast(Any, app))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/readyz")).status_code == 503
        assert (await client.get("/work")).status_code == 503
        await app.startup()
        assert (await client.get("/readyz")).status_code == 200
        assert (await client.get("/work")).status_code == 200
        shutdown = asyncio.create_task(app.shutdown())
        await stopping.wait()
        assert (await client.get("/readyz")).status_code == 503
        assert (await client.get("/work")).status_code == 503
        release.set()
        await shutdown
        assert (await client.get("/readyz")).status_code == 503


@pytest.mark.asyncio
async def test_shutdown_rejects_new_work_and_drains_admitted_request() -> None:
    app = create_application(_settings())
    request_started = asyncio.Event()
    release_request = asyncio.Event()
    module_stop_started = asyncio.Event()

    async def route(_: Request, __: object) -> Response:
        request_started.set()
        await release_request.wait()
        return Response.text("done")

    async def stop() -> None:
        module_stop_started.set()

    app.router.add_route("GET", "/slow", route)
    app.add_lifecycle("drained", lambda: asyncio.sleep(0), stop)
    await app.startup()
    transport = httpx.ASGITransport(app=cast(Any, app))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        admitted = asyncio.create_task(client.get("/slow"))
        await request_started.wait()
        shutdown = asyncio.create_task(app.shutdown())
        await asyncio.sleep(0)
        assert app.state is ApplicationState.STOPPING
        refused = await client.get("/slow")
        assert refused.status_code == 503
        assert not module_stop_started.is_set()
        release_request.set()
        assert (await admitted).status_code == 200
        await shutdown

    assert module_stop_started.is_set()
    assert app.state.value == ApplicationState.STOPPED.value


@pytest.mark.asyncio
async def test_shutdown_aggregates_multiple_cleanup_failures() -> None:
    app = create_application(_settings())
    timeline: list[str] = []

    async def start() -> None:
        return None

    def failing_stop(name: str) -> Any:
        async def stop() -> None:
            timeline.append(name)
            raise RuntimeError(name)

        return stop

    app.add_lifecycle("first", start, failing_stop("first"))
    app.add_lifecycle("second", start, failing_stop("second"))
    await app.startup()
    with pytest.raises(BaseExceptionGroup) as raised:
        await app.shutdown()

    assert timeline == ["second", "first"]
    assert len(raised.value.exceptions) == 2
    assert app.state is ApplicationState.FAILED


@pytest.mark.asyncio
async def test_container_close_failure_is_aggregated_and_state_is_failed() -> None:
    class FailingContainer(Container):
        async def close(self) -> None:
            await super().close()
            raise RuntimeError("container close failed")

    app = BusinessOSApplication(
        _settings(),
        router=Router(),
        container=FailingContainer(),
    )
    await app.startup()
    with pytest.raises(BaseExceptionGroup) as raised:
        await app.shutdown()

    assert len(raised.value.exceptions) == 1
    assert isinstance(raised.value.exceptions[0], RuntimeError)
    assert app.state is ApplicationState.FAILED


@pytest.mark.asyncio
async def test_asgi_lifespan_drives_startup_and_shutdown_to_completion() -> None:
    app = create_application(_settings())
    inbound: asyncio.Queue[dict[str, str]] = asyncio.Queue()
    outbound: list[dict[str, str]] = []
    await inbound.put({"type": "lifespan.startup"})
    await inbound.put({"type": "lifespan.shutdown"})

    async def receive() -> dict[str, str]:
        return await inbound.get()

    async def send(message: dict[str, str]) -> None:
        outbound.append(message)

    await app(
        cast(
            Any,
            {
                "type": "lifespan",
                "asgi": {"version": "3.0", "spec_version": "2.0"},
                "state": {},
            },
        ),
        cast(Any, receive),
        cast(Any, send),
    )

    assert outbound == [
        {"type": "lifespan.startup.complete"},
        {"type": "lifespan.shutdown.complete"},
    ]
    assert app.state is ApplicationState.STOPPED
