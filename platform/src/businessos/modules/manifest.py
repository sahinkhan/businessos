"""Validated, versioned module manifest contract."""

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
    migrations: tuple[str, ...] = ()
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
        dependency_ids = [dependency.module_id for dependency in self.dependencies]
        if len(dependency_ids) != len(set(dependency_ids)):
            raise ValueError("module dependencies must be unique")
        return self

    def supports(self, *, platform: str, sdk: str, python: str) -> bool:
        return (
            Version(platform) in SpecifierSet(self.platform)
            and Version(sdk) in SpecifierSet(self.sdk)
            and Version(python) in SpecifierSet(self.python)
        )
