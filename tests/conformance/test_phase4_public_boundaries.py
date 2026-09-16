from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.modules import discover_modules


def test_phase4_modules_discover_and_declare_dependencies() -> None:
    phase4_ids = {
        "foundation.policy",
        "foundation.audit",
        "foundation.data_governance",
    }
    modules = {
        module.manifest.module_id: module
        for module in discover_modules()
        if module.manifest.module_id in phase4_ids
    }
    assert set(modules) == phase4_ids

    # Policy dependencies
    policy_deps = [d.module_id for d in modules["foundation.policy"].manifest.dependencies]
    assert set(policy_deps) == {
        "foundation.tenant",
        "foundation.identity",
        "foundation.organization",
        "foundation.party",
    }

    # Audit dependencies
    audit_deps = [d.module_id for d in modules["foundation.audit"].manifest.dependencies]
    assert set(audit_deps) == {
        "foundation.tenant",
        "foundation.identity",
        "foundation.policy",
    }

    # Data Governance dependencies
    gov_deps = [d.module_id for d in modules["foundation.data_governance"].manifest.dependencies]
    assert set(gov_deps) == {
        "foundation.tenant",
        "foundation.policy",
        "foundation.audit",
    }


async def test_phase4_public_contracts_are_registered_and_versioned() -> None:
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
        expected = {
            "foundation.audit.write-facade.v1": "foundation.audit",
            "foundation.governance.export-delete-hooks.v1": "foundation.data_governance",
            "foundation.governance.retention-policy.v1": "foundation.data_governance",
            "foundation.policy.approval-authority.v1": "foundation.policy",
            "foundation.policy.authorization.v1": "foundation.policy",
            "foundation.policy.field-policy.v1": "foundation.policy",
        }
        entries = {entry.name: entry for entry in app.runtime.contracts.entries()}
        for name, owner in expected.items():
            assert entries[name].owner == owner
            assert entries[name].value.version == "1"
    finally:
        await app.shutdown()
