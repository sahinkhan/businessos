"""Public module SDK contracts exposed by the protected framework."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol, runtime_checkable

from businessos.activation import ContributionGate, ContributionGeneration, ContributionState
from businessos.context import RequestContext
from businessos.contracts import ContractRegistry, PublicContract
from businessos.dependency_entitlement import internal_valid_restricted_dependency_entitlement
from businessos.di import (
    Container,
    DependencyKey,
    DependencyResolver,
    DependencyScope,
    RequestDependencyScope,
)
from businessos.features import FeatureFlag, FeatureFlagRegistry
from businessos.handler_invocation import internal_capture_handler_provenance
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
from businessos.modules.manifest import ModuleManifest
from businessos.permissions import PermissionDeclaration, PermissionRegistry
from businessos.providers import ProviderRegistry
from businessos.resources import (
    ResourceOwnerFactsProvider,
    ResourceOwnerOperationProvider,
    ResourceOwnershipRegistry,
)

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
        manifest: ModuleManifest | None = None,
        resources: ResourceOwnershipRegistry | None = None,
        coordinator_approved: bool = False,
        owner_restricted_entitlement: object | None = None,
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
        self._manifest = manifest
        self._handler_provenance = internal_capture_handler_provenance(manifest, owner, generation)
        self._owner_restricted_entitlement = owner_restricted_entitlement
        self._resources = resources
        self._coordinator_token: object | None = None
        if coordinator_approved:
            if resources is None:
                raise RuntimeError("Coordinator admission requires the resource registry")
            self._coordinator_token = object()
            resources.authorize_coordinator_generation(generation, self._coordinator_token)
        self._finished = False

    def publish(self) -> None:
        self._ensure_open()
        if self._manifest is not None and self._resources is not None:
            self._resources.stage(self._manifest, self.generation)
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
        await self._remove_contributions(propagate_cancellation=False)

    def retire_owner(self) -> None:
        self._gate.retire(self.owner)

    async def _remove_contributions(self, *, propagate_cancellation: bool = True) -> None:
        cancellation: asyncio.CancelledError | None = None
        try:
            await self._container.remove_owner_generation(self.generation)
        except asyncio.CancelledError as error:
            cancellation = error
        self._router.remove_owner_generation(self.generation)
        self._contracts.remove_owner_generation(self.generation)
        self._metadata.remove_owner_generation(self.generation)
        self._permissions.remove_owner_generation(self.generation)
        self._providers.remove_owner_generation(self.generation)
        if self._resources is not None:
            self._resources.remove_owner_generation(self.generation)
        self._features.remove_owner_generation(self.generation)
        self._messages.commands.remove_owner_generation(self.generation)
        self._messages.queries.remove_owner_generation(self.generation)
        self._messages.events.remove_owner_generation(self.generation)
        self._middleware.remove_owner_generation(self.generation)
        self._jobs.remove_owner_generation(self.generation)
        self._gate.discard(self.generation)
        self._finished = True
        if cancellation is not None and propagate_cancellation:
            raise cancellation

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
        if key.required_owner is not None:
            if self._gate.state(self.generation) is not ContributionState.STAGED:
                raise RuntimeError("Reserved dependencies must register before activation")
            if self.owner != key.required_owner:
                raise PermissionError("Dependency key is reserved to another module owner")
            if not internal_valid_restricted_dependency_entitlement(
                self._owner_restricted_entitlement, self.owner, self.generation
            ):
                raise PermissionError("Reserved dependency requires approved first-party artifact")
        self._container.register(
            key,
            provider,
            scope=scope,
            owner=self.owner,
            generation=self.generation,
            gate=self._gate,
            _owner_restricted_entitlement=self._owner_restricted_entitlement,
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

    def resource_owner_facts(
        self, namespace: str, version: str, provider: ResourceOwnerFactsProvider
    ) -> None:
        self._resource_provider(namespace, version, "facts", provider)

    def resource_owner_operation(
        self, namespace: str, version: str, provider: ResourceOwnerOperationProvider
    ) -> None:
        self._resource_provider(namespace, version, "operation", provider)

    def _resource_provider(self, namespace: str, version: str, kind: str, provider: object) -> None:
        self._ensure_open()
        if self._gate.state(self.generation) is not ContributionState.STAGED:
            raise RuntimeError("Resource providers must register before activation")
        if self._manifest is None or self._resources is None:
            raise RuntimeError("Resource ownership is unavailable to this registration")
        self._resources.register_provider(
            self._manifest, self.generation, namespace, version, kind, provider
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
            coordinator_token=self._coordinator_token,
            _provenance=(
                self._handler_provenance
                if self._gate.state(self.generation) is ContributionState.STAGED
                else None
            ),
            _database_entitlement=(
                self._owner_restricted_entitlement
                if self._gate.state(self.generation) is ContributionState.STAGED
                else None
            ),
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
            _provenance=(
                self._handler_provenance
                if self._gate.state(self.generation) is ContributionState.STAGED
                else None
            ),
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
        handler: Callable[[Job, RequestContext, RequestDependencyScope], Awaitable[None]],
        *,
        permission: str | None = None,
    ) -> None:
        self._ensure_open()
        self._validate_permission(permission)
        self._jobs.add(
            job_type,
            self.owner,
            handler,
            generation=self.generation,
            permission=permission,
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
        if self._finished:
            raise RuntimeError(f"Module registration is closed: {self.owner}")
