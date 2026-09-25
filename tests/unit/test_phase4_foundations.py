"""Unit tests for Phase 4 foundational modules: Policy, Audit, and Data Governance."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from businessos_audit import compute_audit_checksum
from businessos_data_governance import DataGovernanceHooks
from businessos_policy import (
    ApprovalLimitRecord,
    DelegationGrantRecord,
    FieldAccessType,
    FieldPolicyRecord,
    PolicyContext,
    PolicyEvaluationService,
    RecordAccessScope,
    RecordPolicyRecord,
    RolePermissionRecord,
    RoleRecord,
    ScopeType,
    SegregationOfDutiesRuleRecord,
    SubjectRoleAssignmentRecord,
    SupportAccessGrantRecord,
)


def test_authorization_positive_and_negative_matrix_and_inheritance() -> None:
    service = PolicyEvaluationService()
    tenant_id = uuid4()
    subject_id = uuid4()
    now = datetime.now(UTC)

    parent_role_id = uuid4()
    child_role_id = uuid4()

    roles = [
        RoleRecord(
            id=parent_role_id,
            tenant_id=tenant_id,
            code="base_reader",
            name="Base Reader",
            created_at=now,
            updated_at=now,
        ),
        RoleRecord(
            id=child_role_id,
            tenant_id=tenant_id,
            code="specialist",
            name="Specialist",
            parent_role_id=parent_role_id,
            created_at=now,
            updated_at=now,
        ),
    ]

    role_permissions = [
        RolePermissionRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            role_id=parent_role_id,
            permission_code="order.read",
            created_at=now,
        ),
        RolePermissionRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            role_id=child_role_id,
            permission_code="order.edit",
            created_at=now,
        ),
    ]

    assignments = [
        SubjectRoleAssignmentRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            subject_id=subject_id,
            role_id=child_role_id,
            scope_type=ScopeType.TENANT,
            created_at=now,
        )
    ]

    ctx = PolicyContext(tenant_id=tenant_id, subject_id=subject_id, timestamp=now)

    # Positive test on direct permission
    dec_edit = service.authorize("order.edit", "order", ctx, roles, role_permissions, assignments)
    assert dec_edit.allowed is True

    # Positive test on inherited permission from parent_role
    dec_read = service.authorize("order.read", "order", ctx, roles, role_permissions, assignments)
    assert dec_read.allowed is True

    # Negative test on ungranted permission (deny by default)
    dec_delete = service.authorize(
        "order.delete", "order", ctx, roles, role_permissions, assignments
    )
    assert dec_delete.allowed is False
    assert "Deny by default" in dec_delete.reason


def test_cross_company_and_site_scope_enforcement() -> None:
    service = PolicyEvaluationService()
    tenant_id = uuid4()
    subject_id = uuid4()
    now = datetime.now(UTC)

    site_alpha = uuid4()
    site_beta = uuid4()

    role_id = uuid4()
    roles = [
        RoleRecord(
            id=role_id,
            tenant_id=tenant_id,
            code="site_manager",
            name="Site Manager",
            created_at=now,
            updated_at=now,
        )
    ]
    role_permissions = [
        RolePermissionRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            role_id=role_id,
            permission_code="inventory.manage",
            created_at=now,
        )
    ]

    # Assignment scoped strictly to site_alpha and legal_entity_a
    assignments = [
        SubjectRoleAssignmentRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            subject_id=subject_id,
            role_id=role_id,
            scope_type=ScopeType.OPERATING_SITE,
            scope_id=site_alpha,
            created_at=now,
        )
    ]

    # Matching site context -> Allowed
    ctx_allowed = PolicyContext(
        tenant_id=tenant_id,
        subject_id=subject_id,
        operating_site_id=site_alpha,
        timestamp=now,
    )
    dec_allowed = service.authorize(
        "inventory.manage", "inventory", ctx_allowed, roles, role_permissions, assignments
    )
    assert dec_allowed.allowed is True

    # Non-matching site context -> Denied
    ctx_denied = PolicyContext(
        tenant_id=tenant_id,
        subject_id=subject_id,
        operating_site_id=site_beta,
        timestamp=now,
    )
    dec_denied = service.authorize(
        "inventory.manage", "inventory", ctx_denied, roles, role_permissions, assignments
    )
    assert dec_denied.allowed is False


def test_field_level_security_policies() -> None:
    service = PolicyEvaluationService()
    tenant_id = uuid4()
    subject_id = uuid4()
    now = datetime.now(UTC)
    role_admin = uuid4()
    role_user = uuid4()

    policies = [
        FieldPolicyRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            resource_type="party",
            field_name="tax_identifier",
            role_id=role_admin,
            access_type=FieldAccessType.READ,
            mask_pattern=None,
            created_at=now,
        ),
        FieldPolicyRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            resource_type="party",
            field_name="tax_identifier",
            role_id=role_user,
            access_type=FieldAccessType.MASK,
            mask_pattern="***-**-####",
            created_at=now,
        ),
        FieldPolicyRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            resource_type="party",
            field_name="ssn",
            role_id=None,  # All roles
            access_type=FieldAccessType.DENY,
            created_at=now,
        ),
    ]

    ctx = PolicyContext(tenant_id=tenant_id, subject_id=subject_id)

    # Admin access -> full read
    admin_dec = service.evaluate_field_access(
        "tax_identifier", "party", ctx, policies, {role_admin}
    )
    assert admin_dec.allowed is True
    assert admin_dec.access_type == FieldAccessType.READ
    assert admin_dec.mask_pattern is None

    # Regular user access -> masked
    user_dec = service.evaluate_field_access("tax_identifier", "party", ctx, policies, {role_user})
    assert user_dec.allowed is True
    assert user_dec.access_type == FieldAccessType.MASK
    assert user_dec.mask_pattern == "***-**-####"

    # SSN access -> Denied
    deny_dec = service.evaluate_field_access("ssn", "party", ctx, policies, {role_user})
    assert deny_dec.allowed is False
    assert deny_dec.access_type == FieldAccessType.DENY


def test_segregation_of_duties_conflict_detection() -> None:
    service = PolicyEvaluationService()
    tenant_id = uuid4()
    now = datetime.now(UTC)

    rules = [
        SegregationOfDutiesRuleRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            code="SOD-001",
            name="Cannot both create and approve purchase orders",
            permission_a="procurement.po.create",
            permission_b="procurement.po.approve",
            description="Prevent rogue purchasing",
            created_at=now,
        )
    ]

    # Subject with only one permission -> No conflict
    res_clean = service.check_sod_conflict({"procurement.po.create", "general.view"}, rules)
    assert res_clean.has_conflict is False

    # Subject attempting to hold both -> Conflict
    res_conflict = service.check_sod_conflict(
        {"procurement.po.create", "procurement.po.approve"}, rules
    )
    assert res_conflict.has_conflict is True
    assert len(res_conflict.conflicting_rules) == 1
    assert "SOD-001" in res_conflict.conflicting_rules[0]


def test_delegated_authority_and_time_limits() -> None:
    service = PolicyEvaluationService()
    tenant_id = uuid4()
    delegator_id = uuid4()
    delegatee_id = uuid4()
    role_id = uuid4()
    now = datetime.now(UTC)

    roles = [
        RoleRecord(
            id=role_id,
            tenant_id=tenant_id,
            code="approver",
            name="Approver",
            created_at=now,
            updated_at=now,
        )
    ]
    role_permissions = [
        RolePermissionRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            role_id=role_id,
            permission_code="finance.invoice.approve",
            created_at=now,
        )
    ]

    # Active delegation for delegatee
    delegation = DelegationGrantRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        delegator_id=delegator_id,
        delegatee_id=delegatee_id,
        role_id=role_id,
        scope_type=ScopeType.TENANT,
        valid_from=now - timedelta(days=1),
        valid_to=now + timedelta(days=2),
        is_revoked=False,
        created_at=now,
    )

    ctx_during = PolicyContext(tenant_id=tenant_id, subject_id=delegatee_id, timestamp=now)
    dec = service.authorize(
        "finance.invoice.approve", "finance", ctx_during, roles, role_permissions, (), [delegation]
    )
    assert dec.allowed is True

    # After expiry -> Denied
    ctx_expired = PolicyContext(
        tenant_id=tenant_id, subject_id=delegatee_id, timestamp=now + timedelta(days=5)
    )
    dec_expired = service.authorize(
        "finance.invoice.approve", "finance", ctx_expired, roles, role_permissions, (), [delegation]
    )
    assert dec_expired.allowed is False

    # Revoked delegation -> Denied
    delegation_revoked = DelegationGrantRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        delegator_id=delegator_id,
        delegatee_id=delegatee_id,
        role_id=role_id,
        scope_type=ScopeType.TENANT,
        valid_from=now - timedelta(days=1),
        valid_to=now + timedelta(days=2),
        is_revoked=True,
        revocation_reason="Ended early",
        created_at=now,
    )
    dec_revoked = service.authorize(
        "finance.invoice.approve",
        "finance",
        ctx_during,
        roles,
        role_permissions,
        (),
        [delegation_revoked],
    )
    assert dec_revoked.allowed is False


def test_approval_limits_evaluation() -> None:
    service = PolicyEvaluationService()
    tenant_id = uuid4()
    subject_id = uuid4()
    role_id = uuid4()
    now = datetime.now(UTC)

    limits = [
        ApprovalLimitRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            action_type="purchase_order_approval",
            currency="USD",
            amount_limit=Decimal("50000.00"),
            role_id=role_id,
            created_at=now,
        )
    ]

    ctx = PolicyContext(tenant_id=tenant_id, subject_id=subject_id, timestamp=now)

    # Within limit -> Authorized
    auth_ok = service.evaluate_approval_authority(
        "purchase_order_approval", Decimal("25000.00"), "USD", ctx, limits, {role_id}
    )
    assert auth_ok.has_authority is True

    # Exceeding limit -> Not authorized
    auth_over = service.evaluate_approval_authority(
        "purchase_order_approval", Decimal("75000.00"), "USD", ctx, limits, {role_id}
    )
    assert auth_over.has_authority is False


def test_audit_hash_chaining_and_tamper_detection() -> None:
    tenant_id = uuid4()
    now = datetime.now(UTC)

    c1 = compute_audit_checksum(
        tenant_id=tenant_id,
        occurred_at=now,
        actor_id="user_1",
        action="create",
        resource_type="party",
        resource_id="123",
        status="success",
        previous_checksum="",
    )
    assert len(c1) == 64

    c2 = compute_audit_checksum(
        tenant_id=tenant_id,
        occurred_at=now + timedelta(seconds=1),
        actor_id="user_2",
        action="update",
        resource_type="party",
        resource_id="123",
        status="success",
        previous_checksum=c1,
    )
    assert len(c2) == 64
    assert c1 != c2

    # Tampering test: recalculating c2 with altered actor should fail to match c2
    c2_tampered = compute_audit_checksum(
        tenant_id=tenant_id,
        occurred_at=now + timedelta(seconds=1),
        actor_id="hacker_9",
        action="update",
        resource_type="party",
        resource_id="123",
        status="success",
        previous_checksum=c1,
    )
    assert c2_tampered != c2


def test_company_business_unit_and_cross_tenant_scope_are_enforced() -> None:
    service = PolicyEvaluationService()
    tenant_id = uuid4()
    other_tenant = uuid4()
    subject_id = uuid4()
    company_id = uuid4()
    business_unit_id = uuid4()
    role_id = uuid4()
    now = datetime.now(UTC)
    roles = [
        RoleRecord(
            id=role_id,
            tenant_id=tenant_id,
            code="operator",
            name="Operator",
            created_at=now,
            updated_at=now,
        )
    ]
    permissions = [
        RolePermissionRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            role_id=role_id,
            permission_code="inventory.read",
            created_at=now,
        )
    ]
    company_assignment = SubjectRoleAssignmentRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        subject_id=subject_id,
        role_id=role_id,
        scope_type=ScopeType.COMPANY,
        scope_id=company_id,
        created_at=now,
    )
    assert service.authorize(
        "inventory.read",
        "inventory",
        PolicyContext(
            tenant_id=tenant_id,
            subject_id=subject_id,
            company_id=company_id,
            timestamp=now,
        ),
        roles,
        permissions,
        [company_assignment],
    ).allowed
    assert not service.authorize(
        "inventory.read",
        "inventory",
        PolicyContext(
            tenant_id=tenant_id,
            subject_id=subject_id,
            company_id=uuid4(),
            business_unit_id=business_unit_id,
            timestamp=now,
        ),
        roles,
        permissions,
        [company_assignment],
    ).allowed
    assert not service.authorize(
        "inventory.read",
        "inventory",
        PolicyContext(tenant_id=other_tenant, subject_id=subject_id, timestamp=now),
        roles,
        permissions,
        [company_assignment],
    ).allowed


def test_record_policy_abac_and_wildcard_boundaries() -> None:
    service = PolicyEvaluationService()
    tenant_id = uuid4()
    subject_id = uuid4()
    role_id = uuid4()
    now = datetime.now(UTC)
    roles = [
        RoleRecord(
            id=role_id,
            tenant_id=tenant_id,
            code="owner",
            name="Owner",
            created_at=now,
            updated_at=now,
        )
    ]
    assignments = [
        SubjectRoleAssignmentRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            subject_id=subject_id,
            role_id=role_id,
            created_at=now,
        )
    ]
    policies = [
        RecordPolicyRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            resource_type="order",
            role_id=role_id,
            access_scope=RecordAccessScope.OWNED,
            condition_expression=(
                '{"all":[{"attribute":"status","operator":"in","value":["draft","open"]}]}'
            ),
            created_at=now,
        )
    ]
    resource_wildcard = [
        RolePermissionRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            role_id=role_id,
            permission_code="order.*",
            created_at=now,
        )
    ]
    allowed_context = PolicyContext(
        tenant_id=tenant_id,
        subject_id=subject_id,
        record_owner_id=subject_id,
        attributes={"status": "draft"},
        timestamp=now,
    )
    assert service.authorize(
        "order.edit", "order", allowed_context, roles, resource_wildcard, assignments, (), policies
    ).allowed
    denied_context = allowed_context.model_copy(update={"record_owner_id": uuid4()})
    assert not service.authorize(
        "order.edit", "order", denied_context, roles, resource_wildcard, assignments, (), policies
    ).allowed
    global_wildcard = [resource_wildcard[0].model_copy(update={"permission_code": "*"})]
    assert not service.authorize(
        "order.edit", "order", allowed_context, roles, global_wildcard, assignments, (), policies
    ).allowed


def test_field_policy_fails_closed_for_unmatched_role_condition_and_write() -> None:
    service = PolicyEvaluationService()
    tenant_id = uuid4()
    subject_id = uuid4()
    permitted_role = uuid4()
    policy = FieldPolicyRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        resource_type="party",
        field_name="tax_identifier",
        role_id=permitted_role,
        access_type=FieldAccessType.READ,
        condition_expression=('{"all":[{"attribute":"region","operator":"eq","value":"EU"}]}'),
        created_at=datetime.now(UTC),
    )
    context = PolicyContext(
        tenant_id=tenant_id,
        subject_id=subject_id,
        attributes={"region": "EU"},
    )
    assert not service.evaluate_field_access(
        "tax_identifier", "party", context, [policy], set()
    ).allowed
    assert not service.evaluate_field_access(
        "tax_identifier",
        "party",
        context,
        [policy],
        {permitted_role},
        requested_access=FieldAccessType.WRITE,
    ).allowed
    assert not service.evaluate_field_access(
        "tax_identifier",
        "party",
        context.model_copy(update={"attributes": {"region": "US"}}),
        [policy],
        {permitted_role},
    ).allowed


def test_support_access_requires_active_explicit_tenant_grant() -> None:
    service = PolicyEvaluationService()
    tenant_id = uuid4()
    support_id = uuid4()
    now = datetime.now(UTC)
    grant = SupportAccessGrantRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        support_principal_id=support_id,
        approved_by=uuid4(),
        reason="Incident response",
        valid_from=now - timedelta(minutes=1),
        valid_to=now + timedelta(minutes=10),
        created_at=now,
    )
    context = PolicyContext(tenant_id=tenant_id, subject_id=support_id, timestamp=now)
    assert service.authorize_support_access(context, [grant]).allowed
    assert not service.authorize_support_access(
        context.model_copy(update={"timestamp": now + timedelta(hours=1)}), [grant]
    ).allowed
    assert not service.authorize_support_access(
        context, [grant.model_copy(update={"revoked_at": now})]
    ).allowed


def test_audit_v2_integrity_covers_evidence_payload() -> None:
    tenant_id = uuid4()
    now = datetime.now(UTC)
    original = compute_audit_checksum(
        tenant_id,
        now,
        "actor",
        "authorize",
        "order",
        "42",
        "denied",
        before_state={"status": "draft"},
        after_state={"status": "rejected"},
        correlation_id="correlation",
        trace_id="trace",
        decision_metadata={"policy": "deny-owner"},
        integrity_version="2",
    )
    changed = compute_audit_checksum(
        tenant_id,
        now,
        "actor",
        "authorize",
        "order",
        "42",
        "denied",
        before_state={"status": "approved"},
        after_state={"status": "rejected"},
        correlation_id="correlation",
        trace_id="trace",
        decision_metadata={"policy": "deny-owner"},
        integrity_version="2",
    )
    assert original != changed


async def test_governance_export_remains_and_v1_destructive_hook_fails_closed() -> None:
    calls: list[str] = []

    class Hook:
        async def export_tenant_data(self, tenant_id: UUID) -> dict[str, Any]:
            calls.append(f"export:{tenant_id}")
            return {"ok": True}

        async def anonymize_subject(self, tenant_id: UUID, subject_id: UUID) -> None:
            calls.append(f"anonymize:{tenant_id}:{subject_id}")

    hooks = DataGovernanceHooks()
    hook = Hook()
    hooks.register_export_hook("module", hook)
    hooks.register_anonymization_hook("module", hook)
    tenant_id = uuid4()
    subject_id = uuid4()
    assert await hooks.export_tenant_data(tenant_id) == {"module": {"ok": True}}
    with pytest.raises(PermissionError, match=r"destructive-lifecycle\.v2"):
        await hooks.anonymize_subject(tenant_id, subject_id)
    assert calls == [f"export:{tenant_id}"]
