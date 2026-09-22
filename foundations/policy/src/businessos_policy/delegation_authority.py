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
        first = max(request.evaluated_at, request.valid_from)
        last = request.valid_until

        roles_result = await persistence.execute(
            select(ROLES).where(ROLES.c.tenant_id == request.tenant_id)
        )
        roles = [RoleRecord.model_validate(dict(row)) for row in roles_result.mappings()]
        assignments_result = await persistence.execute(
            select(SUBJECT_ROLE_ASSIGNMENTS).where(
                SUBJECT_ROLE_ASSIGNMENTS.c.tenant_id == request.tenant_id,
                SUBJECT_ROLE_ASSIGNMENTS.c.subject_id == request.grantor_principal_id,
                SUBJECT_ROLE_ASSIGNMENTS.c.subject_type == request.grantor_principal_type,
            )
        )
        assignments = [
            SubjectRoleAssignmentRecord.model_validate(dict(row))
            for row in assignments_result.mappings()
            if _covers(row["valid_from"], row["valid_to"], first, last)
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
                DELEGATIONS.c.delegatee_id == request.grantor_principal_id,
                DELEGATIONS.c.delegatee_type == request.grantor_principal_type,
                DELEGATIONS.c.delegator_type.is_not(None),
                DELEGATIONS.c.is_revoked.is_(False),
            )
        )
        delegations = [
            DelegationGrantRecord.model_validate(dict(row))
            for row in delegations_result.mappings()
            if _covers(row["valid_from"], row["valid_to"], first, last)
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
            timestamp=first.astimezone(UTC),
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
