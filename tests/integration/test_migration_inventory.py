import asyncio
import copy
import multiprocessing
import shutil
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from businessos.errors import ConfigurationError
from businessos.migrations import MIGRATION_LOCK_NAME, MigrationCoordinator
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
    statements: tuple[str, ...] = (),
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    if failure == "error":
        upgrade = "\n".join(
            (
                *(f"    op.execute({statement!r})" for statement in statements),
                '    raise RuntimeError("forced migration failure")',
            )
        )
    elif failure == "cancel":
        upgrade = "    raise __import__('asyncio').CancelledError()"
    elif failure == "exit":
        upgrade = "    __import__('os')._exit(17)"
    else:
        upgrade = "\n".join(f"    op.execute({statement!r})" for statement in statements)
        if not upgrade:
            upgrade = "    return None"
    directory.joinpath(filename).write_text(
        "\n".join(
            (
                "from alembic import op",
                f"revision = {revision!r}",
                f"down_revision = {parent!r}",
                f"branch_labels = {((label,) if label else None)!r}",
                f"depends_on = {dependency!r}",
                f"marker = {marker!r}",
                "def upgrade():",
                upgrade,
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


def _raw_inventory(database_url: str) -> dict[str, object]:
    with psycopg.connect(_psycopg_url(database_url)) as connection:
        row = connection.execute(
            "SELECT module_id, module_version, migration_namespace, locations, revision_ids, "
            "distribution_identity, inventory_format, revision_manifest "
            "FROM platform_module.installed_module_migrations "
            "WHERE module_id = 'example.history'"
        ).fetchone()
    assert row is not None
    return dict(
        zip(
            (
                "module_id",
                "module_version",
                "migration_namespace",
                "locations",
                "revision_ids",
                "distribution_identity",
                "inventory_format",
                "revision_manifest",
            ),
            row,
            strict=True,
        )
    )


def _replace_inventory(database_url: str, inventory: dict[str, object]) -> None:
    with psycopg.connect(_psycopg_url(database_url)) as connection:
        constraints = connection.execute(
            "SELECT constraint_name FROM information_schema.table_constraints "
            "WHERE table_schema = 'platform_module' "
            "AND table_name = 'installed_module_migrations' "
            "AND constraint_type = 'CHECK' AND constraint_name LIKE 'ck_%'"
        ).fetchall()
        for (constraint,) in constraints:
            connection.execute(
                sql.SQL(
                    "ALTER TABLE platform_module.installed_module_migrations DROP CONSTRAINT {}"
                ).format(sql.Identifier(constraint))
            )
        connection.execute(
            "UPDATE platform_module.installed_module_migrations SET "
            "module_id = %s, module_version = %s, migration_namespace = %s, "
            "locations = %s, revision_ids = %s, distribution_identity = %s, "
            "inventory_format = %s, revision_manifest = %s "
            "WHERE module_id = 'example.history'",
            (
                inventory["module_id"],
                inventory["module_version"],
                inventory["migration_namespace"],
                Jsonb(inventory["locations"]),
                Jsonb(inventory["revision_ids"]),
                inventory["distribution_identity"],
                inventory["inventory_format"],
                Jsonb(inventory["revision_manifest"]),
            ),
        )


def _database_snapshot(database_url: str, table: str) -> tuple[tuple[str, ...], object, bool]:
    with psycopg.connect(_psycopg_url(database_url)) as connection:
        alembic_exists = connection.execute(
            "SELECT to_regclass('public.alembic_version')"
        ).fetchone()
        heads = (
            tuple(
                row[0]
                for row in connection.execute(
                    "SELECT version_num FROM alembic_version ORDER BY version_num"
                )
            )
            if alembic_exists is not None and alembic_exists[0] is not None
            else ()
        )
        inventory = connection.execute(
            "SELECT to_regclass('platform_module.installed_module_migrations')"
        ).fetchone()
        inventory_rows: object = None
        if inventory is not None and inventory[0] is not None:
            inventory_rows = connection.execute(
                "SELECT module_id, revision_ids FROM "
                "platform_module.installed_module_migrations ORDER BY module_id"
            ).fetchall()
        table_exists = connection.execute("SELECT to_regclass(%s)", (table,)).fetchone()
    return heads, inventory_rows, table_exists is not None and table_exists[0] is not None


def _migration_sessions(database_url: str, application_name: str) -> int:
    with psycopg.connect(_psycopg_url(database_url)) as connection:
        row = connection.execute(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE application_name = %s AND pid <> pg_backend_pid()",
            (application_name,),
        ).fetchone()
    assert row is not None
    return cast(int, row[0])


def _migration_processes() -> set[int]:
    return {
        process.pid
        for process in multiprocessing.active_children()
        if process.pid is not None and process.name.startswith("businessos-migration-")
    }


def _assert_advisory_lock_available(database_url: str) -> None:
    with psycopg.connect(_psycopg_url(database_url)) as connection:
        acquired = connection.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))",
            (MIGRATION_LOCK_NAME,),
        ).fetchone()
        assert acquired == (True,)
        connection.execute(
            "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
            (MIGRATION_LOCK_NAME,),
        )


