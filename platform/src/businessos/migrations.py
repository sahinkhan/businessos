"""Framework-owned Alembic discovery, validation, and upgrade coordination."""

from __future__ import annotations

import ast
import json
import os
from collections.abc import Iterable, Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from importlib.resources import as_file, files
from pathlib import Path
from typing import cast

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from businessos.errors import ConfigurationError, ConflictError
from businessos.modules import ModuleRegistry, ModuleState

CORE_OWNER = "businessos.core"
CORE_NAMESPACE = "businessos_core"
RESOURCE_PREFIX = "python://"


@dataclass(frozen=True, slots=True)
class MigrationSource:
    """One owner-scoped migration source resolved from a path or package resource."""

    owner: str
    namespace: str
    location: str
    allowed_dependencies: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class MigrationRevision:
    revision: str
    owner: str
    namespace: str
    down_revisions: tuple[str, ...]
    dependencies: tuple[str, ...]
    branch_labels: tuple[str, ...]
    source_file: str


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    sources: tuple[MigrationSource, ...]
    revisions: tuple[MigrationRevision, ...]
    heads: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ResolvedSource:
    source: MigrationSource
    path: Path


def _tuple_value(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (tuple, list)) and all(isinstance(item, str) for item in value):
        return tuple(cast(Iterable[str], value))
    raise ConfigurationError("Migration metadata must contain only literal revision strings")


def _literal_assignments(path: Path) -> dict[str, object]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        raise ConfigurationError(f"Cannot parse migration file: {path.name}") from exc
    values: dict[str, object] = {}
    wanted = {"revision", "down_revision", "depends_on", "branch_labels"}
    for node in tree.body:
        name: str | None = None
        value_node: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                name = target.id
                value_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            value_node = node.value
        if name not in wanted or value_node is None:
            continue
        try:
            values[name] = ast.literal_eval(value_node)
        except (ValueError, SyntaxError) as exc:
            raise ConfigurationError(
                f"Migration metadata must be literal in {path.name}: {name}"
            ) from exc
    if not isinstance(values.get("revision"), str):
        raise ConfigurationError(f"Migration file has no literal revision ID: {path.name}")
    return values


