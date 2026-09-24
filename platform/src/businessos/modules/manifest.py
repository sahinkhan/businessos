"""Validated, versioned module manifest contract."""

import re
from enum import StrEnum
from typing import Self

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModuleExecutionType(StrEnum):
    IN_PROCESS = "in_process"
    DECLARATIVE = "declarative"
    ISOLATED_SERVICE = "isolated_service"


class ModuleDependency(BaseModel):
    model_config = ConfigDict(frozen=True)

    module_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    version: str

    @model_validator(mode="after")
    def validate_version_range(self) -> Self:
        try:
            SpecifierSet(self.version)
        except InvalidSpecifier as exc:
            raise ValueError("dependency version must be a valid specifier") from exc
        return self


class ModuleContractDeclaration(BaseModel):
    """Versioned public contract advertised by a module manifest."""

    model_config = ConfigDict(frozen=True)

    contract_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    version: str

    @model_validator(mode="after")
    def validate_version(self) -> Self:
        try:
            Version(self.version)
        except InvalidVersion as exc:
            raise ValueError("contract version must be valid") from exc
        return self


_RESOURCE_NAMESPACE = re.compile(r"[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)+\Z", re.ASCII)


class ResourceOwnership(BaseModel):
    """Canonical, versioned entity ownership claimed by one module."""

    model_config = ConfigDict(frozen=True)

    resource_namespace: str
    owner_module_id: str
    contract_version: str
    aliases: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_canonical_identity(self) -> Self:
        if not _RESOURCE_NAMESPACE.fullmatch(self.resource_namespace):
            raise ValueError("resource namespace must use canonical lowercase ASCII segments")
        if not self.resource_namespace.startswith(self.owner_module_id + "."):
            raise ValueError("resource namespace root must equal owner module ID")
        try:
            Version(self.contract_version)
        except InvalidVersion as exc:
            raise ValueError("resource contract version must be valid") from exc
        if len(set(self.aliases)) != len(self.aliases):
            raise ValueError("resource aliases must be unique")
        for alias in self.aliases:
            if not _RESOURCE_NAMESPACE.fullmatch(alias):
                raise ValueError("resource alias must use canonical lowercase ASCII segments")
            if alias == self.resource_namespace:
                raise ValueError("resource alias cannot equal its canonical namespace")
        return self


class ModuleManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    module_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=200)
    publisher: str = Field(min_length=1, max_length=200)
    version: str
    platform: str
    sdk: str
    python: str = ">=3.13"
    execution_type: ModuleExecutionType = ModuleExecutionType.IN_PROCESS
    entry_point: str | None = None
    dependencies: tuple[ModuleDependency, ...] = ()
    capabilities: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    api_contracts: tuple[ModuleContractDeclaration, ...] = ()
    event_contracts: tuple[ModuleContractDeclaration, ...] = ()
    public_contracts: tuple[ModuleContractDeclaration, ...] = ()
    resource_ownership: tuple[ResourceOwnership, ...] = ()
    ui_contributions: tuple[str, ...] = ()
    configuration_scopes: tuple[str, ...] = ()
    localization_resources: tuple[str, ...] = ()
    tenant_export_supported: bool | None = None
    tenant_delete_supported: bool | None = None
    artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    signature_reference: str | None = None
    sbom_reference: str | None = None
    migrations: tuple[str, ...] = ()
    migration_namespace: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    supported_tenancy_modes: tuple[str, ...] = (
        "dedicated",
        "database_per_tenant",
        "shared_schema",
    )

    @model_validator(mode="after")
    def validate_versions_and_entry_point(self) -> Self:
        try:
            Version(self.version)
            SpecifierSet(self.platform)
            SpecifierSet(self.sdk)
            SpecifierSet(self.python)
        except (InvalidVersion, InvalidSpecifier) as exc:
            raise ValueError("manifest contains an invalid version or compatibility range") from exc
        if self.execution_type is ModuleExecutionType.IN_PROCESS and not self.entry_point:
            raise ValueError("in-process modules require an entry_point")
        if self.migrations and self.migration_namespace is None:
            raise ValueError("modules with migrations require a migration_namespace")
        if not self.migrations and self.migration_namespace is not None:
            raise ValueError("migration_namespace requires at least one migration location")
        dependency_ids = [dependency.module_id for dependency in self.dependencies]
        if len(dependency_ids) != len(set(dependency_ids)):
            raise ValueError("module dependencies must be unique")
        for name in ("api_contracts", "event_contracts", "public_contracts"):
            declarations = getattr(self, name)
            contract_ids = [declaration.contract_id for declaration in declarations]
            if len(contract_ids) != len(set(contract_ids)):
                raise ValueError(f"{name} must contain unique contract IDs")
        for name in ("ui_contributions", "configuration_scopes", "localization_resources"):
            values = getattr(self, name)
            if len(values) != len(set(values)) or any(not value.strip() for value in values):
                raise ValueError(f"{name} must contain unique nonempty values")
        claims: set[tuple[str, str]] = set()
        for declaration in self.resource_ownership:
            if declaration.owner_module_id != self.module_id:
                raise ValueError("resource owner must equal manifest module ID")
            for namespace in (declaration.resource_namespace, *declaration.aliases):
                key = (namespace, declaration.contract_version)
                if key in claims:
                    raise ValueError("duplicate or colliding resource ownership declaration")
                claims.add(key)
        return self

    def supports(self, *, platform: str, sdk: str, python: str) -> bool:
        return (
            Version(platform) in SpecifierSet(self.platform)
            and Version(sdk) in SpecifierSet(self.sdk)
            and Version(python) in SpecifierSet(self.python)
        )
