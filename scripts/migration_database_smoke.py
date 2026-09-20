"""Run real installed-artifact migrations against a disposable PostgreSQL database."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import cast
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from businessos.migrations import (
    CORE_OWNER,
    INVENTORY_FORMAT_VERSION,
    MigrationCoordinator,
    MigrationPlan,
)
from businessos.modules import ModuleRegistry, discover_modules
from businessos.version import runtime_version

# Artifact composition, not revision tips: additional discovered modules remain supported.
REQUIRED_OWNERS = {
    CORE_OWNER,
    "example.phase1-proof",
    "foundation.tenant",
    "foundation.identity",
    "foundation.organization",
    "foundation.geography",
    "foundation.reference_data",
    "foundation.uom",
    "foundation.party",
    "foundation.policy",
    "foundation.audit",
    "foundation.data_governance",
}


def _expected_plan() -> MigrationPlan:
    registry = ModuleRegistry(platform_version=runtime_version(), sdk_version="0.1.0")
    for module in discover_modules():
        registry.add(module)
    plan = MigrationCoordinator(registry).plan()
    missing = REQUIRED_OWNERS - {source.owner for source in plan.sources}
    if missing:
        raise RuntimeError(f"missing required migration sources: {sorted(missing)}")
    return plan


def _verify_installed_plan(output: str, plan: MigrationPlan) -> None:
    expected = {
        "heads": list(plan.heads),
        "sources": [
            {"owner": source.owner, "namespace": source.namespace, "location": source.location}
            for source in plan.sources
        ],
    }
    if json.loads(output) != expected:
        raise RuntimeError("installed migration plan differs from the expected artifact graph")


def _expected_inventory(plan: MigrationPlan) -> dict[str, tuple[object, ...]]:
    inventory: dict[str, tuple[object, ...]] = {}
    for owner in sorted({source.owner for source in plan.sources} - {CORE_OWNER}):
        sources = [source for source in plan.sources if source.owner == owner]
        revisions = sorted(
            (revision for revision in plan.revisions if revision.owner == owner),
            key=lambda revision: revision.revision,
        )
        inventory[owner] = (
            INVENTORY_FORMAT_VERSION,
            sources[0].namespace,
            sorted(source.logical_location for source in sources),
            sources[0].distribution_identity,
            [revision.revision for revision in revisions],
            [
                {
                    "revision": revision.revision,
                    "parents": sorted(revision.down_revisions),
                    "dependencies": sorted(revision.dependencies),
                    "branch_labels": sorted(revision.branch_labels),
                    "logical_location": revision.logical_location,
                    "distribution_identity": revision.distribution_identity,
                    "fingerprint": revision.fingerprint,
                }
                for revision in revisions
            ],
        )
    return inventory


def _graph_snapshot(plan: MigrationPlan) -> str:
    """Pin the build environment's graph before testing isolated installed wheels."""
    return json.dumps(
        {
            "heads": plan.heads,
            "sources": [
                {**asdict(source), "allowed_dependencies": sorted(source.allowed_dependencies)}
                for source in plan.sources
            ],
            "revisions": [asdict(revision) for revision in plan.revisions],
        },
        sort_keys=True,
    )


def _verify_graph_snapshot(snapshot: str, plan: MigrationPlan) -> None:
    if json.loads(snapshot) != json.loads(_graph_snapshot(plan)):
        raise RuntimeError("installed migration graph differs from the build graph")


def _verify_state(
    heads: set[str], inventory: Sequence[tuple[object, ...]], plan: MigrationPlan
) -> None:
    expected_heads = set(plan.heads)
    if heads != expected_heads:
        raise RuntimeError(
            f"unexpected migration heads: missing={sorted(expected_heads - heads)}, "
            f"unexpected={sorted(heads - expected_heads)}"
        )
    expected = _expected_inventory(plan)
    actual = {row[0]: row[1:] for row in inventory}
    if len(actual) != len(inventory) or actual != expected:
        raise RuntimeError("installed migration inventory differs from the expected artifact graph")


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def _url(
    base_url: str,
    database: str,
    *,
    sqlalchemy: bool,
    host: str | None = None,
) -> str:
    parsed = make_url(base_url.replace("postgresql://", "postgresql+psycopg://", 1)).set(
        database=database,
        host=host or make_url(base_url).host,
    )
    rendered = parsed.render_as_string(hide_password=False)
    if not sqlalchemy:
        return rendered.replace("postgresql+psycopg://", "postgresql://", 1)
    return rendered


def _run_installed(
    executable: str,
    arguments: Sequence[str],
    environment: Mapping[str, str],
    workdir: Path,
) -> str:
    result = subprocess.run(
        (executable, *arguments),
        check=True,
        cwd=workdir,
        env=environment,
        stdout=subprocess.PIPE,
        text=True,
    )
    print(result.stdout, end="")
    return result.stdout


