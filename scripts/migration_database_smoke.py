"""Run real installed-artifact migrations against a disposable PostgreSQL database."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import cast
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

EXPECTED_HEADS = {"proof_0004"}


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
) -> None:
    subprocess.run(
        (executable, *arguments),
        check=True,
        cwd=workdir,
        env=environment,
    )


def _run_image(
    image: str,
    network: str,
    arguments: Sequence[str],
    environment: Mapping[str, str],
    workdir: Path,
) -> None:
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
    subprocess.run(command, check=True, cwd=workdir, env=environment)


def _verify(database_url: str) -> None:
    with psycopg.connect(database_url) as connection:
        heads = {row[0] for row in connection.execute("SELECT version_num FROM alembic_version")}
        inventory = connection.execute(
            "SELECT module_id, inventory_format, revision_ids, revision_manifest "
            "FROM platform_module.installed_module_migrations"
        ).fetchall()
    if heads != EXPECTED_HEADS:
        raise RuntimeError(f"unexpected migration heads: {sorted(heads)}")
    if len(inventory) != 1 or inventory[0][0:2] != ("example.phase1-proof", 2):
        raise RuntimeError("proof migration inventory was not persisted")
    revision_ids = inventory[0][2]
    manifest = inventory[0][3]
    if revision_ids != ["proof_0001", "proof_0002", "proof_0003", "proof_0004"]:
        raise RuntimeError("proof revision IDs are incomplete")
    if [item["revision"] for item in manifest] != revision_ids:
        raise RuntimeError("proof immutable revision manifest is incomplete")


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--businessos")
    mode.add_argument("--image")
    parser.add_argument("--docker-network", default="host")
    parser.add_argument("--container-host", default="127.0.0.1")
    arguments = parser.parse_args()

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
            run: Callable[[Sequence[str]], None]
            if businessos_executable:

                def installed_runner(command: Sequence[str]) -> None:
                    _run_installed(businessos_executable, command, environment, workdir)

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

                def image_runner(command: Sequence[str]) -> None:
                    _run_image(
                        image,
                        cast(str, arguments.docker_network),
                        command,
                        container_environment,
                        workdir,
                    )

                run = image_runner
            run(("database", "transition-roles"))
            run(("migrate", "plan"))
            run(("migrate", "upgrade", "heads"))
            run(("migrate", "plan", "--check-database"))
            _verify(_url(migration_base, database_name, sqlalchemy=False))
            run(("migrate", "downgrade", "base"))
            run(("migrate", "upgrade", "heads"))
            _verify(_url(migration_base, database_name, sqlalchemy=False))
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
