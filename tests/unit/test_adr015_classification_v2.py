"""Qualified identity, monotonic controls, and protected alias grant checks."""

from pathlib import Path
from uuid import uuid4

import pytest
from businessos_data_governance import DataGovernanceModule
from businessos_data_governance.classification_v2 import (
    SecurityControls,
    canonical_ref,
    parse_ref,
    tenant_ref,
)

from businessos.errors import ConfigurationError
from businessos.modules import ModuleRegistry
from businessos.modules.artifact import ApprovedModuleArtifact
from businessos.modules.installation_inventory import approved_artifacts_from_operator_inventory
from businessos.version import runtime_version


def test_qualified_identity_is_unambiguous_and_tenant_bound() -> None:
    tenant_a, tenant_b = uuid4(), uuid4()
    assert canonical_ref("PERSONAL") == "core:PERSONAL"
    assert tenant_ref(tenant_a, "LOCAL") == f"tenant:{tenant_a}:LOCAL"
    assert parse_ref("core:PERSONAL", tenant_a) == ("core", "PERSONAL")
    assert parse_ref(tenant_ref(tenant_a, "LOCAL"), tenant_a) == ("tenant", "LOCAL")
    for bad in ("PERSONAL", "core:personal", tenant_ref(tenant_b, "LOCAL")):
        with pytest.raises(ValueError):
            parse_ref(bad, tenant_a)


def test_overlay_composition_is_monotonic() -> None:
    base = SecurityControls(
        3,
        frozenset({"encrypt"}),
        frozenset({"no_export"}),
        frozenset({"staff", "manager"}),
        True,
    )
    addition = SecurityControls(
        4,
        frozenset({"mfa"}),
        frozenset({"region_only"}),
        frozenset({"manager"}),
        False,
    )
    effective = base.compose(addition)
    assert effective.sensitivity_level == 4
    assert effective.required_controls == frozenset({"encrypt", "mfa"})
    assert effective.restrictions == frozenset({"no_export", "region_only"})
    assert effective.allowed_audience == frozenset({"manager"})
    assert effective.mandatory_masking is True
    with pytest.raises(ValueError, match="lower"):
        base.compose(SecurityControls(2))
    with pytest.raises(ValueError, match="expand"):
        base.compose(SecurityControls(4, allowed_audience=frozenset({"manager", "auditor"})))


def test_governance_alias_requires_protected_exact_grant() -> None:
    module = DataGovernanceModule()
    with pytest.raises(ConfigurationError, match="approved artifact"):
        ModuleRegistry(platform_version=runtime_version(), sdk_version="0.1.0").add(module)
    incomplete = ApprovedModuleArtifact(
        loaded_module=module,
        module_id="foundation.data_governance",
        publisher="BusinessOS",
        package_identity="businessos-foundation-data-governance",
        loaded_type="businessos_data_governance.module:DataGovernanceModule",
        install_identity="unit-test-grant",
        first_party=True,
    )
    with pytest.raises(ConfigurationError, match="alias"):
        ModuleRegistry(
            platform_version=runtime_version(),
            sdk_version="0.1.0",
            approved_artifacts={"foundation.data_governance": incomplete},
        ).add(module)
    inventory = Path(__file__).parents[1] / "fixtures" / "approved-module-inventory.ci.json"
    grants = approved_artifacts_from_operator_inventory((module,), str(inventory))
    registry = ModuleRegistry(
        platform_version=runtime_version(), sdk_version="0.1.0", approved_artifacts=grants
    )
    registry.add(module)
    assert registry.get("foundation.data_governance").manifest.resource_ownership[0].aliases == (
        "foundation.governance.data-classification",
    )
