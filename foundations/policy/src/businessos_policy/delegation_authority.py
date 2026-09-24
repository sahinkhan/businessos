"""Policy-owned implementation of Organization's delegation authority port."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from types import MappingProxyType
from uuid import UUID

from businessos_organization import (
    DelegationActionDecision,
    DelegationAuthorityRequest,
    OrganizationScopeType,
)
from sqlalchemy import select, text

from businessos.sdk import TransactionalPersistence

from .contracts import PolicyEvaluationService
from .models import (
    DELEGATIONS,
    RECORD_POLICIES,
    ROLE_PERMISSIONS,
    ROLES,
    SUBJECT_ROLE_ASSIGNMENTS,
    DelegationGrantRecord,
    PolicyContext,
    RecordPolicyRecord,
    RolePermissionRecord,
    RoleRecord,
    ScopeType,
    SubjectRoleAssignmentRecord,
)

_LOCK_DOMAIN = b"businessos.policy.authority.v1\0"
_DEFAULT_ACTION_RESOURCES: Mapping[str, str] = {
    "organization.read": "organization",
    "organization.manage": "organization",
}
_TARGET_TYPES = {
    OrganizationScopeType.COMPANY: ScopeType.COMPANY,
    OrganizationScopeType.LEGAL_ENTITY: ScopeType.LEGAL_ENTITY,
    OrganizationScopeType.OPERATING_SITE: ScopeType.OPERATING_SITE,
}


def authority_lock_key(tenant_id: UUID) -> int:
    """ADR-010's deterministic, signed tenant authority key."""
    return int.from_bytes(
        hashlib.sha256(_LOCK_DOMAIN + tenant_id.bytes).digest()[:8], "big", signed=True
    )


def _scope_covers(
    source_type: ScopeType,
    source_id: UUID | None,
    target_type: ScopeType,
    target_id: UUID | None,
) -> bool:
    # These are the Policy evaluator's existing scope rules: tenant-wide or
    # the same concrete scope. Policy does not infer Organization lineage.
    return (source_type is ScopeType.TENANT and source_id is None) or (
        source_type is target_type and source_id is not None and source_id == target_id
    )


def has_effective_role_source(
    *,
    tenant_id: UUID,
    subject_id: UUID,
    subject_type: str,
    role_id: UUID,
    scope_type: ScopeType,
    scope_id: UUID | None,
    valid_from: datetime,
    valid_until: datetime,
    evaluated_at: datetime,
    assignments: list[SubjectRoleAssignmentRecord],
    delegations: list[DelegationGrantRecord],
    visited: frozenset[tuple[str, UUID]] = frozenset(),
) -> bool:
    """Prove a same-role, currently live Policy path for the whole grant window."""
    principal = (subject_type, subject_id)
    if principal in visited or len(visited) > 16:
        return False
    path = visited | {principal}
    for assignment in assignments:
        if (
            assignment.tenant_id == tenant_id
            and assignment.subject_id == subject_id
            and assignment.subject_type == subject_type
            and assignment.role_id == role_id
            and _scope_covers(assignment.scope_type, assignment.scope_id, scope_type, scope_id)
            and _active_at(assignment.valid_from, assignment.valid_to, evaluated_at)
            and _covers(assignment.valid_from, assignment.valid_to, valid_from, valid_until)
        ):
            return True
    for grant in delegations:
        if (
            grant.tenant_id != tenant_id
            or grant.delegatee_id != subject_id
            or grant.delegatee_type != subject_type
            or grant.delegator_type not in {"user", "service_account", "device"}
            or grant.role_id != role_id
            or grant.is_revoked
            or not _scope_covers(grant.scope_type, grant.scope_id, scope_type, scope_id)
            or not _active_at(grant.valid_from, grant.valid_to, evaluated_at)
            or not _covers(grant.valid_from, grant.valid_to, valid_from, valid_until)
        ):
            continue
        if has_effective_role_source(
            tenant_id=tenant_id,
            subject_id=grant.delegator_id,
            subject_type=grant.delegator_type,
            role_id=role_id,
            scope_type=grant.scope_type,
            scope_id=grant.scope_id,
            valid_from=grant.valid_from,
            valid_until=grant.valid_to,
            evaluated_at=evaluated_at,
            assignments=assignments,
            delegations=delegations,
            visited=path,
        ):
            return True
    return False


