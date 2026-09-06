"""Public module SDK contracts exposed by the protected framework."""

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from businessos.context import RequestContext
from businessos.contracts import ContractRegistry, PublicContract
from businessos.di import (
    Container,
    DependencyKey,
    DependencyResolver,
    DependencyScope,
    RequestDependencyScope,
)
from businessos.features import FeatureFlag, FeatureFlagRegistry
from businessos.http import Request, Response, Router
from businessos.messages import Command, DomainEvent, HandlingContext, MessageDispatcher, Query
from businessos.metadata import MetadataDeclaration, MetadataRegistry
from businessos.modules.manifest import ModuleManifest
from businessos.permissions import PermissionDeclaration, PermissionRegistry
from businessos.providers import ProviderRegistry

RouteHandler = Callable[[Request, RequestDependencyScope], Awaitable[Response]]


@runtime_checkable
class BusinessOSModule(Protocol):
    @property
    def manifest(self) -> ModuleManifest: ...

    async def register(self, registration: "ModuleRegistration") -> None: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class ModuleRegistration:
    """Owner-scoped SDK surface; modules cannot access mutable registries directly."""

    def __init__(
        self,
        owner: str,
        *,
        router: Router,
        container: Container,
        contracts: ContractRegistry,
        metadata: MetadataRegistry,
        permissions: PermissionRegistry,
        providers: ProviderRegistry,
        messages: MessageDispatcher,
        features: FeatureFlagRegistry,
    ) -> None:
        self.owner = owner
        self._router = router
        self._container = container
        self._contracts = contracts
        self._metadata = metadata
        self._permissions = permissions
        self._providers = providers
        self._messages = messages
        self._features = features

    def route(
        self,
        method: str,
        path: str,
        handler: RouteHandler,
        *,
        name: str,
        permission: str | None = None,
    ) -> None:
        if permission is not None:
            self._permissions.get(permission)
        self._router.add_route(
            method,
            path,
            handler,
            name=f"{self.owner}.{name}",
            permission=permission,
        )

    def dependency[T](
        self,
        key: DependencyKey[T],
        provider: Callable[[DependencyResolver], T | Awaitable[T]],
        *,
        scope: DependencyScope = DependencyScope.TRANSIENT,
    ) -> None:
        self._container.register(key, provider, scope=scope)

    def contract(self, name: str, contract: PublicContract) -> None:
        self._contracts.register(name, self.owner, contract)

    def metadata(self, declaration: MetadataDeclaration) -> None:
        self._metadata.add(self.owner, declaration)

    def permission(self, declaration: PermissionDeclaration) -> None:
        self._permissions.add(self.owner, declaration)

    def provider(self, capability: str, provider: object) -> None:
        self._providers.register(capability, self.owner, provider)

    def feature(self, flag: FeatureFlag) -> None:
        self._features.add(self.owner, flag)

    def command[C: Command](
        self,
        command_type: type[C],
        handler: Callable[[C, HandlingContext], Awaitable[object]],
    ) -> None:
        self._messages.commands.register(command_type, self.owner, handler)

    def query[Q: Query](
        self,
        query_type: type[Q],
        handler: Callable[[Q, HandlingContext], Awaitable[object]],
    ) -> None:
        self._messages.queries.register(query_type, self.owner, handler)

    def event[E: DomainEvent](
        self,
        event_type: type[E],
        subscriber: str,
        handler: Callable[[E, RequestContext, RequestDependencyScope], Awaitable[None]],
    ) -> None:
        self._messages.events.subscribe(event_type, f"{self.owner}.{subscriber}", handler)
