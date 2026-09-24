"""Policy-owned live V2 authority in a caller's active framework transaction."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar, Protocol
from uuid import UUID

from businessos_identity import (
    AuthenticatedPrincipalBinding,
    MembershipAuthority,
    PrincipalReference,
)
from sqlalchemy import Select, or_, select

from businessos.sdk import (
    BusinessOSError,
    DependencyKey,
    DomainEvent,
    HandlerTransaction,
    RequestContext,
    ResourceLocator,
    ResourceOwnerResolver,
)

from .contracts import condition_is_valid, condition_matches
from .delegation_authority import (
    PolicyDelegationActionAuthority,
    active_at,
    covers,
    scope_covers,
)
from .models import (
    APPROVAL_LIMITS,
    DELEGATIONS,
    FIELD_POLICIES,
    RECORD_POLICIES,
    ROLE_PERMISSIONS,
    ROLES,
    SUBJECT_ROLE_ASSIGNMENTS,
    SUPPORT_ACCESS_GRANTS,
    ApprovalLimitRecord,
    DelegationGrantRecord,
    FieldAccessType,
    FieldPolicyRecord,
    RecordAccessScope,
    RecordPolicyRecord,
    RoleRecord,
    ScopeType,
    SubjectRoleAssignmentRecord,
)
from .v2_contracts import (
    POLICY_CLASSIFICATION_FACTS_V2,
    AuthorizationOperationFactsV2,
    AuthorizationResourceFactsV2,
    DecisionMode,
    DecisionReason,
    PolicyClassificationFactsV2,
    PolicyCommitDecisionV2,
    PolicyDecisionEvidenceV2,
    PolicyReadDecisionV2,
)

_MAX_ROWS = 256
_MAX_ROLE_DEPTH = 16
_CLASSIFICATION_NAMESPACE = "foundation.governance.data-classification"
_CLASSIFICATION_VERSION = "2"


class _Dependencies(Protocol):
    async def resolve[T](self, key: DependencyKey[T]) -> T: ...


class PolicyDecisionRecordedV2(DomainEvent):
    event_type: ClassVar[str] = "policy.authorization.decision.v2"
    schema_version: ClassVar[int] = 2
    principal_type: str
    principal_id: UUID
    decision_at: datetime
    mode: str
    action: str
    resource_namespace: str
    resource_version: str
    record_id: UUID
    allowed: bool
    reason_code: str
    policy_ids: tuple[UUID, ...] = ()


@dataclass(slots=True)
class _CommitPermit:
    """One-use, nonserializable owner callback guard for the active transaction."""

    _service: PolicyV2Service
    _request: RequestContext
    _transaction: HandlerTransaction
    _locator: ResourceLocator
    _operation: AuthorizationOperationFactsV2
    _evidence: PolicyDecisionEvidenceV2
    _used: bool = False

    async def apply(
        self,
        operation: AuthorizationOperationFactsV2,
        owner_apply: Callable[
            [AuthorizationOperationFactsV2], Awaitable[AuthorizationOperationFactsV2]
        ],
    ) -> None:
        if self._used or type(operation) is not AuthorizationOperationFactsV2:
            raise BusinessOSError(
                "operation_mismatch", "Operation authority is invalid", status_code=403
            )
        if operation != self._operation:
            raise BusinessOSError("operation_mismatch", "Operation has changed", status_code=403)
        evidence = await self._service.revalidate_commit(
            self._request, self._transaction, self._locator, operation, self._evidence.mode
        )
        if not evidence.allowed:
            raise BusinessOSError(evidence.reason.value, "Live authority changed", status_code=403)
        self._used = True
        committed = await owner_apply(operation)
        if type(committed) is not AuthorizationOperationFactsV2 or committed != operation:
            raise BusinessOSError(
                "operation_mismatch", "Committed operation differs from authority", status_code=403
            )
        self._transaction.add_outbox(
            PolicyDecisionRecordedV2(
                tenant_id=evidence.tenant_id,
                correlation_id=self._request.correlation_id,
                principal_type=evidence.principal.principal_type,
                principal_id=evidence.principal.principal_id,
                decision_at=evidence.decision_at,
                mode=evidence.mode.value,
                action=evidence.action,
                resource_namespace=self._locator.namespace,
                resource_version=self._locator.contract_version,
                record_id=self._locator.record_id,
                allowed=True,
                reason_code=evidence.reason.value,
                policy_ids=evidence.policy_ids,
            ).to_outbox()
        )


class PolicyV2Service:
    """Live decisions; no ambient principal, supplied clock, or second UOW."""

    def __init__(
        self,
        binding: AuthenticatedPrincipalBinding,
        memberships: MembershipAuthority,
        resources: ResourceOwnerResolver,
        authority: PolicyDelegationActionAuthority,
        action_resources: Mapping[str, tuple[str, str]],
        dependencies: _Dependencies,
    ) -> None:
        self._binding = binding
        self._memberships = memberships
        self._resources = resources
        self._authority = authority
        self._action_resources = action_resources
        self._dependencies = dependencies

    def _principal(self, request: RequestContext) -> PrincipalReference:
        tenant = request.tenant
        principal = self._binding.principal
        if (
            self._binding.request is not request
            or tenant is None
            or type(tenant.tenant_id) is not UUID
            or type(tenant.principal_id) is not UUID
            or type(principal.tenant_id) is not UUID
            or type(principal.principal_id) is not UUID
            or type(principal.principal_type) is not str
            or tenant.tenant_id != principal.tenant_id
            or tenant.principal_id != principal.principal_id
            or principal.principal_type not in ("user", "service_account", "device")
        ):
            raise BusinessOSError(
                "principal_mismatch", "Trusted typed principal required", status_code=403
            )
        if principal.principal_type == "user":
            return PrincipalReference("user", principal.principal_id)
        if principal.principal_type == "service_account":
            return PrincipalReference("service_account", principal.principal_id)
        return PrincipalReference("device", principal.principal_id)

    async def revalidate_commit(
        self,
        request: RequestContext,
        transaction: HandlerTransaction,
        locator: ResourceLocator,
        operation: AuthorizationOperationFactsV2,
        mode: DecisionMode,
    ) -> PolicyDecisionEvidenceV2:
        return (
            await self._commit_decision(request, transaction, operation, locator, mode)
        ).evidence

    @staticmethod
    def _evidence(
        request: RequestContext,
        principal: PrincipalReference,
        instant: datetime,
        mode: DecisionMode,
        action: str,
        locator: ResourceLocator | None,
        reason: DecisionReason,
        policy_ids: tuple[UUID, ...] = (),
    ) -> PolicyDecisionEvidenceV2:
        assert request.tenant is not None
        return PolicyDecisionEvidenceV2(
            tenant_id=request.tenant.tenant_id,
            principal=principal,
            decision_at=instant,
            mode=mode,
            action=action,
            locator=locator,
            allowed=reason is DecisionReason.ALLOWED,
            reason=reason,
            policy_ids=policy_ids,
        )

    async def _lock_current_membership(
        self,
        transaction: HandlerTransaction,
        tenant_id: UUID,
        principal: PrincipalReference,
    ) -> datetime:
        _, instant = await self._memberships.lock_current(
            transaction.persistence, tenant_id, principal
        )
        return instant

    async def _begin(
        self,
        request: RequestContext,
        transaction: HandlerTransaction,
        action: str,
        locator: ResourceLocator,
        *,
        commit_bound: bool = False,
    ) -> tuple[PrincipalReference, datetime, AuthorizationResourceFactsV2 | None, DecisionReason]:
        principal = self._principal(request)
        tenant = request.tenant
        assert tenant is not None
        if (
            type(action) is not str
            or type(locator) is not ResourceLocator
            or locator.tenant_id != tenant.tenant_id
        ):
            raise BusinessOSError(
                "resource_fact_mismatch", "Canonical locator required", status_code=403
            )
        try:
            binding = self._resources.resolve_owner(locator.namespace, locator.contract_version)
            canonical = ResourceLocator(
                binding.ownership.resource_namespace,
                locator.contract_version,
                locator.record_id,
                locator.tenant_id,
            )
            mapped = self._action_resources.get(action)
            if mapped is None or mapped != (canonical.namespace, canonical.contract_version):
                return principal, datetime.now(UTC), None, DecisionReason.ACTION_UNMAPPED
            if commit_bound:
                self._resources.assert_owner_handler(canonical, request, transaction)
            admitted = await self._resources.resolve_provider(
                canonical, "facts", request, transaction
            )
            facts = AuthorizationResourceFactsV2.from_owner(
                await admitted.read_locked_facts(action),
                canonical,
                binding.ownership.owner_module_id,
            )
        except Exception:
            return principal, datetime.now(UTC), None, DecisionReason.OWNER_UNAVAILABLE
        # ADR-010/011 tenant lock precedes Identity and Policy authority rows.
        # The owner must already hold its record lock for a commit-bound call.
        await self._authority.acquire(tenant.tenant_id, transaction.persistence)
        # A wait on the owner or tenant lock must not revive expired authority.
        try:
            instant = await self._lock_current_membership(transaction, tenant.tenant_id, principal)
        except BusinessOSError:
            return principal, datetime.now(UTC), facts, DecisionReason.INACTIVE_MEMBERSHIP
        return principal, instant, facts, DecisionReason.ALLOWED

    @staticmethod
    async def _rows(
        transaction: HandlerTransaction, statement: Select[Any]
    ) -> list[dict[str, object]]:
        result = await transaction.persistence.execute(statement.limit(_MAX_ROWS + 1))
        rows = [dict(row) for row in result.mappings()]
        if len(rows) > _MAX_ROWS:
            raise BusinessOSError(
                "authority_unbounded", "Policy authority set is too large", status_code=403
            )
        return rows

    @staticmethod
    def _scope_matches(
        scope_type: ScopeType, scope_id: UUID | None, facts: AuthorizationResourceFactsV2
    ) -> bool:
        if scope_type is ScopeType.TENANT:
            return scope_id is None
        value = {
            ScopeType.COMPANY: facts.company_id,
            ScopeType.LEGAL_ENTITY: facts.legal_entity_id,
            ScopeType.OPERATING_SITE: facts.operating_site_id,
            ScopeType.BUSINESS_UNIT: facts.business_unit_id,
        }.get(scope_type)
        return value is not None and scope_id == value

    async def _delegation_source(
        self,
        transaction: HandlerTransaction,
        tenant_id: UUID,
        grant: DelegationGrantRecord,
        instant: datetime,
        visited: frozenset[tuple[str, UUID]],
        budget: list[int],
    ) -> bool:
        budget[0] += 1
        if budget[0] > _MAX_ROWS:
            raise BusinessOSError(
                "authority_unbounded", "Delegation authority is too large", status_code=403
            )
        principal = (grant.delegator_type or "", grant.delegator_id)
        if (
            len(visited) >= _MAX_ROLE_DEPTH
            or principal in visited
            or grant.delegator_type not in ("user", "service_account", "device")
        ):
            return False
        if grant.delegator_type == "user":
            source = PrincipalReference("user", grant.delegator_id)
        elif grant.delegator_type == "service_account":
            source = PrincipalReference("service_account", grant.delegator_id)
        else:
            source = PrincipalReference("device", grant.delegator_id)
        try:
            record, _ = await self._memberships.lock_current(
                transaction.persistence, tenant_id, source
            )
        except BusinessOSError:
            return False
        if not record.is_effective(instant):
            return False
        assignments = await self._rows(
            transaction,
            select(SUBJECT_ROLE_ASSIGNMENTS).where(
                SUBJECT_ROLE_ASSIGNMENTS.c.tenant_id == tenant_id,
                SUBJECT_ROLE_ASSIGNMENTS.c.subject_id == grant.delegator_id,
                SUBJECT_ROLE_ASSIGNMENTS.c.subject_type == grant.delegator_type,
                SUBJECT_ROLE_ASSIGNMENTS.c.role_id == grant.role_id,
            ),
        )
        for raw in assignments:
            assignment = SubjectRoleAssignmentRecord.model_validate(raw)
            if (
                scope_covers(
                    assignment.scope_type, assignment.scope_id, grant.scope_type, grant.scope_id
                )
                and active_at(assignment.valid_from, assignment.valid_to, instant)
                and covers(
                    assignment.valid_from,
                    assignment.valid_to,
                    grant.valid_from,
                    grant.valid_to,
                )
            ):
                return True
        parents = await self._rows(
            transaction,
            select(DELEGATIONS).where(
                DELEGATIONS.c.tenant_id == tenant_id,
                DELEGATIONS.c.delegatee_id == grant.delegator_id,
                DELEGATIONS.c.delegatee_type == grant.delegator_type,
                DELEGATIONS.c.role_id == grant.role_id,
                DELEGATIONS.c.is_revoked.is_(False),
            ),
        )
        for raw in parents:
            parent = DelegationGrantRecord.model_validate(raw)
            if (
                scope_covers(parent.scope_type, parent.scope_id, grant.scope_type, grant.scope_id)
                and active_at(parent.valid_from, parent.valid_to, instant)
                and covers(parent.valid_from, parent.valid_to, grant.valid_from, grant.valid_to)
                and await self._delegation_source(
                    transaction, tenant_id, parent, instant, visited | {principal}, budget
                )
            ):
                return True
        return False

    async def _active_roles(
        self,
        transaction: HandlerTransaction,
        tenant_id: UUID,
        principal: PrincipalReference,
        instant: datetime,
        facts: AuthorizationResourceFactsV2,
    ) -> set[UUID]:
        assignments = await self._rows(
            transaction,
            select(SUBJECT_ROLE_ASSIGNMENTS).where(
                SUBJECT_ROLE_ASSIGNMENTS.c.tenant_id == tenant_id,
                SUBJECT_ROLE_ASSIGNMENTS.c.subject_id == principal.principal_id,
                SUBJECT_ROLE_ASSIGNMENTS.c.subject_type == principal.principal_type,
            ),
        )
        role_ids = {
            row.role_id
            for raw in assignments
            if (row := SubjectRoleAssignmentRecord.model_validate(raw))
            and active_at(row.valid_from, row.valid_to, instant)
            and self._scope_matches(row.scope_type, row.scope_id, facts)
        }
        grants = await self._rows(
            transaction,
            select(DELEGATIONS).where(
                DELEGATIONS.c.tenant_id == tenant_id,
                DELEGATIONS.c.delegatee_id == principal.principal_id,
                DELEGATIONS.c.delegatee_type == principal.principal_type,
                DELEGATIONS.c.is_revoked.is_(False),
            ),
        )
        budget = [0]
        for raw in grants:
            grant = DelegationGrantRecord.model_validate(raw)
            if (
                active_at(grant.valid_from, grant.valid_to, instant)
                and self._scope_matches(grant.scope_type, grant.scope_id, facts)
                and await self._delegation_source(
                    transaction,
                    tenant_id,
                    grant,
                    instant,
                    frozenset({(principal.principal_type, principal.principal_id)}),
                    budget,
                )
            ):
                role_ids.add(grant.role_id)
        frontier = set(role_ids)
        for _ in range(_MAX_ROLE_DEPTH):
            if not frontier:
                return role_ids
            rows = await self._rows(
                transaction,
                select(ROLES).where(ROLES.c.tenant_id == tenant_id, ROLES.c.id.in_(frontier)),
            )
            parents = {
                role.parent_role_id
                for raw in rows
                if (role := RoleRecord.model_validate(raw)).parent_role_id is not None
            }
            frontier = parents - role_ids
            role_ids.update(frontier)
        if frontier:
            raise BusinessOSError(
                "authority_unbounded", "Role hierarchy is too deep", status_code=403
            )
        return role_ids

    @staticmethod
    def _record_scope_allowed(
        policy: RecordPolicyRecord,
        facts: AuthorizationResourceFactsV2,
        principal: PrincipalReference,
        request: RequestContext,
    ) -> bool:
        if policy.access_scope is RecordAccessScope.DENY:
            return False
        if policy.access_scope is RecordAccessScope.ALL:
            return True
        if policy.access_scope is RecordAccessScope.OWNED:
            return (
                facts.record_owner_id == principal.principal_id
                and facts.record_owner_type == principal.principal_type
            )
        tenant = request.tenant
        if tenant is None:
            return False
        scoped = (
            (facts.company_id, tenant.active_company_id),
            (facts.legal_entity_id, tenant.legal_entity_id),
            (facts.operating_site_id, tenant.operating_site_id),
            (facts.business_unit_id, tenant.business_unit_id),
        )
        return any(owner is not None for owner, _ in scoped) and all(
            owner is None or owner == active for owner, active in scoped
        )

    async def _authorize(
        self,
        request: RequestContext,
        transaction: HandlerTransaction,
        principal: PrincipalReference,
        instant: datetime,
        facts: AuthorizationResourceFactsV2,
        action: str,
    ) -> tuple[DecisionReason, tuple[UUID, ...], set[UUID]]:
        tenant_id = facts.tenant_id
        role_ids = await self._active_roles(transaction, tenant_id, principal, instant, facts)
        if not role_ids:
            return DecisionReason.NO_ACTIVE_ROLE, (), role_ids
        permissions = await self._rows(
            transaction,
            select(ROLE_PERMISSIONS).where(
                ROLE_PERMISSIONS.c.tenant_id == tenant_id,
                ROLE_PERMISSIONS.c.role_id.in_(role_ids),
                ROLE_PERMISSIONS.c.permission_code.in_((action, f"{facts.namespace}.*")),
            ),
        )
        if not permissions:
            return DecisionReason.NO_ACTIVE_ROLE, (), role_ids
        policies = await self._rows(
            transaction,
            select(RECORD_POLICIES).where(
                RECORD_POLICIES.c.tenant_id == tenant_id,
                RECORD_POLICIES.c.resource_type == facts.namespace,
                or_(
                    RECORD_POLICIES.c.role_id.is_(None),
                    RECORD_POLICIES.c.role_id.in_(role_ids),
                ),
            ),
        )
        if not policies:
            return DecisionReason.ALLOWED, (), role_ids
        relevant = [
            RecordPolicyRecord.model_validate(raw)
            for raw in policies
            if raw["role_id"] is None or raw["role_id"] in role_ids
        ]
        if any(not condition_is_valid(policy.condition_expression) for policy in relevant):
            return DecisionReason.RECORD_DENIED, (), role_ids
        attributes = dict(facts.attributes)
        for policy in relevant:
            if policy.access_scope is RecordAccessScope.DENY and condition_matches(
                policy.condition_expression, attributes
            ):
                return DecisionReason.RECORD_DENIED, (policy.id,), role_ids
        for policy in relevant:
            if condition_matches(
                policy.condition_expression, attributes
            ) and self._record_scope_allowed(policy, facts, principal, request):
                return DecisionReason.ALLOWED, (policy.id,), role_ids
        return DecisionReason.RECORD_DENIED, (), role_ids

    @staticmethod
    def _canonical_locator(facts: AuthorizationResourceFactsV2) -> ResourceLocator:
        return ResourceLocator(
            facts.namespace, facts.contract_version, facts.record_id, facts.tenant_id
        )

    async def authorize_read(
        self,
        request: RequestContext,
        transaction: HandlerTransaction,
        action: str,
        locator: ResourceLocator,
        *,
        mode: DecisionMode = DecisionMode.READ,
    ) -> PolicyReadDecisionV2:
        if mode not in (DecisionMode.READ, DecisionMode.PRESENTATION):
            raise BusinessOSError(
                "invalid_mode", "Read evaluation cannot authorize commit", status_code=403
            )
        principal, instant, facts, reason = await self._begin(request, transaction, action, locator)
        refs: tuple[UUID, ...] = ()
        if reason is DecisionReason.ALLOWED and facts is not None:
            reason, refs, _ = await self._authorize(
                request, transaction, principal, instant, facts, action
            )
        return PolicyReadDecisionV2(
            self._evidence(
                request,
                principal,
                instant,
                mode,
                action,
                self._canonical_locator(facts) if facts is not None else locator,
                reason,
                refs,
            )
        )

    async def authorize_support_access(
        self, request: RequestContext, transaction: HandlerTransaction
    ) -> PolicyReadDecisionV2:
        principal = self._principal(request)
        tenant = request.tenant
        assert tenant is not None
        await self._authority.acquire(tenant.tenant_id, transaction.persistence)
        try:
            instant = await self._lock_current_membership(transaction, tenant.tenant_id, principal)
        except BusinessOSError:
            instant = datetime.now(UTC)
            reason = DecisionReason.INACTIVE_MEMBERSHIP
        else:
            rows = await self._rows(
                transaction,
                select(SUPPORT_ACCESS_GRANTS).where(
                    SUPPORT_ACCESS_GRANTS.c.tenant_id == tenant.tenant_id,
                    SUPPORT_ACCESS_GRANTS.c.support_principal_id == principal.principal_id,
                    SUPPORT_ACCESS_GRANTS.c.support_principal_type == principal.principal_type,
                    SUPPORT_ACCESS_GRANTS.c.approved_by_type.is_not(None),
                    SUPPORT_ACCESS_GRANTS.c.revoked_at.is_(None),
                    SUPPORT_ACCESS_GRANTS.c.valid_from <= instant,
                    SUPPORT_ACCESS_GRANTS.c.valid_to > instant,
                ),
            )
            reason = DecisionReason.ALLOWED if rows else DecisionReason.SUPPORT_GRANT_MISSING
        return PolicyReadDecisionV2(
            self._evidence(
                request, principal, instant, DecisionMode.READ, "support.access", None, reason
            )
        )

    async def authorize_mutation(
        self,
        request: RequestContext,
        transaction: HandlerTransaction,
        operation: AuthorizationOperationFactsV2,
        locator: ResourceLocator,
    ) -> PolicyCommitDecisionV2:
        return await self._commit_decision(
            request, transaction, operation, locator, DecisionMode.MUTATION
        )

    async def evaluate_approval(
        self,
        request: RequestContext,
        transaction: HandlerTransaction,
        operation: AuthorizationOperationFactsV2,
        locator: ResourceLocator,
    ) -> PolicyCommitDecisionV2:
        return await self._commit_decision(
            request, transaction, operation, locator, DecisionMode.APPROVAL
        )

    async def _commit_decision(
        self,
        request: RequestContext,
        transaction: HandlerTransaction,
        operation: AuthorizationOperationFactsV2,
        locator: ResourceLocator,
        mode: DecisionMode,
    ) -> PolicyCommitDecisionV2:
        if type(operation) is not AuthorizationOperationFactsV2:
            raise BusinessOSError(
                "operation_mismatch", "Normalized operation required", status_code=403
            )
        principal, instant, facts, reason = await self._begin(
            request, transaction, operation.action, locator, commit_bound=True
        )
        refs: tuple[UUID, ...] = ()
        roles: set[UUID] = set()
        if reason is DecisionReason.ALLOWED and facts is not None:
            reason, refs, roles = await self._authorize(
                request, transaction, principal, instant, facts, operation.action
            )
        if (
            reason is DecisionReason.ALLOWED
            and facts is not None
            and facts.normalized_operation != operation
        ):
            reason = DecisionReason.OPERATION_MISMATCH
        if reason is DecisionReason.ALLOWED and mode is DecisionMode.APPROVAL:
            reason, limit_refs = await self._approval_limit(
                transaction, facts, operation, roles, instant
            )
            refs += limit_refs
        canonical = self._canonical_locator(facts) if facts is not None else locator
        evidence = self._evidence(
            request, principal, instant, mode, operation.action, canonical, reason, refs
        )
        if reason is not DecisionReason.ALLOWED or facts is None:
            return PolicyCommitDecisionV2(evidence, None)
        return PolicyCommitDecisionV2(
            evidence,
            _CommitPermit(self, request, transaction, canonical, operation, evidence),
        )

    async def _approval_limit(
        self,
        transaction: HandlerTransaction,
        facts: AuthorizationResourceFactsV2 | None,
        operation: AuthorizationOperationFactsV2,
        role_ids: set[UUID],
        instant: datetime,
    ) -> tuple[DecisionReason, tuple[UUID, ...]]:
        if facts is None or operation.amount is None or operation.currency is None:
            return DecisionReason.APPROVAL_LIMIT_MISSING, ()
        limits = await self._rows(
            transaction,
            select(APPROVAL_LIMITS).where(
                APPROVAL_LIMITS.c.tenant_id == facts.tenant_id,
                APPROVAL_LIMITS.c.action_type == operation.action,
                APPROVAL_LIMITS.c.role_id.in_(role_ids),
            ),
        )
        live = [
            limit
            for raw in limits
            if (limit := ApprovalLimitRecord.model_validate(raw)).subject_id is None
            and active_at(limit.valid_from, limit.valid_to, instant)
        ]
        if not live:
            return DecisionReason.APPROVAL_LIMIT_MISSING, ()
        currency_matches = [item for item in live if item.currency == operation.currency]
        if not currency_matches:
            return DecisionReason.CURRENCY_MISMATCH, ()
        allowed = [item for item in currency_matches if operation.amount <= item.amount_limit]
        if not allowed:
            return DecisionReason.APPROVAL_LIMIT_EXCEEDED, tuple(
                item.id for item in currency_matches
            )
        selected = min(allowed, key=lambda item: item.id.bytes)
        return DecisionReason.ALLOWED, (selected.id,)

    async def evaluate_field(
        self,
        request: RequestContext,
        transaction: HandlerTransaction,
        locator: ResourceLocator,
        field_name: str,
        requested_access: FieldAccessType = FieldAccessType.READ,
    ) -> PolicyReadDecisionV2:
        if (
            type(field_name) is not str
            or not field_name
            or requested_access
            not in (
                FieldAccessType.READ,
                FieldAccessType.WRITE,
            )
        ):
            raise BusinessOSError("field_not_allowed", "Invalid field request", status_code=403)
        action = f"field.{requested_access.value}"
        principal, instant, facts, reason = await self._begin(request, transaction, action, locator)
        access = FieldAccessType.DENY
        refs: tuple[UUID, ...] = ()
        role_ids: set[UUID] = set()
        if reason is DecisionReason.ALLOWED and facts is not None:
            reason, refs, role_ids = await self._authorize(
                request, transaction, principal, instant, facts, action
            )
        if reason is DecisionReason.ALLOWED and facts is not None:
            classification_ref = facts.field_classifications.get(field_name)
            if classification_ref is None:
                reason = DecisionReason.CLASSIFICATION_UNAVAILABLE
            else:
                classification = await self._classification(
                    transaction, facts.tenant_id, classification_ref, instant, request
                )
                if classification is None:
                    reason = DecisionReason.CLASSIFICATION_UNAVAILABLE
                else:
                    policies = await self._rows(
                        transaction,
                        select(FIELD_POLICIES).where(
                            FIELD_POLICIES.c.tenant_id == facts.tenant_id,
                            FIELD_POLICIES.c.resource_type == facts.namespace,
                            FIELD_POLICIES.c.field_name == field_name,
                            or_(
                                FIELD_POLICIES.c.role_id.is_(None),
                                FIELD_POLICIES.c.role_id.in_(role_ids),
                            ),
                        ),
                    )
                    matching = [
                        FieldPolicyRecord.model_validate(raw)
                        for raw in policies
                        if raw["role_id"] is None or raw["role_id"] in role_ids
                    ]
                    if any(
                        not condition_is_valid(policy.condition_expression) for policy in matching
                    ):
                        reason = DecisionReason.FIELD_NOT_ALLOWED
                        matching = []
                    for policy in matching:
                        if policy.access_type is FieldAccessType.DENY and condition_matches(
                            policy.condition_expression, dict(facts.attributes)
                        ):
                            refs = (policy.id,)
                            break
                    else:
                        allowed = [
                            policy
                            for policy in matching
                            if policy.access_type is not FieldAccessType.DENY
                            and condition_matches(
                                policy.condition_expression, dict(facts.attributes)
                            )
                            and (
                                requested_access is FieldAccessType.READ
                                or policy.access_type is FieldAccessType.WRITE
                            )
                        ]
                        if allowed:
                            selected = min(allowed, key=lambda item: item.id.bytes)
                            access = selected.access_type
                            refs = (selected.id, classification.definition_id)
                            reason = DecisionReason.ALLOWED
                        else:
                            reason = DecisionReason.FIELD_NOT_ALLOWED
                    if access is FieldAccessType.DENY:
                        reason = DecisionReason.FIELD_NOT_ALLOWED
        return PolicyReadDecisionV2(
            self._evidence(
                request,
                principal,
                instant,
                DecisionMode.READ,
                action,
                self._canonical_locator(facts) if facts is not None else locator,
                reason,
                refs,
            ),
            access,
        )

    async def _classification(
        self,
        transaction: HandlerTransaction,
        tenant_id: UUID,
        reference: str,
        instant: datetime,
        request: RequestContext,
    ) -> PolicyClassificationFactsV2 | None:
        try:
            provider = await self._dependencies.resolve(POLICY_CLASSIFICATION_FACTS_V2)
            result = await provider.resolve(tenant_id, reference, instant, transaction)
            if (
                type(result) is not PolicyClassificationFactsV2
                or result.tenant_id != tenant_id
                or result.classification_ref != reference
                or not result.active
                or result.ambiguous
            ):
                return None
            binding = self._resources.resolve_owner(
                _CLASSIFICATION_NAMESPACE, _CLASSIFICATION_VERSION
            )
            if result.owner_module_id != binding.ownership.owner_module_id:
                return None
            locator = ResourceLocator(
                _CLASSIFICATION_NAMESPACE, _CLASSIFICATION_VERSION, result.definition_id, tenant_id
            )
            admitted = await self._resources.resolve_provider(
                locator, "facts", request, transaction
            )
            owner = await admitted.read_locked_facts("classification.read")
            if (
                owner.facts.get("classification_ref") != reference
                or owner.facts.get("definition_version") != result.definition_version
                or owner.facts.get("active") is not True
                or owner.facts.get("sensitive") is not result.sensitive
            ):
                return None
            return result
        except Exception:
            return None
