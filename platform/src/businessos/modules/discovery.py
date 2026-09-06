"""Deterministic Python entry-point module discovery."""

from importlib.metadata import EntryPoint, entry_points

from businessos.modules.sdk import BusinessOSModule

ENTRY_POINT_GROUP = "businessos.modules"


def discover_modules(entries: tuple[EntryPoint, ...] | None = None) -> tuple[BusinessOSModule, ...]:
    selected = entries or tuple(entry_points(group=ENTRY_POINT_GROUP))
    modules: list[BusinessOSModule] = []
    for entry in sorted(selected, key=lambda item: (item.name, item.value)):
        loaded = entry.load()
        candidate = loaded() if isinstance(loaded, type) else loaded
        if not isinstance(candidate, BusinessOSModule):
            raise TypeError(f"Entry point {entry.name} does not provide a BusinessOSModule")
        modules.append(candidate)
    return tuple(modules)
