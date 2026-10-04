"""Framework-owned metadata declaration registry."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from weakref import WeakKeyDictionary

from pydantic import BaseModel, ConfigDict, Field

from businessos.activation import ContributionGate, ContributionGeneration
from businessos.registry import OwnedRegistry


class MetadataDeclaration(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    kind: str = Field(min_length=1, max_length=100)
    version: int = Field(default=1, ge=1)
    value: dict[str, object]


class MetadataRegistry(OwnedRegistry[MetadataDeclaration]):
    def __init__(self, gate: ContributionGate | None = None) -> None:
        super().__init__("metadata", gate)
        self._profiles: dict[str, tuple[str, tuple[tuple[str, str], ...]]] = {}

    def add(
        self,
        owner: str,
        declaration: MetadataDeclaration,
        *,
        generation: ContributionGeneration | None = None,
        module_version: str = "",
        dependencies: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.register(declaration.key, owner, declaration, generation=generation)
        self._profiles[declaration.key] = (module_version, tuple(sorted(dependencies)))

    def remove_owner_generation(self, generation: ContributionGeneration) -> None:
        super().remove_owner_generation(generation)
        self._profiles = {
            key: value for key, value in self._profiles.items() if key in self._values
        }

    @asynccontextmanager
    async def admitted_declarations(
        self, *, kind_prefix: str, discriminator: str, value: str, limit: int = 128
    ) -> AsyncGenerator[tuple[AdmittedMetadataDeclaration, ...]]:
        if not 1 <= limit <= 128 or not kind_prefix or len(discriminator) > 100:
            raise ValueError("Invalid bounded metadata selection")
        entries = tuple(
            entry
            for entry in self.entries()
            if entry.value.kind.startswith(kind_prefix)
            and entry.value.value.get(discriminator) == value
        )
        if len(entries) > limit:
            raise ValueError("Metadata selection exceeds budget")
        async with AsyncExitStack() as stack:
            dependency_generations: dict[str, ContributionGeneration] = {}
            for entry in entries:
                _, dependencies = self._profiles[entry.name]
                if dependencies and self._gate is None:
                    raise ValueError("Metadata dependencies require lifecycle admission")
                if self._gate is not None:
                    for owner, _ in dependencies:
                        dependency_generations[owner] = self._gate.active_generation(owner)
            if self._gate is not None:
                await stack.enter_async_context(
                    self._gate.admit_many(
                        dependency_generations[k] for k in sorted(dependency_generations)
                    )
                )
            snapshots: list[AdmittedMetadataDeclaration] = []
            for entry in entries:
                if entry.generation is None:
                    raise ValueError("Metadata source lacks issued generation")
                declaration = await stack.enter_async_context(self.admit_entry(entry))
                version, dependencies = self._profiles[entry.name]
                document = json.dumps(
                    declaration.value,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                )
                if len(document.encode("utf-8")) > 65536:
                    raise ValueError("Metadata declaration exceeds byte budget")
                snapshots.append(
                    AdmittedMetadataDeclaration(
                        declaration.key,
                        declaration.kind,
                        declaration.version,
                        entry.owner,
                        entry.generation,
                        version,
                        dependencies,
                        document,
                        tuple(dependency_generations[k] for k, _ in dependencies),
                    )
                )
            yield tuple(snapshots)
            if self._gate is not None and any(
                not self._gate.is_active(g) for g in dependency_generations.values()
            ):
                raise ValueError("Metadata dependency changed during admission")
            for entry, snapshot in zip(entries, snapshots, strict=True):
                if (
                    self.resolve(entry.name) is not entry
                    or json.dumps(
                        entry.value.value,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                        allow_nan=False,
                    )
                    != snapshot.document_json
                ):
                    raise ValueError("Metadata declaration changed during admission")


@dataclass(frozen=True, slots=True)
class AdmittedMetadataDeclaration:
    """Immutable declaration snapshot, with framework-issued source provenance."""

    key: str
    kind: str
    version: int
    owner: str
    generation: ContributionGeneration
    module_version: str
    dependencies: tuple[tuple[str, str], ...]
    document_json: str
    dependency_generations: tuple[ContributionGeneration, ...] = ()


_catalogs: WeakKeyDictionary[MetadataCatalog, MetadataRegistry] = WeakKeyDictionary()


class MetadataCatalog:
    """Read-only v1 SDK surface; never exposes registry mutation or admission callbacks.

    Selection is a declaration discriminator, not a security/scope assertion.
    Leases last through the context manager and changed snapshots fail closed.
    """

    __slots__ = ("__weakref__",)
    version = "1.0"

    def __init__(self, registry: MetadataRegistry) -> None:
        _catalogs[self] = registry

    @asynccontextmanager
    async def admitted(
        self, *, kind_prefix: str, discriminator: str, value: str, limit: int = 128
    ) -> AsyncGenerator[tuple[AdmittedMetadataDeclaration, ...]]:
        async with _catalogs[self].admitted_declarations(
            kind_prefix=kind_prefix, discriminator=discriminator, value=value, limit=limit
        ) as declarations:
            yield declarations