class PolicyDelegationActionAuthority:
    """Fail-closed action decisions using the caller's active transaction."""

    def __init__(self, action_resources: Mapping[str, str] | None = None) -> None:
        mapping = dict(_DEFAULT_ACTION_RESOURCES)
        if action_resources is not None:
            for action, resource in action_resources.items():
                if action in mapping and mapping[action] != resource:
                    raise ValueError("Conflicting Policy action/resource registration")
                mapping[action] = resource
        if any(
            not action or "*" in action or not resource or "*" in resource
            for action, resource in mapping.items()
        ):
            raise ValueError("Invalid Policy action/resource registration")
        self._resources = MappingProxyType(mapping)
        self._evaluator = PolicyEvaluationService()

    async def acquire(self, tenant_id: UUID, persistence: TransactionalPersistence) -> None:
        if type(tenant_id) is not UUID or tenant_id.int == 0:
            raise ValueError("Trusted tenant ID is required")
        await persistence.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": authority_lock_key(tenant_id)}
        )

    async def allows(
        self, request: DelegationAuthorityRequest, persistence: TransactionalPersistence
    ) -> bool:
        return (await self.evaluate(request, persistence)).allowed

    async def evaluate(
        self, request: DelegationAuthorityRequest, persistence: TransactionalPersistence
    ) -> DelegationActionDecision:
        if (
            type(request.tenant_id) is not UUID
            or request.tenant_id.int == 0
            or type(request.grantor_principal_id) is not UUID
            or request.grantor_principal_type not in {"user", "service_account", "device"}
            or request.grantor_principal_id.int == 0
            or request.evaluated_at.tzinfo is None
            or request.valid_from.tzinfo is None
            or request.valid_until.tzinfo is None
            or request.valid_until <= request.valid_from
            or request.valid_until <= request.evaluated_at
        ):
            return DelegationActionDecision(False)
        resource = self._resources.get(request.action)
        scope = _TARGET_TYPES.get(request.scope_type)
        if resource is None or scope is None or request.scope_id.int == 0:
            return DelegationActionDecision(False)

        # Reacquiring the same xact lock is safe and proves the decision reads
        # cannot precede serialization, including calls by other consumers.
        await self.acquire(request.tenant_id, persistence)
        first = request.valid_from
        last = request.valid_until
        # The same grant must authorize now and cover the full proposed
        # interval; interval coverage alone would admit future-only authority.

        roles_result = await persistence.execute(
            select(ROLES).where(ROLES.c.tenant_id == request.tenant_id)
        )
        roles = [RoleRecord.model_validate(dict(row)) for row in roles_result.mappings()]
        assignments_result = await persistence.execute(
            select(SUBJECT_ROLE_ASSIGNMENTS).where(
                SUBJECT_ROLE_ASSIGNMENTS.c.tenant_id == request.tenant_id
            )
        )
        all_assignments = [
            SubjectRoleAssignmentRecord.model_validate(dict(row))
            for row in assignments_result.mappings()
        ]
        assignments = [
            assignment
            for assignment in all_assignments
            if assignment.subject_id == request.grantor_principal_id
            and assignment.subject_type == request.grantor_principal_type
            and _active_at(assignment.valid_from, assignment.valid_to, request.evaluated_at)
            and _covers(assignment.valid_from, assignment.valid_to, first, last)
        ]
        permissions_result = await persistence.execute(
            select(ROLE_PERMISSIONS).where(ROLE_PERMISSIONS.c.tenant_id == request.tenant_id)
        )
        permissions = [
            RolePermissionRecord.model_validate(dict(row)) for row in permissions_result.mappings()
        ]
        delegations_result = await persistence.execute(
            select(DELEGATIONS).where(
                DELEGATIONS.c.tenant_id == request.tenant_id,
                DELEGATIONS.c.is_revoked.is_(False),
            )
        )
        all_delegations = [
            DelegationGrantRecord.model_validate(dict(row)) for row in delegations_result.mappings()
        ]
        delegations = [
            grant
            for grant in all_delegations
            if grant.delegatee_id == request.grantor_principal_id
            and grant.delegatee_type == request.grantor_principal_type
            and grant.delegator_type in {"user", "service_account", "device"}
            and _scope_covers(grant.scope_type, grant.scope_id, scope, request.scope_id)
            and _active_at(grant.valid_from, grant.valid_to, request.evaluated_at)
            and _covers(grant.valid_from, grant.valid_to, first, last)
            and has_effective_role_source(
                tenant_id=request.tenant_id,
                subject_id=grant.delegator_id,
                subject_type=grant.delegator_type,
                role_id=grant.role_id,
                scope_type=grant.scope_type,
                scope_id=grant.scope_id,
                valid_from=grant.valid_from,
                valid_until=grant.valid_to,
                evaluated_at=request.evaluated_at,
                assignments=all_assignments,
                delegations=all_delegations,
            )
        ]
        policies_result = await persistence.execute(
            select(RECORD_POLICIES).where(
                RECORD_POLICIES.c.tenant_id == request.tenant_id,
                RECORD_POLICIES.c.resource_type == resource,
            )
        )
        policies = [
            RecordPolicyRecord.model_validate(dict(row)) for row in policies_result.mappings()
        ]
        context = PolicyContext(
            tenant_id=request.tenant_id,
            subject_id=request.grantor_principal_id,
            company_id=request.scope_id if scope is ScopeType.COMPANY else None,
            legal_entity_id=request.scope_id if scope is ScopeType.LEGAL_ENTITY else None,
            operating_site_id=request.scope_id if scope is ScopeType.OPERATING_SITE else None,
            record_scope_type=scope,
            record_scope_id=request.scope_id,
            timestamp=request.evaluated_at.astimezone(UTC),
        )
        decision = self._evaluator.authorize(
            request.action,
            resource,
            context,
            roles,
            permissions,
            assignments,
            delegations,
            policies,
        )
        return DelegationActionDecision(decision.allowed, decision.matched_policy)


def _covers(start: datetime | None, end: datetime | None, first: datetime, last: datetime) -> bool:
    return (start is None or start <= first) and (end is None or end >= last)


def _active_at(start: datetime | None, end: datetime | None, instant: datetime) -> bool:
    return (start is None or start <= instant) and (end is None or instant < end)


def scope_covers(
    source_type: ScopeType,
    source_id: UUID | None,
    target_type: ScopeType,
    target_id: UUID | None,
) -> bool:
    return _scope_covers(source_type, source_id, target_type, target_id)


def covers(start: datetime | None, end: datetime | None, first: datetime, last: datetime) -> bool:
    return _covers(start, end, first, last)


def active_at(start: datetime | None, end: datetime | None, instant: datetime) -> bool:
    return _active_at(start, end, instant)
