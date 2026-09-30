"""Conformance tests for Phase 5A Metadata Foundation module boundaries and public contracts."""

from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.modules import discover_modules


def test_phase5a_metadata_module_discovery_and_manifest() -> None:
    modules = {module.manifest.module_id: module for module in discover_modules()}
    assert "foundation.metadata" in modules

    meta_module = modules["foundation.metadata"]
    manifest = meta_module.manifest

    assert manifest.module_id == "foundation.metadata"
    assert manifest.publisher == "BusinessOS"
    assert manifest.version == "0.1.0"
    assert manifest.migration_namespace == "foundation_metadata"

    deps = {d.module_id for d in manifest.dependencies}
    assert "foundation.tenant" in deps
    assert "foundation.policy" in deps
    assert "foundation.audit" in deps

    permissions = set(manifest.permissions)
    assert permissions == {
        "foundation.metadata.read",
        "foundation.metadata.draft.write",
        "foundation.metadata.publish",
        "foundation.metadata.rollback",
        "foundation.metadata.retire",
    }

    assert len(manifest.resource_ownership) >= 1
    assert manifest.resource_ownership[0].resource_namespace == "foundation.metadata.definition"


async def test_phase5a_public_contracts_are_registered_and_versioned() -> None:
    app = create_application(
        Settings(
            environment="test",
            database_url="postgresql+psycopg://unused:unused@localhost/unused",
        ),
        modules=(
            module
            for module in discover_modules()
            if module.manifest.module_id.startswith("foundation.")
        ),
    )
    assert app.runtime is not None
    await app.startup()
    try:
        expected_contracts = {
            "foundation.metadata.definition.v1": "foundation.metadata",
            "foundation.metadata.revision.v1": "foundation.metadata",
            "foundation.metadata.publish.v1": "foundation.metadata",
            "foundation.metadata.rollback.v1": "foundation.metadata",
            "foundation.metadata.validation-grammar.v1": "foundation.metadata",
            "foundation.metadata.reference-resolution.v1": "foundation.metadata",
            "foundation.metadata.publication-fence.v1": "foundation.metadata",
        }
        entries = {entry.name: entry for entry in app.runtime.contracts.entries()}
        for name, expected_owner in expected_contracts.items():
            assert name in entries, f"Missing registered contract {name}"
            assert entries[name].owner == expected_owner
            assert entries[name].value.version == "1"
    finally:
        await app.shutdown()
