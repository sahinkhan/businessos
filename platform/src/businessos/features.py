"""Framework-owned feature flag declarations and runtime evaluation."""

from pydantic import BaseModel, ConfigDict, Field

from businessos.activation import ContributionGate, ContributionGeneration
from businessos.registry import OwnedRegistry


class FeatureFlag(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    description: str = Field(min_length=1, max_length=500)
    default: bool = False


class FeatureFlagRegistry(OwnedRegistry[FeatureFlag]):
    def __init__(self, gate: ContributionGate | None = None) -> None:
        super().__init__("feature flag", gate)
        self._overrides: dict[str, bool] = {}

    def add(
        self,
        owner: str,
        flag: FeatureFlag,
        *,
        generation: ContributionGeneration | None = None,
    ) -> None:
        self.register(flag.key, owner, flag, generation=generation)

    def set_override(self, key: str, enabled: bool) -> None:
        self.get(key)
        self._overrides[key] = enabled

    def is_enabled(self, key: str) -> bool:
        flag = self.get(key)
        return self._overrides.get(key, flag.default)

    def remove_owner_generation(self, generation: ContributionGeneration) -> None:
        removed = {entry.name for entry in self._values.values() if entry.generation == generation}
        super().remove_owner_generation(generation)
        for key in removed:
            self._overrides.pop(key, None)
