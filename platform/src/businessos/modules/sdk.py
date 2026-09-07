"""Public module SDK contracts exposed by the protected framework."""

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol, runtime_checkable

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

    def publish(self) -> None:
        self._ensure_open()
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
                return await handler(request, dependencies)

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
            provider,
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
            provider,
            generation=self.generation,
        )

    def feature(self, flag: FeatureFlag) -> None:
        self._ensure_open()
        self._features.add(self.owner, flag, generation=self.generation)

    def command[C: Command](
        self,
        command_type: type[C],
        handler: Callable[[C, HandlingContext], Awaitable[object]],
    ) -> None:
        self._ensure_open()
        self._messages.commands.register(
            command_type,
            self.owner,
            handler,
            generation=self.generation,
        )

    def query[Q: Query](
        self,
        query_type: type[Q],
        handler: Callable[[Q, HandlingContext], Awaitable[object]],
    ) -> None:
        self._ensure_open()
        self._messages.queries.register(
            query_type,
            self.owner,
            handler,
            generation=self.generation,
        )

    def event[E: DomainEvent](
        self,
        event_type: type[E],
        subscriber: str,
        handler: Callable[[E, RequestContext, RequestDependencyScope], Awaitable[None]],
    ) -> None:
        self._ensure_open()
        self._messages.events.subscribe(
            event_type,
            f"{self.owner}.{subscriber}",
            handler,
            owner=self.owner,
            generation=self.generation,
        )

    def job(
        self,
        job_type: str,
        handler: Callable[[Job, RequestContext, RequestDependencyScope], Awaitable[None]],
    ) -> None:
        self._ensure_open()
        self._jobs.add(
            job_type,
            self.owner,
            handler,
            generation=self.generation,
        )

    def _ensure_open(self) -> None:
        if self._finished:
            raise RuntimeError(f"Module registration is closed: {self.owner}")
