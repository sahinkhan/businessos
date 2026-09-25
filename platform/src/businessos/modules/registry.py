"""Deterministic module dependency, lifecycle and upgrade coordination."""

import asyncio
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from packaging.specifiers import SpecifierSet
from packaging.version import Version
from pydantic import ValidationError

from businessos.activation import ContributionGeneration
from businessos.dependency_entitlement import InternalRestrictedDependencyEntitlement
from businessos.errors import ConfigurationError, ConflictError, NotFoundError
from businessos.modules.artifact import (
    ApprovedModuleArtifact,
    internal_issue_restricted_dependency_entitlement,
)
from businessos.modules.manifest import ModuleContractDeclaration, ModuleManifest
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
    manifest: ModuleManifest
    state: ModuleState = ModuleState.AVAILABLE
    error: str | None = None
    registration: ModuleRegistration | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    started: bool = False


@dataclass(frozen=True, slots=True)
class UpgradePlan:
    ordered_module_ids: tuple[str, ...]
    migration_locations: tuple[tuple[str, str], ...]


def _ordered_manifests(
    manifests: Mapping[str, ModuleManifest],
) -> tuple[ModuleManifest, ...]:
    pending = set(manifests)
    resolved: list[str] = []
    while pending:
        ready: list[str] = []
        for module_id in sorted(pending):
            manifest = manifests[module_id]
            _validate_dependencies(manifest, manifests)
            if all(dependency.module_id in resolved for dependency in manifest.dependencies):
                ready.append(module_id)
        if not ready:
            cycle = ", ".join(sorted(pending))
            raise ConfigurationError(f"Circular module dependency detected: {cycle}")
        for module_id in ready:
            pending.remove(module_id)
            resolved.append(module_id)
    return tuple(manifests[module_id] for module_id in resolved)


def _validate_dependencies(
    manifest: ModuleManifest,
    manifests: Mapping[str, ModuleManifest],
) -> None:
    for dependency in manifest.dependencies:
        target = manifests.get(dependency.module_id)
        if target is None:
            raise ConfigurationError(
                f"Module '{manifest.module_id}' requires missing module '{dependency.module_id}'"
            )
        if Version(target.version) not in SpecifierSet(dependency.version):
            raise ConfigurationError(
                f"Module '{manifest.module_id}' requires '{dependency.module_id}' "
                f"{dependency.version}, found {target.version}"
            )


def _validate_contract_upgrade(
    module_id: str,
    kind: str,
    current: tuple[ModuleContractDeclaration, ...],
    target: tuple[ModuleContractDeclaration, ...],
) -> None:
    proposed = {declaration.contract_id: declaration for declaration in target}
    for declaration in current:
        replacement = proposed.get(declaration.contract_id)
        if replacement is None:
            raise ConfigurationError(
                f"Upgrade target removes {kind} contract "
                f"'{declaration.contract_id}' from module '{module_id}'"
            )
        if Version(replacement.version) < Version(declaration.version):
            raise ConfigurationError(
                f"Upgrade target downgrades {kind} contract "
                f"'{declaration.contract_id}' in module '{module_id}'"
            )


def _validate_manifest_upgrade(current: ModuleManifest, target: ModuleManifest) -> None:
    for kind, old_contracts, new_contracts in (
        ("API", current.api_contracts, target.api_contracts),
        ("event", current.event_contracts, target.event_contracts),
        ("public", current.public_contracts, target.public_contracts),
    ):
        _validate_contract_upgrade(current.module_id, kind, old_contracts, new_contracts)
    for kind, old_values, new_values in (
        ("UI contribution", current.ui_contributions, target.ui_contributions),
        ("configuration scope", current.configuration_scopes, target.configuration_scopes),
        ("localization resource", current.localization_resources, target.localization_resources),
    ):
        removed = set(old_values) - set(new_values)
        if removed:
            raise ConfigurationError(
                f"Upgrade target removes {kind} {sorted(removed)} from module '{current.module_id}'"
            )
    for kind, old_support, new_support in (
        ("tenant export", current.tenant_export_supported, target.tenant_export_supported),
        ("tenant delete", current.tenant_delete_supported, target.tenant_delete_supported),
    ):
        if (old_support is True and new_support is not True) or (
            old_support is False and new_support is None
        ):
            raise ConfigurationError(
                f"Upgrade target withdraws {kind} declaration from module '{current.module_id}'"
            )
    next_resources = {
        (item.resource_namespace, item.contract_version): item for item in target.resource_ownership
    }
    for old in current.resource_ownership:
        replacement = next_resources.get((old.resource_namespace, old.contract_version))
        if replacement is None or not set(old.aliases).issubset(replacement.aliases):
            raise ConfigurationError("Upgrade target withdraws resource ownership or aliases")


