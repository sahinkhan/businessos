import asyncio
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
import pytest

from businessos.errors import ConfigurationError
from businessos.migrations import MigrationCoordinator
from businessos.modules import ModuleManifest, ModuleRegistry


class HistoryModule:
    def __init__(
        self,
        location: Path,
        *,
        module_id: str = "example.history",
        namespace: str = "module_history",
        version: str = "1.0.0",
    ) -> None:
        self.manifest = ModuleManifest(
            module_id=module_id,
            name="History test module",
            publisher="tests",
            version=version,
            platform=">=0.1,<1",
            sdk=">=0.1,<1",
            entry_point="tests:history",
            migrations=(str(location),),
            migration_namespace=namespace,
        )

    async def register(self, registration: object) -> None:
        return None

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


def _coordinator(
    location: Path,
    *,
    module_id: str = "example.history",
    namespace: str = "module_history",
    version: str = "1.0.0",
) -> MigrationCoordinator:
    registry = ModuleRegistry(platform_version="0.1.0", sdk_version="0.1.0")
    registry.add(
        HistoryModule(
            location,
            module_id=module_id,
            namespace=namespace,
            version=version,
        )
    )
    return MigrationCoordinator(registry)


def _revision(
    directory: Path,
    filename: str,
    revision: str,
    *,
    parent: str,
    label: str | None = None,
    dependency: str | None = None,
    marker: str = "stable",
    failure: str | None = None,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    if failure == "error":
        upgrade = 'raise RuntimeError("forced migration failure")'
    elif failure == "cancel":
        upgrade = "raise __import__('asyncio').CancelledError()"
    else:
        upgrade = "return None"
    directory.joinpath(filename).write_text(
        "\n".join(
            (
                f"revision = {revision!r}",
                f"down_revision = {parent!r}",
                f"branch_labels = {((label,) if label else None)!r}",
                f"depends_on = {dependency!r}",
                f"marker = {marker!r}",
                "def upgrade():",
                f"    {upgrade}",
                "def downgrade():",
                "    return None",
            )
        ),
        encoding="utf-8",
    )


def _psycopg_url(sqlalchemy_url: str) -> str:
    return sqlalchemy_url.replace("postgresql+psycopg://", "postgresql://", 1)


def _inventory(
    database_url: str,
) -> tuple[str, str, list[str], str, int, list[dict[str, object]]]:
    with psycopg.connect(_psycopg_url(database_url)) as connection:
        row = connection.execute(
            "SELECT module_version, migration_namespace, locations, "
            "distribution_identity, inventory_format, revision_manifest "
            "FROM platform_module.installed_module_migrations "
            "WHERE module_id = 'example.history'"
        ).fetchone()
    assert row is not None
    return row


@pytest.mark.integration
@pytest.mark.postgres
def test_inventory_is_append_only_and_tamper_detecting(
    tmp_path: Path, postgres_migration_database_url: str
) -> None:
    history = tmp_path / "history"
    _revision(
        history,
        "0001.py",
        "history_0001",
        parent="0001_phase1_kernel",
        label="module_history",
    )
    _revision(history, "0002.py", "history_0002", parent="history_0001")
    coordinator = _coordinator(history)
    coordinator.upgrade(postgres_migration_database_url)
    initial_files = {path.name: path.read_bytes() for path in history.glob("*.py")}

    version, namespace, locations, distribution, inventory_format, manifest = _inventory(
        postgres_migration_database_url
    )
    assert (version, namespace, locations, distribution, inventory_format) == (
        "1.0.0",
        "module_history",
        ["filesystem://example.history/history"],
        "module:example.history",
        2,
    )
    assert [item["revision"] for item in manifest] == ["history_0001", "history_0002"]
    assert all(len(str(item["fingerprint"])) == 64 for item in manifest)

    history.joinpath("0001.py").unlink()
    _revision(
        history,
        "0002.py",
        "history_0002",
        parent="0001_phase1_kernel",
        label="module_history",
    )
    with pytest.raises(ConfigurationError, match="removed historical revisions"):
        _coordinator(history).plan(postgres_migration_database_url)

    for filename, content in initial_files.items():
        history.joinpath(filename).write_bytes(content)
    _revision(
        history,
        "0002.py",
        "history_0002",
        parent="history_0001",
        marker="replacement",
    )
    with pytest.raises(ConfigurationError, match="rewrote historical revision"):
        _coordinator(history).plan(postgres_migration_database_url)

    for filename, content in initial_files.items():
        history.joinpath(filename).write_bytes(content)
    _revision(
        history,
        "0002.py",
        "history_0002",
        parent="0001_phase1_kernel",
    )
    with pytest.raises(ConfigurationError, match="rewrote historical revision"):
        _coordinator(history).plan(postgres_migration_database_url)

    for filename, content in initial_files.items():
        history.joinpath(filename).write_bytes(content)
    _revision(
        history,
        "0002.py",
        "history_0002",
        parent="history_0001",
        dependency="0002_module_migration_inventory",
    )
    with pytest.raises(ConfigurationError, match="rewrote historical revision"):
        _coordinator(history).plan(postgres_migration_database_url)

    for filename, content in initial_files.items():
        history.joinpath(filename).write_bytes(content)
    _revision(
        history,
        "0001.py",
        "history_0001",
        parent="0001_phase1_kernel",
        label="module_history_changed",
    )
    with pytest.raises(ConfigurationError, match="changed migration namespace"):
        _coordinator(history, namespace="module_history_changed").plan(
            postgres_migration_database_url
        )

    for filename, content in initial_files.items():
        history.joinpath(filename).write_bytes(content)
    renamed = tmp_path / "history-renamed"
    shutil.copytree(history, renamed)
    with pytest.raises(ConfigurationError, match="changed migration location"):
        _coordinator(renamed).plan(postgres_migration_database_url)

    with pytest.raises(ConfigurationError, match="packages are unavailable"):
        _coordinator(
            history,
            module_id="example.history-substitute",
            namespace="module_history",
        ).plan(postgres_migration_database_url)

    with pytest.raises(ConfigurationError, match="cannot downgrade"):
        _coordinator(history, version="0.9.0").plan(postgres_migration_database_url)

    _revision(history, "0003.py", "history_0003", parent="history_0002")
    append_coordinator = _coordinator(history, version="1.1.0")
    assert "history_0003" in {
        revision.revision
        for revision in append_coordinator.plan(postgres_migration_database_url).revisions
    }
    append_coordinator.upgrade(postgres_migration_database_url)
    appended_inventory = _inventory(postgres_migration_database_url)
    assert appended_inventory[0] == "1.1.0"
    assert [item["revision"] for item in appended_inventory[-1]] == [
        "history_0001",
        "history_0002",
        "history_0003",
    ]

    _revision(
        history,
        "0004.py",
        "history_0004",
        parent="history_0003",
        failure="error",
    )
    with pytest.raises(RuntimeError, match="forced migration failure"):
        _coordinator(history, version="1.2.0").upgrade(postgres_migration_database_url)
    failed_inventory = _inventory(postgres_migration_database_url)
    assert failed_inventory == appended_inventory

    _revision(
        history,
        "0004.py",
        "history_0004",
        parent="history_0003",
        failure="cancel",
    )
    with pytest.raises(asyncio.CancelledError):
        _coordinator(history, version="1.2.0").upgrade(postgres_migration_database_url)
    assert _inventory(postgres_migration_database_url) == appended_inventory
    with psycopg.connect(_psycopg_url(postgres_migration_database_url)) as connection:
        heads = {row[0] for row in connection.execute("SELECT version_num FROM alembic_version")}
    assert heads == {"0003_migration_graph_inventory", "history_0003"}


@pytest.mark.integration
@pytest.mark.postgres
def test_concurrent_migrations_serialize_graph_and_inventory(
    tmp_path: Path, postgres_migration_database_url: str
) -> None:
    history = tmp_path / "concurrent-history"
    _revision(
        history,
        "0001.py",
        "concurrent_history_0001",
        parent="0001_phase1_kernel",
        label="module_history",
    )

    def upgrade(_: int) -> None:
        _coordinator(history).upgrade(postgres_migration_database_url)

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert tuple(executor.map(upgrade, range(2))) == (None, None)

    inventory = _inventory(postgres_migration_database_url)
    assert inventory[2] == ["filesystem://example.history/concurrent-history"]
    assert [item["revision"] for item in inventory[-1]] == ["concurrent_history_0001"]
    with psycopg.connect(_psycopg_url(postgres_migration_database_url)) as connection:
        heads = {row[0] for row in connection.execute("SELECT version_num FROM alembic_version")}
    assert heads == {"0003_migration_graph_inventory", "concurrent_history_0001"}
