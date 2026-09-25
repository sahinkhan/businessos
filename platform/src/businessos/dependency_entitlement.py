"""Opaque protected entitlement for owner-restricted dependency registration."""

from weakref import WeakKeyDictionary

from businessos.activation import ContributionGeneration


class InternalRestrictedDependencyEntitlement:
    __slots__ = ("__weakref__",)


_issued: WeakKeyDictionary[
    InternalRestrictedDependencyEntitlement, tuple[str, ContributionGeneration]
] = WeakKeyDictionary()


def internal_issue_restricted_dependency_entitlement(
    owner: str, generation: ContributionGeneration
) -> InternalRestrictedDependencyEntitlement:
    entitlement = InternalRestrictedDependencyEntitlement()
    _issued[entitlement] = (owner, generation)
    return entitlement


def internal_valid_restricted_dependency_entitlement(
    entitlement: object, owner: str, generation: ContributionGeneration | None
) -> bool:
    if type(entitlement) is not InternalRestrictedDependencyEntitlement:
        return False
    facts = _issued.get(entitlement)
    return facts is not None and facts[0] == owner and facts[1] is generation
