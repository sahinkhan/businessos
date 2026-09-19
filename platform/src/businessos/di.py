"""Explicit framework-owned dependency registration and scopes."""

import asyncio
import inspect
from asyncio import Future, Task
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from contextvars import Context, ContextVar, copy_context
from dataclasses import dataclass, field
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
    """Own resource entry and exit in one explicit context and task."""

    context: Context
    stack: AsyncExitStack
    result: Future[object]
    close_requested: asyncio.Event
    key: DependencyKey[Any]
    registration: _Registration
    dependencies: list["_RequestResourceOwner"] = field(
        default_factory=lambda: list[_RequestResourceOwner]()
    )
    task: Task[None] | None = None
    published: bool = False
    cache_result: bool = False
    shutdown_requested: bool = False
    finalizing: bool = False
    failed_after_publication: bool = False
    initialization_cleanup_error: BaseException | None = None
    resource_cleanup_error: BaseException | None = None
    terminal_failure: BaseException | None = None
    exit_details: tuple[
        type[BaseException] | None,
        BaseException | None,
        TracebackType | None,
    ] = (None, None, None)

    def request_close(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.exit_details = (exc_type, exc_value, traceback)
        self.close_requested.set()


@dataclass(slots=True)
class _SingletonResourceOwner:
    """Keep singleton acquisition and release in one task and context."""

    context: Context
    stack: AsyncExitStack
    result: Future[object]
    close_requested: asyncio.Event
    key: DependencyKey[Any]
    registration: _Registration
    task: Task[None] | None = None
    published: bool = False
    shutdown_requested: bool = False
    finalizing: bool = False
    initialization_cleanup_error: BaseException | None = None
    resource_cleanup_error: BaseException | None = None

    def request_close(self) -> None:
        self.close_requested.set()


_request_owner: ContextVar[_RequestResourceOwner | None] = ContextVar(
    "businessos_request_owner", default=None
)


class Container:
    """Application dependency registry; request scopes own their resource teardown."""

    def __init__(self) -> None:
        self._registrations: dict[DependencyKey[Any], _Registration] = {}
        self._singletons: dict[DependencyKey[Any], object] = {}
        self._singleton_owners: dict[DependencyKey[Any], _SingletonResourceOwner] = {}
        self._singleton_order: list[DependencyKey[Any]] = []
        self._singleton_flights: dict[DependencyKey[Any], Future[object]] = {}
        self._singleton_owner_tasks: dict[Task[None], _SingletonResourceOwner] = {}
        self._singleton_waits: dict[DependencyKey[Any], dict[DependencyKey[Any], int]] = {}
        self._cleanup_task: Task[None] | None = None
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
        caller = asyncio.current_task()
        cancellations_on_entry = caller.cancelling() if caller is not None else 0
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(
                self._cleanup_singletons(),
                name="businessos-di-singleton-cleanup",
            )
        while True:
            try:
                await asyncio.shield(self._cleanup_task)
                break
            except asyncio.CancelledError:
                continue
        if caller is not None and caller.cancelling() > cancellations_on_entry:
            raise asyncio.CancelledError

    async def remove_owner_generation(self, generation: ContributionGeneration) -> None:
        caller = asyncio.current_task()
        cancellations_on_entry = caller.cancelling() if caller is not None else 0
        keys = tuple(
            key
            for key, registration in self._registrations.items()
            if registration.generation == generation
        )
        cleanup = asyncio.create_task(
            self._remove_singleton_keys(keys, generation),
            name=f"businessos-di-remove:{generation.owner}/{generation.number}",
        )
        while True:
            try:
                await asyncio.shield(cleanup)
                break
            except asyncio.CancelledError:
                continue
        if caller is not None and caller.cancelling() > cancellations_on_entry:
            raise asyncio.CancelledError

    async def resolve_for_scope(
        self,
        key: DependencyKey[T],
        request_cache: dict[DependencyKey[Any], object],
        request_flights: dict[DependencyKey[Any], Future[object]],
        request_waits: dict[DependencyKey[Any], dict[DependencyKey[Any], int]],
        start_initialization: Callable[[DependencyKey[Any], _Registration, bool], Future[object]],
        validate_initialization: Callable[[DependencyKey[Any], Future[object]], None],
    ) -> T:
        registration = self._registration_for_resolution(key)
        if registration.scope is DependencyScope.SINGLETON:
            return cast(T, await self._resolve_singleton(key, registration))
        if registration.scope is DependencyScope.REQUEST and key in request_cache:
            return cast(T, request_cache[key])
        if registration.scope is DependencyScope.REQUEST:
            wait_edges = self._add_wait_chain(request_waits, _resolution_path.get(), key)
            flight = request_flights.get(key)
            if flight is not None and flight.done():
                request_flights.pop(key, None)
                flight = None
            if flight is None:
                flight = start_initialization(key, registration, True)
                request_flights[key] = flight
            try:
                value = await asyncio.shield(flight)
                validate_initialization(key, flight)
                return cast(T, value)
            finally:
                for source, target in reversed(wait_edges):
                    self._remove_wait(request_waits, source, target)
        flight = start_initialization(key, registration, False)
        value = await asyncio.shield(flight)
        validate_initialization(key, flight)
        return cast(T, value)

    def validate_registration(self, key: DependencyKey[Any], registration: _Registration) -> None:
        if self._closed or self._registrations.get(key) is not registration:
            raise ConfigurationError(f"Dependency registration is no longer active: {key.name}")
        if registration.gate is not None and not registration.gate.is_active(
            registration.generation
        ):
            raise ConfigurationError(f"Dependency is not active: {key.name}")

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
            self._validate_singleton_owner(self._singleton_owners[key])
            return cached
        path = _resolution_path.get()
        wait_edges = self._add_wait_chain(self._singleton_waits, path, key)
        flight = self._singleton_flights.get(key)
        if flight is not None and flight.done():
            self._singleton_flights.pop(key, None)
            flight = None
        if flight is None:
            flight = self._start_singleton_initialization(key, registration)
        try:
            value = await asyncio.shield(flight)
            owner = self._singleton_owners.get(key)
            if owner is None:
                raise ConfigurationError(f"Dependency owner is no longer active: {key.name}")
            self._validate_singleton_owner(owner)
            return value
        finally:
            for source, target in reversed(wait_edges):
                self._remove_wait(self._singleton_waits, source, target)

    def _start_singleton_initialization(
        self,
        key: DependencyKey[Any],
        registration: _Registration,
    ) -> Future[object]:
        result = asyncio.get_running_loop().create_future()
        owner = _SingletonResourceOwner(
            copy_context(),
            AsyncExitStack(),
            result,
            asyncio.Event(),
            key,
            registration,
        )
        task = asyncio.create_task(
            self._initialize_singleton(key, registration, owner),
            context=owner.context,
            name=f"businessos-di:{key.name}",
        )
        owner.task = task
        self._singleton_flights[key] = result
        self._singleton_owner_tasks[task] = owner
        task.add_done_callback(
            lambda completed: self._singleton_owner_finished(key, owner, completed)
        )
        result.add_done_callback(self._consume_flight_result)
        return result

    async def _initialize_singleton(
        self,
        key: DependencyKey[Any],
        registration: _Registration,
        owner: _SingletonResourceOwner,
    ) -> None:
        entered = False
        try:
            await owner.stack.__aenter__()
            entered = True
            try:
                resolver = _SingletonDependencyResolver(self, owner.stack, key)
                value = await self._provide(key, registration, resolver, owner.stack)
                self.validate_registration(key, registration)
            except asyncio.CancelledError:
                if not owner.result.done():
                    owner.result.cancel()
                return
            except BaseException as error:
                if owner.shutdown_requested:
                    owner.initialization_cleanup_error = error
                if not owner.result.done():
                    owner.result.set_exception(error)
                return
            if self._closed:
                if not owner.result.done():
                    owner.result.set_exception(ConfigurationError("Dependency container is closed"))
                return
            self._singletons[key] = value
            self._singleton_owners[key] = owner
            self._singleton_order.append(key)
            owner.published = True
            if not owner.result.done():
                owner.result.set_result(value)
            await owner.close_requested.wait()
        finally:
            owner.finalizing = True
            if entered:
                try:
                    await owner.stack.aclose()
                except BaseException as error:
                    owner.resource_cleanup_error = error
                    raise

    def _singleton_owner_finished(
        self,
        key: DependencyKey[Any],
        owner: _SingletonResourceOwner,
        task: Task[None],
    ) -> None:
        self._singleton_owner_tasks.pop(task, None)
        if not owner.published and self._singleton_flights.get(key) is owner.result:
            self._singleton_flights.pop(key, None)
        if owner.result.done():
            return
        if task.cancelled():
            owner.result.cancel()
            return
        error = task.exception()
        if error is not None:
            owner.result.set_exception(error)
            return
        owner.result.set_exception(ConfigurationError("Dependency owner terminated before result"))

    def _validate_singleton_owner(self, owner: _SingletonResourceOwner) -> None:
        self.validate_registration(owner.key, owner.registration)
        if not owner.published or owner.finalizing:
            raise ConfigurationError(f"Dependency owner is no longer active: {owner.key.name}")

    @staticmethod
    def _record_singleton_cleanup_error(
        errors: list[BaseException],
        seen: set[int],
        error: BaseException | None,
    ) -> None:
        if error is not None and id(error) not in seen:
            seen.add(id(error))
            errors.append(error)

    async def _drain_singleton_owner(
        self,
        owner: _SingletonResourceOwner,
        errors: list[BaseException],
        seen: set[int],
    ) -> None:
        task = owner.task
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except BaseException as error:
                self._record_singleton_cleanup_error(errors, seen, error)
        self._record_singleton_cleanup_error(errors, seen, owner.initialization_cleanup_error)
        self._record_singleton_cleanup_error(errors, seen, owner.resource_cleanup_error)

    async def _cleanup_singletons(self) -> None:
        errors: list[BaseException] = []
        seen: set[int] = set()
        published_tasks = {
            owner.task for owner in self._singleton_owners.values() if owner.task is not None
        }
        initializers = tuple(
            owner
            for task, owner in self._singleton_owner_tasks.items()
            if task not in published_tasks
        )
        for owner in initializers:
            owner.shutdown_requested = True
            if owner.task is not None and not owner.finalizing:
                owner.task.cancel()
        for owner in initializers:
            await self._drain_singleton_owner(owner, errors, seen)
        for key in reversed(self._singleton_order):
            published_owner = self._singleton_owners.get(key)
            if published_owner is None:
                continue
            published_owner.request_close()
            await self._drain_singleton_owner(published_owner, errors, seen)
        self._clear_singletons()
        self._registrations.clear()
        if errors:
            raise BaseExceptionGroup("Dependency cleanup failed", errors)

    async def _remove_singleton_keys(
        self,
        keys: tuple[DependencyKey[Any], ...],
        generation: ContributionGeneration,
    ) -> None:
        errors: list[BaseException] = []
        seen: set[int] = set()
        key_set = set(keys)
        initializers = tuple(
            owner
            for owner in self._singleton_owner_tasks.values()
            if owner.key in key_set and not owner.published
        )
        for owner in initializers:
            await self._drain_singleton_owner(owner, errors, seen)
        for key in reversed(self._singleton_order):
            if key not in key_set:
                continue
            published_owner = self._singleton_owners.get(key)
            if published_owner is not None:
                published_owner.request_close()
                await self._drain_singleton_owner(published_owner, errors, seen)
            self._remove_singleton(key)
        for key in keys:
            self._singleton_flights.pop(key, None)
            self._registrations.pop(key, None)
        if errors:
            raise BaseExceptionGroup(
                f"Dependency cleanup failed: {generation.owner}/{generation.number}",
                errors,
            )

    def _remove_singleton(self, key: DependencyKey[Any]) -> None:
        self._singleton_owners.pop(key, None)
        self._singletons.pop(key, None)
        self._singleton_flights.pop(key, None)
        if key in self._singleton_order:
            self._singleton_order.remove(key)

    def _clear_singletons(self) -> None:
        self._singleton_order.clear()
        self._singleton_owners.clear()
        self._singletons.clear()
        self._singleton_flights.clear()
        self._singleton_owner_tasks.clear()
        self._singleton_waits.clear()

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
    def _consume_flight_result(flight: Future[object]) -> None:
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
        self._flights: dict[DependencyKey[Any], Future[object]] = {}
        self._waits: dict[DependencyKey[Any], dict[DependencyKey[Any], int]] = {}
        self._owner_tasks: dict[Task[None], _RequestResourceOwner] = {}
        self._result_owners: dict[Future[object], _RequestResourceOwner] = {}
        self._resource_owners: list[_RequestResourceOwner] = []
        self._published_owners: dict[DependencyKey[Any], _RequestResourceOwner] = {}
        self._failed_owners: dict[DependencyKey[Any], _RequestResourceOwner] = {}
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
            self._owner_tasks.clear()
            self._result_owners.clear()
            self._resource_owners.clear()
            self._published_owners.clear()
            self._failed_owners.clear()
            self._state = _RequestScopeState.CLOSED
        if cancelled:
            raise asyncio.CancelledError

    async def resolve(self, key: DependencyKey[T]) -> T:
        self._ensure_resolution_valid(key)
        cached_owner = self._published_owners.get(key)
        if cached_owner is not None:
            try:
                self._validate_owner(cached_owner, set())
            except ConfigurationError:
                self._cache.pop(key, None)
                self._published_owners.pop(key, None)
                self._flights.pop(key, None)
                raise
            self._retain_dependency(cached_owner)
        value = await self._container.resolve_for_scope(
            key,
            self._cache,
            self._flights,
            self._waits,
            self._start_initialization,
            self._ensure_initialization_valid,
        )
        self._ensure_resolution_valid(key)
        return value

    def _ensure_resolution_valid(self, key: DependencyKey[Any]) -> None:
        if self._state is not _RequestScopeState.OPEN:
            raise ConfigurationError("Dependency scope must be entered before resolution")
        failed_owner = self._failed_owners.get(key)
        if failed_owner is not None:
            failure = failed_owner.terminal_failure or failed_owner.resource_cleanup_error
            raise ConfigurationError(
                f"Dependency owner terminated after publication: {key.name}"
            ) from failure

    def _ensure_initialization_valid(self, key: DependencyKey[Any], result: Future[object]) -> None:
        self._ensure_resolution_valid(key)
        owner = self._result_owners.get(result)
        if owner is None:
            raise ConfigurationError("Dependency scope closed during resolution")
        self._validate_owner(owner, set())
        self._retain_dependency(owner)

    @staticmethod
    def _retain_dependency(owner: _RequestResourceOwner) -> None:
        parent = _request_owner.get()
        if parent is not None and parent is not owner:
            if all(dependency is not owner for dependency in parent.dependencies):
                parent.dependencies.append(owner)

    def _validate_owner(self, owner: _RequestResourceOwner, visited: set[int]) -> None:
        if id(owner) in visited:
            return
        visited.add(id(owner))
        self._container.validate_registration(owner.key, owner.registration)
        if owner.failed_after_publication:
            failure = owner.terminal_failure or owner.resource_cleanup_error
            raise ConfigurationError("Dependency owner terminated after publication") from failure
        for dependency in owner.dependencies:
            self._validate_owner(dependency, visited)

    def _start_initialization(
        self,
        key: DependencyKey[Any],
        registration: _Registration,
        cache_result: bool,
    ) -> Future[object]:
        result = asyncio.get_running_loop().create_future()
        owner = _RequestResourceOwner(
            copy_context(),
            AsyncExitStack(),
            result,
            asyncio.Event(),
            key=key,
            registration=registration,
            cache_result=cache_result,
        )
        task = asyncio.create_task(
            self._initialize_owned(key, registration, cache_result, owner),
            context=owner.context,
            name=f"businessos-di-request:{key.name}",
        )
        owner.task = task
        self._owner_tasks[task] = owner
        self._result_owners[result] = owner
        task.add_done_callback(lambda completed: self._owner_finished(key, owner, completed))
        result.add_done_callback(self._consume_resolution_result)
        return result

    async def _initialize_owned(
        self,
        key: DependencyKey[Any],
        registration: _Registration,
        cache_result: bool,
        owner: _RequestResourceOwner,
    ) -> None:
        entered = False
        _request_owner.set(owner)
        try:
            await owner.stack.__aenter__()
            entered = True
            try:
                value = await self._container.provide_for_request(
                    key, registration, self, owner.stack
                )
                self._validate_owner(owner, set())
            except asyncio.CancelledError:
                if not owner.result.done():
                    owner.result.cancel()
                return
            except BaseException as error:
                if owner.shutdown_requested:
                    owner.initialization_cleanup_error = error
                if not owner.result.done():
                    owner.result.set_exception(error)
                return
            if self._state is not _RequestScopeState.OPEN:
                if not owner.result.done():
                    owner.result.set_exception(
                        ConfigurationError("Dependency scope closed during resolution")
                    )
                return
            if cache_result:
                self._cache[key] = value
                self._published_owners[key] = owner
            owner.published = True
            self._resource_owners.append(owner)
            if not owner.result.done():
                owner.result.set_result(value)
            await owner.close_requested.wait()
        finally:
            owner.finalizing = True
            if entered:
                if owner.published and not owner.close_requested.is_set():
                    self._invalidate_published_owner(key, owner)
                try:
                    await owner.stack.__aexit__(*owner.exit_details)
                except BaseException as error:
                    owner.resource_cleanup_error = error
                    if owner.failed_after_publication:
                        owner.terminal_failure = error
                    raise

    @staticmethod
    def _consume_resolution_result(result: Future[object]) -> None:
        if not result.cancelled():
            result.exception()

    def _invalidate_published_owner(
        self,
        key: DependencyKey[Any],
        owner: _RequestResourceOwner,
    ) -> None:
        owner.failed_after_publication = True
        if not owner.cache_result:
            return
        if self._published_owners.get(key) is owner:
            self._published_owners.pop(key, None)
            self._cache.pop(key, None)
            if self._flights.get(key) is owner.result:
                self._flights.pop(key, None)
            self._failed_owners[key] = owner

    def _owner_finished(
        self,
        key: DependencyKey[Any],
        owner: _RequestResourceOwner,
        task: Task[None],
    ) -> None:
        if (
            owner.published
            and not owner.close_requested.is_set()
            and self._state is _RequestScopeState.OPEN
        ):
            self._invalidate_published_owner(key, owner)
            if owner.terminal_failure is None:
                if task.cancelled():
                    owner.terminal_failure = ConfigurationError(
                        f"Dependency owner cancelled after publication: {key.name}"
                    )
                else:
                    owner.terminal_failure = task.exception()
        if owner.result.done():
            return
        if task.cancelled():
            owner.result.cancel()
            return
        error = task.exception()
        if error is not None:
            owner.result.set_exception(error)
            return
        owner.result.set_exception(ConfigurationError("Dependency owner terminated before result"))

    @staticmethod
    def _record_cleanup_error(
        errors: list[BaseException],
        seen: set[int],
        error: BaseException | None,
    ) -> None:
        if error is not None and id(error) not in seen:
            seen.add(id(error))
            errors.append(error)

    async def _drain_owner(
        self,
        owner: _RequestResourceOwner,
        errors: list[BaseException],
        seen: set[int],
    ) -> None:
        task = owner.task
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except BaseException as error:
                self._record_cleanup_error(errors, seen, error)
        self._record_cleanup_error(errors, seen, owner.initialization_cleanup_error)
        self._record_cleanup_error(errors, seen, owner.resource_cleanup_error)
        self._record_cleanup_error(errors, seen, owner.terminal_failure)

    async def _cleanup(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        errors: list[BaseException] = []
        seen: set[int] = set()
        published_tasks = {owner.task for owner in self._resource_owners if owner.task is not None}
        initializers = tuple(
            owner for task, owner in self._owner_tasks.items() if task not in published_tasks
        )
        for owner in initializers:
            owner.shutdown_requested = True
            if owner.task is not None and not owner.finalizing:
                owner.task.cancel()
        for owner in initializers:
            await self._drain_owner(owner, errors, seen)
        for owner in reversed(self._resource_owners):
            owner.request_close(exc_type, exc_value, traceback)
            await self._drain_owner(owner, errors, seen)
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
