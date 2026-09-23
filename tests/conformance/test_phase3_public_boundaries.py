from pathlib import Path
from tomllib import load

from businessos.modules import discover_modules

PHASE2_DEPENDENCIES = {
    "foundation.tenant": [],
    "foundation.identity": ["foundation.tenant"],
    "foundation.organization": ["foundation.tenant", "foundation.identity"],
}

PHASE3_DEPENDENCIES = {
    "foundation.currency": ["foundation.tenant"],
    "foundation.geography": ["foundation.tenant", "foundation.organization", "foundation.currency"],
    "foundation.reference_data": ["foundation.tenant", "foundation.geography"],
    "foundation.uom": ["foundation.tenant", "foundation.reference_data"],
    "foundation.party": [
        "foundation.tenant",
        "foundation.identity",
        "foundation.geography",
        "foundation.reference_data",
        "foundation.uom",
    ],
}

PHASE3_DISTRIBUTIONS = {
    "currency": "businessos-foundation-tenant>=0.2,<1",
    "geography": "businessos-foundation-currency>=0.3,<1",
    "reference_data": "businessos-foundation-geography>=0.3,<1",
    "uom": "businessos-foundation-reference-data>=0.3,<1",
    "party": "businessos-foundation-uom>=0.3,<1",
}


def test_phase3_modules_discover_and_declare_dependencies() -> None:
    expected = {**PHASE2_DEPENDENCIES, **PHASE3_DEPENDENCIES}
    modules = {
        module.manifest.module_id: module
        for module in discover_modules()
        if module.manifest.module_id in expected
    }
    assert set(modules) == set(expected)
    for module_id, dependency_ids in expected.items():
        actual = [item.module_id for item in modules[module_id].manifest.dependencies]
        assert actual == dependency_ids


def test_phase3_distribution_dependencies_match_module_migration_dependencies() -> None:
    repository = Path(__file__).resolve().parents[2]
    for package, requirement in PHASE3_DISTRIBUTIONS.items():
        with repository.joinpath("foundations", package, "pyproject.toml").open("rb") as stream:
            metadata = load(stream)
        assert requirement in metadata["project"]["dependencies"]
