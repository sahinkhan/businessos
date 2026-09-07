"""Composition of all framework-owned registries and module lifecycle services."""

from dataclasses import dataclass

from businessos.activation import ContributionGate
from businessos.contracts import ContractRegistry
from businessos.di import Container
from businessos.eventing import DurableEventConsumer
from businessos.features import FeatureFlagRegistry
from businessos.http import Router
from businessos.http.middleware import MiddlewareRegistry
from businessos.jobs import JobHandlerRegistry
from businessos.messages import EventBus, MessageDispatcher
from businessos.metadata import MetadataRegistry
from businessos.migrations import MigrationCoordinator
from businessos.modules import (
    LifecycleManager,
    ModuleRegistry,
    RegistrationController,
    UpgradeCoordinator,
)
from businessos.permissions import PermissionRegistry
from businessos.providers import ProviderRegistry


@dataclass(frozen=True, slots=True)
class FrameworkRuntime:
    contributions: ContributionGate
    router: Router
    middleware: MiddlewareRegistry
    container: Container
    contracts: ContractRegistry
    metadata: MetadataRegistry
    permissions: PermissionRegistry
    providers: ProviderRegistry
    features: FeatureFlagRegistry
    events: EventBus
    event_consumer: DurableEventConsumer
    messages: MessageDispatcher
    jobs: JobHandlerRegistry
    modules: ModuleRegistry
    lifecycle: LifecycleManager
    upgrades: UpgradeCoordinator
    migrations: MigrationCoordinator

    def registration(self, owner: str) -> RegistrationController:
        generation = self.contributions.reserve(owner)
        return RegistrationController(
            owner,
            router=self.router,
            container=self.container,
            contracts=self.contracts,
            metadata=self.metadata,
            permissions=self.permissions,
            providers=self.providers,
            messages=self.messages,
            features=self.features,
            middleware=self.middleware,
            jobs=self.jobs,
            gate=self.contributions,
            generation=generation,
        )
