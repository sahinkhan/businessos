"""Public contracts, domain events, and policy evaluation services."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from businessos.sdk import DomainEvent
from businessos_policy.models import (
    ApprovalAuthorityDecision,
    ApprovalLimitRecord,
    AuthorizationDecision,
    DelegationGrantRecord,
    FieldAccessDecision,
    FieldAccessType,
    FieldPolicyRecord,
    PolicyContext,
    RecordAccessScope,
    RecordPolicyRecord,
    RolePermissionRecord,
    RoleRecord,
    ScopeType,
    SegregationOfDutiesRuleRecord,
    SoDConflictResult,
    SubjectRoleAssignmentRecord,
    SupportAccessGrantRecord,
)


class RoleCreated(DomainEvent):
    event_type: ClassVar[str] = "policy.role.created.v1"
    tenant_id: UUID
    role_id: UUID
    code: str
    name: str


class RoleUpdated(DomainEvent):
    event_type: ClassVar[str] = "policy.role.updated.v1"
    tenant_id: UUID
    role_id: UUID
    name: str


class RoleDeleted(DomainEvent):
    event_type: ClassVar[str] = "policy.role.deleted.v1"
    tenant_id: UUID
    role_id: UUID


class PermissionAssignedToRole(DomainEvent):
    event_type: ClassVar[str] = "policy.permission.assignment.changed.v1"
    tenant_id: UUID
    role_id: UUID
    permission_code: str


class PermissionRevokedFromRole(DomainEvent):
    event_type: ClassVar[str] = "policy.permission.assignment.revoked.v1"
    tenant_id: UUID
    role_id: UUID
    permission_code: str


class RoleAssignedToSubject(DomainEvent):
    event_type: ClassVar[str] = "policy.role.assignment.changed.v1"
    tenant_id: UUID
    subject_id: UUID
    role_id: UUID
    scope_type: str
    scope_id: UUID | None


class RoleRevokedFromSubject(DomainEvent):
    event_type: ClassVar[str] = "policy.role.assignment.revoked.v1"
    tenant_id: UUID
    subject_id: UUID
    role_id: UUID


class DelegationGranted(DomainEvent):
    event_type: ClassVar[str] = "policy.delegation.granted.v1"
    tenant_id: UUID
    delegation_id: UUID
    delegator_id: UUID
    delegatee_id: UUID
    role_id: UUID
    valid_from: datetime
    valid_to: datetime


class DelegationRevoked(DomainEvent):
    event_type: ClassVar[str] = "policy.delegation.revoked.v1"
    tenant_id: UUID
    delegation_id: UUID
    reason: str


class SupportAccessGranted(DomainEvent):
    event_type: ClassVar[str] = "policy.support_access.granted.v1"
    tenant_id: UUID
    grant_id: UUID
    support_principal_id: UUID
    approved_by: UUID
    valid_to: datetime


class SupportAccessRevoked(DomainEvent):
    event_type: ClassVar[str] = "policy.support_access.revoked.v1"
    tenant_id: UUID
    grant_id: UUID
    reason: str


class PolicyEvaluationService:
    """Evaluate authorization, scope, field security, and approval limits deterministically."""

    version: str = "1"

    def authorize(
        self,
        action: str,
        resource: str,
        context: PolicyContext,
        roles: Sequence[RoleRecord],
        role_permissions: Sequence[RolePermissionRecord],
        assignments: Sequence[SubjectRoleAssignmentRecord],
        delegations: Sequence[DelegationGrantRecord] = (),
        record_policies: Sequence[RecordPolicyRecord] = (),
    ) -> AuthorizationDecision:
        now = context.timestamp
        active_role_ids: set[UUID] = set()

        # Direct subject assignments
        for assignment in assignments:
            if (
                assignment.tenant_id != context.tenant_id
                or assignment.subject_id != context.subject_id
            ):
                continue
            if assignment.valid_from and assignment.valid_from > now:
                continue
            if assignment.valid_to and assignment.valid_to < now:
                continue

            # Check scope match
            if assignment.scope_type == ScopeType.TENANT:
                active_role_ids.add(assignment.role_id)
            elif (
                assignment.scope_type == ScopeType.COMPANY
                and assignment.scope_id == context.company_id
            ):
                active_role_ids.add(assignment.role_id)
            elif (
                assignment.scope_type == ScopeType.LEGAL_ENTITY
                and assignment.scope_id == context.legal_entity_id
            ):
                active_role_ids.add(assignment.role_id)
            elif (
                assignment.scope_type == ScopeType.OPERATING_SITE
                and assignment.scope_id == context.operating_site_id
            ):
                active_role_ids.add(assignment.role_id)
            elif (
                assignment.scope_type == ScopeType.BUSINESS_UNIT
                and assignment.scope_id == context.business_unit_id
            ):
                active_role_ids.add(assignment.role_id)

        # Delegations
        for delegation in delegations:
            if (
                delegation.tenant_id != context.tenant_id
                or delegation.delegatee_id != context.subject_id
            ):
                continue
            if delegation.is_revoked:
                continue
            if delegation.valid_from <= now <= delegation.valid_to:
                if delegation.scope_type == ScopeType.TENANT:
                    active_role_ids.add(delegation.role_id)
                elif (
                    delegation.scope_type == ScopeType.COMPANY
                    and delegation.scope_id == context.company_id
                ):
                    active_role_ids.add(delegation.role_id)
                elif (
                    delegation.scope_type == ScopeType.LEGAL_ENTITY
                    and delegation.scope_id == context.legal_entity_id
                ):
                    active_role_ids.add(delegation.role_id)
                elif (
                    delegation.scope_type == ScopeType.OPERATING_SITE
                    and delegation.scope_id == context.operating_site_id
                ):
                    active_role_ids.add(delegation.role_id)
                elif (
                    delegation.scope_type == ScopeType.BUSINESS_UNIT
                    and delegation.scope_id == context.business_unit_id
                ):
                    active_role_ids.add(delegation.role_id)

        # Role inheritance
        role_map = {r.id: r for r in roles if r.tenant_id == context.tenant_id}
        expanded_role_ids = set(active_role_ids)
        for r_id in list(active_role_ids):
            curr = role_map.get(r_id)
            visited = {r_id}
            while curr and curr.parent_role_id and curr.parent_role_id not in visited:
                expanded_role_ids.add(curr.parent_role_id)
                visited.add(curr.parent_role_id)
                curr = role_map.get(curr.parent_role_id)

        # Match permissions
        for rp in role_permissions:
            if rp.tenant_id != context.tenant_id or rp.role_id not in expanded_role_ids:
                continue
            if rp.permission_code == action or rp.permission_code == f"{resource}.*":
                if not self._record_access_allowed(
                    resource, context, record_policies, expanded_role_ids
                ):
                    continue
                return AuthorizationDecision(
                    allowed=True,
                    reason=f"Granted by permission '{rp.permission_code}' on active role",
                    matched_policy=rp.permission_code,
                )

        return AuthorizationDecision(
            allowed=False,
            reason=(
                "Deny by default: no active role assignment grants the requested action and scope"
            ),
            matched_policy=None,
        )

    def evaluate_field_access(
        self,
        field_name: str,
        resource_type: str,
        context: PolicyContext,
        policies: Sequence[FieldPolicyRecord],
        active_role_ids: set[UUID],
        requested_access: FieldAccessType = FieldAccessType.READ,
    ) -> FieldAccessDecision:
        matching = [
            p
            for p in policies
            if p.tenant_id == context.tenant_id
            and p.resource_type == resource_type
            and p.field_name == field_name
        ]
        if not matching:
            # Default is full read access if no specific field policy exists
            return FieldAccessDecision(
                allowed=True, access_type=FieldAccessType.READ, mask_pattern=None
            )

        # Check role-specific policy first, then wildcard role
        role_policy = next((p for p in matching if p.role_id in active_role_ids), None)
        if not role_policy:
            role_policy = next((p for p in matching if p.role_id is None), None)

        if not role_policy or not _condition_matches(
            role_policy.condition_expression, context.attributes
        ):
            return FieldAccessDecision(
                allowed=False, access_type=FieldAccessType.DENY, mask_pattern=None
            )

        if role_policy.access_type == FieldAccessType.DENY:
            return FieldAccessDecision(
                allowed=False, access_type=FieldAccessType.DENY, mask_pattern=None
            )

        if (
            requested_access is FieldAccessType.WRITE
            and role_policy.access_type is not FieldAccessType.WRITE
        ):
            return FieldAccessDecision(
                allowed=False, access_type=FieldAccessType.DENY, mask_pattern=None
            )

        return FieldAccessDecision(
            allowed=True,
            access_type=role_policy.access_type,
            mask_pattern=role_policy.mask_pattern,
        )

    def _record_access_allowed(
        self,
        resource: str,
        context: PolicyContext,
        policies: Sequence[RecordPolicyRecord],
        active_role_ids: set[UUID],
    ) -> bool:
        matching = [
            policy
            for policy in policies
            if policy.tenant_id == context.tenant_id and policy.resource_type == resource
        ]
        if not matching:
            return True
        policy = next((item for item in matching if item.role_id in active_role_ids), None)
        if policy is None:
            policy = next((item for item in matching if item.role_id is None), None)
        if policy is None or not _condition_matches(
            policy.condition_expression, context.attributes
        ):
            return False
        if policy.access_scope is RecordAccessScope.DENY:
            return False
        if policy.access_scope is RecordAccessScope.ALL:
            return True
        if policy.access_scope is RecordAccessScope.OWNED:
            return context.record_owner_id == context.subject_id
        if context.record_scope_type is None or context.record_scope_id is None:
            return False
        active_scope = {
            ScopeType.COMPANY: context.company_id,
            ScopeType.LEGAL_ENTITY: context.legal_entity_id,
            ScopeType.OPERATING_SITE: context.operating_site_id,
            ScopeType.BUSINESS_UNIT: context.business_unit_id,
        }.get(context.record_scope_type)
        return active_scope is not None and active_scope == context.record_scope_id

    def evaluate_approval_authority(
        self,
        action_type: str,
        amount: Decimal,
        currency: str,
        context: PolicyContext,
        limits: Sequence[ApprovalLimitRecord],
        active_role_ids: set[UUID],
    ) -> ApprovalAuthorityDecision:
        now = context.timestamp
        max_limit = Decimal("0")
        found = False

        for limit in limits:
            if limit.tenant_id != context.tenant_id or limit.action_type != action_type:
                continue
            if limit.currency.upper() != currency.upper():
                continue
            if limit.valid_from and limit.valid_from > now:
                continue
            if limit.valid_to and limit.valid_to < now:
                continue

            # Check if assigned to subject directly or through active roles
            if limit.subject_id == context.subject_id or (
                limit.role_id and limit.role_id in active_role_ids
            ):
                found = True
                if limit.amount_limit > max_limit:
                    max_limit = limit.amount_limit

        if not found:
            return ApprovalAuthorityDecision(
                has_authority=False,
                limit=Decimal("0"),
                currency=currency,
                reason="No approval limit configured for subject or active roles",
            )

        has_authority = amount <= max_limit
        reason = (
            f"Amount {amount} {currency} is within approval limit of {max_limit} {currency}"
            if has_authority
            else f"Amount {amount} {currency} exceeds approval limit of {max_limit} {currency}"
        )
        return ApprovalAuthorityDecision(
            has_authority=has_authority,
            limit=max_limit,
            currency=currency,
            reason=reason,
        )

    def check_sod_conflict(
        self,
        candidate_permissions: set[str],
        sod_rules: Sequence[SegregationOfDutiesRuleRecord],
    ) -> SoDConflictResult:
        conflicts: list[str] = []
        for rule in sod_rules:
            if (
                rule.permission_a in candidate_permissions
                and rule.permission_b in candidate_permissions
            ):
                conflicts.append(
                    f"SoD Conflict: [{rule.code}] {rule.name} "
                    f"('{rule.permission_a}' vs '{rule.permission_b}')"
                )

        return SoDConflictResult(
            has_conflict=len(conflicts) > 0,
            conflicting_rules=conflicts,
        )

    def authorize_support_access(
        self,
        context: PolicyContext,
        grants: Sequence[SupportAccessGrantRecord],
    ) -> AuthorizationDecision:
        for grant in grants:
            if (
                grant.tenant_id == context.tenant_id
                and grant.support_principal_id == context.subject_id
                and grant.revoked_at is None
                and grant.valid_from <= context.timestamp <= grant.valid_to
            ):
                return AuthorizationDecision(
                    allowed=True,
                    reason="Explicit tenant-approved support access is active",
                    matched_policy=str(grant.id),
                )
        return AuthorizationDecision(
            allowed=False,
            reason="Deny by default: no active tenant-approved support access grant",
            matched_policy=None,
        )


type _ConditionValue = str | int | float | bool | list[str | int | float | bool | None] | None


class _ABACCondition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attribute: str
    operator: Literal["eq", "ne", "in"]
    value: _ConditionValue


class _ABACExpression(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    all: tuple[_ABACCondition, ...] = Field(min_length=1)


def _condition_matches(expression: str | None, attributes: dict[str, object]) -> bool:
    if expression is None:
        return True
    try:
        payload = _ABACExpression.model_validate_json(expression)
    except (TypeError, ValueError, ValidationError):
        return False
    for condition in payload.all:
        actual = attributes.get(condition.attribute)
        if condition.operator == "eq" and actual != condition.value:
            return False
        if condition.operator == "ne" and actual == condition.value:
            return False
        if condition.operator == "in" and (
            not isinstance(condition.value, list) or actual not in condition.value
        ):
            return False
    return True
