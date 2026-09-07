"""Public module SDK contracts exposed by the protected framework."""

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol, cast, runtime_checkable

from businessos.activation import ContributionGate, ContributionGeneration
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
from businessos.http.middleware import CallNext, Middleware, MiddlewareRegistry
from businessos.jobs import Job, JobHandlerRegistry
from businessos.messages import (
    Command,
    DomainEvent,
    EventHandlingContext,
    HandlingContext,
    MessageDispatcher,
    Query,
)
from businessos.metadata import MetadataDeclaration, MetadataRegistry
from businessos.module_access import (
    ModuleDependencies,
    module_dependencies,
    restricted_dependencies,
)
from businessos.modules.manifest import ModuleManifest
from businessos.permissions import PermissionDeclaration, PermissionRegistry
from businessos.providers import ProviderRegistry, RevocableProvider

RouteHandler = Callable[[Request, ModuleDependencies], Awaitable[Response]]


@runtime_checkable
class BusinessOSModule(Protocol):
    @property
    def manifest(self) -> ModuleManifest: ...

    async def register(self, registration: "ModuleRegistration") -> None: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class RegistrationController:
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
        middleware: MiddlewareRegistry,
        jobs: JobHandlerRegistry,
        gate: ContributionGate,
        generation: ContributionGeneration,
    ) -> None:
        self.owner = owner
        self.generation = generation
        self._router = router
        self._container = container
        self._contracts = contracts
        self._metadata = metadata
        self._permissions = permissions
        self._providers = providers
        self._messages = messages
        self._features = features
        self._middleware = middleware
        self._jobs = jobs
        self._gate = gate
        self._finished = False
        self._sealed = False

    def seal(self) -> None:
        self._ensure_open()
        self._sealed = True

    def public(self) -> "ModuleRegistration":
        return cast(
            ModuleRegistration,
            _RegistrationFacade({name: getattr(self, name) for name in _PUBLIC_METHODS}),
        )

    def publish(self) -> None:
        if self._finished or not self._sealed:
            raise RuntimeError("Only a sealed registration can be published")
        self._gate.publish(self.generation)

    async def deactivate(self, *, timeout_seconds: float) -> None:
        if self._finished:
            return
        await self.stop_accepting(timeout_seconds=timeout_seconds)
        await self.remove()

    async def stop_accepting(self, *, timeout_seconds: float) -> None:
        if self._finished:
            return
        await self._gate.close_and_drain(
            self.generation,
            timeout_seconds=timeout_seconds,
        )

    async def remove(self) -> None:
        if self._finished:
            return
        await self._remove_contributions()

    async def rollback(self) -> None:
        if self._finished:
            return
        await self._remove_contributions()

    def retire_owner(self) -> None:
        self._gate.retire(self.owner)

    async def _remove_contributions(self) -> None:
        await self._container.remove_owner_generation(self.generation)
        self._router.remove_owner_generation(self.generation)
        self._contracts.remove_owner_generation(self.generation)
        self._metadata.remove_owner_generation(self.generation)
        self._permissions.remove_owner_generation(self.generation)
        self._providers.remove_owner_generation(self.generation)
        self._features.remove_owner_generation(self.generation)
        self._messages.commands.remove_owner_generation(self.generation)
        self._messages.queries.remove_owner_generation(self.generation)
        self._messages.events.remove_owner_generation(self.generation)
        self._middleware.remove_owner_generation(self.generation)
        self._jobs.remove_owner_generation(self.generation)
        self._gate.discard(self.generation)
        self._finished = True

    def route(
        self,
        method: str,
        path: str,
        handler: RouteHandler,
        *,
        name: str,
        permission: str | None = None,
    ) -> None:
        self._ensure_open()
        if permission is not None:
            if not self._permissions.contains(
                permission,
                owner=self.owner,
                generation=self.generation,
                include_inactive=True,
            ):
                self._permissions.get(permission)

        async def admitted(request: Request, dependencies: RequestDependencyScope) -> Response:
            async with self._gate.admit(self.generation):
                public = module_dependencies(dependencies, request.context)
                try:
                    return await handler(request, public)
                finally:
                    public.close()

        self._router.add_route(
            method,
            path,
            admitted,
            name=f"{self.owner}.{name}",
            permission=permission,
            owner=self.owner,
            generation=self.generation,
        )

    def middleware(self, name: str, middleware: Middleware) -> None:
        self._ensure_open()

        async def admitted(request: Request, call_next: CallNext) -> Response:
            async with self._gate.admit(self.generation):
                return await middleware(request, call_next)

        self._middleware.register(
            f"{self.owner}.{name}",
            self.owner,
            admitted,
            self.generation,
        )

    def dependency[T](
        self,
        key: DependencyKey[T],
        provider: Callable[
            [DependencyResolver],
            T | Awaitable[T] | AbstractAsyncContextManager[T],
        ],
        *,
        scope: DependencyScope = DependencyScope.TRANSIENT,
    ) -> None:
        self._ensure_open()
        self._container.register(
            key,
            lambda resolver: provider(restricted_dependencies(resolver)),
            scope=scope,
            owner=self.owner,
            generation=self.generation,
            gate=self._gate,
        )

    def contract(self, name: str, contract: PublicContract) -> None:
        self._ensure_open()
        self._contracts.register(name, self.owner, contract, generation=self.generation)

    def metadata(self, declaration: MetadataDeclaration) -> None:
        self._ensure_open()
        self._metadata.add(self.owner, declaration, generation=self.generation)

    def permission(self, declaration: PermissionDeclaration) -> None:
        self._ensure_open()
        self._permissions.add(self.owner, declaration, generation=self.generation)

    def provider(self, capability: str, provider: object) -> None:
        self._ensure_open()
        self._providers.register(
            capability,
            self.owner,
            RevocableProvider(provider, self._gate, self.generation),
            generation=self.generation,
        )

    def feature(self, flag: FeatureFlag) -> None:
        self._ensure_open()
        self._features.add(self.owner, flag, generation=self.generation)

    def command[C: Command](
        self,
        command_type: type[C],
        handler: Callable[[C, HandlingContext], Awaitable[object]],
        *,
        permission: str | None = None,
    ) -> None:
        self._ensure_open()
        self._validate_permission(permission)
        self._messages.commands.register(
            command_type,
            self.owner,
            handler,
            generation=self.generation,
            permission=permission,
        )

    def query[Q: Query](
        self,
        query_type: type[Q],
        handler: Callable[[Q, HandlingContext], Awaitable[object]],
        *,
        permission: str | None = None,
    ) -> None:
        self._ensure_open()
        self._validate_permission(permission)
        self._messages.queries.register(
            query_type,
            self.owner,
            handler,
            generation=self.generation,
            permission=permission,
        )

    def event[E: DomainEvent](
        self,
        event_type: type[E],
        subscriber: str,
        handler: Callable[[E, EventHandlingContext], Awaitable[None]],
        *,
        permission: str | None = None,
    ) -> None:
        self._ensure_open()
        self._validate_permission(permission)
        self._messages.events.subscribe(
            event_type,
            f"{self.owner}.{subscriber}",
            handler,
            owner=self.owner,
            generation=self.generation,
            permission=permission,
        )

    def job(
        self,
        job_type: str,
        handler: Callable[[Job, RequestContext, ModuleDependencies], Awaitable[None]],
        *,
        permission: str | None = None,
        version: int = 1,
    ) -> None:
        self._ensure_open()
        self._validate_permission(permission)

        async def invoke(
            job: Job, context: RequestContext, dependencies: RequestDependencyScope
        ) -> None:
            public = module_dependencies(dependencies, context)
            try:
                await handler(job, context, public)
            finally:
                public.close()

        self._jobs.add(
            job_type,
            self.owner,
            invoke,
            generation=self.generation,
            permission=permission,
            version=version,
        )

    def _validate_permission(self, permission: str | None) -> None:
        if permission is None:
            return
        if self._permissions.contains(
            permission,
            owner=self.owner,
            generation=self.generation,
            include_inactive=True,
        ):
            return
        self._permissions.get(permission)

    def _ensure_open(self) -> None:
        if self._finished or self._sealed:
            raise RuntimeError(f"Module registration is closed: {self.owner}")


