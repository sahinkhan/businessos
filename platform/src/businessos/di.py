"""Explicit framework-owned dependency registration and scopes."""

import inspect
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from dataclasses import dataclass
from enum import StrEnum
from types import TracebackType
from typing import Any, Protocol, TypeVar, cast

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


@dataclass(frozen=True, slots=True)
class _Registration:
    provider: Provider
    scope: DependencyScope


class Container:
    """Application dependency registry; request scopes own their resource teardown."""

    def __init__(self) -> None:
        self._registrations: dict[DependencyKey[Any], _Registration] = {}
        self._singletons: dict[DependencyKey[Any], object] = {}
        self._exit_stack = AsyncExitStack()
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
    ) -> None:
        if key in self._registrations:
            raise ConflictError(f"Dependency already registered: {key.name}")
        self._registrations[key] = _Registration(cast(Provider, provider), scope)

    def request_scope(self) -> "RequestDependencyScope":
        if self._closed:
            raise ConfigurationError("Dependency container is closed")
        return RequestDependencyScope(self)

    async def close(self) -> None:
        self._closed = True
        await self._exit_stack.aclose()
        self._singletons.clear()

    async def resolve_for_scope(
        self,
        key: DependencyKey[T],
        request_cache: dict[DependencyKey[Any], object],
        request_stack: AsyncExitStack,
        resolver: DependencyResolver,
    ) -> T:
        registration = self._registrations.get(key)
        if registration is None:
            raise ConfigurationError(f"Dependency is not registered: {key.name}")
        cache = (
            self._singletons if registration.scope is DependencyScope.SINGLETON else request_cache
        )
        if registration.scope is not DependencyScope.TRANSIENT and key in cache:
            return cast(T, cache[key])
        value = registration.provider(resolver)
        if inspect.isawaitable(value):
            value = await value
        stack = (
            self._exit_stack if registration.scope is DependencyScope.SINGLETON else request_stack
        )
        if isinstance(value, AbstractAsyncContextManager):
            context_manager = cast(AbstractAsyncContextManager[object], value)
            value = await stack.enter_async_context(context_manager)
        if registration.scope is not DependencyScope.TRANSIENT:
            cache[key] = value
        return cast(T, value)


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
