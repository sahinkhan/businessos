"""Owner-aware protected registries used by framework subsystems."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from businessos.activation import ContributionGate, ContributionGeneration
from businessos.errors import ConflictError, NotFoundError


@dataclass(frozen=True, slots=True)
class OwnedValue[T]:
    name: str
    owner: str
    value: T
    generation: ContributionGeneration | None = None


class OwnedRegistry[T]:
    """Reject duplicate public contract ownership and preserve stable ordering."""

    def __init__(self, kind: str, gate: ContributionGate | None = None) -> None:
        self.kind = kind
        self._values: dict[str, OwnedValue[T]] = {}
        self._gate = gate

    def register(
        self,
        name: str,
        owner: str,
        value: T,
        *,
        generation: ContributionGeneration | None = None,
    ) -> None:
        current = self._values.get(name)
        if current is not None:
            raise ConflictError(
                f"{self.kind} '{name}' is already owned by module '{current.owner}'"
            )
        self._values[name] = OwnedValue(
            name=name,
            owner=owner,
            value=value,
            generation=generation,
        )

    def get(self, name: str) -> T:
        return self.resolve(name).value

    def resolve(self, name: str) -> OwnedValue[T]:
        """Capture one active immutable registration for admission and use."""
        entry = self._values.get(name)
        if entry is None or not self._is_active(entry):
            raise NotFoundError(f"Unknown {self.kind}: {name}")
        return entry

    def entries(self, *, include_inactive: bool = False) -> tuple[OwnedValue[T], ...]:
        return tuple(
            self._values[name]
            for name in sorted(self._values)
            if include_inactive or self._is_active(self._values[name])
        )

    @asynccontextmanager
    async def admitted(self, name: str) -> AsyncGenerator[T]:
        entry = self.resolve(name)
        async with self.admit_entry(entry) as value:
            yield value

    @asynccontextmanager
    async def admit_entry(self, entry: OwnedValue[T]) -> AsyncGenerator[T]:
        """Admit the exact registration previously resolved by the caller."""
        if self._gate is None:
            yield entry.value
            return
        async with self._gate.admit(entry.generation):
            yield entry.value

    def contains(
        self,
        name: str,
        *,
        owner: str | None = None,
        generation: ContributionGeneration | None = None,
        include_inactive: bool = False,
    ) -> bool:
        entry = self._values.get(name)
        if entry is None:
            return False
        if owner is not None and entry.owner != owner:
            return False
        if generation is not None and entry.generation != generation:
            return False
        return include_inactive or self._is_active(entry)

    def remove_owner_generation(self, generation: ContributionGeneration) -> None:
        self._values = {
            name: entry for name, entry in self._values.items() if entry.generation != generation
        }

    def _is_active(self, entry: OwnedValue[T]) -> bool:
        return self._gate is None or self._gate.is_active(entry.generation)
