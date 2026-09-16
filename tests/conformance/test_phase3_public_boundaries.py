from businessos.modules import discover_modules


def test_phase3_modules_discover_and_declare_dependencies() -> None:
    phase3_ids = {
        "foundation.geography",
        "foundation.reference_data",
        "foundation.uom",
        "foundation.party",
    }
    modules = {
        module.manifest.module_id: module
        for module in discover_modules()
        if module.manifest.module_id in phase3_ids
    }
    assert set(modules) == phase3_ids

    # Geography dependencies
    geo_deps = [d.module_id for d in modules["foundation.geography"].manifest.dependencies]
    assert geo_deps == ["foundation.tenant"]

    # Reference data dependencies
    ref_deps = [d.module_id for d in modules["foundation.reference_data"].manifest.dependencies]
    assert ref_deps == ["foundation.tenant"]

    # UoM dependencies
    uom_deps = [d.module_id for d in modules["foundation.uom"].manifest.dependencies]
    assert uom_deps == ["foundation.tenant"]

    # Party dependencies
    party_deps = [d.module_id for d in modules["foundation.party"].manifest.dependencies]
    assert set(party_deps) == {
        "foundation.tenant",
        "foundation.identity",
        "foundation.geography",
        "foundation.reference_data",
    }
