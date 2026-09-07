"""Deterministic module dependency, lifecycle and upgrade coordination."""

import asyncio
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from businessos.errors import ConfigurationError, ConflictError, NotFoundError
from businessos.modules.manifest import ModuleManifest
from businessos.modules.sdk import BusinessOSModule, ModuleRegistration
from businessos.providers import ProviderRegistry


class ModuleState(StrEnum):
    AVAILABLE = "available"
    INSTALLING = "installing"
    INSTALLED = "installed"
    ENABLED = "enabled"
    DISABLED = "disabled"
    UPGRADING = "upgrading"
    FAILED = "failed"
    UNINSTALLING = "uninstalling"
    RETIRED = "retired"
    REMOVED = "retired"


@dataclass(slots=True)
class RegisteredModule:
    module: BusinessOSModule
    state: ModuleState = ModuleState.AVAILABLE
    error: str | None = None
    registration: ModuleRegistration | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    started: bool = False


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
        *,
        providers: ProviderRegistry | None = None,
        drain_timeout_seconds: float = 10.0,
    ) -> None:
        self._registry = registry
        self._registration_factory = registration_factory
        self._providers = providers
        self._drain_timeout_seconds = drain_timeout_seconds
        self._lifecycle_lock = asyncio.Lock()

    async def install_all(self) -> None:
        for registered in self._registry.ordered():
            if registered.state is not ModuleState.AVAILABLE:
                continue
            registered.state = ModuleState.INSTALLING
            registered.state = ModuleState.INSTALLED

    async def enable_all(self) -> None:
        async with self._lifecycle_lock:
            await self._enable_all()

    async def _enable_all(self) -> None:
        enabled: list[str] = []
        try:
            for registered in self._registry.ordered():
                was_enabled = registered.state is ModuleState.ENABLED
                await self._enable(registered.module.manifest.module_id)
                if not was_enabled and registered.state is ModuleState.ENABLED:
                    enabled.append(registered.module.manifest.module_id)
        except BaseException as activation_error:
            rollback_errors: list[BaseException] = []
            for module_id in reversed(enabled):
                try:
                    await self._disable(module_id, validate_dependents=False)
                except BaseException as rollback_error:
                    rollback_errors.append(rollback_error)
            if rollback_errors:
                raise BaseExceptionGroup(
                    "Module activation sequence and rollback failed",
                    [activation_error, *rollback_errors],
                ) from None
            raise

    async def enable(self, module_id: str) -> None:
        async with self._lifecycle_lock:
            await self._enable(module_id)

    async def _enable(self, module_id: str) -> None:
        registered = self._registry.get(module_id)
        async with registered.lock:
            if registered.state is ModuleState.ENABLED:
                return
            if registered.state is ModuleState.RETIRED:
                raise ConfigurationError(f"Retired module cannot be enabled: {module_id}")
            if registered.state not in {ModuleState.INSTALLED, ModuleState.DISABLED}:
                return
            registration = self._registration_factory(module_id)
            start_attempted = False
            try:
                self._validate_active_dependencies(registered.module.manifest)
                self._validate_capabilities(registered.module.manifest)
                await registered.module.register(registration)
                start_attempted = True
                await registered.module.start()
                registered.started = True
                registration.publish()
            except BaseException as exc:
                rollback_errors: list[BaseException] = []
                if start_attempted:
                    try:
                        await registered.module.stop()
                        registered.started = False
                    except BaseException as rollback_error:
                        registered.started = True
                        rollback_errors.append(rollback_error)
                try:
                    await registration.rollback()
                except BaseException as rollback_error:
                    rollback_errors.append(rollback_error)
                registered.state = ModuleState.FAILED
                registered.error = type(exc).__name__
                if rollback_errors:
                    raise BaseExceptionGroup(
                        f"Module activation and rollback failed: {module_id}",
                        [exc, *rollback_errors],
                    ) from None
                raise
            registered.registration = registration
            registered.error = None
            registered.state = ModuleState.ENABLED

    def _validate_active_dependencies(self, manifest: ModuleManifest) -> None:
        for dependency in manifest.dependencies:
            target = self._registry.get(dependency.module_id)
            if target.state is not ModuleState.ENABLED:
                raise ConfigurationError(
                    f"Module '{manifest.module_id}' requires enabled module "
                    f"'{dependency.module_id}', found {target.state.value}"
                )

    def _validate_capabilities(self, manifest: ModuleManifest) -> None:
        if not manifest.capabilities:
            return
        if self._providers is None:
            raise ConfigurationError(
                f"Module '{manifest.module_id}' requires infrastructure capabilities"
            )
        for capability in manifest.capabilities:
            try:
                self._providers.get(capability)
            except NotFoundError as exc:
                raise ConfigurationError(
                    f"Module '{manifest.module_id}' requires missing capability '{capability}'"
                ) from exc

    async def disable_all(self) -> None:
        async with self._lifecycle_lock:
            errors: list[BaseException] = []
            for registered in reversed(self._registry.ordered()):
                try:
                    await self._disable(
                        registered.module.manifest.module_id,
                        validate_dependents=False,
                    )
                except BaseException as exc:
                    errors.append(exc)
            if errors:
                raise BaseExceptionGroup("Module disable failed", errors)

    async def disable(self, module_id: str) -> None:
        async with self._lifecycle_lock:
            await self._disable(module_id, validate_dependents=True)

    async def _disable(self, module_id: str, *, validate_dependents: bool) -> None:
        registered = self._registry.get(module_id)
        async with registered.lock:
            if registered.state is ModuleState.RETIRED:
                return
            if (
                registered.state is ModuleState.FAILED
                and registered.registration is None
                and not registered.started
            ):
                return
            if registered.state not in {ModuleState.ENABLED, ModuleState.FAILED}:
                return
            if validate_dependents:
                self._reject_enabled_dependents(module_id)
            registration = registered.registration
            if registration is None and registered.state is ModuleState.ENABLED:
                raise ConfigurationError(f"Enabled module has no registration: {module_id}")
            errors: list[BaseException] = []
            if registration is not None:
                try:
                    await registration.stop_accepting(timeout_seconds=self._drain_timeout_seconds)
                except BaseException as exc:
                    registered.state = ModuleState.FAILED
                    registered.error = type(exc).__name__
                    raise
            if registered.started:
                try:
                    await registered.module.stop()
                    registered.started = False
                except BaseException as exc:
                    errors.append(exc)
            if registration is not None:
                try:
                    await registration.remove()
                    registered.registration = None
                except BaseException as exc:
                    errors.append(exc)
            if errors:
                registered.state = ModuleState.FAILED
                registered.error = ",".join(type(error).__name__ for error in errors)
                raise BaseExceptionGroup(f"Module disable failed: {module_id}", errors)
            registered.state = ModuleState.DISABLED
            registered.error = None

    async def retire(self, module_id: str) -> None:
        async with self._lifecycle_lock:
            await self._retire(module_id)

    async def _retire(self, module_id: str) -> None:
        registered = self._registry.get(module_id)
        self._reject_enabled_dependents(module_id)
        if (
            registered.state is ModuleState.ENABLED
            or registered.started
            or registered.registration is not None
        ):
            await self._disable(module_id, validate_dependents=False)
        async with registered.lock:
            if registered.state is ModuleState.RETIRED:
                return
            if registered.state not in {
                ModuleState.INSTALLED,
                ModuleState.DISABLED,
                ModuleState.FAILED,
            }:
                raise ConfigurationError(
                    f"Module cannot retire from state {registered.state}: {module_id}"
                )
            if registered.registration is not None:
                await registered.registration.rollback()
                registered.registration = None
            registered.state = ModuleState.UNINSTALLING
            registration = self._registration_factory(module_id)
            await registration.rollback()
            registration.retire_owner()
            registered.state = ModuleState.RETIRED
            registered.error = None

    def _reject_enabled_dependents(self, module_id: str) -> None:
        dependents = tuple(
            candidate.module.manifest.module_id
            for candidate in self._registry.entries()
            if candidate.state is ModuleState.ENABLED
            and any(
                dependency.module_id == module_id
                for dependency in candidate.module.manifest.dependencies
            )
        )
        if dependents:
            raise ConfigurationError(
                f"Cannot change module '{module_id}' with enabled dependents: {dependents}"
            )


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
