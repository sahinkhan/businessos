"""Ordered BusinessOS middleware contracts and core middleware."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from businessos.activation import ContributionGate, ContributionGeneration
from businessos.context import bind_request_context
from businessos.http.request import Request
from businessos.http.response import Response

CallNext = Callable[[Request], Awaitable[Response]]


class Middleware(Protocol):
    async def __call__(self, request: Request, call_next: CallNext) -> Response: ...


@dataclass(frozen=True, slots=True)
class MiddlewareContribution:
    name: str
    owner: str
    middleware: Middleware
    generation: ContributionGeneration


class MiddlewareRegistry:
    """Deterministic owner-scoped middleware contributions."""

    def __init__(self, gate: ContributionGate) -> None:
        self._gate = gate
        self._items: dict[str, MiddlewareContribution] = {}

    def register(
        self,
        name: str,
        owner: str,
        middleware: Middleware,
        generation: ContributionGeneration,
    ) -> None:
        if name in self._items:
            from businessos.errors import ConflictError

            raise ConflictError(f"Middleware already registered: {name}")
        self._items[name] = MiddlewareContribution(name, owner, middleware, generation)

    def active(self) -> tuple[Middleware, ...]:
        return tuple(
            item.middleware
            for name in sorted(self._items)
            if self._gate.is_active((item := self._items[name]).generation)
        )

    def remove_owner_generation(self, generation: ContributionGeneration) -> None:
        self._items = {
            name: item for name, item in self._items.items() if item.generation != generation
        }


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
