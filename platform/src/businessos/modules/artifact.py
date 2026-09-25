"""Protected, operator-supplied installation grants for resource claims.

The composition root receives these from its trusted installation inventory.
They are not verified signatures and must never be sourced from a module manifest,
module entry point, tenant API, or tenant configuration.
"""

from dataclasses import dataclass
from weakref import WeakKeyDictionary

from businessos.activation import ContributionGeneration
from businessos.errors import ConfigurationError
from businessos.modules.manifest import ModuleManifest


@dataclass(frozen=True, slots=True)
class ApprovedModuleArtifact:
    loaded_module: object
    module_id: str
    publisher: str
    package_identity: str
    loaded_type: str
    install_identity: str
    artifact_sha256: str | None = None
    first_party: bool = False
    revoked: bool = False
    approved_aliases: frozenset[tuple[str, str, str]] = frozenset()

    def verify(self, module: object, manifest: ModuleManifest) -> None:
        actual_type = f"{type(module).__module__}:{type(module).__qualname__}"
        if (
            self.revoked
            or self.loaded_module is not module
            or not self.package_identity.strip()
            or not self.install_identity.strip()
            or self.module_id != manifest.module_id
            or self.publisher != manifest.publisher
            or self.loaded_type != actual_type
            or (
                self.artifact_sha256 is not None
                and self.artifact_sha256 != manifest.artifact_sha256
            )
        ):
            raise ConfigurationError("Resource claim lacks matching approved installation evidence")
        if (
            manifest.module_id.startswith(("foundation.", "business.", "businessos."))
            and not self.first_party
        ):
            raise ConfigurationError("Reserved first-party module ID requires first-party approval")
        for ownership in manifest.resource_ownership:
            for alias in ownership.aliases:
                if (
                    alias,
                    ownership.resource_namespace,
                    ownership.contract_version,
                ) not in self.approved_aliases:
                    raise ConfigurationError("Resource alias lacks protected operator approval")


class _RestrictedDependencyEntitlement:
    __slots__ = ("__weakref__",)


_dependency_entitlements: WeakKeyDictionary[
    _RestrictedDependencyEntitlement, tuple[str, ContributionGeneration]
] = WeakKeyDictionary()


def _issue_restricted_dependency_entitlement(
    grant: ApprovedModuleArtifact,
    module: object,
    manifest: ModuleManifest,
    generation: ContributionGeneration,
) -> _RestrictedDependencyEntitlement:
    grant.verify(module, manifest)
    if not grant.first_party or generation.owner != manifest.module_id:
        raise ConfigurationError("Reserved dependency requires approved first-party artifact")
    entitlement = _RestrictedDependencyEntitlement()
    _dependency_entitlements[entitlement] = (manifest.module_id, generation)
    return entitlement


def _valid_restricted_dependency_entitlement(
    entitlement: object, owner: str, generation: ContributionGeneration
) -> bool:
    if type(entitlement) is not _RestrictedDependencyEntitlement:
        return False
    facts = _dependency_entitlements.get(entitlement)
    return facts is not None and facts[0] == owner and facts[1] is generation
