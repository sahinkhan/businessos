"""Framework-owned metadata declaration registry."""

from pydantic import BaseModel, ConfigDict, Field

from businessos.activation import ContributionGate, ContributionGeneration
from businessos.registry import OwnedRegistry


class MetadataDeclaration(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    kind: str = Field(min_length=1, max_length=100)
    version: int = Field(default=1, ge=1)
    value: dict[str, object]


class MetadataRegistry(OwnedRegistry[MetadataDeclaration]):
    def __init__(self, gate: ContributionGate | None = None) -> None:
        super().__init__("metadata", gate)

    def add(
        self,
        owner: str,
        declaration: MetadataDeclaration,
        *,
        generation: ContributionGeneration | None = None,
    ) -> None:
        self.register(declaration.key, owner, declaration, generation=generation)
