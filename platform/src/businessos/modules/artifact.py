"""Protected, operator-supplied installation grants for resource claims.

The composition root receives these from its trusted installation inventory.
They are not verified signatures and must never be sourced from a module manifest,
module entry point, tenant API, or tenant configuration.
"""

from dataclasses import dataclass

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
        if manifest.module_id.startswith(("foundation.", "businessos.")) and not self.first_party:
            raise ConfigurationError("Reserved first-party module ID requires first-party approval")
        for ownership in manifest.resource_ownership:
            for alias in ownership.aliases:
                if (
                    alias,
                    ownership.resource_namespace,
                    ownership.contract_version,
                ) not in self.approved_aliases:
                    raise ConfigurationError("Resource alias lacks protected operator approval")
