"""Composition of all framework-owned registries and module lifecycle services."""

from dataclasses import dataclass

from businessos.contracts import ContractRegistry
from businessos.di import Container
from businessos.features import FeatureFlagRegistry
from businessos.http import Router
from businessos.messages import EventBus, MessageDispatcher
from businessos.metadata import MetadataRegistry
from businessos.migrations import MigrationCoordinator
from businessos.modules import (
    LifecycleManager,
    ModuleRegistration,
    ModuleRegistry,
    UpgradeCoordinator,
)
from businessos.permissions import PermissionRegistry
from businessos.providers import ProviderRegistry


@dataclass(frozen=True, slots=True)
class FrameworkRuntime:
    router: Router
    container: Container
    contracts: ContractRegistry
    metadata: MetadataRegistry
    permissions: PermissionRegistry
    providers: ProviderRegistry
    features: FeatureFlagRegistry
    events: EventBus
    messages: MessageDispatcher
    modules: ModuleRegistry
    lifecycle: LifecycleManager
    upgrades: UpgradeCoordinator
    migrations: MigrationCoordinator

    def registration(self, owner: str) -> ModuleRegistration:
        return ModuleRegistration(
            owner,
            router=self.router,
            container=self.container,
            contracts=self.contracts,
            metadata=self.metadata,
            permissions=self.permissions,
            providers=self.providers,
            messages=self.messages,
            features=self.features,
        )
