"""Request-bound capabilities crossing the public module boundary."""

from collections.abc import Awaitable, Callable
from typing import cast

from businessos.context import RequestContext
from businessos.di import DependencyKey, DependencyResolver, RequestDependencyScope
from businessos.errors import ConfigurationError
from businessos.messages import Command, MessageDispatcher, Query
from businessos.providers import CacheProvider, ObjectStorageProvider


class ModuleDependencies:
    __slots__ = ("__active", "__resolve")

    def __init__(self, resolve: Callable[[DependencyKey[object]], Awaitable[object]]) -> None:
        self.__resolve = resolve
        self.__active = True

    def close(self) -> None:
        self.__active = False

    def check(self) -> None:
        if not self.__active:
            raise ConfigurationError("Module request capability has expired")

    async def resolve[T](self, key: DependencyKey[T]) -> T:
        self.check()
        return cast(T, await self.__resolve(cast(DependencyKey[object], key)))


class CommandClient:
    __slots__ = ("__command", "__query")

    def __init__(
        self,
        command: Callable[[Command], Awaitable[object]],
        query: Callable[[Query], Awaitable[object]],
    ) -> None:
        self.__command = command
        self.__query = query

    async def command(self, message: Command) -> object:
        return await self.__command(message)

    async def query(self, message: Query) -> object:
        return await self.__query(message)


class TenantStorage:
    __slots__ = ("__get", "__put")

    def __init__(
        self, put: Callable[[str, bytes], Awaitable[None]], get: Callable[[str], Awaitable[bytes]]
    ) -> None:
        self.__put = put
        self.__get = get

    async def put(self, key: str, content: bytes) -> None:
        await self.__put(key, content)

    async def get(self, key: str) -> bytes:
        return await self.__get(key)


class TenantCache:
    __slots__ = ("__get", "__set")

    def __init__(
        self,
        get: Callable[[str], Awaitable[bytes | None]],
        set_value: Callable[[str, bytes, int], Awaitable[None]],
    ) -> None:
        self.__get = get
        self.__set = set_value

    async def get(self, key: str) -> bytes | None:
        return await self.__get(key)

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        await self.__set(key, value, ttl_seconds)


def module_dependencies(
    scope: RequestDependencyScope, context: RequestContext
) -> ModuleDependencies:
    from businessos.dependencies import CACHE, MESSAGE_DISPATCHER, OBJECT_STORAGE

    async def resolve(key: DependencyKey[object]) -> object:
        if key is MESSAGE_DISPATCHER:
            dispatcher: MessageDispatcher = await scope.resolve(MESSAGE_DISPATCHER)

            async def command(message: Command) -> object:
                public.check()
                return await dispatcher.command(message, context, scope)

            async def query(message: Query) -> object:
                public.check()
                return await dispatcher.query(message, context, scope)

            return CommandClient(command, query)
        if key is OBJECT_STORAGE:
            storage: ObjectStorageProvider = await scope.resolve(OBJECT_STORAGE)
            if context.tenant is None:
                raise ConfigurationError("Object storage requires trusted tenant context")
            tenant_id = context.tenant.tenant_id

            async def put(name: str, content: bytes) -> None:
                public.check()
                await storage.put(tenant_id, name, content)

            async def get(name: str) -> bytes:
                public.check()
                return await storage.get(tenant_id, name)

            return TenantStorage(put, get)
        if key is CACHE:
            cache: CacheProvider = await scope.resolve(CACHE)
            if context.tenant is None:
                raise ConfigurationError("Cache requires trusted tenant context")
            tenant_id = context.tenant.tenant_id

            async def cache_get(name: str) -> bytes | None:
                public.check()
                return await cache.get(tenant_id, name)

            async def cache_set(name: str, value: bytes, ttl: int) -> None:
                public.check()
                await cache.set(tenant_id, name, value, ttl)

            return TenantCache(cache_get, cache_set)
        if key.name.startswith("businessos."):
            raise ConfigurationError("Internal dependency is not a public module capability")
        return await scope.resolve(key)

    public = ModuleDependencies(resolve)
    return public


def restricted_dependencies(resolver: DependencyResolver) -> ModuleDependencies:
    async def resolve(key: DependencyKey[object]) -> object:
        if key.name.startswith("businessos."):
            raise ConfigurationError("Module factories cannot resolve framework dependencies")
        return await resolver.resolve(key)

    return ModuleDependencies(resolve)
