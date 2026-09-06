"""Custom BusinessOS ASGI application and lifecycle."""

import logging
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import cast

from asgiref.typing import (
    ASGIReceiveCallable,
    ASGISendCallable,
    HTTPScope,
    LifespanScope,
)

from businessos.config import Settings
from businessos.context import RequestContext
from businessos.di import Container, RequestDependencyScope
from businessos.errors import BusinessOSError
from businessos.http import Request, Response, Router
from businessos.http.middleware import ContextMiddleware, Middleware, compose_middleware

LifecycleHook = Callable[[], Awaitable[None]]


class ApplicationState(StrEnum):
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class BusinessOSApplication:
    """Framework-owned ASGI application independent of Uvicorn internals."""

    def __init__(self, settings: Settings, *, router: Router, container: Container) -> None:
        self.settings = settings
        self.router = router
        self.container = container
        self.state = ApplicationState.CREATED
        self._middleware: list[Middleware] = [ContextMiddleware()]
        self._startup_hooks: list[LifecycleHook] = []
        self._shutdown_hooks: list[LifecycleHook] = []
        self._logger = logging.getLogger("businessos.application")

    def add_middleware(self, middleware: Middleware) -> None:
        if self.state is not ApplicationState.CREATED:
            raise RuntimeError("Middleware can only be registered before application startup")
        self._middleware.append(middleware)

    def on_startup(self, hook: LifecycleHook) -> None:
        self._startup_hooks.append(hook)

    def on_shutdown(self, hook: LifecycleHook) -> None:
        self._shutdown_hooks.append(hook)

    async def startup(self) -> None:
        if self.state is ApplicationState.RUNNING:
            return
        if self.state not in {ApplicationState.CREATED, ApplicationState.STOPPED}:
            raise RuntimeError(f"Cannot start application from state {self.state}")
        self.state = ApplicationState.STARTING
        try:
            for hook in self._startup_hooks:
                await hook()
        except Exception:
            self.state = ApplicationState.FAILED
            raise
        self.state = ApplicationState.RUNNING

    async def shutdown(self) -> None:
        if self.state is ApplicationState.STOPPED:
            return
        self.state = ApplicationState.STOPPING
        errors: list[Exception] = []
        for hook in reversed(self._shutdown_hooks):
            try:
                await hook()
            except Exception as exc:
                errors.append(exc)
        await self.container.close()
        self.state = ApplicationState.STOPPED if not errors else ApplicationState.FAILED
        if errors:
            raise ExceptionGroup("Application shutdown failed", errors)

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
        generated_context = RequestContext()
        context = RequestContext(
            correlation_id=(
                self._header(scope, "x-correlation-id") or generated_context.correlation_id
            ),
            trace_id=self._header(scope, "traceparent") or generated_context.trace_id,
        )
        try:
            match = self.router.match(scope["method"], scope["path"])
            request = Request(
                scope,
                receive,
                context,
                path_params=match.path_params,
                body_limit_bytes=self.settings.request_body_limit_bytes,
            )
            async with self.container.request_scope() as dependencies:
                endpoint = self._endpoint(match.route.handler, dependencies)
                response = await compose_middleware(tuple(self._middleware), endpoint)(request)
        except BusinessOSError as exc:
            response = Response.json(exc.payload(), status_code=exc.status_code)
        except Exception:
            self._logger.exception("Unhandled request failure")
            response = Response.json(
                {"code": "internal_error", "message": "Internal server error"},
                status_code=500,
            )
        if scope["method"] == "HEAD":
            response.body = b""
        await response.send(send)

    @staticmethod
    def _endpoint(
        handler: Callable[[Request, RequestDependencyScope], Awaitable[Response]],
        dependencies: RequestDependencyScope,
    ) -> Callable[[Request], Awaitable[Response]]:
        async def endpoint(request: Request) -> Response:
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
                    await send({"type": "lifespan.startup.failed", "message": str(exc)})
                else:
                    await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                try:
                    await self.shutdown()
                except Exception as exc:
                    await send({"type": "lifespan.shutdown.failed", "message": str(exc)})
                else:
                    await send({"type": "lifespan.shutdown.complete"})
                return

    @staticmethod
    def _header(scope: HTTPScope, name: str) -> str | None:
        target = name.encode("latin-1")
        for key, value in scope.get("headers", []):
            if key.lower() == target:
                return value.decode("latin-1")
        return None
