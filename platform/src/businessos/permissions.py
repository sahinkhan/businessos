"""Permission declarations owned and validated by the framework."""

from pydantic import BaseModel, ConfigDict, Field

from businessos.activation import ContributionGate, ContributionGeneration
from businessos.registry import OwnedRegistry


class PermissionDeclaration(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str = Field(pattern=r"^[a-z][a-z0-9_.:-]+$")
    description: str = Field(min_length=1, max_length=500)


class PermissionRegistry(OwnedRegistry[PermissionDeclaration]):
    def __init__(self, gate: ContributionGate | None = None) -> None:
        super().__init__("permission", gate)

    def add(
        self,
        owner: str,
        declaration: PermissionDeclaration,
        *,
        generation: ContributionGeneration | None = None,
    ) -> None:
        self.register(declaration.key, owner, declaration, generation=generation)