async def _wait_for_session_query(database_url: str, application_name: str, fragment: str) -> None:
    for _ in range(500):
        with psycopg.connect(_psycopg_url(database_url)) as connection:
            row = connection.execute(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE application_name = %s AND query LIKE %s",
                (application_name, f"%{fragment}%"),
            ).fetchone()
        if row is not None and row[0] == 1:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"migration session did not execute {fragment}")


async def _assert_cancelled_migration_is_terminal(
    task: asyncio.Task[None],
    database_url: str,
    application_name: str,
    baseline_processes: set[int],
    baseline_snapshot: tuple[tuple[str, ...], object, bool],
    table: str,
    *,
    cancel_again_during_cleanup: bool = False,
    check_advisory_lock: bool = True,
) -> None:
    task.cancel()
    if cancel_again_during_cleanup:
        await asyncio.sleep(0)
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert _migration_processes() == baseline_processes
    assert _migration_sessions(database_url, application_name) == 0
    assert _database_snapshot(database_url, table) == baseline_snapshot
    if check_advisory_lock:
        _assert_advisory_lock_available(database_url)
    await asyncio.sleep(0.25)
    assert _migration_sessions(database_url, application_name) == 0
    assert _database_snapshot(database_url, table) == baseline_snapshot


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.parametrize(
    "corruption",
    (
        "empty_manifest",
        "empty_revision_ids",
        "duplicate_revision_ids",
        "manifest_id_mismatch",
        "missing_manifest_field",
        "invalid_fingerprint",
        "wrong_json_type",
        "null_nested_value",
        "unknown_manifest_field",
        "additional_unknown_revision",
        "blank_identity",
    ),
)
def test_format_2_inventory_rejects_malformed_persisted_rows_before_migration(
    corruption: str,
    tmp_path: Path,
    postgres_migration_database_url: str,
) -> None:
    history = tmp_path / "strict-history"
    _revision(
        history,
        "0001.py",
        "strict_history_0001",
        parent="0001_phase1_kernel",
        label="module_history",
    )
    coordinator = _coordinator(history)
    coordinator.upgrade(postgres_migration_database_url)
    malformed = copy.deepcopy(_raw_inventory(postgres_migration_database_url))
    revision_ids = malformed["revision_ids"]
    manifest = malformed["revision_manifest"]
    assert isinstance(revision_ids, list)
    assert isinstance(manifest, list)
    assert isinstance(manifest[0], dict)
    first_manifest = cast(dict[str, object], manifest[0])

    if corruption == "empty_manifest":
        malformed["revision_manifest"] = []
    elif corruption == "empty_revision_ids":
        malformed["revision_ids"] = []
    elif corruption == "duplicate_revision_ids":
        malformed["revision_ids"] = [revision_ids[0], revision_ids[0]]
    elif corruption == "manifest_id_mismatch":
        malformed["revision_ids"] = ["different_0001"]
    elif corruption == "missing_manifest_field":
        del first_manifest["dependencies"]
    elif corruption == "invalid_fingerprint":
        first_manifest["fingerprint"] = "not-a-sha256"
    elif corruption == "wrong_json_type":
        malformed["revision_ids"] = "strict_history_0001"
    elif corruption == "null_nested_value":
        first_manifest["fingerprint"] = None
    elif corruption == "unknown_manifest_field":
        first_manifest["unexpected"] = "field"
    elif corruption == "additional_unknown_revision":
        unknown = copy.deepcopy(first_manifest)
        unknown["revision"] = "unknown_0002"
        malformed["revision_ids"] = [revision_ids[0], "unknown_0002"]
        malformed["revision_manifest"] = [first_manifest, unknown]
    elif corruption == "blank_identity":
        malformed["module_version"] = ""
    else:  # pragma: no cover - parametrization is closed
        raise AssertionError(corruption)

    _replace_inventory(postgres_migration_database_url, malformed)
    before = _raw_inventory(postgres_migration_database_url)
    with psycopg.connect(_psycopg_url(postgres_migration_database_url)) as connection:
        heads_before = tuple(
            connection.execute("SELECT version_num FROM alembic_version ORDER BY version_num")
        )

    with pytest.raises(ConfigurationError):
        coordinator.upgrade(postgres_migration_database_url)

    assert _raw_inventory(postgres_migration_database_url) == before
    with psycopg.connect(_psycopg_url(postgres_migration_database_url)) as connection:
        heads_after = tuple(
            connection.execute("SELECT version_num FROM alembic_version ORDER BY version_num")
        )
    assert heads_after == heads_before


