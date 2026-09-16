import json
from dataclasses import replace

import pytest
from scripts import migration_database_smoke as smoke

from businessos.migrations import MigrationPlan
from businessos.modules import discover_modules


def _inventory(plan: MigrationPlan) -> list[tuple[object, ...]]:
    return [(owner, *values) for owner, values in smoke._expected_inventory(plan).items()]


def _plan_json(plan: MigrationPlan) -> str:
    return json.dumps(
        {
            "heads": plan.heads,
            "sources": [
                {"owner": source.owner, "namespace": source.namespace, "location": source.location}
                for source in plan.sources
            ],
        }
    )


def test_artifact_graph_preserves_phase1_and_phase2_branches() -> None:
    plan = smoke._expected_plan()
    assert {source.owner for source in plan.sources} == smoke.REQUIRED_OWNERS
    assert plan.heads == ("organization_0001", "proof_0003")
    parents = {revision.revision: revision.down_revisions for revision in plan.revisions}
    assert parents["proof_0001"] == ("0001_phase1_kernel",)
    assert parents["proof_0002"] == ("proof_0001",)
    assert parents["proof_0003"] == ("proof_0002",)
    assert parents["tenant_0001"] == ("0005_durable_event_subscribers",)
    assert parents["identity_0001"] == ("tenant_0001",)
    assert parents["organization_0001"] == ("identity_0001",)
    smoke._verify_installed_plan(_plan_json(plan), plan)
    smoke._verify_state(set(plan.heads), _inventory(plan), plan)


@pytest.mark.parametrize("change", ["missing_revision", "rogue_revision", "rewritten_revision"])
def test_wheel_graph_must_preserve_build_revisions(change: str) -> None:
    plan = smoke._expected_plan()
    revisions = list(plan.revisions)
    if change == "missing_revision":
        revisions.pop()
    elif change == "rogue_revision":
        revisions.append(replace(revisions[-1], revision="rogue_0001"))
    else:
        revisions[-1] = replace(revisions[-1], fingerprint="0" * 64)
    with pytest.raises(RuntimeError, match="installed migration graph differs"):
        smoke._verify_graph_snapshot(
            smoke._graph_snapshot(plan), replace(plan, revisions=tuple(revisions))
        )


def test_artifact_discovery_rejects_missing_required_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modules = [
        module
        for module in discover_modules()
        if module.manifest.module_id != "foundation.organization"
    ]
    monkeypatch.setattr(smoke, "discover_modules", lambda: modules)
    with pytest.raises(RuntimeError, match="missing required migration sources"):
        smoke._expected_plan()


@pytest.mark.parametrize("change", ["missing_head", "rogue_head", "missing_source", "rogue_source"])
def test_installed_plan_must_match_expected_graph(change: str) -> None:
    plan = smoke._expected_plan()
    altered = plan
    if change == "missing_head":
        altered = replace(plan, heads=plan.heads[:-1])
    elif change == "rogue_head":
        altered = replace(plan, heads=(*plan.heads, "rogue_0001"))
    elif change == "missing_source":
        altered = replace(plan, sources=plan.sources[:-1])
    else:
        altered = replace(
            plan, sources=(*plan.sources, replace(plan.sources[-1], owner="example.rogue"))
        )
    with pytest.raises(RuntimeError, match="installed migration plan differs"):
        smoke._verify_installed_plan(_plan_json(altered), plan)


@pytest.mark.parametrize("change", ["missing", "rogue", "old_core"])
def test_database_heads_must_equal_all_expected_heads(change: str) -> None:
    plan = smoke._expected_plan()
    heads = set(plan.heads)
    if change == "missing":
        heads.remove("organization_0001")
    elif change == "rogue":
        heads.add("rogue_0001")
    else:
        heads = {"0005_durable_event_subscribers", "proof_0003"}
    with pytest.raises(RuntimeError, match="unexpected migration heads"):
        smoke._verify_state(heads, _inventory(plan), plan)


@pytest.mark.parametrize(
    "change", ["missing_owner", "rogue_owner", "duplicate_owner", "revision", "fingerprint"]
)
def test_inventory_must_match_every_expected_module_and_revision(change: str) -> None:
    plan = smoke._expected_plan()
    inventory = _inventory(plan)
    if change == "missing_owner":
        inventory.pop()
    elif change == "rogue_owner":
        inventory.append(("example.rogue", *inventory[0][1:]))
    elif change == "duplicate_owner":
        inventory.append(inventory[0])
    else:
        row = list(inventory[0])
        if change == "revision":
            row[5] = ["proof_0001", "proof_0002"]
        else:
            row[6] = [{"revision": "proof_0001", "fingerprint": "0" * 64}]
        inventory[0] = tuple(row)
    with pytest.raises(RuntimeError, match="installed migration inventory differs"):
        smoke._verify_state(set(plan.heads), inventory, plan)


def test_additional_independent_module_head_needs_no_smoke_revision_edit() -> None:
    plan = smoke._expected_plan()
    source = replace(
        plan.sources[-1],
        owner="example.future",
        namespace="future",
        location="python://future/versions",
        logical_location="python://future/versions",
        distribution_identity="python-distribution:future",
    )
    revision = replace(
        plan.revisions[-1],
        owner=source.owner,
        revision="future_0001",
        namespace=source.namespace,
        down_revisions=("0005_durable_event_subscribers",),
        branch_labels=(source.namespace,),
        logical_location=source.logical_location,
        distribution_identity=source.distribution_identity,
    )
    extended = replace(
        plan,
        sources=(*plan.sources, source),
        revisions=(*plan.revisions, revision),
        heads=(*plan.heads, revision.revision),
    )
    smoke._verify_installed_plan(_plan_json(extended), extended)
    smoke._verify_state(set(extended.heads), _inventory(extended), extended)
