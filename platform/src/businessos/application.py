"""Custom BusinessOS ASGI application and lifecycle."""

import logging
from collections.abc import Awaitable, Callable
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
from businessos.errors import BusinessOSError
from businessos.http import Request, Response, Router
from businessos.http.middleware import ContextMiddleware, Middleware, compose_middleware
from businessos.security import (
    AnonymousContextResolver,
    RequestIdentity,
    TrustedContextResolver,
)

if TYPE_CHECKING:
    from businessos.runtime import FrameworkRuntime

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
        self.state = ApplicationState.CREATED
        self._context_resolver = context_resolver or AnonymousContextResolver()
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
        try:
            generated_context = RequestContext()
            headers = self._headers(scope)
            identity = RequestIdentity(
                method=scope["method"],
                path=scope["path"],
                headers=headers,
                correlation_id=headers.get("x-correlation-id", generated_context.correlation_id),
                trace_id=headers.get("traceparent", generated_context.trace_id),
            )
            context = await self._context_resolver.resolve(identity)
            match = self.router.match(scope["method"], scope["path"])
            request = Request(
                scope,
                receive,
                context,
                path_params=match.path_params,
                body_limit_bytes=self.settings.request_body_limit_bytes,
            )
            async with self.container.request_scope() as dependencies:
                endpoint = self._endpoint(
                    match.route.handler,
                    dependencies,
                    permission=match.route.permission,
                )
                response = await compose_middleware(tuple(self._middleware), endpoint)(request)
        except BusinessOSError as exc:
            response = Response.json(exc.payload(), status_code=exc.status_code)
        except ValidationError as exc:
            response = Response.json(
                {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "details": {"errors": exc.errors(include_url=False)},
                },
                status_code=422,
            )
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
    def _headers(scope: HTTPScope) -> dict[str, str]:
        return {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
