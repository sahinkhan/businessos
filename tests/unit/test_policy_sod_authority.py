"""Focused projections for the private preventative SoD authority closure."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from businessos_policy.delegation_authority import has_effective_role_source
from businessos_policy.models import (
    DelegationGrantRecord,
    RolePermissionRecord,
    RoleRecord,
    ScopeType,
    SegregationOfDutiesRuleRecord,
    SoDSeverity,
    SubjectRoleAssignmentRecord,
)
from businessos_policy.sod_authority import SoDAuthority

from businessos.errors import BusinessOSError

NOW = datetime.now(UTC)
TENANT = uuid4()
FIRST = "policy.first"
SECOND = "policy.second"


def role(parent: UUID | None = None) -> RoleRecord:
    return RoleRecord(
        id=uuid4(),
        tenant_id=TENANT,
        code="role",
        name="Role",
        parent_role_id=parent,
        created_at=NOW,
        updated_at=NOW,
    )


def permission(target: RoleRecord, code: str) -> RolePermissionRecord:
    return RolePermissionRecord(
        id=uuid4(), tenant_id=TENANT, role_id=target.id, permission_code=code, created_at=NOW
    )


def assignment(
    target: RoleRecord, subject: UUID, kind: str | None = "user"
) -> SubjectRoleAssignmentRecord:
    return SubjectRoleAssignmentRecord(
        id=uuid4(),
        tenant_id=TENANT,
        subject_id=subject,
        subject_type=kind,
        role_id=target.id,
        scope_type=ScopeType.TENANT,
        created_at=NOW,
    )


def delegation(target: RoleRecord, source: UUID, recipient: UUID) -> DelegationGrantRecord:
    return DelegationGrantRecord(
        id=uuid4(),
        tenant_id=TENANT,
        delegator_id=source,
        delegator_type="user",
        delegatee_id=recipient,
        delegatee_type="user",
        role_id=target.id,
        scope_type=ScopeType.TENANT,
        valid_from=NOW - timedelta(minutes=1),
        valid_to=NOW + timedelta(days=1),
        is_revoked=False,
        created_at=NOW,
    )


def rule(severity: SoDSeverity = SoDSeverity.PREVENTATIVE) -> SegregationOfDutiesRuleRecord:
    return SegregationOfDutiesRuleRecord(
        id=uuid4(),
        tenant_id=TENANT,
        code="pair",
        name="Pair",
        permission_a=FIRST,
        permission_b=SECOND,
        severity=severity,
        created_at=NOW,
    )


def graph(
    *,
    roles: tuple[RoleRecord, ...] = (),
    permissions: tuple[RolePermissionRecord, ...] = (),
    assignments: tuple[SubjectRoleAssignmentRecord, ...] = (),
    delegations: tuple[DelegationGrantRecord, ...] = (),
    rules: tuple[SegregationOfDutiesRuleRecord, ...] = (),
) -> SoDAuthority:
    return SoDAuthority(TENANT, roles, permissions, assignments, delegations, rules)


def conflict(base: SoDAuthority, projected: SoDAuthority, *, new_rule: bool = False) -> None:
    with pytest.raises(BusinessOSError) as failure:
        base.reject_new_conflicts(projected, new_rule=new_rule)
    assert failure.value.code == "segregation_of_duties_conflict"


def test_assignment_uses_inherited_permissions_and_ignores_legacy_type() -> None:
    parent = role()
    child = role(parent.id)
    second = role()
    subject = uuid4()
    base = graph(
        roles=(parent, child, second),
        permissions=(permission(parent, FIRST), permission(second, SECOND)),
        assignments=(assignment(second, subject), assignment(child, subject, None)),
        rules=(rule(),),
    )
    assert base.permissions_for(("user", subject), NOW) == {SECOND}
    conflict(base, base.with_assignment(assignment(child, subject)))


def test_parent_permission_add_checks_descendant_and_detective_is_nonblocking() -> None:
    parent = role()
    child = role(parent.id)
    second = role()
    subject = uuid4()
    base = graph(
        roles=(parent, child, second),
        permissions=(permission(second, SECOND),),
        assignments=(assignment(child, subject), assignment(second, subject)),
        rules=(rule(),),
    )
    conflict(base, base.with_permission(permission(parent, FIRST)))
    detective = graph(
        roles=base.roles,
        permissions=base.permissions,
        assignments=base.assignments,
        rules=(rule(SoDSeverity.DETECTIVE),),
    )
    detective.reject_new_conflicts(detective.with_permission(permission(parent, FIRST)))


def test_transitive_delegation_and_rule_preflight_share_closure() -> None:
    first = role()
    second = role()
    source, middle, recipient = uuid4(), uuid4(), uuid4()
    base = graph(
        roles=(first, second),
        permissions=(permission(first, FIRST), permission(second, SECOND)),
        assignments=(assignment(first, source), assignment(second, recipient)),
        delegations=(delegation(first, source, middle),),
        rules=(rule(),),
    )
    conflict(base, base.with_delegation(delegation(first, middle, recipient)))
    no_rule = graph(
        roles=base.roles,
        permissions=base.permissions,
        assignments=(*base.assignments, assignment(first, recipient)),
        delegations=base.delegations,
    )
    conflict(no_rule, no_rule.with_rule(rule()), new_rule=True)
    no_rule.reject_new_conflicts(no_rule.with_rule(rule(SoDSeverity.DETECTIVE)), new_rule=True)


def test_permission_add_reaches_transitive_delegatee_but_not_revoked_chain() -> None:
    first = role()
    second = role()
    source, middle, recipient = uuid4(), uuid4(), uuid4()
    parent = delegation(first, source, middle)
    child = delegation(first, middle, recipient)
    base = graph(
        roles=(first, second),
        permissions=(permission(first, FIRST),),
        assignments=(assignment(first, source), assignment(second, recipient)),
        delegations=(parent, child),
        rules=(rule(),),
    )
    conflict(base, base.with_permission(permission(second, SECOND)))
    revoked = graph(
        roles=base.roles,
        permissions=base.permissions,
        assignments=base.assignments,
        delegations=(parent.model_copy(update={"is_revoked": True}), child),
        rules=base.rules,
    )
    revoked.reject_new_conflicts(revoked.with_permission(permission(second, SECOND)))


def test_future_overlap_is_checked_at_start_boundary() -> None:
    first = role()
    second = role()
    subject = uuid4()
    future = assignment(second, subject).model_copy(
        update={"valid_from": NOW + timedelta(days=2), "valid_to": NOW + timedelta(days=3)}
    )
    base = graph(
        roles=(first, second),
        permissions=(permission(first, FIRST), permission(second, SECOND)),
        assignments=(assignment(first, subject),),
        rules=(rule(),),
    )
    conflict(base, base.with_assignment(future))


def test_malformed_role_cycle_fails_closed() -> None:
    first = role()
    second = role(first.id)
    first = first.model_copy(update={"parent_role_id": second.id})
    base = graph(roles=(first, second), rules=(rule(),))
    with pytest.raises(BusinessOSError) as failure:
        base.reject_new_conflicts(base)
    assert failure.value.code == "authority_unbounded"


def test_typed_uuid_collision_and_revoked_delegation_do_not_grant_authority() -> None:
    first = role()
    second = role()
    shared_id, source = uuid4(), uuid4()
    revoked = delegation(first, source, shared_id).model_copy(update={"is_revoked": True})
    expired = delegation(first, source, shared_id).model_copy(
        update={"valid_to": NOW - timedelta(seconds=1), "valid_from": NOW - timedelta(hours=2)}
    )
    base = graph(
        roles=(first, second),
        permissions=(permission(first, FIRST), permission(second, SECOND)),
        assignments=(
            assignment(first, shared_id, "user"),
            assignment(second, shared_id, "device"),
            assignment(first, source),
        ),
        delegations=(revoked, expired),
        rules=(rule(),),
    )
    assert base.permissions_for(("device", shared_id), NOW) == {SECOND}
    base.reject_new_conflicts(base.with_assignment(assignment(second, uuid4())))


def test_unrelated_subject_does_not_block_permission_mutation() -> None:
    first = role()
    second = role()
    unrelated = role()
    subject = uuid4()
    # A historical conflict cannot make an unrelated subject's harmless
    # permission addition fail; only newly gained conflicting authority does.
    base = graph(
        roles=(first, second, unrelated),
        permissions=(permission(first, FIRST), permission(second, SECOND)),
        assignments=(assignment(first, subject), assignment(second, subject)),
        rules=(rule(),),
    )
    base.reject_new_conflicts(base.with_permission(permission(unrelated, FIRST)))


def test_bounded_affected_subject_scan_fails_closed() -> None:
    first = role()
    start = NOW + timedelta(days=2)
    assignments = tuple(
        assignment(first, uuid4()).model_copy(update={"valid_from": start + timedelta(minutes=i)})
        for i in range(65)
    )
    base = graph(roles=(first,), assignments=assignments, rules=(rule(),))
    with pytest.raises(BusinessOSError) as failure:
        base.reject_new_conflicts(base.with_permission(permission(first, FIRST)))
    assert failure.value.code == "authority_unbounded"


def test_dense_delegation_paths_exhaust_traversal_budget() -> None:
    target = role()
    previous = (uuid4(), uuid4())
    grants: list[DelegationGrantRecord] = []
    for _ in range(14):
        current = (uuid4(), uuid4())
        grants.extend(
            delegation(target, source, recipient) for source in previous for recipient in current
        )
        previous = current
    terminal = uuid4()
    grants.extend(delegation(target, source, terminal) for source in previous)
    base = graph(
        roles=(target,),
        permissions=(permission(target, FIRST),),
        delegations=tuple(grants),
        rules=(rule(),),
    )
    with pytest.raises(BusinessOSError) as source_failure:
        has_effective_role_source(
            tenant_id=TENANT,
            subject_id=terminal,
            subject_type="user",
            role_id=target.id,
            scope_type=ScopeType.TENANT,
            scope_id=None,
            valid_from=NOW,
            valid_until=NOW + timedelta(minutes=30),
            evaluated_at=NOW,
            assignments=[],
            delegations=grants,
            traversal_budget=[128],
        )
    assert source_failure.value.code == "authority_unbounded"
    with pytest.raises(BusinessOSError) as failure:
        base.reject_new_conflicts(base.with_permission(permission(target, SECOND)))
    assert failure.value.code == "authority_unbounded"
    assert "delegation source traversal" in failure.value.message


def test_projected_row_bound_rejects_the_257th_authority_row() -> None:
    target = role()
    subject = uuid4()
    permission_row = permission(target, FIRST)
    assignment_row = assignment(target, subject)
    delegation_row = delegation(target, subject, uuid4())
    rule_row = rule()
    projections = (
        (
            graph(roles=(target,), permissions=(permission_row,) * 256),
            graph(roles=(target,), permissions=(permission_row,) * 257),
        ),
        (
            graph(roles=(target,), assignments=(assignment_row,) * 256),
            graph(roles=(target,), assignments=(assignment_row,) * 257),
        ),
        (
            graph(roles=(target,), delegations=(delegation_row,) * 256),
            graph(roles=(target,), delegations=(delegation_row,) * 257),
        ),
        (
            graph(roles=(target,), rules=(rule_row,) * 256),
            graph(roles=(target,), rules=(rule_row,) * 257),
        ),
    )
    for base, projected in projections:
        base._validate_shape()
        with pytest.raises(BusinessOSError) as failure:
            base.reject_new_conflicts(projected)
        assert failure.value.code == "authority_unbounded"

    base = graph(roles=(target,) * 256)
    base._validate_shape()
    with pytest.raises(BusinessOSError) as failure:
        base.with_role(role())
    assert failure.value.code == "authority_unbounded"
