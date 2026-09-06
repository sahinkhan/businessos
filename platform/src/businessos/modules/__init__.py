"""BusinessOS module SDK, manifests, discovery, lifecycle and upgrades."""

from businessos.modules.discovery import discover_modules
from businessos.modules.manifest import ModuleDependency, ModuleExecutionType, ModuleManifest
from businessos.modules.registry import (
    LifecycleManager,
    ModuleRegistry,
    ModuleState,
    UpgradeCoordinator,
)
from businessos.modules.sdk import BusinessOSModule, ModuleRegistration

__all__ = [
    "BusinessOSModule",
    "LifecycleManager",
    "ModuleDependency",
    "ModuleExecutionType",
    "ModuleManifest",
    "ModuleRegistration",
    "ModuleRegistry",
    "ModuleState",
    "UpgradeCoordinator",
    "discover_modules",
]