@pytest.mark.integration
@pytest.mark.postgres
def test_retained_format_1_inventory_is_accepted_and_promoted(
    tmp_path: Path, postgres_migration_database_url: str
) -> None:
    history = tmp_path / "retained-format-1"
    _revision(
        history,
        "0001.py",
        "retained_history_0001",
        parent="0001_phase1_kernel",
        label="module_history",
    )
    coordinator = _coordinator(history)
    coordinator.upgrade(postgres_migration_database_url)
    retained = _raw_inventory(postgres_migration_database_url)
    retained["inventory_format"] = 1
    retained["distribution_identity"] = "legacy:unknown"
    retained["revision_manifest"] = []
    _replace_inventory(postgres_migration_database_url, retained)

    coordinator.upgrade(postgres_migration_database_url)

    promoted = _raw_inventory(postgres_migration_database_url)
    assert promoted["inventory_format"] == 2
    assert promoted["distribution_identity"] == "module:example.history"
    assert promoted["revision_ids"] == ["retained_history_0001"]
    promoted_manifest = cast(list[dict[str, object]], promoted["revision_manifest"])
    assert [item["revision"] for item in promoted_manifest] == ["retained_history_0001"]


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
    assert heads == {"0004_strict_migration_inventory", "history_0003"}


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
    assert heads == {"0004_strict_migration_inventory", "concurrent_history_0001"}


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.parametrize(
    "phase",
    ("lock_acquired", "schema_applied", "inventory_staged", "ready_to_commit"),
)
async def test_real_task_cancellation_rolls_back_each_uncommitted_phase(
    phase: str,
    tmp_path: Path,
    postgres_migration_database_url: str,
) -> None:
    history = tmp_path / f"cancel-{phase}"
    table = f"public.cancel_{phase}"
    _revision(
        history,
        "0001.py",
        f"cancel_{phase}_0001",
        parent="0001_phase1_kernel",
        label="module_history",
        statements=(f"CREATE TABLE {table} (id integer PRIMARY KEY)",),
    )
    coordinator = _coordinator(history)
    application_name = f"businessos-cancel-{phase}"
    database_url = f"{postgres_migration_database_url}?application_name={application_name}"
    reached = asyncio.Event()
    never_release = asyncio.Event()

    async def observe(current_phase: str) -> None:
        if current_phase == phase:
            reached.set()
            await never_release.wait()

    baseline_processes = _migration_processes()
    baseline_snapshot = _database_snapshot(database_url, table)
    task = asyncio.create_task(coordinator.upgrade_async(database_url, _phase_callback=observe))
    await asyncio.wait_for(reached.wait(), timeout=10)
    await _assert_cancelled_migration_is_terminal(
        task,
        database_url,
        application_name,
        baseline_processes,
        baseline_snapshot,
        table,
        cancel_again_during_cleanup=phase == "inventory_staged",
    )

    await coordinator.upgrade_async(database_url)
    heads, inventory, table_exists = _database_snapshot(database_url, table)
    assert set(heads) == {"0004_strict_migration_inventory", f"cancel_{phase}_0001"}
    assert inventory is not None
    assert table_exists


