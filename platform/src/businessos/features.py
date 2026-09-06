"""Framework-owned feature flag declarations and runtime evaluation."""

from pydantic import BaseModel, ConfigDict, Field

from businessos.registry import OwnedRegistry


class FeatureFlag(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    description: str = Field(min_length=1, max_length=500)
    default: bool = False


class FeatureFlagRegistry(OwnedRegistry[FeatureFlag]):
    def __init__(self) -> None:
        super().__init__("feature flag")
        self._overrides: dict[str, bool] = {}

    def add(self, owner: str, flag: FeatureFlag) -> None:
        self.register(flag.key, owner, flag)

    def set_override(self, key: str, enabled: bool) -> None:
        self.get(key)
        self._overrides[key] = enabled

    def is_enabled(self, key: str) -> bool:
        flag = self.get(key)
        return self._overrides.get(key, flag.default)
