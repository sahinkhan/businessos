"""Policy and authorization foundation module registration, commands, and query handlers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from importlib.resources import files
from typing import Any, ClassVar
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import delete, insert, select, update

from businessos.sdk import (
    BusinessOSError,
    Command,
    DomainEvent,
    HandlingContext,
    ModuleManifest,
    ModuleRegistration,
    PermissionDeclaration,
    Query,
)

from .contracts import (
    PolicyEvaluationService,
)
from .models import (
    APPROVAL_LIMITS,
    DELEGATIONS,
    FIELD_POLICIES,
    PERMISSIONS,
    ROLE_PERMISSIONS,
    ROLES,
    SOD_RULES,
    SUBJECT_ROLE_ASSIGNMENTS,
    ApprovalAuthorityDecision,
    ApprovalLimitRecord,
    AuthorizationDecision,
    DelegationGrantRecord,
    FieldAccessDecision,
    FieldAccessType,
    FieldPolicyRecord,
    PermissionRecord,
    PolicyContext,
    RolePermissionRecord,
    RoleRecord,
    ScopeType,
    SegregationOfDutiesRuleRecord,
    SoDConflictResult,
    SoDSeverity,
    SubjectRoleAssignmentRecord,
)


class RegisterPermissionCommand(Command):
    code: str = Field(min_length=3, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)


class CreateRoleCommand(Command):
    tenant_id: UUID
    code: str = Field(min_length=2, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=500)
    is_system: bool = False
    parent_role_id: UUID | None = None


class AssignPermissionToRoleCommand(Command):
    tenant_id: UUID
    role_id: UUID
    permission_code: str


class AssignRoleToSubjectCommand(Command):
    tenant_id: UUID
    subject_id: UUID
    role_id: UUID
    scope_type: ScopeType = ScopeType.TENANT
    scope_id: UUID | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class SetFieldPolicyCommand(Command):
    tenant_id: UUID
    resource_type: str = Field(min_length=1, max_length=100)
    field_name: str = Field(min_length=1, max_length=100)
    role_id: UUID | None = None
    access_type: FieldAccessType = FieldAccessType.READ
    mask_pattern: str | None = None
    condition_expression: str | None = None


class SetApprovalLimitCommand(Command):
    tenant_id: UUID
    action_type: str = Field(min_length=1, max_length=100)
    currency: str = Field(min_length=3, max_length=3)
    amount_limit: Decimal = Field(ge=0)
    role_id: UUID | None = None
    subject_id: UUID | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class CreateSoDRuleCommand(Command):
    tenant_id: UUID
    code: str = Field(min_length=2, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    permission_a: str
    permission_b: str
    severity: SoDSeverity = SoDSeverity.PREVENTATIVE
    description: str = ""


class CreateDelegationCommand(Command):
    tenant_id: UUID
    delegator_id: UUID
    delegatee_id: UUID
    role_id: UUID
    scope_type: ScopeType = ScopeType.TENANT
    scope_id: UUID | None = None
    valid_from: datetime
    valid_to: datetime


class RevokeDelegationCommand(Command):
    tenant_id: UUID
    delegation_id: UUID
    reason: str = Field(min_length=1, max_length=500)


class AuthorizeActionQuery(Query):
    tenant_id: UUID
    subject_id: UUID
    action: str
    resource: str
    legal_entity_id: UUID | None = None
    operating_site_id: UUID | None = None
    business_unit_id: UUID | None = None
    client_ip: str | None = None
    timestamp: datetime | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class EvaluateFieldAccessQuery(Query):
    tenant_id: UUID
    subject_id: UUID
    resource_type: str
    field_name: str


class EvaluateApprovalLimitQuery(Query):
    tenant_id: UUID
    subject_id: UUID
    action_type: str
    amount: Decimal
    currency: str


class CheckSoDConflictQuery(Query):
    tenant_id: UUID
    candidate_permissions: list[str]


class RoleCreatedEvent(DomainEvent):
    event_type: ClassVar[str] = "policy.role.created.v1"
    tenant_id: UUID
    role_id: UUID
    code: str
    name: str


class RoleAssignmentEvent(DomainEvent):
    event_type: ClassVar[str] = "policy.assignment.changed.v1"
    tenant_id: UUID
    subject_id: UUID
    role_id: UUID
    action: str


class PolicyModule:
    def __init__(self) -> None:
        data = json.loads(
            files("businessos_policy").joinpath("manifest.json").read_text(encoding="utf-8")
        )
        self.manifest = ModuleManifest.model_validate(data)
        self.evaluator = PolicyEvaluationService()

    async def register(self, registration: ModuleRegistration) -> None:
        registration.permission(
            PermissionDeclaration(
                key="foundation.policy.read",
                description="Read roles, permissions, and policy rules",
            )
        )
        registration.permission(
            PermissionDeclaration(
                key="foundation.policy.manage",
                description="Manage roles, permissions, and policy rules",
            )
        )
        registration.permission(
            PermissionDeclaration(
                key="foundation.policy.authorize", description="Evaluate authorization decisions"
            )
        )

        registration.command(
            RegisterPermissionCommand,
            self._register_permission,
            permission="foundation.policy.manage",
        )
        registration.command(
            CreateRoleCommand, self._create_role, permission="foundation.policy.manage"
        )
        registration.command(
            AssignPermissionToRoleCommand,
            self._assign_permission,
            permission="foundation.policy.manage",
        )
        registration.command(
            AssignRoleToSubjectCommand, self._assign_role, permission="foundation.policy.manage"
        )
        registration.command(
            SetFieldPolicyCommand, self._set_field_policy, permission="foundation.policy.manage"
        )
        registration.command(
            SetApprovalLimitCommand, self._set_approval_limit, permission="foundation.policy.manage"
        )
        registration.command(
            CreateSoDRuleCommand, self._create_sod_rule, permission="foundation.policy.manage"
        )
        registration.command(
            CreateDelegationCommand, self._create_delegation, permission="foundation.policy.manage"
        )
        registration.command(
            RevokeDelegationCommand, self._revoke_delegation, permission="foundation.policy.manage"
        )

        registration.query(
            AuthorizeActionQuery, self._authorize_action, permission="foundation.policy.authorize"
        )
        registration.query(
            EvaluateFieldAccessQuery,
            self._evaluate_field_access,
            permission="foundation.policy.authorize",
        )
        registration.query(
            EvaluateApprovalLimitQuery,
            self._evaluate_approval_limit,
            permission="foundation.policy.authorize",
        )
        registration.query(
            CheckSoDConflictQuery, self._check_sod_conflict, permission="foundation.policy.read"
        )

    async def _register_permission(
        self, cmd: RegisterPermissionCommand, ctx: HandlingContext
    ) -> PermissionRecord:
        stmt = (
            insert(PERMISSIONS)
            .values(
                code=cmd.code,
                name=cmd.name,
                category=cmd.category,
                description=cmd.description,
            )
            .on_conflict_do_update(
                index_elements=[PERMISSIONS.c.code],
                set_=dict(name=cmd.name, category=cmd.category, description=cmd.description),
            )
        )
        await ctx.session.execute(stmt)
        return PermissionRecord(
            code=cmd.code,
            name=cmd.name,
            category=cmd.category,
            description=cmd.description,
        )

    async def _create_role(self, cmd: CreateRoleCommand, ctx: HandlingContext) -> RoleRecord:
        now = datetime.now(timezone.utc)
        role_id = uuid4()
        stmt = insert(ROLES).values(
            id=role_id,
            tenant_id=cmd.tenant_id,
            code=cmd.code,
            name=cmd.name,
            description=cmd.description,
            is_system=cmd.is_system,
            parent_role_id=cmd.parent_role_id,
            created_at=now,
            updated_at=now,
        )
        await ctx.session.execute(stmt)
        return RoleRecord(
            id=role_id,
            tenant_id=cmd.tenant_id,
            code=cmd.code,
            name=cmd.name,
            description=cmd.description,
            is_system=cmd.is_system,
            parent_role_id=cmd.parent_role_id,
            created_at=now,
            updated_at=now,
        )

    async def _assign_permission(
        self, cmd: AssignPermissionToRoleCommand, ctx: HandlingContext
    ) -> RolePermissionRecord:
        now = datetime.now(timezone.utc)
        rp_id = uuid4()
        stmt = insert(ROLE_PERMISSIONS).values(
            id=rp_id,
            tenant_id=cmd.tenant_id,
            role_id=cmd.role_id,
            permission_code=cmd.permission_code,
            created_at=now,
        )
        await ctx.session.execute(stmt)
        return RolePermissionRecord(
            id=rp_id,
            tenant_id=cmd.tenant_id,
            role_id=cmd.role_id,
            permission_code=cmd.permission_code,
            created_at=now,
        )

    async def _assign_role(
        self, cmd: AssignRoleToSubjectCommand, ctx: HandlingContext
    ) -> SubjectRoleAssignmentRecord:
        now = datetime.now(timezone.utc)
        assignment_id = uuid4()
        stmt = insert(SUBJECT_ROLE_ASSIGNMENTS).values(
            id=assignment_id,
            tenant_id=cmd.tenant_id,
            subject_id=cmd.subject_id,
            role_id=cmd.role_id,
            scope_type=cmd.scope_type.value,
            scope_id=cmd.scope_id,
            valid_from=cmd.valid_from,
            valid_to=cmd.valid_to,
            created_at=now,
        )
        await ctx.session.execute(stmt)
        return SubjectRoleAssignmentRecord(
            id=assignment_id,
            tenant_id=cmd.tenant_id,
            subject_id=cmd.subject_id,
            role_id=cmd.role_id,
            scope_type=cmd.scope_type,
            scope_id=cmd.scope_id,
            valid_from=cmd.valid_from,
            valid_to=cmd.valid_to,
            created_at=now,
        )

    async def _set_field_policy(
        self, cmd: SetFieldPolicyCommand, ctx: HandlingContext
    ) -> FieldPolicyRecord:
        now = datetime.now(timezone.utc)
        fp_id = uuid4()
        stmt = insert(FIELD_POLICIES).values(
            id=fp_id,
            tenant_id=cmd.tenant_id,
            resource_type=cmd.resource_type,
            field_name=cmd.field_name,
            role_id=cmd.role_id,
            access_type=cmd.access_type.value,
            mask_pattern=cmd.mask_pattern,
            condition_expression=cmd.condition_expression,
            created_at=now,
        )
        await ctx.session.execute(stmt)
        return FieldPolicyRecord(
            id=fp_id,
            tenant_id=cmd.tenant_id,
            resource_type=cmd.resource_type,
            field_name=cmd.field_name,
            role_id=cmd.role_id,
            access_type=cmd.access_type,
            mask_pattern=cmd.mask_pattern,
            condition_expression=cmd.condition_expression,
            created_at=now,
        )

    async def _set_approval_limit(
        self, cmd: SetApprovalLimitCommand, ctx: HandlingContext
    ) -> ApprovalLimitRecord:
        now = datetime.now(timezone.utc)
        limit_id = uuid4()
        stmt = insert(APPROVAL_LIMITS).values(
            id=limit_id,
            tenant_id=cmd.tenant_id,
            action_type=cmd.action_type,
            currency=cmd.currency.upper(),
            amount_limit=cmd.amount_limit,
            role_id=cmd.role_id,
            subject_id=cmd.subject_id,
            valid_from=cmd.valid_from,
            valid_to=cmd.valid_to,
            created_at=now,
        )
        await ctx.session.execute(stmt)
        return ApprovalLimitRecord(
            id=limit_id,
            tenant_id=cmd.tenant_id,
            action_type=cmd.action_type,
            currency=cmd.currency.upper(),
            amount_limit=cmd.amount_limit,
            role_id=cmd.role_id,
            subject_id=cmd.subject_id,
            valid_from=cmd.valid_from,
            valid_to=cmd.valid_to,
            created_at=now,
        )

    async def _create_sod_rule(
        self, cmd: CreateSoDRuleCommand, ctx: HandlingContext
    ) -> SegregationOfDutiesRuleRecord:
        now = datetime.now(timezone.utc)
        rule_id = uuid4()
        stmt = insert(SOD_RULES).values(
            id=rule_id,
            tenant_id=cmd.tenant_id,
            code=cmd.code,
            name=cmd.name,
            permission_a=cmd.permission_a,
            permission_b=cmd.permission_b,
            severity=cmd.severity.value,
            description=cmd.description,
            created_at=now,
        )
        await ctx.session.execute(stmt)
        return SegregationOfDutiesRuleRecord(
            id=rule_id,
            tenant_id=cmd.tenant_id,
            code=cmd.code,
            name=cmd.name,
            permission_a=cmd.permission_a,
            permission_b=cmd.permission_b,
            severity=cmd.severity,
            description=cmd.description,
            created_at=now,
        )

    async def _create_delegation(
        self, cmd: CreateDelegationCommand, ctx: HandlingContext
    ) -> DelegationGrantRecord:
        now = datetime.now(timezone.utc)
        del_id = uuid4()
        stmt = insert(DELEGATIONS).values(
            id=del_id,
            tenant_id=cmd.tenant_id,
            delegator_id=cmd.delegator_id,
            delegatee_id=cmd.delegatee_id,
            role_id=cmd.role_id,
            scope_type=cmd.scope_type.value,
            scope_id=cmd.scope_id,
            valid_from=cmd.valid_from,
            valid_to=cmd.valid_to,
            is_revoked=False,
            created_at=now,
        )
        await ctx.session.execute(stmt)
        return DelegationGrantRecord(
            id=del_id,
            tenant_id=cmd.tenant_id,
            delegator_id=cmd.delegator_id,
            delegatee_id=cmd.delegatee_id,
            role_id=cmd.role_id,
            scope_type=cmd.scope_type,
            scope_id=cmd.scope_id,
            valid_from=cmd.valid_from,
            valid_to=cmd.valid_to,
            is_revoked=False,
            revocation_reason=None,
            created_at=now,
        )

    async def _revoke_delegation(self, cmd: RevokeDelegationCommand, ctx: HandlingContext) -> None:
        stmt = (
            update(DELEGATIONS)
            .where(DELEGATIONS.c.id == cmd.delegation_id)
            .where(DELEGATIONS.c.tenant_id == cmd.tenant_id)
            .values(is_revoked=True, revocation_reason=cmd.reason)
        )
        res = await ctx.session.execute(stmt)
        if res.rowcount == 0:
            raise BusinessOSError(f"Delegation grant {cmd.delegation_id} not found")

    async def _authorize_action(
        self, query: AuthorizeActionQuery, ctx: HandlingContext
    ) -> AuthorizationDecision:
        # Query roles, permissions, assignments, delegations
        roles_res = await ctx.session.execute(
            select(ROLES).where(ROLES.c.tenant_id == query.tenant_id)
        )
        roles = [RoleRecord.model_validate(dict(r._mapping)) for r in roles_res]

        assign_res = await ctx.session.execute(
            select(SUBJECT_ROLE_ASSIGNMENTS)
            .where(SUBJECT_ROLE_ASSIGNMENTS.c.tenant_id == query.tenant_id)
            .where(SUBJECT_ROLE_ASSIGNMENTS.c.subject_id == query.subject_id)
        )
        assignments = [
            SubjectRoleAssignmentRecord.model_validate(dict(r._mapping)) for r in assign_res
        ]

        rp_res = await ctx.session.execute(
            select(ROLE_PERMISSIONS).where(ROLE_PERMISSIONS.c.tenant_id == query.tenant_id)
        )
        role_permissions = [RolePermissionRecord.model_validate(dict(r._mapping)) for r in rp_res]

        del_res = await ctx.session.execute(
            select(DELEGATIONS)
            .where(DELEGATIONS.c.tenant_id == query.tenant_id)
            .where(DELEGATIONS.c.delegatee_id == query.subject_id)
            .where(DELEGATIONS.c.is_revoked == False)
        )
        delegations = [DelegationGrantRecord.model_validate(dict(r._mapping)) for r in del_res]

        policy_ctx = PolicyContext(
            tenant_id=query.tenant_id,
            subject_id=query.subject_id,
            legal_entity_id=query.legal_entity_id,
            operating_site_id=query.operating_site_id,
            business_unit_id=query.business_unit_id,
            client_ip=query.client_ip,
            timestamp=query.timestamp or datetime.now(timezone.utc),
            attributes=query.attributes,
        )

        return self.evaluator.authorize(
            action=query.action,
            resource=query.resource,
            context=policy_ctx,
            roles=roles,
            role_permissions=role_permissions,
            assignments=assignments,
            delegations=delegations,
        )

    async def _evaluate_field_access(
        self, query: EvaluateFieldAccessQuery, ctx: HandlingContext
    ) -> FieldAccessDecision:
        assign_res = await ctx.session.execute(
            select(SUBJECT_ROLE_ASSIGNMENTS)
            .where(SUBJECT_ROLE_ASSIGNMENTS.c.tenant_id == query.tenant_id)
            .where(SUBJECT_ROLE_ASSIGNMENTS.c.subject_id == query.subject_id)
        )
        role_ids = {r.role_id for r in assign_res}

        fp_res = await ctx.session.execute(
            select(FIELD_POLICIES)
            .where(FIELD_POLICIES.c.tenant_id == query.tenant_id)
            .where(FIELD_POLICIES.c.resource_type == query.resource_type)
            .where(FIELD_POLICIES.c.field_name == query.field_name)
        )
        policies = [FieldPolicyRecord.model_validate(dict(r._mapping)) for r in fp_res]

        policy_ctx = PolicyContext(tenant_id=query.tenant_id, subject_id=query.subject_id)
        return self.evaluator.evaluate_field_access(
            field_name=query.field_name,
            resource_type=query.resource_type,
            context=policy_ctx,
            policies=policies,
            active_role_ids=role_ids,
        )

    async def _evaluate_approval_limit(
        self, query: EvaluateApprovalLimitQuery, ctx: HandlingContext
    ) -> ApprovalAuthorityDecision:
        assign_res = await ctx.session.execute(
            select(SUBJECT_ROLE_ASSIGNMENTS)
            .where(SUBJECT_ROLE_ASSIGNMENTS.c.tenant_id == query.tenant_id)
            .where(SUBJECT_ROLE_ASSIGNMENTS.c.subject_id == query.subject_id)
        )
        role_ids = {r.role_id for r in assign_res}

        lim_res = await ctx.session.execute(
            select(APPROVAL_LIMITS)
            .where(APPROVAL_LIMITS.c.tenant_id == query.tenant_id)
            .where(APPROVAL_LIMITS.c.action_type == query.action_type)
        )
        limits = [ApprovalLimitRecord.model_validate(dict(r._mapping)) for r in lim_res]

        policy_ctx = PolicyContext(tenant_id=query.tenant_id, subject_id=query.subject_id)
        return self.evaluator.evaluate_approval_authority(
            action_type=query.action_type,
            amount=query.amount,
            currency=query.currency,
            context=policy_ctx,
            limits=limits,
            active_role_ids=role_ids,
        )

    async def _check_sod_conflict(
        self, query: CheckSoDConflictQuery, ctx: HandlingContext
    ) -> SoDConflictResult:
        rules_res = await ctx.session.execute(
            select(SOD_RULES).where(SOD_RULES.c.tenant_id == query.tenant_id)
        )
        rules = [SegregationOfDutiesRuleRecord.model_validate(dict(r._mapping)) for r in rules_res]
        return self.evaluator.check_sod_conflict(set(query.candidate_permissions), rules)
