"""Opaque protected entitlement for owner-restricted dependency registration."""

from weakref import WeakKeyDictionary

from businessos.activation import ContributionGeneration


class _RestrictedDependencyEntitlement:
    __slots__ = ("__weakref__",)


_issued: WeakKeyDictionary[_RestrictedDependencyEntitlement, tuple[str, ContributionGeneration]] = (
    WeakKeyDictionary()
)


def _issue_restricted_dependency_entitlement(
    owner: str, generation: ContributionGeneration
) -> _RestrictedDependencyEntitlement:
    entitlement = _RestrictedDependencyEntitlement()
    _issued[entitlement] = (owner, generation)
    return entitlement


def _valid_restricted_dependency_entitlement(
    entitlement: object, owner: str, generation: ContributionGeneration | None
) -> bool:
    if type(entitlement) is not _RestrictedDependencyEntitlement:
        return False
    facts = _issued.get(entitlement)
    return facts is not None and facts[0] == owner and facts[1] is generation