def _run_image(
    image: str,
    network: str,
    arguments: Sequence[str],
    environment: Mapping[str, str],
    workdir: Path,
) -> str:
    names = (
        "BOS_ADMIN_DATABASE_URL",
        "BOS_MIGRATION_DATABASE_URL",
        "BOS_MIGRATOR_PASSWORD",
        "BOS_APPLICATION_PASSWORD",
        "BOS_OPERATIONS_PASSWORD",
    )
    command = ["docker", "run", "--rm", "--network", network]
    for name in names:
        command.extend(("-e", name))
    command.extend((image, "businessos", *arguments))
    result = subprocess.run(
        command, check=True, cwd=workdir, env=environment, stdout=subprocess.PIPE, text=True
    )
    print(result.stdout, end="")
    return result.stdout


def _verify(database_url: str, plan: MigrationPlan) -> None:
    with psycopg.connect(database_url) as connection:
        heads = {row[0] for row in connection.execute("SELECT version_num FROM alembic_version")}
        inventory = connection.execute(
            "SELECT module_id, inventory_format, migration_namespace, locations, "
            "distribution_identity, revision_ids, revision_manifest "
            "FROM platform_module.installed_module_migrations"
        ).fetchall()
    _verify_state(heads, inventory, plan)


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--businessos")
    mode.add_argument("--image")
    mode.add_argument("--write-graph", type=Path)
    parser.add_argument("--expected-graph", type=Path)
    parser.add_argument("--docker-network", default="host")
    parser.add_argument("--container-host", default="127.0.0.1")
    arguments = parser.parse_args()

    plan = _expected_plan()
    if arguments.write_graph:
        arguments.write_graph.write_text(_graph_snapshot(plan), encoding="utf-8")
        return
    if arguments.expected_graph:
        _verify_graph_snapshot(arguments.expected_graph.read_text(encoding="utf-8"), plan)

    administrator_base = _required("BOS_TEST_DATABASE_ADMIN_URL")
    migration_base = _required("BOS_TEST_DATABASE_MIGRATION_URL")
    database_name = f"businessos_artifact_smoke_{uuid4().hex}"
    host_admin_url = _url(administrator_base, database_name, sqlalchemy=False)
    host_migration_url = _url(migration_base, database_name, sqlalchemy=True)

    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update(
        {
            "BOS_ADMIN_DATABASE_URL": host_admin_url,
            "BOS_MIGRATION_DATABASE_URL": host_migration_url,
            "BOS_MIGRATOR_PASSWORD": _required("BOS_MIGRATOR_PASSWORD"),
            "BOS_APPLICATION_PASSWORD": _required("BOS_APPLICATION_PASSWORD"),
            "BOS_OPERATIONS_PASSWORD": _required("BOS_OPERATIONS_PASSWORD"),
        }
    )

    with psycopg.connect(administrator_base, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))

    try:
        with tempfile.TemporaryDirectory() as temporary:
            workdir = Path(temporary)
            businessos_executable = cast(str | None, arguments.businessos)
            image = cast(str | None, arguments.image)
            run: Callable[[Sequence[str]], str]
            if businessos_executable:

                def installed_runner(command: Sequence[str]) -> str:
                    return _run_installed(businessos_executable, command, environment, workdir)

                run = installed_runner
            else:
                if image is None:  # pragma: no cover - argparse enforces the group
                    raise SystemExit("an installed executable or image is required")
                container_environment = environment.copy()
                container_environment["BOS_ADMIN_DATABASE_URL"] = _url(
                    administrator_base,
                    database_name,
                    sqlalchemy=False,
                    host=arguments.container_host,
                )
                container_environment["BOS_MIGRATION_DATABASE_URL"] = _url(
                    migration_base,
                    database_name,
                    sqlalchemy=True,
                    host=arguments.container_host,
                )

                def image_runner(command: Sequence[str]) -> str:
                    return _run_image(
                        image,
                        cast(str, arguments.docker_network),
                        command,
                        container_environment,
                        workdir,
                    )

                run = image_runner

            _verify_installed_plan(run(("migrate", "plan")), plan)
            run(("database", "transition-roles"))
            run(("migrate", "upgrade", "heads"))
            _verify_installed_plan(run(("migrate", "plan", "--check-database")), plan)
            _verify(_url(migration_base, database_name, sqlalchemy=False), plan)
            run(("migrate", "downgrade", "base"))
            run(("migrate", "upgrade", "heads"))
            _verify_installed_plan(run(("migrate", "plan", "--check-database")), plan)
            _verify(_url(migration_base, database_name, sqlalchemy=False), plan)
    finally:
        with psycopg.connect(administrator_base, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database_name,),
            )
            connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name))
            )


if __name__ == "__main__":
    main()
