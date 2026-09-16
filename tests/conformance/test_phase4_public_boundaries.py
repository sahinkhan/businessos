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
    }

    # Audit dependencies
    audit_deps = [d.module_id for d in modules["foundation.audit"].manifest.dependencies]
    assert set(audit_deps) == {
        "foundation.tenant",
        "foundation.identity",
    }

    # Data Governance dependencies
    gov_deps = [d.module_id for d in modules["foundation.data_governance"].manifest.dependencies]
    assert set(gov_deps) == {
        "foundation.tenant",
        "foundation.policy",
        "foundation.audit",
    }
