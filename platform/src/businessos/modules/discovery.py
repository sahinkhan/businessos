"""Deterministic Python entry-point module discovery."""

from importlib.metadata import EntryPoint, entry_points
from typing import cast

from businessos.modules.sdk import BusinessOSModule
from businessos.security import ContextResolverFactory

ENTRY_POINT_GROUP = "businessos.modules"
CONTEXT_RESOLVER_GROUP = "businessos.context_resolvers"


def discover_modules(entries: tuple[EntryPoint, ...] | None = None) -> tuple[BusinessOSModule, ...]:
    selected = entries if entries is not None else tuple(entry_points(group=ENTRY_POINT_GROUP))
    modules: list[BusinessOSModule] = []
    for entry in sorted(selected, key=lambda item: (item.name, item.value)):
        loaded = entry.load()
        candidate = loaded() if isinstance(loaded, type) else loaded
        if not isinstance(candidate, BusinessOSModule):
            raise TypeError(f"Entry point {entry.name} does not provide a BusinessOSModule")
        modules.append(candidate)
    return tuple(modules)


def discover_context_resolver_factory(
    entries: tuple[EntryPoint, ...] | None = None,
) -> ContextResolverFactory | None:
    """Load the single deployment authentication boundary, when installed."""

    selected = entries if entries is not None else tuple(entry_points(group=CONTEXT_RESOLVER_GROUP))
    ordered = sorted(selected, key=lambda item: (item.name, item.value))
    if not ordered:
        return None
    if len(ordered) != 1:
        names = ", ".join(item.name for item in ordered)
        raise RuntimeError(f"Exactly one trusted context resolver is allowed; found: {names}")
    loaded = ordered[0].load()
    if not callable(loaded):
        raise TypeError(f"Entry point {ordered[0].name} does not provide a resolver factory")
    return cast(ContextResolverFactory, loaded)