def _validate_resource_claims(manifests: Iterable[ModuleManifest]) -> None:
    allocated: dict[tuple[str, str], str] = {}
    for manifest in manifests:
        for ownership in manifest.resource_ownership:
            for namespace in (ownership.resource_namespace, *ownership.aliases):
                key = (namespace, ownership.contract_version)
                prior = allocated.get(key)
                if prior is not None:
                    raise ConflictError(
                        f"Resource namespace/version collision between '{prior}' "
                        f"and '{manifest.module_id}'"
                    )
                allocated[key] = manifest.module_id


class ModuleRegistry:
    def __init__(
        self,
        *,
        platform_version: str,
        sdk_version: str,
        approved_artifacts: Mapping[str, ApprovedModuleArtifact] | None = None,
        coordinator_ids: frozenset[str] = frozenset(),
    ) -> None:
        self.platform_version = Version(platform_version)
        self.sdk_version = Version(sdk_version)
        self.python_version = Version(
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        )
        self._modules: dict[str, RegisteredModule] = {}
        self._approved_artifacts = dict(approved_artifacts or {})
        self._coordinator_ids = coordinator_ids
        self._allocations: dict[str, tuple[str, str]] = {}

    def add(self, module: BusinessOSModule) -> None:
        try:
            manifest = ModuleManifest.model_validate(module.manifest.model_dump())
        except ValidationError as exc:
            raise ConfigurationError("Module manifest failed admission validation") from exc
        module_id = manifest.module_id
        if module_id in self._modules:
            raise ConflictError(f"Module already registered: {module_id}")
        if not manifest.supports(
            platform=str(self.platform_version),
            sdk=str(self.sdk_version),
            python=str(self.python_version),
        ):
            raise ConfigurationError(f"Module is incompatible with this runtime: {module_id}")
        if manifest.resource_ownership or module_id in self._coordinator_ids:
            grant = self._approved_artifacts.get(module_id)
            if grant is None:
                raise ConfigurationError("Resource or coordinator claim requires approved artifact")
            grant.verify(module, manifest)
            allocation = (grant.publisher, grant.package_identity)
            previous = self._allocations.get(module_id)
            if previous is not None and previous != allocation:
                raise ConfigurationError("Retired module ID allocation cannot transfer publisher")
            self._allocations[module_id] = allocation
        self._modules[module_id] = RegisteredModule(module=module, manifest=manifest)

    def replace(self, module: BusinessOSModule, artifact: ApprovedModuleArtifact) -> None:
        """Stage a disabled module's reviewed replacement under its allocated ID."""
        try:
            manifest = ModuleManifest.model_validate(module.manifest.model_dump())
        except ValidationError as exc:
            raise ConfigurationError(
                "Module replacement manifest failed admission validation"
            ) from exc
        module_id = manifest.module_id
        current = self.get(module_id)
        if (
            current.lock.locked()
            or current.registration is not None
            or current.started
            or current.state not in {ModuleState.DISABLED, ModuleState.INSTALLED}
        ):
            raise ConfigurationError("Module replacement requires an inactive installed module")
        previous_grant = self._approved_artifacts.get(module_id)
        if previous_grant is None or previous_grant.install_identity == artifact.install_identity:
            raise ConfigurationError("Replacement requires fresh approved artifact evidence")
        artifact.verify(module, manifest)
        if (artifact.publisher, artifact.package_identity) != self._allocations.get(module_id):
            raise ConfigurationError("Replacement cannot transfer a module ID allocation")
        if not manifest.supports(
            platform=str(self.platform_version),
            sdk=str(self.sdk_version),
            python=str(self.python_version),
        ):
            raise ConfigurationError("Replacement is incompatible with this runtime")
        if Version(manifest.version) < Version(current.manifest.version):
            raise ConfigurationError("Replacement cannot downgrade the module")
        _validate_manifest_upgrade(current.manifest, manifest)
        self._approved_artifacts[module_id] = artifact
        self._modules[module_id] = RegisteredModule(
            module=module, manifest=manifest, state=ModuleState.INSTALLED
        )

    def get(self, module_id: str) -> RegisteredModule:
        registered = self._modules.get(module_id)
        if registered is None:
            raise NotFoundError(f"Unknown module: {module_id}")
        return registered

    def is_approved_coordinator(self, module_id: str) -> bool:
        return module_id in self._coordinator_ids and module_id in self._approved_artifacts

    def restricted_dependency_entitlement(
        self, module_id: str, generation: ContributionGeneration
    ) -> InternalRestrictedDependencyEntitlement | None:
        """Issue only from protected inventory and the exact admitted module artifact."""
        grant = self._approved_artifacts.get(module_id)
        if grant is None or not grant.first_party:
            return None
        registered = self.get(module_id)
        return internal_issue_restricted_dependency_entitlement(
            grant, registered.module, registered.manifest, generation
        )

    def ordered(self) -> tuple[RegisteredModule, ...]:
        manifests = {
            module_id: registered.manifest for module_id, registered in self._modules.items()
        }
        _validate_resource_claims(manifests.values())
        return tuple(
            self._modules[manifest.module_id] for manifest in _ordered_manifests(manifests)
        )

    def entries(self) -> tuple[RegisteredModule, ...]:
        return tuple(self._modules[module_id] for module_id in sorted(self._modules))


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
                await self._enable(registered.manifest.module_id)
                if not was_enabled and registered.state is ModuleState.ENABLED:
                    enabled.append(registered.manifest.module_id)
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
            if self._registry.get(module_id) is not registered:
                raise ConfigurationError("Module was replaced while activation was pending")
            if registered.state is ModuleState.ENABLED:
                return
            if registered.state is ModuleState.RETIRED:
                raise ConfigurationError(f"Retired module cannot be enabled: {module_id}")
            if registered.state not in {ModuleState.INSTALLED, ModuleState.DISABLED}:
                return
            registration = self._registration_factory(module_id)
            start_attempted = False
            try:
                if registered.module.manifest != registered.manifest:
                    raise ConfigurationError("Module manifest changed after artifact admission")
                self._validate_active_dependencies(registered.manifest)
                self._validate_capabilities(registered.manifest)
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
                        registered.manifest.module_id,
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
            candidate.manifest.module_id
            for candidate in self._registry.entries()
            if candidate.state is ModuleState.ENABLED
            and any(
                dependency.module_id == module_id for dependency in candidate.manifest.dependencies
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
        current_entries = self._registry.entries()
        current_ids = {registered.manifest.module_id for registered in current_entries}
        unknown = set(target_map) - current_ids
        if unknown:
            raise ConfigurationError(f"Upgrade targets contain unknown modules: {sorted(unknown)}")
        proposed = {
            registered.manifest.module_id: target_map.get(
                registered.manifest.module_id,
                registered.manifest,
            )
            for registered in current_entries
        }
        for registered in current_entries:
            current = registered.manifest
            target = proposed[current.module_id]
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
            _validate_manifest_upgrade(current, target)
        _validate_resource_claims(proposed.values())
        ordered = _ordered_manifests(proposed)
        migrations = tuple(
            (manifest.module_id, location)
            for manifest in ordered
            for location in manifest.migrations
        )
        return UpgradePlan(tuple(manifest.module_id for manifest in ordered), migrations)
