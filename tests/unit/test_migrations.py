from pathlib import Path

import pytest

from businessos.errors import ConfigurationError, ConflictError
from businessos.migrations import MigrationCoordinator
from businessos.modules import ModuleDependency, ModuleManifest, ModuleRegistry, ModuleState


class MigrationModule:
    def __init__(
        self,
        module_id: str,
        location: Path | str,
        namespace: str,
        *,
        dependencies: tuple[ModuleDependency, ...] = (),
    ) -> None:
        self.manifest = ModuleManifest(
            module_id=module_id,
            name=module_id,
            publisher="tests",
            version="1.0.0",
            platform=">=0.1,<1",
            sdk=">=0.1,<1",
            entry_point="tests:module",
            dependencies=dependencies,
            migrations=(str(location),),
            migration_namespace=namespace,
        )

    async def register(self, registration: object) -> None:
        return None

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


def _revision(
    directory: Path,
    filename: str,
    revision: str,
    *,
    down_revision: str | None = "0001_phase1_kernel",
    branch_label: str | None = None,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    directory.joinpath(filename).write_text(
        "\n".join(
            (
                f"revision = {revision!r}",
                f"down_revision = {down_revision!r}",
                f"branch_labels = {((branch_label,) if branch_label else None)!r}",
                "depends_on = None",
            )
        ),
        encoding="utf-8",
    )


def _registry(*modules: MigrationModule) -> ModuleRegistry:
    registry = ModuleRegistry(platform_version="0.1.0", sdk_version="0.1.0")
    for module in modules:
        registry.add(module)
    return registry


def test_plan_supports_core_and_two_independent_module_heads(tmp_path: Path) -> None:
    alpha_path = tmp_path / "alpha"
    beta_path = tmp_path / "beta"
    _revision(alpha_path, "0001.py", "alpha_0001", branch_label="module_alpha")
    _revision(beta_path, "0001.py", "beta_0001", branch_label="module_beta")
    coordinator = MigrationCoordinator(
        _registry(
            MigrationModule("example.alpha", alpha_path, "module_alpha"),
            MigrationModule("example.beta", beta_path, "module_beta"),
        )
    )

    plan = coordinator.plan()

    assert plan.heads == (
        "0002_module_migration_inventory",
        "alpha_0001",
        "beta_0001",
    )
    assert tuple(source.owner for source in plan.sources) == (
        "businessos.core",
        "example.alpha",
        "example.beta",
    )


def test_plan_rejects_duplicate_revision_and_branch_label(tmp_path: Path) -> None:
    duplicate_revision_path = tmp_path / "duplicate-revision"
    _revision(
        duplicate_revision_path,
        "0001.py",
        "0001_phase1_kernel",
        branch_label="module_duplicate_revision",
    )
    with pytest.raises(ConflictError, match="Duplicate migration revision"):
        MigrationCoordinator(
            _registry(
                MigrationModule(
                    "example.duplicate-revision",
                    duplicate_revision_path,
                    "module_duplicate_revision",
                )
            )
        ).plan()

    alpha_path = tmp_path / "alpha"
    beta_path = tmp_path / "beta"
    _revision(alpha_path, "0001.py", "alpha_0001", branch_label="shared_branch")
    _revision(beta_path, "0001.py", "beta_0001", branch_label="shared_branch")
    with pytest.raises(ConflictError, match="namespace collision"):
        MigrationCoordinator(
            _registry(
                MigrationModule("example.alpha", alpha_path, "shared_branch"),
                MigrationModule("example.beta", beta_path, "shared_branch"),
            )
        ).plan()


def test_plan_rejects_missing_revision_resource_and_dependency(tmp_path: Path) -> None:
    missing_revision_path = tmp_path / "missing-revision"
    _revision(
        missing_revision_path,
        "0001.py",
        "missing_0001",
        down_revision="not_installed",
        branch_label="module_missing_revision",
    )
    with pytest.raises(ConfigurationError, match="references missing revision"):
        MigrationCoordinator(
            _registry(
                MigrationModule(
                    "example.missing-revision",
                    missing_revision_path,
                    "module_missing_revision",
                )
            )
        ).plan()

    missing_package = MigrationModule(
        "example.missing-package",
        "python://package_that_does_not_exist/migrations",
        "module_missing_package",
    )
    with pytest.raises(ConfigurationError, match="package or resource is unavailable"):
        MigrationCoordinator(_registry(missing_package)).plan()

    alpha_path = tmp_path / "alpha"
    beta_path = tmp_path / "beta"
    _revision(alpha_path, "0001.py", "alpha_0001", branch_label="module_alpha")
    _revision(
        beta_path,
        "0001.py",
        "beta_0001",
        down_revision="alpha_0001",
        branch_label="module_beta",
    )
    with pytest.raises(ConfigurationError, match="undeclared module"):
        MigrationCoordinator(
            _registry(
                MigrationModule("example.alpha", alpha_path, "module_alpha"),
                MigrationModule("example.beta", beta_path, "module_beta"),
            )
        ).plan()


def test_disabled_and_retired_module_migrations_remain_discoverable(tmp_path: Path) -> None:
    disabled_path = tmp_path / "disabled"
    retired_path = tmp_path / "retired"
    _revision(disabled_path, "0001.py", "disabled_0001", branch_label="module_disabled")
    _revision(retired_path, "0001.py", "retired_0001", branch_label="module_retired")
    registry = _registry(
        MigrationModule("example.disabled", disabled_path, "module_disabled"),
        MigrationModule("example.retired", retired_path, "module_retired"),
    )
    registry.get("example.disabled").state = ModuleState.DISABLED
    registry.get("example.retired").state = ModuleState.REMOVED

    plan = MigrationCoordinator(registry).plan()

    assert {revision.revision for revision in plan.revisions} >= {
        "disabled_0001",
        "retired_0001",
    }
