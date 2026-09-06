"""Framework-owned Alembic discovery, validation, and upgrade coordination."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from collections.abc import Generator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from importlib.metadata import packages_distributions
from importlib.resources import as_file, files
from pathlib import Path
from typing import Self, cast

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.script.revision import RevisionError
from alembic.util.exc import CommandError
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from businessos.errors import ConfigurationError, ConflictError
from businessos.modules import ModuleRegistry, ModuleState

CORE_OWNER = "businessos.core"
CORE_NAMESPACE = "businessos_core"
RESOURCE_PREFIX = "python://"
INVENTORY_FORMAT_VERSION = 2
MIGRATION_LOCK_NAME = "businessos.migrations"
REVISION_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
MODULE_PATTERN = r"^[a-z][a-z0-9_.-]+$"
NAMESPACE_PATTERN = r"^[a-z][a-z0-9_]*$"
LOGICAL_LOCATION_PATTERN = r"^(?:python|filesystem)://[^\s]+$"
DISTRIBUTION_PATTERN = r"^(?:python-distribution|python-package|module):[a-z0-9][a-z0-9_.-]*$"
FINGERPRINT_PATTERN = r"^[0-9a-f]{64}$"


@dataclass(frozen=True, slots=True)
class MigrationSource:
    """One owner-scoped migration source with stable installed identity."""

    owner: str
    namespace: str
    location: str
    logical_location: str
    distribution_identity: str
    allowed_dependencies: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class MigrationRevision:
    """Canonical immutable facts for one discovered revision."""

    revision: str
    owner: str
    namespace: str
    down_revisions: tuple[str, ...]
    dependencies: tuple[str, ...]
    branch_labels: tuple[str, ...]
    source_file: str
    logical_location: str
    distribution_identity: str
    fingerprint: str


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    sources: tuple[MigrationSource, ...]
    revisions: tuple[MigrationRevision, ...]
    heads: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ResolvedSource:
    source: MigrationSource
    path: Path


@dataclass(frozen=True, slots=True)
class _StoredInventory:
    module_id: str
    module_version: str
    migration_namespace: str
    locations: tuple[str, ...]
    revision_ids: tuple[str, ...]
    distribution_identity: str | None
    inventory_format: int | None
    revision_manifest: tuple[Mapping[str, object], ...]


class _StoredRevision(BaseModel):
    """Strict persisted form of one immutable migration revision."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    revision: str = Field(pattern=REVISION_PATTERN)
    parents: list[str]
    dependencies: list[str]
    branch_labels: list[str]
    logical_location: str = Field(pattern=LOGICAL_LOCATION_PATTERN)
    distribution_identity: str = Field(pattern=DISTRIBUTION_PATTERN)
    fingerprint: str = Field(pattern=FINGERPRINT_PATTERN)

    @field_validator("parents", "dependencies")
    @classmethod
    def validate_revision_references(cls, values: list[str]) -> list[str]:
        if any(not re.fullmatch(REVISION_PATTERN, value) for value in values):
            raise ValueError("revision references must be canonical strings")
        if len(values) != len(set(values)):
            raise ValueError("revision references must be unique")
        return values

    @field_validator("branch_labels")
    @classmethod
    def validate_branch_labels(cls, values: list[str]) -> list[str]:
        if any(not re.fullmatch(NAMESPACE_PATTERN, value) for value in values):
            raise ValueError("branch labels must be canonical strings")
        if len(values) != len(set(values)):
            raise ValueError("branch labels must be unique")
        return values


