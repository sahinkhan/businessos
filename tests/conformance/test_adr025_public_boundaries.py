"""Gate 1 remains additive representation, without activating a composed runtime."""

import ast
from pathlib import Path

import businessos_policy as policy

import businessos.sdk as sdk
from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.modules import discover_modules


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_field_contracts_are_available_from_their_supported_owning_surfaces() -> None:
    assert sdk.FIELD_CONTRACT_VERSION == "1.0"
    assert sdk.CanonicalFieldLocator.__module__ == "businessos.field_identity"
    assert sdk.OwnerFieldWitness.__module__ == "businessos.field_identity"
    assert sdk.OwnerFieldWitnessProvider.__module__ == "businessos.field_identity"
    assert policy.FIELD_CLASSIFICATION_CONTRACT_VERSION == "1.0"
    assert policy.FIELD_CLASSIFICATION_COMPOSITION_CAPABILITY == (
        "field-classification-composition.v1"
    )
    for contract in (
        policy.PolicyFieldTagFacts,
        policy.PolicyFieldTagFactsResult,
        policy.PolicyFieldTagFactsProvider,
        policy.PolicyEffectiveClassificationControlsFacts,
        policy.PolicyEffectiveClassificationControlsResult,
        policy.PolicyEffectiveClassificationControlsProvider,
        policy.FieldClassificationEnrollment,
    ):
        assert contract.__module__ == "businessos_policy.field_classification_contracts"
        assert contract.__name__ in policy.__all__
        assert contract.__name__ not in sdk.__all__


def test_neutral_and_policy_contract_imports_preserve_downward_dependencies() -> None:
    neutral = imported_modules(Path("platform/src/businessos/field_identity.py"))
    assert not any(name.startswith("businessos_") for name in neutral)
    policy_imports = imported_modules(
        Path("foundations/policy/src/businessos_policy/field_classification_contracts.py")
    )
    assert "businessos.sdk" in policy_imports
    assert not any(name.startswith("businessos_data_governance") for name in policy_imports)
    assert not any(name.startswith("businessos_party") for name in policy_imports)
    for source in Path("foundations/party/src/businessos_party").rglob("*.py"):
        assert not any(
            name.startswith("businessos_data_governance") for name in imported_modules(source)
        ), source


async def test_gate1_interfaces_do_not_activate_or_replace_frozen_policy_contracts() -> None:
    modules = tuple(
        module
        for module in discover_modules()
        if module.manifest.module_id.startswith("foundation.")
        and module.manifest.module_id != "foundation.metadata"
    )
    new_ports = {
        sdk.CANONICAL_FIELD_LOCATOR_CONTRACT_ID,
        sdk.OWNER_FIELD_WITNESS_CONTRACT_ID,
        policy.FIELD_TAG_FACTS_CONTRACT_ID,
        policy.EFFECTIVE_CLASSIFICATION_CONTROLS_CONTRACT_ID,
        policy.FIELD_CLASSIFICATION_COMPOSITION_CAPABILITY,
    }
    for module in modules:
        assert new_ports.isdisjoint(
            contract.contract_id for contract in module.manifest.public_contracts
        )
    app = create_application(
        Settings(
            environment="test",
            database_url="postgresql+psycopg://unused:unused@localhost/unused",
        ),
        modules=modules,
    )
    assert app.runtime is not None
    await app.startup()
    try:
        entries = {entry.name: entry for entry in app.runtime.contracts.entries()}
        assert new_ports.isdisjoint(entries)
        for name in (
            "foundation.policy.authorization.v2",
            "foundation.policy.field-policy.v2",
            "foundation.policy.approval-authority.v2",
        ):
            assert entries[name].owner == "foundation.policy"
            assert entries[name].value.version == "2"
    finally:
        await app.shutdown()