class ModuleRegistration(Protocol):
    """Contribution declarations only; lifecycle authority stays in the framework."""

    def route(
        self,
        method: str,
        path: str,
        handler: RouteHandler,
        *,
        name: str,
        permission: str | None = None,
    ) -> None: ...

    def middleware(self, name: str, middleware: Middleware) -> None: ...

    def dependency[T](
        self,
        key: DependencyKey[T],
        provider: Callable[
            [DependencyResolver],
            T | Awaitable[T] | AbstractAsyncContextManager[T],
        ],
        *,
        scope: DependencyScope = DependencyScope.TRANSIENT,
    ) -> None: ...

    def contract(self, name: str, contract: PublicContract) -> None: ...

    def metadata(self, declaration: MetadataDeclaration) -> None: ...

    def permission(self, declaration: PermissionDeclaration) -> None: ...

    def provider(self, capability: str, provider: object) -> None: ...

    def feature(self, flag: FeatureFlag) -> None: ...

    def command[C: Command](
        self,
        command_type: type[C],
        handler: Callable[[C, HandlingContext], Awaitable[object]],
        *,
        permission: str | None = None,
    ) -> None: ...

    def query[Q: Query](
        self,
        query_type: type[Q],
        handler: Callable[[Q, HandlingContext], Awaitable[object]],
        *,
        permission: str | None = None,
    ) -> None: ...

    def event[E: DomainEvent](
        self,
        event_type: type[E],
        subscriber: str,
        handler: Callable[[E, EventHandlingContext], Awaitable[None]],
        *,
        permission: str | None = None,
    ) -> None: ...

    def job(
        self,
        job_type: str,
        handler: Callable[[Job, RequestContext, ModuleDependencies], Awaitable[None]],
        *,
        permission: str | None = None,
        version: int = 1,
    ) -> None: ...


_PUBLIC_METHODS = (
    "route",
    "middleware",
    "dependency",
    "contract",
    "metadata",
    "permission",
    "provider",
    "feature",
    "command",
    "query",
    "event",
    "job",
)


class _RegistrationFacade:
    __slots__ = ("__methods",)

    def __init__(self, methods: dict[str, Any]) -> None:
        self.__methods = methods

    def __getattr__(self, name: str) -> Any:
        if name not in _PUBLIC_METHODS:
            raise AttributeError(name)
        return self.__methods[name]
