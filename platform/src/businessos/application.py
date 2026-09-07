"""Custom BusinessOS ASGI application and lifecycle."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, cast

from asgiref.typing import (
    ASGIReceiveCallable,
    ASGISendCallable,
    HTTPScope,
    LifespanScope,
)
from pydantic import ValidationError

from businessos.config import Settings
from businessos.context import RequestContext
from businessos.dependencies import AUTHORIZER
from businessos.di import Container, RequestDependencyScope
from businessos.errors import BusinessOSError, ClientDisconnectedError
from businessos.http import Request, Response, Router
from businessos.http.middleware import ContextMiddleware, Middleware, compose_middleware
from businessos.security import (
    AnonymousContextResolver,
    RequestIdentity,
    TrustedContextResolver,
)
from businessos.telemetry import server_span

if TYPE_CHECKING:
    from businessos.runtime import FrameworkRuntime

LifecycleHook = Callable[[], Awaitable[None]]


def _public_validation_errors(exc: ValidationError) -> list[dict[str, object]]:
    """Return only allowlisted validation metadata, never exception-derived text."""
    public: list[dict[str, object]] = []
    for error in exc.errors(include_url=False, include_input=False, include_context=False):
        error_type = error.get("type")
        if error_type == "missing":
            code, message = "required", "Field is required"
        elif error_type == "json_invalid":
            code, message = "invalid_json", "Request body is not valid JSON"
        else:
            code, message = "invalid_value", "Value is not valid"
        location = list(error.get("loc", ()))
        public.append({"code": code, "location": location, "message": message})
    return public


class ApplicationState(StrEnum):
    NEW = "new"
    CREATED = "new"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class _LifecycleComponent:
    name: str
    startup: LifecycleHook
    shutdown: LifecycleHook


class BusinessOSApplication:
    """Framework-owned ASGI application independent of Uvicorn internals."""

    def __init__(
        self,
        settings: Settings,
        *,
        router: Router,
        container: Container,
        runtime: "FrameworkRuntime | None" = None,
        context_resolver: TrustedContextResolver | None = None,
    ) -> None:
        self.settings = settings
        self.router = router
        self.container = container
        self.runtime = runtime
        self.state = ApplicationState.NEW
        self._context_resolver = context_resolver or AnonymousContextResolver()
        self._middleware: list[Middleware] = [ContextMiddleware()]
        self._startup_hooks: list[LifecycleHook] = []
        self._shutdown_hooks: list[LifecycleHook] = []
        self._components: list[_LifecycleComponent] = []
        self._started_components: list[_LifecycleComponent] = []
        self._lifecycle_lock = asyncio.Lock()
        self._active_requests = 0
        self._requests_drained = asyncio.Event()
        self._requests_drained.set()
        self._cleanup_complete = False
        self._logger = logging.getLogger("businessos.application")

    def add_middleware(self, middleware: Middleware) -> None:
        if self.state is not ApplicationState.NEW:
            raise RuntimeError("Middleware can only be registered before application startup")
        self._middleware.append(middleware)

    def on_startup(self, hook: LifecycleHook) -> None:
        self._startup_hooks.append(hook)

    def on_shutdown(self, hook: LifecycleHook) -> None:
        self._shutdown_hooks.append(hook)

    def add_lifecycle(
        self,
        name: str,
        startup: LifecycleHook,
        shutdown: LifecycleHook,
    ) -> None:
        if self.state is not ApplicationState.NEW:
            raise RuntimeError("Lifecycle components can only be added before startup")
        self._components.append(_LifecycleComponent(name, startup, shutdown))

    async def readiness(self) -> None:
        if self.state is not ApplicationState.RUNNING:
            raise RuntimeError("Application lifecycle is not running")

    async def startup(self) -> None:
        async with self._lifecycle_lock:
            if self.state is ApplicationState.RUNNING:
                return
            if self.state is not ApplicationState.NEW:
                raise RuntimeError(f"Cannot start application from state {self.state}")
            self.state = ApplicationState.STARTING
            completed: list[_LifecycleComponent] = []
            deadline = asyncio.get_running_loop().time() + self.settings.startup_timeout_seconds
            try:
                for component in self._components:
                    await self._run_startup_hook(component.startup, deadline=deadline)
                    completed.append(component)
                    self._started_components.append(component)
                for hook in self._startup_hooks:
                    await self._run_startup_hook(hook, deadline=deadline)
            except BaseException as startup_error:
                rollback_task = asyncio.create_task(
                    self._startup_rollback(completed),
                    name="businessos-startup-rollback",
                )
                rollback_error, _ = await self._await_cleanup(rollback_task)
                self.state = ApplicationState.FAILED
                self._cleanup_complete = True
                self._started_components.clear()
                if rollback_error is not None:
                    raise BaseExceptionGroup(
                        "Application startup and rollback failed",
                        [startup_error, rollback_error],
                    ) from None
                raise
            self.state = ApplicationState.RUNNING

    async def shutdown(self) -> None:
        async with self._lifecycle_lock:
            if self.state is ApplicationState.STOPPED or self._cleanup_complete:
                return
            if self.state is ApplicationState.NEW:
                self.state = ApplicationState.STOPPING
            elif self.state not in {ApplicationState.RUNNING, ApplicationState.FAILED}:
                raise RuntimeError(f"Cannot stop application from state {self.state}")
            else:
                self.state = ApplicationState.STOPPING
            cleanup_task = asyncio.create_task(
                self._shutdown_sequence(),
                name="businessos-shutdown",
            )
            cleanup_error, cancellation_count = await self._await_cleanup(cleanup_task)
            self._cleanup_complete = True
            self.state = (
                ApplicationState.STOPPED if cleanup_error is None else ApplicationState.FAILED
            )
            if cleanup_error is not None:
                raise cleanup_error
            if cancellation_count:
                raise asyncio.CancelledError

    async def _startup_rollback(
        self,
        completed: list[_LifecycleComponent],
    ) -> None:
        deadline = asyncio.get_running_loop().time() + self.settings.shutdown_timeout_seconds
        errors = await self._run_cleanup_hooks(
            [component.shutdown for component in reversed(completed)],
            include_finalizers=True,
            deadline=deadline,
        )
        if errors:
            raise BaseExceptionGroup("Application startup rollback failed", errors)

    async def _shutdown_sequence(self) -> None:
        errors: list[BaseException] = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.settings.shutdown_timeout_seconds
        try:
            async with asyncio.timeout(max(0.0, deadline - loop.time())):
                await self._requests_drained.wait()
        except BaseException as exc:
            errors.append(exc)
            await self._requests_drained.wait()
        errors.extend(
            await self._run_cleanup_hooks(
                [component.shutdown for component in reversed(self._started_components)],
                include_finalizers=True,
                deadline=deadline,
            )
        )
        self._started_components.clear()
        if errors:
            raise BaseExceptionGroup("Application shutdown failed", errors)

    async def _run_cleanup_hooks(
        self,
        hooks: list[LifecycleHook],
        *,
        include_finalizers: bool,
        deadline: float,
    ) -> list[BaseException]:
        errors: list[BaseException] = []
        cleanup_hooks = [*hooks]
        if include_finalizers:
            cleanup_hooks.extend(reversed(self._shutdown_hooks))
            cleanup_hooks.append(self.container.close)
        for hook in cleanup_hooks:

            async def run_hook(current_hook: LifecycleHook = hook) -> None:
                await current_hook()

            task: asyncio.Task[None] = asyncio.create_task(run_hook())
            remaining = max(0.0, deadline - asyncio.get_running_loop().time())
            done, _ = await asyncio.wait((task,), timeout=remaining)
            if task in done:
                try:
                    task.result()
                except BaseException as exc:
                    errors.append(exc)
                continue
            errors.append(TimeoutError("Application lifecycle cleanup timed out"))
            cancellation_task = asyncio.create_task(
                self._cancel_owned_task(task),
                name="businessos-lifecycle-hook-cancellation",
            )
            cancellation_error, _ = await self._await_cleanup(cancellation_task)
            if cancellation_error is not None:
                errors.append(cancellation_error)
        return errors

    async def _run_startup_hook(self, hook: LifecycleHook, *, deadline: float) -> None:
        async def run_hook() -> None:
            await hook()

        task: asyncio.Task[None] = asyncio.create_task(
            run_hook(), name="businessos-lifecycle-startup-hook"
        )
        remaining = max(0.0, deadline - asyncio.get_running_loop().time())
        try:
            done, _ = await asyncio.wait((task,), timeout=remaining)
        except BaseException as startup_error:
            cancellation_task = asyncio.create_task(
                self._cancel_owned_task(task),
                name="businessos-startup-hook-cancellation",
            )
            cancellation_error, _ = await self._await_cleanup(cancellation_task)
            if cancellation_error is not None:
                raise BaseExceptionGroup(
                    "Application startup interruption and hook cleanup failed",
                    [startup_error, cancellation_error],
                ) from None
            raise
        if task in done:
            task.result()
            return
        timeout_error = TimeoutError("Application lifecycle startup timed out")
        cancellation_task = asyncio.create_task(
            self._cancel_owned_task(task),
            name="businessos-startup-hook-cancellation",
        )
        cancellation_error, _ = await self._await_cleanup(cancellation_task)
        if cancellation_error is not None:
            raise BaseExceptionGroup(
                "Application startup timeout and hook cleanup failed",
                [timeout_error, cancellation_error],
            ) from None
        raise timeout_error

    @staticmethod
    async def _cancel_owned_task(task: asyncio.Task[None]) -> None:
        for _ in range(8):
            if task.done():
                break
            task.cancel()
            await asyncio.sleep(0)
        if not task.done():
            # Never report terminal shutdown while framework-owned work survives.
            # The ASGI process supervisor owns any hard process deadline.
            await BusinessOSApplication._await_cleanup(task)
        try:
            task.result()
        except asyncio.CancelledError:
            return

    @staticmethod
    def _consume_task_result(task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()

    @staticmethod
    async def _await_cleanup(
        cleanup_task: asyncio.Task[None],
    ) -> tuple[BaseException | None, int]:
        cancellation_count = 0
        current = asyncio.current_task()
        while not cleanup_task.done():
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                cancellation_count += 1
                if current is not None:
                    while current.cancelling():
                        current.uncancel()
            except BaseException as exc:
                return exc, cancellation_count
        try:
            cleanup_task.result()
        except BaseException as exc:
            return exc, cancellation_count
        return None, cancellation_count

    async def __call__(
        self, scope: object, receive: ASGIReceiveCallable, send: ASGISendCallable
    ) -> None:
        scope_type = cast(dict[str, object], scope).get("type")
        if scope_type == "lifespan":
            await self._handle_lifespan(cast(LifespanScope, scope), receive, send)
            return
        if scope_type == "http":
            await self._handle_http(cast(HTTPScope, scope), receive, send)
            return
        raise RuntimeError(f"Unsupported ASGI scope type: {scope_type}")

    async def _handle_http(
        self, scope: HTTPScope, receive: ASGIReceiveCallable, send: ASGISendCallable
    ) -> None:
        headers = self._headers(scope)
        with server_span(scope["method"], scope["path"], headers) as trace_id:
            await self._handle_http_traced(scope, receive, send, headers, trace_id)

    async def _handle_http_traced(
        self,
        scope: HTTPScope,
        receive: ASGIReceiveCallable,
        send: ASGISendCallable,
        headers: dict[str, str],
        trace_id: str,
    ) -> None:
        admitted = False
        try:
            generated_context = RequestContext(trace_id=trace_id)
            response_context = generated_context
            try:
                if not self._is_operational_path(scope["path"]):
                    if self.state is not ApplicationState.RUNNING:
                        raise BusinessOSError(
                            "service_unavailable",
                            "Application is not accepting requests",
                            status_code=503,
                            public=True,
                        )
                    self._active_requests += 1
                    self._requests_drained.clear()
                    admitted = True
                identity = RequestIdentity(
                    method=scope["method"],
                    path=scope["path"],
                    headers=headers,
                    correlation_id=headers.get(
                        "x-correlation-id", generated_context.correlation_id
                    ),
                    trace_id=trace_id,
                )
                context = await self._context_resolver.resolve(identity)
                response_context = context
                match = self.router.match(scope["method"], scope["path"])
                request = Request(
                    scope,
                    receive,
                    context,
                    path_params=match.path_params,
                    body_limit_bytes=self.settings.request_body_limit_bytes,
                )
                await request.body()
                dependency_scope = (
                    RequestDependencyScope(self.container)
                    if self._is_operational_path(scope["path"])
                    and self.state in {ApplicationState.STOPPED, ApplicationState.FAILED}
                    else self.container.request_scope()
                )
                async with dependency_scope as dependencies:
                    endpoint = self._endpoint(
                        match.route.handler,
                        dependencies,
                        permission=match.route.permission,
                    )
                    module_middleware = self.runtime.middleware.active() if self.runtime else ()
                    response = await self._run_request_until_disconnect(
                        compose_middleware((*self._middleware, *module_middleware), endpoint),
                        request,
                        receive,
                    )
            except ClientDisconnectedError:
                return
            except BusinessOSError as exc:
                if not exc.public:
                    response = Response.json(
                        {"code": "internal_error", "message": "Internal server error"},
                        status_code=500,
                    )
                else:
                    response = Response.json(
                        exc.payload(),
                        status_code=exc.status_code,
                        headers=exc.headers,
                    )
            except ValidationError as exc:
                response = Response.json(
                    {
                        "code": "validation_error",
                        "message": "Request validation failed",
                        "details": {"errors": _public_validation_errors(exc)},
                    },
                    status_code=422,
                )
            except Exception as exc:
                self._logger.error(
                    "Unhandled request failure",
                    extra={"error_type": type(exc).__name__},
                )
                response = Response.json(
                    {"code": "internal_error", "message": "Internal server error"},
                    status_code=500,
                )
            response.headers.setdefault("x-correlation-id", response_context.correlation_id)
            if scope["method"] == "HEAD":
                response.body = b""
            await response.send(send)

        finally:
            if admitted:
                self._active_requests -= 1
                if self._active_requests == 0:
                    self._requests_drained.set()

    async def _run_request_until_disconnect(
        self,
        endpoint: Callable[[Request], Awaitable[Response]],
        request: Request,
        receive: ASGIReceiveCallable,
    ) -> Response:
        async def invoke() -> Response:
            return await endpoint(request)

        handler: asyncio.Task[Response] = asyncio.create_task(
            invoke(), name="businessos-http-handler"
        )
        disconnected = asyncio.create_task(
            self._wait_for_disconnect(receive),
            name="businessos-http-disconnect-watcher",
        )
        try:
            done, _ = await asyncio.wait(
                (handler, disconnected),
                return_when=asyncio.FIRST_COMPLETED,
            )
        except BaseException:
            handler.cancel()
            disconnected.cancel()
            await asyncio.gather(handler, disconnected, return_exceptions=True)
            raise
        if handler in done:
            disconnected.cancel()
            await asyncio.gather(disconnected, return_exceptions=True)
            return handler.result()
        handler.cancel()
        await asyncio.gather(handler, return_exceptions=True)
        raise ClientDisconnectedError

    @staticmethod
    async def _wait_for_disconnect(receive: ASGIReceiveCallable) -> None:
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return

    @staticmethod
    def _endpoint(
        handler: Callable[[Request, RequestDependencyScope], Awaitable[Response]],
        dependencies: RequestDependencyScope,
        *,
        permission: str | None,
    ) -> Callable[[Request], Awaitable[Response]]:
        async def endpoint(request: Request) -> Response:
            if permission is not None:
                authorizer = await dependencies.resolve(AUTHORIZER)
                await authorizer.require(request.context, permission)
            return await handler(request, dependencies)

        return endpoint

    async def _handle_lifespan(
        self,
        _: LifespanScope,
        receive: ASGIReceiveCallable,
        send: ASGISendCallable,
    ) -> None:
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                try:
                    await self.startup()
                except Exception as exc:
                    self._logger.error(
                        "Application startup failed",
                        extra={"error_type": type(exc).__name__},
                    )
                    await send(
                        {
                            "type": "lifespan.startup.failed",
                            "message": "Application startup failed",
                        }
                    )
                else:
                    await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                try:
                    await self.shutdown()
                except Exception as exc:
                    self._logger.error(
                        "Application shutdown failed",
                        extra={"error_type": type(exc).__name__},
                    )
                    await send(
                        {
                            "type": "lifespan.shutdown.failed",
                            "message": "Application shutdown failed",
                        }
                    )
                else:
                    await send({"type": "lifespan.shutdown.complete"})
                return

    @staticmethod
    def _headers(scope: HTTPScope) -> dict[str, str]:
        return {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }

    @staticmethod
    def _is_operational_path(path: str) -> bool:
        return path in {"/livez", "/readyz", "/version", "/diagnostics/modules"}