@pytest.mark.integration
@pytest.mark.postgres
async def test_real_task_cancellation_while_waiting_for_advisory_lock_is_terminal(
    tmp_path: Path,
    postgres_migration_database_url: str,
) -> None:
    history = tmp_path / "cancel-lock-wait"
    table = "public.cancel_lock_wait"
    _revision(
        history,
        "0001.py",
        "cancel_lock_wait_0001",
        parent="0001_phase1_kernel",
        label="module_history",
        statements=(f"CREATE TABLE {table} (id integer PRIMARY KEY)",),
    )
    coordinator = _coordinator(history)
    application_name = "businessos-cancel-lock-wait"
    database_url = f"{postgres_migration_database_url}?application_name={application_name}"
    baseline_processes = _migration_processes()
    baseline_snapshot = _database_snapshot(database_url, table)

    with psycopg.connect(_psycopg_url(postgres_migration_database_url)) as lock_connection:
        lock_connection.execute(
            "SELECT pg_advisory_lock(hashtextextended(%s, 0))",
            (MIGRATION_LOCK_NAME,),
        )
        task = asyncio.create_task(coordinator.upgrade_async(database_url))
        await _wait_for_session_query(database_url, application_name, "pg_advisory_xact_lock")
        await _assert_cancelled_migration_is_terminal(
            task,
            database_url,
            application_name,
            baseline_processes,
            baseline_snapshot,
            table,
            check_advisory_lock=False,
        )
        lock_connection.execute(
            "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
            (MIGRATION_LOCK_NAME,),
        )

    _assert_advisory_lock_available(database_url)
    await coordinator.upgrade_async(database_url)
    assert _database_snapshot(database_url, table)[2]


@pytest.mark.integration
@pytest.mark.postgres
async def test_real_task_cancellation_interrupts_running_postgresql_work(
    tmp_path: Path,
    postgres_migration_database_url: str,
) -> None:
    history = tmp_path / "cancel-running"
    table = "public.cancel_running"
    _revision(
        history,
        "0001.py",
        "cancel_running_0001",
        parent="0001_phase1_kernel",
        label="module_history",
        statements=(
            f"CREATE TABLE {table} (id integer PRIMARY KEY)",
            "SELECT pg_sleep(30)",
        ),
    )
    coordinator = _coordinator(history)
    application_name = "businessos-cancel-running"
    database_url = f"{postgres_migration_database_url}?application_name={application_name}"
    baseline_processes = _migration_processes()
    baseline_snapshot = _database_snapshot(database_url, table)
    task = asyncio.create_task(coordinator.upgrade_async(database_url))
    await _wait_for_session_query(database_url, application_name, "pg_sleep")
    await _assert_cancelled_migration_is_terminal(
        task,
        database_url,
        application_name,
        baseline_processes,
        baseline_snapshot,
        table,
    )

    _revision(
        history,
        "0001.py",
        "cancel_running_0001",
        parent="0001_phase1_kernel",
        label="module_history",
        statements=(f"CREATE TABLE {table} (id integer PRIMARY KEY)",),
    )
    await coordinator.upgrade_async(database_url)
    assert _database_snapshot(database_url, table)[2]


@pytest.mark.integration
@pytest.mark.postgres
async def test_cancellation_after_commit_authorization_returns_durable_success(
    tmp_path: Path,
    postgres_migration_database_url: str,
) -> None:
    history = tmp_path / "cancel-after-commit"
    table = "public.cancel_after_commit"
    _revision(
        history,
        "0001.py",
        "cancel_after_commit_0001",
        parent="0001_phase1_kernel",
        label="module_history",
        statements=(f"CREATE TABLE {table} (id integer PRIMARY KEY)",),
    )
    coordinator = _coordinator(history)
    application_name = "businessos-cancel-after-commit"
    database_url = f"{postgres_migration_database_url}?application_name={application_name}"
    terminal_outcome_stored = asyncio.Event()
    release_cleanup = asyncio.Event()

    async def observe(phase: str) -> None:
        if phase == "terminal_outcome_stored":
            terminal_outcome_stored.set()
            await release_cleanup.wait()

    baseline_processes = _migration_processes()
    task = asyncio.create_task(coordinator.upgrade_async(database_url, _phase_callback=observe))
    await asyncio.wait_for(terminal_outcome_stored.wait(), timeout=10)
    for _ in range(3):
        task.cancel()
        await asyncio.sleep(0)
    assert not task.done()
    release_cleanup.set()
    await task

    assert not task.cancelled()
    assert task.cancelling() == 0
    assert _migration_processes() == baseline_processes
    assert _migration_sessions(database_url, application_name) == 0
    heads, inventory, table_exists = _database_snapshot(database_url, table)
    assert set(heads) == {"0004_strict_migration_inventory", "cancel_after_commit_0001"}
    assert inventory is not None
    assert table_exists
    _assert_advisory_lock_available(database_url)


