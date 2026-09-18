"""Explicit framework-owned dependency registration and scopes."""

import asyncio
import inspect
from asyncio import Task
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from contextvars import Context, ContextVar, copy_context
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
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


class _RequestScopeState(StrEnum):
    NEW = "new"
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


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


@dataclass(slots=True)
class _RequestResourceOwner:
    """Own resource entry and exit in one explicit context."""

    context: Context
    stack: AsyncExitStack

    async def close(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        closing = asyncio.create_task(
            self.stack.__aexit__(exc_type, exc_value, traceback),
            context=self.context,
            name="businessos-di-request-resource-cleanup",
        )
        await closing


class Container:
    """Application dependency registry; request scopes own their resource teardown."""

    def __init__(self) -> None:
        self._registrations: dict[DependencyKey[Any], _Registration] = {}
        self._singletons: dict[DependencyKey[Any], object] = {}
        self._singleton_stacks: dict[DependencyKey[Any], AsyncExitStack] = {}
        self._singleton_order: list[DependencyKey[Any]] = []
        self._singleton_flights: dict[DependencyKey[Any], Task[object]] = {}
        self._singleton_waits: dict[DependencyKey[Any], dict[DependencyKey[Any], int]] = {}
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
        request_flights: dict[DependencyKey[Any], Task[object]],
        request_waits: dict[DependencyKey[Any], dict[DependencyKey[Any], int]],
        start_initialization: Callable[[DependencyKey[Any], _Registration, bool], Task[object]],
    ) -> T:
        registration = self._registration_for_resolution(key)
        if registration.scope is DependencyScope.SINGLETON:
            return cast(T, await self._resolve_singleton(key, registration))
        if registration.scope is DependencyScope.REQUEST and key in request_cache:
            return cast(T, request_cache[key])
        if registration.scope is DependencyScope.REQUEST:
            wait_edges = self._add_wait_chain(request_waits, _resolution_path.get(), key)
            flight = request_flights.get(key)
            if flight is None:
                flight = start_initialization(key, registration, True)
                flight.add_done_callback(self._consume_flight_result)
                request_flights[key] = flight
            try:
                return cast(T, await asyncio.shield(flight))
            finally:
                for source, target in reversed(wait_edges):
                    self._remove_wait(request_waits, source, target)
        return cast(T, await asyncio.shield(start_initialization(key, registration, False)))

    def _registration_for_resolution(self, key: DependencyKey[Any]) -> _Registration:
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
        return registration

    async def _resolve_singleton(
        self,
        key: DependencyKey[Any],
        registration: _Registration,
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
                self._initialize_singleton(key, registration),
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
    ) -> object:
        stack = AsyncExitStack()
        await stack.__aenter__()
        resolver = _SingletonDependencyResolver(self, stack, key)
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

    async def resolve_for_singleton(
        self,
        key: DependencyKey[T],
        stack: AsyncExitStack,
        resolver: DependencyResolver,
        owner: DependencyKey[Any],
    ) -> T:
        registration = self._registration_for_resolution(key)
        if registration.scope is DependencyScope.REQUEST:
            raise ConfigurationError(
                f"Singleton dependency '{owner.name}' cannot capture request-scoped "
                f"dependency '{key.name}'"
            )
        if registration.scope is DependencyScope.SINGLETON:
            return cast(T, await self._resolve_singleton(key, registration))
        return cast(T, await self._provide(key, registration, resolver, stack))

    async def provide_for_request(
        self,
        key: DependencyKey[Any],
        registration: _Registration,
        resolver: DependencyResolver,
        stack: AsyncExitStack,
    ) -> object:
        """Invoke a provider within its request-owned resource stack."""

        return await self._provide(key, registration, resolver, stack)

    def _add_singleton_wait(
        self,
        source: DependencyKey[Any],
        target: DependencyKey[Any],
    ) -> None:
        self._add_wait(self._singleton_waits, source, target)

    def _remove_singleton_wait(
        self,
        source: DependencyKey[Any],
        target: DependencyKey[Any],
    ) -> None:
        self._remove_wait(self._singleton_waits, source, target)

    @classmethod
    def _add_wait_chain(
        cls,
        graph: dict[DependencyKey[Any], dict[DependencyKey[Any], int]],
        ancestry: tuple[DependencyKey[Any], ...],
        target: DependencyKey[Any],
    ) -> tuple[tuple[DependencyKey[Any], DependencyKey[Any]], ...]:
        chain = (*ancestry, target)
        edges: list[tuple[DependencyKey[Any], DependencyKey[Any]]] = []
        try:
            for source, dependency in pairwise(chain):
                cls._add_wait(graph, source, dependency)
                edges.append((source, dependency))
        except BaseException:
            for source, dependency in reversed(edges):
                cls._remove_wait(graph, source, dependency)
            raise
        return tuple(edges)

    @classmethod
    def _add_wait(
        cls,
        graph: dict[DependencyKey[Any], dict[DependencyKey[Any], int]],
        source: DependencyKey[Any],
        target: DependencyKey[Any],
    ) -> None:
        waits = graph.setdefault(source, {})
        waits[target] = waits.get(target, 0) + 1
        path = cls._wait_path(graph, target, source, set())
        if path is None:
            return
        cls._remove_wait(graph, source, target)
        cycle = (source, *path)
        names = " -> ".join(item.name for item in cycle)
        raise ConfigurationError(f"Dependency cycle detected: {names}")

    @staticmethod
    def _remove_wait(
        graph: dict[DependencyKey[Any], dict[DependencyKey[Any], int]],
        source: DependencyKey[Any],
        target: DependencyKey[Any],
    ) -> None:
        waits = graph.get(source)
        if waits is None:
            return
        count = waits.get(target, 0)
        if count > 1:
            waits[target] = count - 1
        else:
            waits.pop(target, None)
        if not waits:
            graph.pop(source, None)

    @classmethod
    def _wait_path(
        cls,
        graph: dict[DependencyKey[Any], dict[DependencyKey[Any], int]],
        current: DependencyKey[Any],
        target: DependencyKey[Any],
        visited: set[DependencyKey[Any]],
    ) -> tuple[DependencyKey[Any], ...] | None:
        if current == target:
            return (current,)
        if current in visited:
            return None
        visited.add(current)
        for dependency in sorted(graph.get(current, ()), key=lambda item: item.name):
            path = cls._wait_path(graph, dependency, target, visited)
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
        self._flights: dict[DependencyKey[Any], Task[object]] = {}
        self._waits: dict[DependencyKey[Any], dict[DependencyKey[Any], int]] = {}
        self._initializers: set[Task[object]] = set()
        self._resource_owners: list[_RequestResourceOwner] = []
        self._cleanup_task: Task[None] | None = None
        self._state = _RequestScopeState.NEW

    async def __aenter__(self) -> "RequestDependencyScope":
        if self._state is not _RequestScopeState.NEW:
            raise ConfigurationError("Dependency scope cannot be re-entered")
        self._state = _RequestScopeState.OPEN
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._state = _RequestScopeState.CLOSING
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(
                self._cleanup(exc_type, exc_value, traceback),
                name="businessos-di-request-scope-cleanup",
            )
        cancelled = False
        try:
            while True:
                try:
                    await asyncio.shield(self._cleanup_task)
                    break
                except asyncio.CancelledError:
                    cancelled = True
        finally:
            self._cache.clear()
            self._flights.clear()
            self._waits.clear()
            self._initializers.clear()
            self._resource_owners.clear()
            self._state = _RequestScopeState.CLOSED
        if cancelled:
            raise asyncio.CancelledError

    async def resolve(self, key: DependencyKey[T]) -> T:
        if self._state is not _RequestScopeState.OPEN:
            raise ConfigurationError("Dependency scope must be entered before resolution")
        return await self._container.resolve_for_scope(
            key,
            self._cache,
            self._flights,
            self._waits,
            self._start_initialization,
        )

    def _start_initialization(
        self,
        key: DependencyKey[Any],
        registration: _Registration,
        cache_result: bool,
    ) -> Task[object]:
        owner = _RequestResourceOwner(copy_context(), AsyncExitStack())
        task = asyncio.create_task(
            self._initialize_owned(key, registration, cache_result, owner),
            context=owner.context,
            name=f"businessos-di-request:{key.name}",
        )
        self._initializers.add(task)
        task.add_done_callback(self._initialization_finished)
        return task

    async def _initialize_owned(
        self,
        key: DependencyKey[Any],
        registration: _Registration,
        cache_result: bool,
        owner: _RequestResourceOwner,
    ) -> object:
        await owner.stack.__aenter__()
        try:
            value = await self._container.provide_for_request(key, registration, self, owner.stack)
            if self._state is not _RequestScopeState.OPEN:
                raise ConfigurationError("Dependency scope closed during resolution")
            if cache_result:
                self._cache[key] = value
            self._resource_owners.append(owner)
            return value
        except BaseException:
            await owner.stack.aclose()
            raise

    def _initialization_finished(self, task: Task[object]) -> None:
        self._initializers.discard(task)
        if not task.cancelled():
            task.exception()
        for key, flight in tuple(self._flights.items()):
            if flight is task:
                self._flights.pop(key, None)

    async def _cleanup(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        initializers = tuple(self._initializers)
        for initializer in initializers:
            initializer.cancel()
        if initializers:
            await asyncio.gather(*initializers, return_exceptions=True)
        errors: list[BaseException] = []
        for owner in reversed(self._resource_owners):
            try:
                await owner.close(exc_type, exc_value, traceback)
            except BaseException as error:
                errors.append(error)
        if errors:
            raise BaseExceptionGroup("Dependency cleanup failed", errors)


class _SingletonDependencyResolver(DependencyResolver):
    """Resolve a singleton graph against its own lifetime boundary."""

    def __init__(
        self,
        container: Container,
        stack: AsyncExitStack,
        owner: DependencyKey[Any],
    ) -> None:
        self._container = container
        self._stack = stack
        self._owner = owner

    async def resolve(self, key: DependencyKey[T]) -> T:
        return await self._container.resolve_for_singleton(key, self._stack, self, self._owner)