class _Format2Inventory(BaseModel):
    """Fail-closed schema for the current persisted inventory format."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    module_id: str = Field(pattern=MODULE_PATTERN)
    module_version: str = Field(min_length=1)
    migration_namespace: str = Field(pattern=NAMESPACE_PATTERN)
    locations: list[str] = Field(min_length=1)
    revision_ids: list[str] = Field(min_length=1)
    distribution_identity: str = Field(pattern=DISTRIBUTION_PATTERN)
    inventory_format: int
    revision_manifest: list[_StoredRevision] = Field(min_length=1)

    @field_validator("module_version")
    @classmethod
    def validate_module_version(cls, value: str) -> str:
        try:
            Version(value)
        except InvalidVersion as exc:
            raise ValueError("module version must be valid") from exc
        return value

    @field_validator("locations")
    @classmethod
    def validate_locations(cls, values: list[str]) -> list[str]:
        if any(not re.fullmatch(LOGICAL_LOCATION_PATTERN, value) for value in values):
            raise ValueError("locations must be canonical logical URIs")
        if len(values) != len(set(values)):
            raise ValueError("locations must be unique")
        return values

    @field_validator("revision_ids")
    @classmethod
    def validate_revision_ids(cls, values: list[str]) -> list[str]:
        if any(not re.fullmatch(REVISION_PATTERN, value) for value in values):
            raise ValueError("revision IDs must be canonical strings")
        if len(values) != len(set(values)):
            raise ValueError("revision IDs must be unique")
        return values

    @model_validator(mode="after")
    def validate_manifest_relationship(self) -> Self:
        if self.inventory_format != INVENTORY_FORMAT_VERSION:
            raise ValueError("inventory format does not match the format-2 schema")
        manifest_ids = [item.revision for item in self.revision_manifest]
        if len(manifest_ids) != len(set(manifest_ids)):
            raise ValueError("manifest revision IDs must be unique")
        if manifest_ids != self.revision_ids:
            raise ValueError("manifest and revision IDs must have an exact ordered relationship")
        if any(item.logical_location not in self.locations for item in self.revision_manifest):
            raise ValueError("manifest contains an unknown logical location")
        if any(
            item.distribution_identity != self.distribution_identity
            for item in self.revision_manifest
        ):
            raise ValueError("manifest contains an inconsistent distribution identity")
        return self


def _tuple_value(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (tuple, list)):
        sequence = cast(Sequence[object], value)
        if all(isinstance(item, str) for item in sequence):
            return tuple(cast(str, item) for item in sequence)
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


def _source_identity(owner: str, location: str, index: int) -> tuple[str, str]:
    if location.startswith(RESOURCE_PREFIX):
        resource = location.removeprefix(RESOURCE_PREFIX)
        package, separator, _ = resource.partition("/")
        if not package or not separator:
            raise ConfigurationError(f"Invalid migration resource URI: {location}")
        distributions = sorted(
            {canonicalize_name(name) for name in packages_distributions().get(package, ())}
        )
        if len(distributions) > 1:
            raise ConfigurationError(
                f"Migration package '{package}' must belong to exactly one distribution"
            )
        identity = (
            f"python-distribution:{distributions[0]}"
            if distributions
            else f"python-package:{package}"
        )
        return location, identity
    name = Path(location).name or f"source-{index}"
    return f"filesystem://{owner}/{name}", f"module:{owner}"


def _json_sequence(value: object, field: str) -> Sequence[object]:
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, list):
        raise ConfigurationError(f"Stored migration inventory has invalid {field}")
    return cast(Sequence[object], parsed)


def _json_strings(value: object, field: str) -> tuple[str, ...]:
    sequence = _json_sequence(value, field)
    if not all(isinstance(item, str) for item in sequence):
        raise ConfigurationError(f"Stored migration inventory has invalid {field}")
    return tuple(cast(str, item) for item in sequence)


class MigrationCoordinator:
    """Validate and execute the complete protected/module migration graph."""

    def __init__(self, modules: ModuleRegistry) -> None:
        self._modules = modules

    def sources(self) -> tuple[MigrationSource, ...]:
        core_location = "python://businessos/migration_assets/versions"
        _, core_distribution = _source_identity(CORE_OWNER, core_location, 0)
        sources = [
            MigrationSource(
                owner=CORE_OWNER,
                namespace=CORE_NAMESPACE,
                location=core_location,
                logical_location=core_location,
                distribution_identity=core_distribution,
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
            for index, location in enumerate(manifest.migrations):
                logical_location, distribution_identity = _source_identity(
                    manifest.module_id, location, index
                )
                sources.append(
                    MigrationSource(
                        owner=manifest.module_id,
                        namespace=manifest.migration_namespace,
                        location=location,
                        logical_location=logical_location,
                        distribution_identity=distribution_identity,
                        allowed_dependencies=allowed,
                    )
                )
        return tuple(sources)

    @contextmanager
    def _resolved_sources(self) -> Generator[tuple[_ResolvedSource, ...]]:
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
                        f"Migration location is unavailable for '{source.owner}': "
                        f"{source.logical_location}"
                    )
                resolved.append(_ResolvedSource(source, path))
            yield tuple(resolved)

    def _build_plan(self, resolved: Sequence[_ResolvedSource]) -> MigrationPlan:
        revisions: list[MigrationRevision] = []
        revision_owners: dict[str, MigrationRevision] = {}
        namespace_owners: dict[str, str] = {}
        branch_declarations: dict[str, str] = {}
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
                raise ConfigurationError(
                    f"Migration source has no revisions: {source.logical_location}"
                )
            for path in migration_files:
                values = _literal_assignments(path)
                revision_id = cast(str, values["revision"])
                labels = _tuple_value(values.get("branch_labels"))
                if len(labels) != len(set(labels)):
                    raise ConflictError(
                        f"Migration '{revision_id}' declares a duplicate branch label"
                    )
                revision = MigrationRevision(
                    revision=revision_id,
                    owner=source.owner,
                    namespace=source.namespace,
                    down_revisions=_tuple_value(values.get("down_revision")),
                    dependencies=_tuple_value(values.get("depends_on")),
                    branch_labels=labels,
                    source_file=f"{source.logical_location}/{path.name}",
                    logical_location=source.logical_location,
                    distribution_identity=source.distribution_identity,
                    fingerprint=hashlib.sha256(path.read_bytes()).hexdigest(),
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
                    previous_revision = branch_declarations.setdefault(label, revision_id)
                    if previous_revision != revision_id:
                        raise ConflictError(
                            f"Migration branch-label collision '{label}' in revisions "
                            f"'{previous_revision}' and '{revision_id}'"
                        )

        shared_symbols = sorted(set(revision_owners).intersection(branch_declarations))
        if shared_symbols:
            symbol = shared_symbols[0]
            raise ConflictError(
                f"Migration symbol '{symbol}' is both a revision ID and a branch label"
            )

        for owner, sources in sorted(owner_sources.items()):
            namespaces = {source.namespace for source in sources}
            distributions = {source.distribution_identity for source in sources}
            if len(namespaces) != 1 or len(distributions) != 1:
                raise ConfigurationError(
                    f"Migration owner '{owner}' has inconsistent namespace or distribution identity"
                )
            namespace = sources[0].namespace
            declared_by = branch_declarations.get(namespace)
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
        allowed_by_owner: dict[str, frozenset[str]] = {}
        for owner, sources in owner_sources.items():
            allowed: set[str] = set()
            for source in sources:
                allowed.update(source.allowed_dependencies)
            allowed_by_owner[owner] = frozenset(allowed)
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

        self._reject_cycles(revision_owners)
        ordered = tuple(sorted(revisions, key=lambda item: (item.owner, item.revision)))
        heads = tuple(sorted(known - referenced_as_parent))
        plan = MigrationPlan(self.sources(), ordered, heads)
        self._validate_alembic_revision_map(resolved, heads)
        return plan

    @staticmethod
    def _reject_cycles(revisions: Mapping[str, MigrationRevision]) -> None:
        states: dict[str, int] = {}
        stack: list[str] = []

        def visit(revision_id: str) -> None:
            state = states.get(revision_id, 0)
            if state == 2:
                return
            if state == 1:
                start = stack.index(revision_id)
                cycle = (*stack[start:], revision_id)
                raise ConflictError("Migration dependency cycle: " + " -> ".join(cycle))
            states[revision_id] = 1
            stack.append(revision_id)
            revision = revisions[revision_id]
            prerequisites = sorted(set((*revision.down_revisions, *revision.dependencies)))
            for prerequisite in prerequisites:
                visit(prerequisite)
            stack.pop()
            states[revision_id] = 2

        for revision_id in sorted(revisions):
            visit(revision_id)

    def plan(self, database_url: str | None = None) -> MigrationPlan:
        with self._resolved_sources() as resolved:
            plan = self._build_plan(resolved)
        if database_url is not None:
            self._validate_database_inventory(database_url, plan)
        return plan

    @staticmethod
    def _configuration(
        database_url: str | None,
        resolved: Sequence[_ResolvedSource],
        connection: Connection | None = None,
    ) -> Config:
        core_versions = next(item.path for item in resolved if item.source.owner == CORE_OWNER)
        config = Config()
        if database_url is not None:
            config.attributes["database_url"] = database_url
            config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
        if connection is not None:
            config.attributes["connection"] = connection
        config.set_main_option("script_location", str(core_versions.parent))
        config.set_main_option("path_separator", "os")
        config.set_main_option(
            "version_locations",
            os.pathsep.join(str(item.path) for item in resolved),
        )
        return config

    def _validate_alembic_revision_map(
        self, resolved: Sequence[_ResolvedSource], expected_heads: tuple[str, ...]
    ) -> None:
        try:
            script = ScriptDirectory.from_config(self._configuration(None, resolved))
            alembic_heads = tuple(sorted(script.get_heads()))
        except (CommandError, RevisionError) as exc:
            raise ConfigurationError(f"Alembic migration graph is invalid: {exc}") from exc
        if alembic_heads != expected_heads:
            raise ConfigurationError(
                "Canonical migration heads do not match Alembic heads: "
                f"canonical={expected_heads}, alembic={alembic_heads}"
            )

    def upgrade(self, database_url: str, revision: str = "heads") -> None:
        with self._resolved_sources() as resolved:
            plan = self._build_plan(resolved)
            engine = create_engine(database_url)
            try:
                with engine.connect() as connection, connection.begin():
                    self._lock_migrations(connection)
                    self._validate_database_inventory_connection(connection, plan)
                    command.upgrade(
                        self._configuration(database_url, resolved, connection), revision
                    )
                    self._persist_inventory(connection, plan)
            finally:
                engine.dispose()

    def downgrade(self, database_url: str, revision: str = "base") -> None:
        with self._resolved_sources() as resolved:
            plan = self._build_plan(resolved)
            engine = create_engine(database_url)
            try:
                with engine.connect() as connection, connection.begin():
                    self._lock_migrations(connection)
                    self._validate_database_inventory_connection(connection, plan)
                    command.downgrade(
                        self._configuration(database_url, resolved, connection), revision
                    )
                    self._persist_inventory(connection, plan)
            finally:
                engine.dispose()

    @staticmethod
    def _lock_migrations(connection: Connection) -> None:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_name, 0))"),
            {"lock_name": MIGRATION_LOCK_NAME},
        )

    def _validate_database_inventory(self, database_url: str, plan: MigrationPlan) -> None:
        engine = create_engine(database_url)
        try:
            with engine.connect() as connection:
                self._validate_database_inventory_connection(connection, plan)
        finally:
            engine.dispose()

    def _validate_database_inventory_connection(
        self, connection: Connection, plan: MigrationPlan
    ) -> None:
        applied = self._applied_revisions(connection)
        known = {revision.revision for revision in plan.revisions}
        missing = sorted(applied - known)
        if missing:
            raise ConfigurationError(
                "Database contains revisions whose migration packages are unavailable: "
                + ", ".join(missing)
            )

        inventories = self._stored_inventories(connection)
        discovered = {source.owner for source in plan.sources if source.owner != CORE_OWNER}
        unavailable = sorted(set(inventories) - discovered)
        if unavailable:
            raise ConfigurationError(
                "Installed module migration packages are unavailable: " + ", ".join(unavailable)
            )
        for module_id, stored in sorted(inventories.items()):
            self._validate_stored_module(plan, module_id, stored)

    @staticmethod
    def _applied_revisions(connection: Connection) -> set[str]:
        exists = connection.execute(
            text("SELECT to_regclass('public.alembic_version')")
        ).scalar_one()
        if exists is None:
            return set()
        return set(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())

    @staticmethod
    def _inventory_columns(connection: Connection) -> set[str]:
        return set(
            connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'platform_module' "
                    "AND table_name = 'installed_module_migrations'"
                )
            ).scalars()
        )

    def _stored_inventories(self, connection: Connection) -> dict[str, _StoredInventory]:
        exists = connection.execute(
            text("SELECT to_regclass('platform_module.installed_module_migrations')")
        ).scalar_one()
        if exists is None:
            return {}
        columns = self._inventory_columns(connection)
        has_graph = {
            "distribution_identity",
            "inventory_format",
            "revision_manifest",
        }.issubset(columns)
        graph_fields = (
            "distribution_identity, inventory_format, revision_manifest"
            if has_graph
            else "NULL AS distribution_identity, NULL AS inventory_format, "
            "'[]'::jsonb AS revision_manifest"
        )
        rows = connection.execute(
            text(
                "SELECT module_id, module_version, migration_namespace, locations, "
                f"revision_ids, {graph_fields} "
                "FROM platform_module.installed_module_migrations"
            )
        ).mappings()
        inventories: dict[str, _StoredInventory] = {}
        for row in rows:
            module_id = row["module_id"]
            module_version = row["module_version"]
            namespace = row["migration_namespace"]
            distribution = row["distribution_identity"]
            inventory_format = row["inventory_format"]
            try:
                if inventory_format == INVENTORY_FORMAT_VERSION:
                    validated = _Format2Inventory.model_validate(
                        {
                            "module_id": module_id,
                            "module_version": module_version,
                            "migration_namespace": namespace,
                            "locations": _json_sequence(row["locations"], "locations"),
                            "revision_ids": _json_sequence(row["revision_ids"], "revision_ids"),
                            "distribution_identity": distribution,
                            "inventory_format": inventory_format,
                            "revision_manifest": _json_sequence(
                                row["revision_manifest"], "revision_manifest"
                            ),
                        }
                    )
                    stored = _StoredInventory(
                        module_id=validated.module_id,
                        module_version=validated.module_version,
                        migration_namespace=validated.migration_namespace,
                        locations=tuple(validated.locations),
                        revision_ids=tuple(validated.revision_ids),
                        distribution_identity=validated.distribution_identity,
                        inventory_format=validated.inventory_format,
                        revision_manifest=tuple(
                            item.model_dump() for item in validated.revision_manifest
                        ),
                    )
                else:
                    stored = self._legacy_inventory(
                        module_id=module_id,
                        module_version=module_version,
                        namespace=namespace,
                        locations=row["locations"],
                        revision_ids=row["revision_ids"],
                        distribution=distribution,
                        inventory_format=inventory_format,
                    )
            except (ValidationError, ValueError, TypeError) as exc:
                raise ConfigurationError("Stored migration inventory is malformed") from exc
            inventories[stored.module_id] = stored
        return inventories

    @staticmethod
    def _legacy_inventory(
        *,
        module_id: object,
        module_version: object,
        namespace: object,
        locations: object,
        revision_ids: object,
        distribution: object,
        inventory_format: object,
    ) -> _StoredInventory:
        if inventory_format is not None and (
            type(inventory_format) is not int or inventory_format != 1
        ):
            raise ValueError("unsupported inventory format")
        if not isinstance(module_id, str) or not re.fullmatch(MODULE_PATTERN, module_id):
            raise ValueError("invalid module ID")
        if not isinstance(module_version, str):
            raise ValueError("invalid module version")
        Version(module_version)
        if not isinstance(namespace, str) or not re.fullmatch(NAMESPACE_PATTERN, namespace):
            raise ValueError("invalid migration namespace")
        typed_locations = _json_strings(locations, "locations")
        typed_revision_ids = _json_strings(revision_ids, "revision_ids")
        if not typed_locations or len(typed_locations) != len(set(typed_locations)):
            raise ValueError("invalid migration locations")
        if any(not re.fullmatch(LOGICAL_LOCATION_PATTERN, item) for item in typed_locations):
            raise ValueError("invalid migration location")
        if not typed_revision_ids or len(typed_revision_ids) != len(set(typed_revision_ids)):
            raise ValueError("invalid revision IDs")
        if any(not re.fullmatch(REVISION_PATTERN, item) for item in typed_revision_ids):
            raise ValueError("invalid revision ID")
        typed_distribution = distribution if isinstance(distribution, str) else None
        return _StoredInventory(
            module_id=module_id,
            module_version=module_version,
            migration_namespace=namespace,
            locations=typed_locations,
            revision_ids=typed_revision_ids,
            distribution_identity=typed_distribution,
            inventory_format=inventory_format,
            revision_manifest=(),
        )

    def _validate_stored_module(
        self, plan: MigrationPlan, module_id: str, stored: _StoredInventory
    ) -> None:
        sources = tuple(source for source in plan.sources if source.owner == module_id)
        revisions = tuple(revision for revision in plan.revisions if revision.owner == module_id)
        if not sources:
            raise ConfigurationError(
                f"Installed module migration package is unavailable: {module_id}"
            )
        namespace = sources[0].namespace
        locations = tuple(sorted(source.logical_location for source in sources))
        distributions = {source.distribution_identity for source in sources}
        distribution = next(iter(distributions))
        if stored.migration_namespace != namespace:
            raise ConfigurationError(f"Installed module '{module_id}' changed migration namespace")
        if tuple(sorted(stored.locations)) != locations:
            raise ConfigurationError(f"Installed module '{module_id}' changed migration location")
        if (
            stored.inventory_format == INVENTORY_FORMAT_VERSION
            and stored.distribution_identity != distribution
        ):
            raise ConfigurationError(
                f"Installed module '{module_id}' changed distribution identity"
            )
        current_revision_ids = {revision.revision for revision in revisions}
        removed = sorted(set(stored.revision_ids) - current_revision_ids)
        if removed:
            raise ConfigurationError(
                f"Installed module '{module_id}' removed historical revisions: "
                + ", ".join(removed)
            )
        current_version = self._module_version(module_id)
        try:
            if Version(current_version) < Version(stored.module_version):
                raise ConfigurationError(
                    f"Installed module '{module_id}' cannot downgrade from "
                    f"{stored.module_version} to {current_version}"
                )
        except InvalidVersion as exc:
            raise ConfigurationError(
                f"Installed module '{module_id}' has invalid recorded version"
            ) from exc

        current_manifest = {
            cast(str, item["revision"]): item for item in self._revision_manifest(revisions)
        }
        for historical in stored.revision_manifest:
            revision_id = historical.get("revision")
            if not isinstance(revision_id, str):
                raise ConfigurationError(
                    f"Installed module '{module_id}' has invalid revision history"
                )
            current = current_manifest.get(revision_id)
            if current is None:
                raise ConfigurationError(
                    f"Installed module '{module_id}' removed historical revision '{revision_id}'"
                )
            if dict(historical) != current:
                raise ConfigurationError(
                    f"Installed module '{module_id}' rewrote historical revision '{revision_id}'"
                )

    def _module_version(self, module_id: str) -> str:
        return self._modules.get(module_id).module.manifest.version

    @staticmethod
    def _revision_manifest(
        revisions: Sequence[MigrationRevision],
    ) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "revision": revision.revision,
                "parents": sorted(revision.down_revisions),
                "dependencies": sorted(revision.dependencies),
                "branch_labels": sorted(revision.branch_labels),
                "logical_location": revision.logical_location,
                "distribution_identity": revision.distribution_identity,
                "fingerprint": revision.fingerprint,
            }
            for revision in sorted(revisions, key=lambda item: item.revision)
        )

    def _persist_inventory(self, connection: Connection, plan: MigrationPlan) -> None:
        exists = connection.execute(
            text("SELECT to_regclass('platform_module.installed_module_migrations')")
        ).scalar_one()
        if exists is None:
            return
        columns = self._inventory_columns(connection)
        has_graph = {
            "distribution_identity",
            "inventory_format",
            "revision_manifest",
        }.issubset(columns)

        for registered in self._modules.entries():
            manifest = registered.module.manifest
            if not manifest.migrations:
                continue
            sources = tuple(source for source in plan.sources if source.owner == manifest.module_id)
            revisions = tuple(
                revision for revision in plan.revisions if revision.owner == manifest.module_id
            )
            locations = sorted(source.logical_location for source in sources)
            distribution = next(iter({source.distribution_identity for source in sources}))
            revision_ids = sorted(revision.revision for revision in revisions)
            lifecycle_state = (
                "retired" if registered.state is ModuleState.REMOVED else registered.state.value
            )
            parameters: dict[str, object] = {
                "module_id": manifest.module_id,
                "module_version": manifest.version,
                "migration_namespace": manifest.migration_namespace,
                "locations": json.dumps(locations),
                "revision_ids": json.dumps(revision_ids),
                "lifecycle_state": lifecycle_state,
            }
            if has_graph:
                parameters.update(
                    {
                        "distribution_identity": distribution,
                        "inventory_format": INVENTORY_FORMAT_VERSION,
                        "revision_manifest": json.dumps(
                            self._revision_manifest(revisions), sort_keys=True
                        ),
                    }
                )
                statement = text(
                    "INSERT INTO platform_module.installed_module_migrations "
                    "(module_id, module_version, migration_namespace, locations, revision_ids, "
                    "lifecycle_state, distribution_identity, inventory_format, revision_manifest) "
                    "VALUES (:module_id, :module_version, :migration_namespace, "
                    "CAST(:locations AS jsonb), CAST(:revision_ids AS jsonb), :lifecycle_state, "
                    ":distribution_identity, :inventory_format, "
                    "CAST(:revision_manifest AS jsonb)) "
                    "ON CONFLICT (module_id) DO UPDATE SET "
                    "module_version = EXCLUDED.module_version, "
                    "migration_namespace = EXCLUDED.migration_namespace, "
                    "locations = EXCLUDED.locations, revision_ids = EXCLUDED.revision_ids, "
                    "lifecycle_state = EXCLUDED.lifecycle_state, "
                    "distribution_identity = EXCLUDED.distribution_identity, "
                    "inventory_format = EXCLUDED.inventory_format, "
                    "revision_manifest = EXCLUDED.revision_manifest, updated_at = now()"
                )
            else:
                statement = text(
                    "INSERT INTO platform_module.installed_module_migrations "
                    "(module_id, module_version, migration_namespace, locations, revision_ids, "
                    "lifecycle_state) VALUES (:module_id, :module_version, "
                    ":migration_namespace, CAST(:locations AS jsonb), "
                    "CAST(:revision_ids AS jsonb), :lifecycle_state) "
                    "ON CONFLICT (module_id) DO UPDATE SET "
                    "module_version = EXCLUDED.module_version, "
                    "migration_namespace = EXCLUDED.migration_namespace, "
                    "locations = EXCLUDED.locations, revision_ids = EXCLUDED.revision_ids, "
                    "lifecycle_state = EXCLUDED.lifecycle_state, updated_at = now()"
                )
            connection.execute(statement, parameters)
