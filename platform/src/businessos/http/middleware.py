"""Ordered BusinessOS middleware contracts and core middleware."""

from collections.abc import Awaitable, Callable
from typing import Protocol

from businessos.context import bind_request_context
from businessos.http.request import Request
from businessos.http.response import Response

CallNext = Callable[[Request], Awaitable[Response]]


class Middleware(Protocol):
    async def __call__(self, request: Request, call_next: CallNext) -> Response: ...


def compose_middleware(middleware: tuple[Middleware, ...], endpoint: CallNext) -> CallNext:
    """Compose middleware in registration order; first registered is outermost."""
    current = endpoint
    for item in reversed(middleware):
        next_handler = current

        async def wrapped(
            request: Request, *, current_item: Middleware = item, next_item: CallNext = next_handler
        ) -> Response:
            return await current_item(request, next_item)

        current = wrapped
    return current


class ContextMiddleware:
    async def __call__(self, request: Request, call_next: CallNext) -> Response:
        with bind_request_context(request.context):
            response = await call_next(request)
        response.headers.setdefault("x-correlation-id", request.context.correlation_id)
        return response
