import pytest

from businessos.errors import ConflictError, NotFoundError
from businessos.features import FeatureFlag, FeatureFlagRegistry
from businessos.registry import OwnedRegistry


def test_owned_registry_rejects_duplicate_ownership() -> None:
    registry = OwnedRegistry[str]("example")
    registry.register("shared", "module.a", "first")

    with pytest.raises(ConflictError, match=r"module\.a"):
        registry.register("shared", "module.b", "second")


def test_owned_registry_is_sorted_and_unknown_values_fail() -> None:
    registry = OwnedRegistry[str]("example")
    registry.register("z", "module", "last")
    registry.register("a", "module", "first")

    assert [entry.name for entry in registry.entries()] == ["a", "z"]
    with pytest.raises(NotFoundError):
        registry.get("missing")


def test_feature_flags_require_declaration_before_override() -> None:
    flags = FeatureFlagRegistry()
    flags.add("module", FeatureFlag(key="feature.enabled", description="Example"))
    assert not flags.is_enabled("feature.enabled")

    flags.set_override("feature.enabled", True)
    assert flags.is_enabled("feature.enabled")

    with pytest.raises(NotFoundError):
        flags.set_override("feature.missing", True)
