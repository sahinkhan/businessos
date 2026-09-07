"""Explicit framework-owned dependency registration and scopes."""

import asyncio
import inspect
from asyncio import Task
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from types import TracebackType
from typing import Any, Protocol, TypeVar, cast

from businessos.activation import ContributionGate, ContributionGeneration
from businessos.errors import ConfigurationError, ConflictError

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class DependencyKey[T]:
    """Typed identifier that keeps dependencies explicit across module boundaries."""

    name: str


class DependencyResolver(Protocol):
    async def resolve(self, key: DependencyKey[T]) -> T: ...


class DependencyScope(StrEnum):
    SINGLETON = "singleton"
    REQUEST = "request"
    TRANSIENT = "transient"


Provider = Callable[[DependencyResolver], object | Awaitable[object]]
_resolution_path: ContextVar[tuple[DependencyKey[Any], ...]] = ContextVar(
    "businessos_dependency_resolution_path",
    default=(),
)


@dataclass(frozen=True, slots=True)
class _Registration:
    provider: Provider
    scope: DependencyScope
    owner: str | None = None
    generation: ContributionGeneration | None = None
    gate: ContributionGate | None = None


class Container:
    """Application dependency registry; request scopes own their resource teardown."""

    def __init__(self) -> None:
        self._registrations: dict[DependencyKey[Any], _Registration] = {}
        self._singletons: dict[DependencyKey[Any], object] = {}
        self._singleton_stacks: dict[DependencyKey[Any], AsyncExitStack] = {}
        self._singleton_order: list[DependencyKey[Any]] = []
        self._singleton_flights: dict[DependencyKey[Any], Task[object]] = {}
        self._singleton_waits: dict[DependencyKey[Any], set[DependencyKey[Any]]] = {}
        self._closed = False

    def register(
        self,
        key: DependencyKey[T],
        provider: Callable[
            [DependencyResolver],
            T | Awaitable[T] | AbstractAsyncContextManager[T],
        ],
        *,
        scope: DependencyScope = DependencyScope.TRANSIENT,
        owner: str | None = None,
        generation: ContributionGeneration | None = None,
        gate: ContributionGate | None = None,
    ) -> None:
        if self._closed:
            raise ConfigurationError("Dependency container is closed")
        if key in self._registrations:
            raise ConflictError(f"Dependency already registered: {key.name}")
        self._registrations[key] = _Registration(
            cast(Provider, provider),
            scope,
            owner,
            generation,
            gate,
        )

    def request_scope(self) -> "RequestDependencyScope":
        if self._closed:
            raise ConfigurationError("Dependency container is closed")
        return RequestDependencyScope(self)

    async def close(self) -> None:
        self._closed = True
        flights = tuple(self._singleton_flights.values())
        for flight in flights:
            flight.cancel()
        if flights:
            await asyncio.gather(*flights, return_exceptions=True)
        errors: list[BaseException] = []
        for key in reversed(self._singleton_order):
            try:
                await self._singleton_stacks.pop(key).aclose()
            except BaseException as exc:
                errors.append(exc)
        self._singleton_order.clear()
        self._singletons.clear()
        self._singleton_flights.clear()
        self._singleton_waits.clear()
        self._registrations.clear()
        if errors:
            raise BaseExceptionGroup("Dependency cleanup failed", errors)

    async def remove_owner_generation(self, generation: ContributionGeneration) -> None:
        keys = tuple(
            key
            for key, registration in self._registrations.items()
            if registration.generation == generation
        )
        flights = tuple(
            flight for key in keys if (flight := self._singleton_flights.get(key)) is not None
        )
        if flights:
            await asyncio.gather(*(asyncio.shield(flight) for flight in flights))
        errors: list[BaseException] = []
        for key in reversed(self._singleton_order):
            if key not in keys:
                continue
            try:
                await self._singleton_stacks.pop(key).aclose()
            except BaseException as exc:
                errors.append(exc)
            self._singleton_order.remove(key)
            self._singletons.pop(key, None)
        for key in keys:
            self._registrations.pop(key, None)
        if errors:
            raise BaseExceptionGroup(
                f"Dependency cleanup failed: {generation.owner}/{generation.number}",
                errors,
            )

    async def resolve_for_scope(
        self,
        key: DependencyKey[T],
        request_cache: dict[DependencyKey[Any], object],
        request_stack: AsyncExitStack,
        resolver: DependencyResolver,
    ) -> T:
        if self._closed:
            raise ConfigurationError("Dependency container is closed")
        registration = self._registrations.get(key)
        if registration is None:
            raise ConfigurationError(f"Dependency is not registered: {key.name}")
        if registration.gate is not None and not registration.gate.is_active(
            registration.generation
        ):
            raise ConfigurationError(f"Dependency is not active: {key.name}")
        path = _resolution_path.get()
        if key in path:
            cycle = (*path[path.index(key) :], key)
            names = " -> ".join(item.name for item in cycle)
            raise ConfigurationError(f"Dependency cycle detected: {names}")
        if registration.scope is DependencyScope.SINGLETON:
            return cast(T, await self._resolve_singleton(key, registration, resolver))
        if registration.scope is DependencyScope.REQUEST and key in request_cache:
            return cast(T, request_cache[key])
        value = await self._provide(key, registration, resolver, request_stack)
        if registration.scope is DependencyScope.REQUEST:
            request_cache[key] = value
        return cast(T, value)

    async def _resolve_singleton(
        self,
        key: DependencyKey[Any],
        registration: _Registration,
        resolver: DependencyResolver,
    ) -> object:
        cached = self._singletons.get(key)
        if cached is not None or key in self._singletons:
            return cached
        path = _resolution_path.get()
        parent = path[-1] if path else None
        if parent is not None:
            self._add_singleton_wait(parent, key)
        flight = self._singleton_flights.get(key)
        if flight is None:
            flight = asyncio.create_task(
                self._initialize_singleton(key, registration, resolver),
                name=f"businessos-di:{key.name}",
            )
            flight.add_done_callback(self._consume_flight_result)
            self._singleton_flights[key] = flight
        try:
            return await asyncio.shield(flight)
        finally:
            if parent is not None:
                self._remove_singleton_wait(parent, key)

    async def _initialize_singleton(
        self,
        key: DependencyKey[Any],
        registration: _Registration,
        resolver: DependencyResolver,
    ) -> object:
        stack = AsyncExitStack()
        await stack.__aenter__()
        try:
            value = await self._provide(key, registration, resolver, stack)
            self._singletons[key] = value
            self._singleton_stacks[key] = stack
            self._singleton_order.append(key)
            return value
        except BaseException:
            await stack.aclose()
            raise
        finally:
            current = asyncio.current_task()
            if self._singleton_flights.get(key) is current:
                self._singleton_flights.pop(key, None)

    def _add_singleton_wait(
        self,
        source: DependencyKey[Any],
        target: DependencyKey[Any],
    ) -> None:
        waits = self._singleton_waits.setdefault(source, set())
        waits.add(target)
        path = self._wait_path(target, source, set())
        if path is None:
            return
        waits.remove(target)
        if not waits:
            self._singleton_waits.pop(source, None)
        cycle = (source, *path)
        names = " -> ".join(item.name for item in cycle)
        raise ConfigurationError(f"Dependency cycle detected: {names}")

    def _remove_singleton_wait(
        self,
        source: DependencyKey[Any],
        target: DependencyKey[Any],
    ) -> None:
        waits = self._singleton_waits.get(source)
        if waits is None:
            return
        waits.discard(target)
        if not waits:
            self._singleton_waits.pop(source, None)

    def _wait_path(
        self,
        current: DependencyKey[Any],
        target: DependencyKey[Any],
        visited: set[DependencyKey[Any]],
    ) -> tuple[DependencyKey[Any], ...] | None:
        if current == target:
            return (current,)
        if current in visited:
            return None
        visited.add(current)
        for dependency in sorted(
            self._singleton_waits.get(current, ()), key=lambda item: item.name
        ):
            path = self._wait_path(dependency, target, visited)
            if path is not None:
                return (current, *path)
        return None

    @staticmethod
    def _consume_flight_result(flight: Task[object]) -> None:
        if not flight.cancelled():
            flight.exception()

    async def _provide(
        self,
        key: DependencyKey[Any],
        registration: _Registration,
        resolver: DependencyResolver,
        stack: AsyncExitStack,
    ) -> object:
        token = _resolution_path.set((*_resolution_path.get(), key))
        try:
            if registration.gate is None:
                return await self._invoke_provider(registration.provider, resolver, stack)
            async with registration.gate.admit(registration.generation):
                return await self._invoke_provider(registration.provider, resolver, stack)
        finally:
            _resolution_path.reset(token)

    @staticmethod
    async def _invoke_provider(
        provider: Provider,
        resolver: DependencyResolver,
        stack: AsyncExitStack,
    ) -> object:
        value = provider(resolver)
        if inspect.isawaitable(value):
            value = await value
        if isinstance(value, AbstractAsyncContextManager):
            context_manager = cast(AbstractAsyncContextManager[object], value)
            value = await stack.enter_async_context(context_manager)
        return value


class RequestDependencyScope(
    DependencyResolver, AbstractAsyncContextManager["RequestDependencyScope"]
):
    """One operation-scoped dependency resolver."""

    def __init__(self, container: Container) -> None:
        self._container = container
        self._cache: dict[DependencyKey[Any], object] = {}
        self._exit_stack = AsyncExitStack()
        self._entered = False

    async def __aenter__(self) -> "RequestDependencyScope":
        await self._exit_stack.__aenter__()
        self._entered = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._entered = False
        await self._exit_stack.__aexit__(exc_type, exc_value, traceback)
        self._cache.clear()

    async def resolve(self, key: DependencyKey[T]) -> T:
        if not self._entered:
            raise ConfigurationError("Dependency scope must be entered before resolution")
        return await self._container.resolve_for_scope(key, self._cache, self._exit_stack, self)