@pytest.mark.integration
@pytest.mark.postgres
async def test_repeated_cancellation_preserves_terminal_migration_error(
    tmp_path: Path,
    postgres_migration_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = tmp_path / "cancel-after-error"
    table = "public.cancel_after_error"
    _revision(
        history,
        "0001.py",
        "cancel_after_error_0001",
        parent="0001_phase1_kernel",
        label="module_history",
        failure="error",
        statements=(f"CREATE TABLE {table} (id integer PRIMARY KEY)",),
    )
    coordinator = _coordinator(history)
    application_name = "businessos-cancel-after-error"
    database_url = f"{postgres_migration_database_url}?application_name={application_name}"
    terminal_outcome_stored = asyncio.Event()
    release_cleanup = asyncio.Event()
    original_wait = cast(
        Callable[[str, int | None], Awaitable[None]],
        vars(MigrationCoordinator)["_wait_backend_stopped"],
    )

    async def wait_then_report_diagnostic(url: str, backend_pid: int | None) -> None:
        await original_wait(url, backend_pid)
        raise RuntimeError("test cleanup diagnostic")

    monkeypatch.setattr(
        MigrationCoordinator,
        "_wait_backend_stopped",
        staticmethod(wait_then_report_diagnostic),
    )

    async def observe(phase: str) -> None:
        if phase == "terminal_outcome_stored":
            terminal_outcome_stored.set()
            await release_cleanup.wait()

    baseline_processes = _migration_processes()
    baseline_snapshot = _database_snapshot(database_url, table)
    task = asyncio.create_task(coordinator.upgrade_async(database_url, _phase_callback=observe))
    await asyncio.wait_for(terminal_outcome_stored.wait(), timeout=10)
    for _ in range(3):
        task.cancel()
        await asyncio.sleep(0)
    assert not task.done()
    release_cleanup.set()

    with pytest.raises(RuntimeError, match="forced migration failure"):
        await task

    assert not task.cancelled()
    assert task.cancelling() == 0
    assert _migration_processes() == baseline_processes
    assert _migration_sessions(database_url, application_name) == 0
    assert _database_snapshot(database_url, table) == baseline_snapshot
    _assert_advisory_lock_available(database_url)


@pytest.mark.integration
@pytest.mark.postgres
async def test_pipe_eof_before_terminal_outcome_is_worker_failure(
    tmp_path: Path,
    postgres_migration_database_url: str,
) -> None:
    history = tmp_path / "eof-before-outcome"
    table = "public.eof_before_outcome"
    _revision(
        history,
        "0001.py",
        "eof_before_outcome_0001",
        parent="0001_phase1_kernel",
        label="module_history",
        failure="exit",
    )
    coordinator = _coordinator(history)
    application_name = "businessos-eof-before-outcome"
    database_url = f"{postgres_migration_database_url}?application_name={application_name}"
    baseline_processes = _migration_processes()
    baseline_snapshot = _database_snapshot(database_url, table)

    with pytest.raises(RuntimeError, match="pipe closed before a terminal outcome"):
        await coordinator.upgrade_async(database_url)

    assert _migration_processes() == baseline_processes
    assert _migration_sessions(database_url, application_name) == 0
    assert _database_snapshot(database_url, table) == baseline_snapshot
    _assert_advisory_lock_available(database_url)


@pytest.mark.integration
@pytest.mark.postgres
async def test_cleanup_diagnostic_does_not_replace_committed_outcome(
    tmp_path: Path,
    postgres_migration_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = tmp_path / "cleanup-diagnostic"
    table = "public.cleanup_diagnostic"
    _revision(
        history,
        "0001.py",
        "cleanup_diagnostic_0001",
        parent="0001_phase1_kernel",
        label="module_history",
        statements=(f"CREATE TABLE {table} (id integer PRIMARY KEY)",),
    )
    coordinator = _coordinator(history)
    application_name = "businessos-cleanup-diagnostic"
    database_url = f"{postgres_migration_database_url}?application_name={application_name}"
    original_wait = cast(
        Callable[[str, int | None], Awaitable[None]],
        vars(MigrationCoordinator)["_wait_backend_stopped"],
    )

    async def wait_then_report_diagnostic(url: str, backend_pid: int | None) -> None:
        await original_wait(url, backend_pid)
        raise RuntimeError("test cleanup diagnostic")

    monkeypatch.setattr(
        MigrationCoordinator,
        "_wait_backend_stopped",
        staticmethod(wait_then_report_diagnostic),
    )

    await coordinator.upgrade_async(database_url)

    assert _migration_sessions(database_url, application_name) == 0
    heads, inventory, table_exists = _database_snapshot(database_url, table)
    assert set(heads) == {"0004_strict_migration_inventory", "cleanup_diagnostic_0001"}
    assert inventory is not None
    assert table_exists
    _assert_advisory_lock_available(database_url)
