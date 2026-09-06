"""Owner-aware protected registries used by framework subsystems."""

from dataclasses import dataclass

from businessos.errors import ConflictError, NotFoundError


@dataclass(frozen=True, slots=True)
class OwnedValue[T]:
    name: str
    owner: str
    value: T


class OwnedRegistry[T]:
    """Reject duplicate public contract ownership and preserve stable ordering."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._values: dict[str, OwnedValue[T]] = {}

    def register(self, name: str, owner: str, value: T) -> None:
        current = self._values.get(name)
        if current is not None:
            raise ConflictError(
                f"{self.kind} '{name}' is already owned by module '{current.owner}'"
            )
        self._values[name] = OwnedValue(name=name, owner=owner, value=value)

    def get(self, name: str) -> T:
        entry = self._values.get(name)
        if entry is None:
            raise NotFoundError(f"Unknown {self.kind}: {name}")
        return entry.value

    def entries(self) -> tuple[OwnedValue[T], ...]:
        return tuple(self._values[name] for name in sorted(self._values))
