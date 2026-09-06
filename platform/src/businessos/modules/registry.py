"""Deterministic module dependency, lifecycle and upgrade coordination."""

import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from businessos.errors import ConfigurationError, ConflictError, NotFoundError
from businessos.modules.manifest import ModuleManifest
from businessos.modules.sdk import BusinessOSModule, ModuleRegistration


class ModuleState(StrEnum):
    AVAILABLE = "available"
    INSTALLING = "installing"
    INSTALLED = "installed"
    ENABLED = "enabled"
    DISABLED = "disabled"
    UPGRADING = "upgrading"
    FAILED = "failed"
    UNINSTALLING = "uninstalling"
    REMOVED = "removed"


@dataclass(slots=True)
class RegisteredModule:
    module: BusinessOSModule
    state: ModuleState = ModuleState.AVAILABLE
    error: str | None = None


@dataclass(frozen=True, slots=True)
class UpgradePlan:
    ordered_module_ids: tuple[str, ...]
    migration_locations: tuple[tuple[str, str], ...]


class ModuleRegistry:
    def __init__(self, *, platform_version: str, sdk_version: str) -> None:
        self.platform_version = Version(platform_version)
        self.sdk_version = Version(sdk_version)
        self.python_version = Version(
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        )
        self._modules: dict[str, RegisteredModule] = {}

    def add(self, module: BusinessOSModule) -> None:
        module_id = module.manifest.module_id
        if module_id in self._modules:
            raise ConflictError(f"Module already registered: {module_id}")
        if not module.manifest.supports(
            platform=str(self.platform_version),
            sdk=str(self.sdk_version),
            python=str(self.python_version),
        ):
            raise ConfigurationError(f"Module is incompatible with this runtime: {module_id}")
        self._modules[module_id] = RegisteredModule(module=module)

    def get(self, module_id: str) -> RegisteredModule:
        registered = self._modules.get(module_id)
        if registered is None:
            raise NotFoundError(f"Unknown module: {module_id}")
        return registered

    def ordered(self) -> tuple[RegisteredModule, ...]:
        pending = set(self._modules)
        resolved: list[str] = []
        while pending:
            ready: list[str] = []
            for module_id in sorted(pending):
                manifest = self._modules[module_id].module.manifest
                self._validate_dependencies(manifest)
                if all(dependency.module_id in resolved for dependency in manifest.dependencies):
                    ready.append(module_id)
            if not ready:
                cycle = ", ".join(sorted(pending))
                raise ConfigurationError(f"Circular module dependency detected: {cycle}")
            for module_id in ready:
                pending.remove(module_id)
                resolved.append(module_id)
        return tuple(self._modules[module_id] for module_id in resolved)

    def entries(self) -> tuple[RegisteredModule, ...]:
        return tuple(self._modules[module_id] for module_id in sorted(self._modules))

    def _validate_dependencies(self, manifest: ModuleManifest) -> None:
        for dependency in manifest.dependencies:
            target = self._modules.get(dependency.module_id)
            if target is None:
                raise ConfigurationError(
                    f"Module '{manifest.module_id}' requires missing module "
                    f"'{dependency.module_id}'"
                )
            if Version(target.module.manifest.version) not in SpecifierSet(dependency.version):
                raise ConfigurationError(
                    f"Module '{manifest.module_id}' requires '{dependency.module_id}' "
                    f"{dependency.version}, found {target.module.manifest.version}"
                )


class LifecycleManager:
    def __init__(
        self,
        registry: ModuleRegistry,
        registration_factory: Callable[[str], ModuleRegistration],
    ) -> None:
        self._registry = registry
        self._registration_factory = registration_factory

    async def install_all(self) -> None:
        for registered in self._registry.ordered():
            if registered.state is not ModuleState.AVAILABLE:
                continue
            registered.state = ModuleState.INSTALLING
            try:
                await registered.module.register(
                    self._registration_factory(registered.module.manifest.module_id)
                )
            except Exception as exc:
                registered.state = ModuleState.FAILED
                registered.error = str(exc)
                raise
            registered.state = ModuleState.INSTALLED

    async def enable_all(self) -> None:
        for registered in self._registry.ordered():
            if registered.state not in {ModuleState.INSTALLED, ModuleState.DISABLED}:
                continue
            try:
                await registered.module.start()
            except Exception as exc:
                registered.state = ModuleState.FAILED
                registered.error = str(exc)
                raise
            registered.state = ModuleState.ENABLED

    async def disable_all(self) -> None:
        for registered in reversed(self._registry.ordered()):
            if registered.state is not ModuleState.ENABLED:
                continue
            try:
                await registered.module.stop()
            except Exception as exc:
                registered.state = ModuleState.FAILED
                registered.error = str(exc)
                raise
            registered.state = ModuleState.DISABLED

    async def retire(self, module_id: str) -> None:
        registered = self._registry.get(module_id)
        if registered.state is ModuleState.ENABLED:
            await registered.module.stop()
            registered.state = ModuleState.DISABLED
        if registered.state not in {
            ModuleState.INSTALLED,
            ModuleState.DISABLED,
            ModuleState.FAILED,
        }:
            raise ConfigurationError(
                f"Module cannot retire from state {registered.state}: {module_id}"
            )
        registered.state = ModuleState.UNINSTALLING
        registered.state = ModuleState.REMOVED


class UpgradeCoordinator:
    """Validate target manifests and produce deterministic module migration order."""

    def __init__(self, registry: ModuleRegistry) -> None:
        self._registry = registry

    def plan(self, targets: Iterable[ModuleManifest]) -> UpgradePlan:
        target_list = tuple(targets)
        target_map = {manifest.module_id: manifest for manifest in target_list}
        if len(target_map) != len(target_list):
            raise ConflictError("Upgrade targets must contain unique module IDs")
        migrations: list[tuple[str, str]] = []
        ordered_ids: list[str] = []
        for registered in self._registry.ordered():
            current = registered.module.manifest
            target = target_map.get(current.module_id, current)
            if Version(target.version) < Version(current.version):
                raise ConfigurationError(
                    f"Upgrade target cannot downgrade module '{current.module_id}'"
                )
            if not target.supports(
                platform=str(self._registry.platform_version),
                sdk=str(self._registry.sdk_version),
                python=str(self._registry.python_version),
            ):
                raise ConfigurationError(f"Upgrade target is incompatible: {target.module_id}")
            ordered_ids.append(target.module_id)
            migrations.extend((target.module_id, location) for location in target.migrations)
        unknown = set(target_map) - set(ordered_ids)
        if unknown:
            raise ConfigurationError(f"Upgrade targets contain unknown modules: {sorted(unknown)}")
        return UpgradePlan(tuple(ordered_ids), tuple(migrations))
