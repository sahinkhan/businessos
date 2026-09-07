"""BusinessOS server and administrative command entry point."""

import argparse
import asyncio
import json
import logging
import multiprocessing
import os
import signal
import sys
from collections.abc import Sequence

import uvicorn
from pydantic import ValidationError

from businessos.config import get_settings
from businessos.database_admin import (
    DatabaseRolePasswords,
    DatabaseTransitionError,
    transition_database_roles,
)
from businessos.event_worker import EventWorkerSettings, create_event_worker
from businessos.migrations import MigrationCoordinator
from businessos.modules import ModuleRegistry, discover_modules
from businessos.version import runtime_version


def _migration_coordinator() -> MigrationCoordinator:
    registry = ModuleRegistry(platform_version=runtime_version(), sdk_version="0.2.0")
    for module in discover_modules():
        registry.add(module)
    return MigrationCoordinator(registry)


def _migration_url() -> str:
    database_url = os.getenv("BOS_MIGRATION_DATABASE_URL")
    if not database_url:
        raise SystemExit("BOS_MIGRATION_DATABASE_URL is required")
    return database_url


def _required_environment(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def _run_database_admin(arguments: Sequence[str]) -> None:
    parser = argparse.ArgumentParser(prog="businessos database")
    subcommands = parser.add_subparsers(dest="action", required=True)
    subcommands.add_parser("transition-roles")
    parsed = parser.parse_args(arguments)
    if parsed.action != "transition-roles":  # pragma: no cover - argparse guards this
        parser.error("unsupported database administration action")
    passwords = DatabaseRolePasswords(
        migrator=_required_environment("BOS_MIGRATOR_PASSWORD"),
        application=_required_environment("BOS_APPLICATION_PASSWORD"),
        operations=_required_environment("BOS_OPERATIONS_PASSWORD"),
    )
    try:
        transition_database_roles(_required_environment("BOS_ADMIN_DATABASE_URL"), passwords)
    except DatabaseTransitionError as exc:
        raise SystemExit(str(exc)) from None
    print("database role transition complete")


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


async def _serve_event_worker() -> None:
    try:
        settings = EventWorkerSettings()  # pyright: ignore[reportCallIssue]
    except ValidationError:
        raise SystemExit("Invalid or incomplete event worker configuration") from None
    worker = create_event_worker(settings)
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    registered_signals: list[signal.Signals] = []
    for current_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(current_signal, stopping.set)
        except NotImplementedError:  # pragma: no cover - Unix deployment path supports signals
            continue
        registered_signals.append(current_signal)
    try:
        await worker.start()
        await worker.readiness()
        await stopping.wait()
    finally:
        await worker.stop()
        for current_signal in registered_signals:
            loop.remove_signal_handler(current_signal)


def _event_worker_child() -> None:
    try:
        asyncio.run(_serve_event_worker())
    except BaseException as exc:
        logging.getLogger("businessos.event-worker").error(
            "Event worker child failed",
            extra={"error_type": type(exc).__name__},
        )
        raise SystemExit(1) from None


def _supervise_event_worker(settings: EventWorkerSettings) -> None:
    """Give the async worker a hard OS-process shutdown boundary."""
    context = multiprocessing.get_context("spawn")
    process = context.Process(target=_event_worker_child, name="businessos-event-worker")
    stop_requested = False

    def request_stop(_: int, __: object) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    process.start()
    process_id = process.pid
    if process_id is None:  # pragma: no cover - multiprocessing start contract
        raise RuntimeError("Event worker process did not start")
    forced = False
    exit_code: int | None = None
    try:
        while process.is_alive() and not stop_requested:
            process.join(timeout=0.2)
        if stop_requested and process.is_alive():
            os.kill(process_id, signal.SIGTERM)
            process.join(timeout=settings.process_shutdown_timeout_seconds)
        if process.is_alive():
            forced = True
            process.kill()
            process.join(timeout=5.0)
    finally:
        if process.is_alive():
            process.kill()
            process.join(timeout=5.0)
        exit_code = process.exitcode
        process.close()
    if forced:
        raise SystemExit("Event worker exceeded its process shutdown deadline")
    if exit_code not in {0, -signal.SIGINT, -signal.SIGTERM}:
        raise SystemExit("Event worker process failed")


def _run_events(arguments: Sequence[str]) -> None:
    parser = argparse.ArgumentParser(prog="businessos events")
    subcommands = parser.add_subparsers(dest="action", required=True)
    subcommands.add_parser("run")
    parsed = parser.parse_args(arguments)
    if parsed.action != "run":  # pragma: no cover - argparse guards this
        parser.error("unsupported event worker action")
    try:
        settings = EventWorkerSettings()  # pyright: ignore[reportCallIssue]
    except ValidationError:
        raise SystemExit("Invalid or incomplete event worker configuration") from None
    _supervise_event_worker(settings)


def main(arguments: Sequence[str] | None = None) -> None:
    args = tuple(arguments) if arguments is not None else tuple(sys.argv[1:])
    if args and args[0] == "migrate":
        _run_migrations(args[1:])
        return
    if args and args[0] == "database":
        _run_database_admin(args[1:])
        return
    if args and args[0] == "events":
        _run_events(args[1:])
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