class MigrationCoordinator:
    """Validate and execute the complete protected/module migration graph."""

    def __init__(self, modules: ModuleRegistry) -> None:
        self._modules = modules

    def sources(self) -> tuple[MigrationSource, ...]:
        sources = [
            MigrationSource(
                owner=CORE_OWNER,
                namespace=CORE_NAMESPACE,
                location="python://businessos/migration_assets/versions",
            )
        ]
        for registered in self._modules.ordered():
            manifest = registered.module.manifest
            if not manifest.migrations:
                continue
            if manifest.migration_namespace is None:  # guarded by manifest validation
                raise ConfigurationError(
                    f"Module '{manifest.module_id}' has migrations without a namespace"
                )
            allowed = frozenset(
                {CORE_OWNER, *(dependency.module_id for dependency in manifest.dependencies)}
            )
            sources.extend(
                MigrationSource(
                    owner=manifest.module_id,
                    namespace=manifest.migration_namespace,
                    location=location,
                    allowed_dependencies=allowed,
                )
                for location in manifest.migrations
            )
        return tuple(sources)

    @contextmanager
    def _resolved_sources(self) -> Iterator[tuple[_ResolvedSource, ...]]:
        with ExitStack() as stack:
            resolved: list[_ResolvedSource] = []
            for source in self.sources():
                location = source.location
                if location.startswith(RESOURCE_PREFIX):
                    resource = location.removeprefix(RESOURCE_PREFIX)
                    package, separator, relative = resource.partition("/")
                    if not package or not separator or not relative:
                        raise ConfigurationError(f"Invalid migration resource URI: {location}")
                    try:
                        traversable = files(package).joinpath(*relative.split("/"))
                        path = stack.enter_context(as_file(traversable))
                    except (FileNotFoundError, ModuleNotFoundError) as exc:
                        raise ConfigurationError(
                            f"Migration package or resource is unavailable for '{source.owner}'"
                        ) from exc
                else:
                    path = Path(location).resolve()
                if not path.is_dir():
                    raise ConfigurationError(
                        f"Migration location is unavailable for '{source.owner}': {location}"
                    )
                resolved.append(_ResolvedSource(source, path))
            yield tuple(resolved)

    def _build_plan(self, resolved: Sequence[_ResolvedSource]) -> MigrationPlan:
        revisions: list[MigrationRevision] = []
        revision_owners: dict[str, MigrationRevision] = {}
        namespace_owners: dict[str, str] = {}
        namespace_declarations: dict[str, str] = {}
        owner_sources: dict[str, list[MigrationSource]] = {}

        for item in resolved:
            source = item.source
            owner_sources.setdefault(source.owner, []).append(source)
            previous_owner = namespace_owners.setdefault(source.namespace, source.owner)
            if previous_owner != source.owner:
                raise ConflictError(
                    f"Migration namespace collision '{source.namespace}' between "
                    f"'{previous_owner}' and '{source.owner}'"
                )
            migration_files = sorted(
                path for path in item.path.glob("*.py") if path.name != "__init__.py"
            )
            if not migration_files:
                raise ConfigurationError(f"Migration source has no revisions: {source.location}")
            for path in migration_files:
                values = _literal_assignments(path)
                revision_id = cast(str, values["revision"])
                revision = MigrationRevision(
                    revision=revision_id,
                    owner=source.owner,
                    namespace=source.namespace,
                    down_revisions=_tuple_value(values.get("down_revision")),
                    dependencies=_tuple_value(values.get("depends_on")),
                    branch_labels=_tuple_value(values.get("branch_labels")),
                    source_file=f"{source.location}/{path.name}",
                )
                duplicate = revision_owners.get(revision_id)
                if duplicate is not None:
                    raise ConflictError(
                        f"Duplicate migration revision '{revision_id}' in "
                        f"'{duplicate.source_file}' and '{revision.source_file}'"
                    )
                revision_owners[revision_id] = revision
                revisions.append(revision)
                for label in revision.branch_labels:
                    previous_revision = namespace_declarations.setdefault(label, revision_id)
                    if previous_revision != revision_id:
                        raise ConflictError(
                            f"Migration branch-label collision '{label}' in revisions "
                            f"'{previous_revision}' and '{revision_id}'"
                        )

        for owner, sources in owner_sources.items():
            namespace = sources[0].namespace
            declared_by = namespace_declarations.get(namespace)
            if declared_by is None:
                raise ConfigurationError(
                    f"Migration owner '{owner}' does not declare branch label '{namespace}'"
                )
            if revision_owners[declared_by].owner != owner:
                raise ConflictError(
                    f"Migration branch label '{namespace}' is owned by another module"
                )

        known = set(revision_owners)
        referenced_as_parent: set[str] = set()
        allowed_by_owner = {
            owner: frozenset().union(*(source.allowed_dependencies for source in sources))
            for owner, sources in owner_sources.items()
        }
        for revision in revisions:
            for referenced in (*revision.down_revisions, *revision.dependencies):
                if referenced not in known:
                    raise ConfigurationError(
                        f"Migration '{revision.revision}' references missing "
                        f"revision '{referenced}'"
                    )
                referenced_owner = revision_owners[referenced].owner
                if (
                    referenced_owner != revision.owner
                    and referenced_owner not in allowed_by_owner[revision.owner]
                ):
                    raise ConfigurationError(
                        f"Migration '{revision.revision}' owned by '{revision.owner}' depends on "
                        f"undeclared module '{referenced_owner}'"
                    )
            referenced_as_parent.update(revision.down_revisions)

        ordered = tuple(sorted(revisions, key=lambda item: (item.owner, item.revision)))
        heads = tuple(sorted(known - referenced_as_parent))
        return MigrationPlan(self.sources(), ordered, heads)

    def plan(self, database_url: str | None = None) -> MigrationPlan:
        with self._resolved_sources() as resolved:
            plan = self._build_plan(resolved)
        if database_url is not None:
            self._validate_database_inventory(database_url, plan)
        return plan

    @staticmethod
    def _configuration(database_url: str, resolved: Sequence[_ResolvedSource]) -> Config:
        core_versions = next(item.path for item in resolved if item.source.owner == CORE_OWNER)
        config = Config()
        config.attributes["database_url"] = database_url
        config.set_main_option("script_location", str(core_versions.parent))
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
        config.set_main_option("path_separator", "os")
        config.set_main_option(
            "version_locations",
            os.pathsep.join(str(item.path) for item in resolved),
        )
        return config

    def upgrade(self, database_url: str, revision: str = "heads") -> None:
        with self._resolved_sources() as resolved:
            plan = self._build_plan(resolved)
            self._validate_database_inventory(database_url, plan)
            command.upgrade(self._configuration(database_url, resolved), revision)
        self._persist_inventory(database_url, plan)

    def downgrade(self, database_url: str, revision: str = "base") -> None:
        with self._resolved_sources() as resolved:
            plan = self._build_plan(resolved)
            self._validate_database_inventory(database_url, plan)
            command.downgrade(self._configuration(database_url, resolved), revision)

    def _validate_database_inventory(self, database_url: str, plan: MigrationPlan) -> None:
        engine = create_engine(database_url)
        try:
            with engine.connect() as connection:
                applied = self._applied_revisions(connection)
                known = {revision.revision for revision in plan.revisions}
                missing = sorted(applied - known)
                if missing:
                    raise ConfigurationError(
                        "Database contains revisions whose migration packages are unavailable: "
                        + ", ".join(missing)
                    )
                installed = self._installed_modules(connection)
                discovered = {source.owner for source in plan.sources if source.owner != CORE_OWNER}
                unavailable = sorted(installed - discovered)
                if unavailable:
                    raise ConfigurationError(
                        "Installed module migration packages are unavailable: "
                        + ", ".join(unavailable)
                    )
        finally:
            engine.dispose()

    @staticmethod
    def _applied_revisions(connection: Connection) -> set[str]:
        exists = connection.execute(
            text("SELECT to_regclass('public.alembic_version')")
        ).scalar_one()
        if exists is None:
            return set()
        return set(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())

    @staticmethod
    def _installed_modules(connection: Connection) -> set[str]:
        exists = connection.execute(
            text("SELECT to_regclass('platform_module.installed_module_migrations')")
        ).scalar_one()
        if exists is None:
            return set()
        return set(
            connection.execute(
                text("SELECT module_id FROM platform_module.installed_module_migrations")
            ).scalars()
        )

    def _persist_inventory(self, database_url: str, plan: MigrationPlan) -> None:
        revisions_by_owner: dict[str, list[str]] = {}
        locations_by_owner: dict[str, list[str]] = {}
        namespaces: dict[str, str] = {}
        for source in plan.sources:
            if source.owner == CORE_OWNER:
                continue
            locations_by_owner.setdefault(source.owner, []).append(source.location)
            namespaces[source.owner] = source.namespace
        for revision in plan.revisions:
            revisions_by_owner.setdefault(revision.owner, []).append(revision.revision)

        engine = create_engine(database_url)
        try:
            with engine.begin() as connection:
                exists = connection.execute(
                    text("SELECT to_regclass('platform_module.installed_module_migrations')")
                ).scalar_one()
                if exists is None:
                    return
                for registered in self._modules.entries():
                    manifest = registered.module.manifest
                    if not manifest.migrations:
                        continue
                    lifecycle_state = (
                        "retired"
                        if registered.state is ModuleState.REMOVED
                        else registered.state.value
                    )
                    connection.execute(
                        text(
                            "INSERT INTO platform_module.installed_module_migrations "
                            "(module_id, module_version, migration_namespace, locations, "
                            "revision_ids, lifecycle_state) "
                            "VALUES (:module_id, :module_version, :migration_namespace, "
                            "CAST(:locations AS jsonb), CAST(:revision_ids AS jsonb), "
                            ":lifecycle_state) "
                            "ON CONFLICT (module_id) DO UPDATE SET "
                            "module_version = EXCLUDED.module_version, "
                            "migration_namespace = EXCLUDED.migration_namespace, "
                            "locations = EXCLUDED.locations, revision_ids = EXCLUDED.revision_ids, "
                            "lifecycle_state = EXCLUDED.lifecycle_state, updated_at = now()"
                        ),
                        {
                            "module_id": manifest.module_id,
                            "module_version": manifest.version,
                            "migration_namespace": namespaces[manifest.module_id],
                            "locations": json.dumps(sorted(locations_by_owner[manifest.module_id])),
                            "revision_ids": json.dumps(
                                sorted(revisions_by_owner.get(manifest.module_id, []))
                            ),
                            "lifecycle_state": lifecycle_state,
                        },
                    )
        finally:
            engine.dispose()
