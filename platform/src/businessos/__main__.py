"""BusinessOS server and administrative command entry point."""

import argparse
import json
import os
import sys
from collections.abc import Sequence

import uvicorn

from businessos.config import get_settings
from businessos.migrations import MigrationCoordinator
from businessos.modules import ModuleRegistry, discover_modules
from businessos.version import runtime_version


def _migration_coordinator() -> MigrationCoordinator:
    registry = ModuleRegistry(platform_version=runtime_version(), sdk_version="0.1.0")
    for module in discover_modules():
        registry.add(module)
    return MigrationCoordinator(registry)


def _migration_url() -> str:
    database_url = os.getenv("BOS_MIGRATION_DATABASE_URL")
    if not database_url:
        raise SystemExit("BOS_MIGRATION_DATABASE_URL is required")
    return database_url


def _run_migrations(arguments: Sequence[str]) -> None:
    parser = argparse.ArgumentParser(prog="businessos migrate")
    subcommands = parser.add_subparsers(dest="action", required=True)
    plan_parser = subcommands.add_parser("plan")
    plan_parser.add_argument("--check-database", action="store_true")
    upgrade_parser = subcommands.add_parser("upgrade")
    upgrade_parser.add_argument("revision", nargs="?", default="heads")
    downgrade_parser = subcommands.add_parser("downgrade")
    downgrade_parser.add_argument("revision", nargs="?", default="base")
    parsed = parser.parse_args(arguments)
    coordinator = _migration_coordinator()
    if parsed.action == "plan":
        database_url = _migration_url() if parsed.check_database else None
        plan = coordinator.plan(database_url)
        print(
            json.dumps(
                {
                    "heads": plan.heads,
                    "sources": [
                        {
                            "owner": source.owner,
                            "namespace": source.namespace,
                            "location": source.location,
                        }
                        for source in plan.sources
                    ],
                },
                sort_keys=True,
            )
        )
    elif parsed.action == "upgrade":
        coordinator.upgrade(_migration_url(), parsed.revision)
    else:
        coordinator.downgrade(_migration_url(), parsed.revision)


def main(arguments: Sequence[str] | None = None) -> None:
    args = tuple(arguments) if arguments is not None else tuple(sys.argv[1:])
    if args and args[0] == "migrate":
        _run_migrations(args[1:])
        return
    settings = get_settings()
    uvicorn.run(
        "businessos.asgi:application",
        host=settings.host,
        port=settings.port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
