"""Policy and authorization foundation module registration, commands, and query handlers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from importlib.resources import files
from typing import Any, cast
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from businessos.sdk import (
    MESSAGE_DISPATCHER,
    BusinessOSError,
    Command,
    HandlingContext,
    ModuleManifest,
    ModuleRegistration,
    PermissionDeclaration,
    Query,
    Request,
    RequestContext,
    RequestDependencyScope,
    Response,
    TenantContext,
)

from .contracts import (
    DelegationGranted,
    DelegationRevoked,
    PermissionAssignedToRole,
    PolicyEvaluationService,
    RoleAssignedToSubject,
    RoleCreated,
    SupportAccessGranted,
    SupportAccessRevoked,
)
from .models import (
    APPROVAL_LIMITS,
    DELEGATIONS,
    FIELD_POLICIES,
    PERMISSIONS,
    RECORD_POLICIES,
    ROLE_PERMISSIONS,
    ROLES,
    SOD_RULES,
    SUBJECT_ROLE_ASSIGNMENTS,
    SUPPORT_ACCESS_GRANTS,
    ApprovalAuthorityDecision,
    ApprovalLimitRecord,
    AuthorizationDecision,
    DelegationGrantRecord,
    FieldAccessDecision,
    FieldAccessType,
    FieldPolicyRecord,
    PermissionRecord,
    PolicyContext,
    RecordAccessScope,
    RecordPolicyRecord,
    RolePermissionRecord,
    RoleRecord,
    ScopeType,
    SegregationOfDutiesRuleRecord,
    SoDConflictResult,
    SoDSeverity,
    SubjectRoleAssignmentRecord,
    SupportAccessGrantRecord,
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


class SetRecordPolicyCommand(Command):
    tenant_id: UUID
    resource_type: str = Field(min_length=1, max_length=100)
    role_id: UUID | None = None
    access_scope: RecordAccessScope = RecordAccessScope.ORGANIZATION
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


class GrantSupportAccessCommand(Command):
    tenant_id: UUID
    support_principal_id: UUID
    reason: str = Field(min_length=1, max_length=1000)
    valid_to: datetime


class RevokeSupportAccessCommand(Command):
    tenant_id: UUID
    grant_id: UUID
    reason: str = Field(min_length=1, max_length=500)


class AuthorizeActionQuery(Query):
    tenant_id: UUID
    subject_id: UUID
    action: str
    resource: str
    company_id: UUID | None = None
    legal_entity_id: UUID | None = None
    operating_site_id: UUID | None = None
    business_unit_id: UUID | None = None
    record_owner_id: UUID | None = None
    record_scope_type: ScopeType | None = None
    record_scope_id: UUID | None = None
    client_ip: str | None = None
    timestamp: datetime | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class EvaluateFieldAccessQuery(Query):
    tenant_id: UUID
    subject_id: UUID
    resource_type: str
    field_name: str
    requested_access: FieldAccessType = FieldAccessType.READ
    attributes: dict[str, Any] = Field(default_factory=dict)


class EvaluateApprovalLimitQuery(Query):
    tenant_id: UUID
    subject_id: UUID
    action_type: str
    amount: Decimal
    currency: str


class CheckSoDConflictQuery(Query):
    tenant_id: UUID
    candidate_permissions: list[str]


class AuthorizeSupportAccessQuery(Query):
    tenant_id: UUID
    support_principal_id: UUID
    timestamp: datetime | None = None


class PolicyModule:
    def __init__(self) -> None:
        data = json.loads(
            files("businessos_policy").joinpath("manifest.json").read_text(encoding="utf-8")
        )
        self.manifest = ModuleManifest.model_validate(data)
        self.evaluator = PolicyEvaluationService()

    async def register(self, registration: ModuleRegistration) -> None:
        registration.contract("foundation.policy.authorization.v1", self.evaluator)
        registration.contract("foundation.policy.field-policy.v1", self.evaluator)
        registration.contract("foundation.policy.approval-authority.v1", self.evaluator)
        registration.permission(
            PermissionDeclaration(
                key="foundation.policy.read",
                description="Read roles, permissions, and policy rules",
            )
        )
        registration.permission(
            PermissionDeclaration(
                key="foundation.policy.support_access",
                description="Approve and revoke explicit time-limited support access",
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
            SetRecordPolicyCommand,
            self._set_record_policy,
            permission="foundation.policy.manage",
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
        registration.command(
            GrantSupportAccessCommand,
            self._grant_support_access,
            permission="foundation.policy.support_access",
        )
        registration.command(
            RevokeSupportAccessCommand,
            self._revoke_support_access,
            permission="foundation.policy.support_access",
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
        registration.query(
            AuthorizeSupportAccessQuery,
            self._authorize_support_access,
            permission="foundation.policy.authorize",
        )
        registration.route(
            "POST", "/api/v1/policy/authorize", self._http_authorize, name="policy-authorize"
        )
        registration.route(
            "POST",
            "/api/v1/policy/field-access",
            self._http_field_access,
            name="policy-field-access",
        )
        registration.route(
            "POST",
            "/api/v1/policy/approval-limit",
            self._http_approval_limit,
            name="policy-approval-limit",
        )

    @staticmethod
    async def _http_payload(request: Request) -> tuple[dict[str, object], TenantContext]:
        tenant = request.context.tenant
        if tenant is None:
            raise BusinessOSError("unauthenticated", "Authentication required", status_code=401)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise BusinessOSError("invalid_request", "Request must be an object", status_code=400)
        return cast(dict[str, object], payload), tenant

    async def _http_authorize(
        self, request: Request, dependencies: RequestDependencyScope
    ) -> Response:
        payload, tenant = await self._http_payload(request)
        query = AuthorizeActionQuery.model_validate(
            {
                **payload,
                "tenant_id": tenant.tenant_id,
                "subject_id": tenant.principal_id,
                "company_id": tenant.active_company_id,
                "legal_entity_id": tenant.legal_entity_id,
                "operating_site_id": tenant.operating_site_id,
                "business_unit_id": tenant.business_unit_id,
            }
        )
        dispatcher = await dependencies.resolve(MESSAGE_DISPATCHER)
        result = await dispatcher.query(query, request.context, dependencies)
        if not isinstance(result, AuthorizationDecision):
            raise RuntimeError("Policy authorization contract returned an invalid result")
        return Response.json(result)

    async def _http_field_access(
        self, request: Request, dependencies: RequestDependencyScope
    ) -> Response:
        payload, tenant = await self._http_payload(request)
        query = EvaluateFieldAccessQuery.model_validate(
            {**payload, "tenant_id": tenant.tenant_id, "subject_id": tenant.principal_id}
        )
        dispatcher = await dependencies.resolve(MESSAGE_DISPATCHER)
        result = await dispatcher.query(query, request.context, dependencies)
        if not isinstance(result, FieldAccessDecision):
            raise RuntimeError("Policy field-access contract returned an invalid result")
        return Response.json(result)

    async def _http_approval_limit(
        self, request: Request, dependencies: RequestDependencyScope
    ) -> Response:
        payload, tenant = await self._http_payload(request)
        query = EvaluateApprovalLimitQuery.model_validate(
            {**payload, "tenant_id": tenant.tenant_id, "subject_id": tenant.principal_id}
        )
        dispatcher = await dependencies.resolve(MESSAGE_DISPATCHER)
        result = await dispatcher.query(query, request.context, dependencies)
        if not isinstance(result, ApprovalAuthorityDecision):
            raise RuntimeError("Policy approval contract returned an invalid result")
        return Response.json(result)

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

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
        await ctx.unit_of_work.persistence.execute(stmt)
        return PermissionRecord(
            code=cmd.code,
            name=cmd.name,
            category=cmd.category,
            description=cmd.description,
        )

    async def _create_role(self, cmd: CreateRoleCommand, ctx: HandlingContext) -> RoleRecord:
        tenant = _require_tenant(ctx.request, cmd.tenant_id)
        if cmd.parent_role_id is not None:
            await _require_role(ctx, cmd.tenant_id, cmd.parent_role_id)
        now = datetime.now(UTC)
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
        await ctx.unit_of_work.persistence.execute(stmt)
        record = RoleRecord(
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
        ctx.emit(
            RoleCreated(
                tenant_id=tenant.tenant_id,
                correlation_id=ctx.request.correlation_id,
                role_id=role_id,
                code=cmd.code,
                name=cmd.name,
            )
        )
        return record

    async def _assign_permission(
        self, cmd: AssignPermissionToRoleCommand, ctx: HandlingContext
    ) -> RolePermissionRecord:
        tenant = _require_tenant(ctx.request, cmd.tenant_id)
        await _require_role(ctx, cmd.tenant_id, cmd.role_id)
        now = datetime.now(UTC)
        rp_id = uuid4()
        stmt = insert(ROLE_PERMISSIONS).values(
            id=rp_id,
            tenant_id=cmd.tenant_id,
            role_id=cmd.role_id,
            permission_code=cmd.permission_code,
            created_at=now,
        )
        await ctx.unit_of_work.persistence.execute(stmt)
        record = RolePermissionRecord(
            id=rp_id,
            tenant_id=cmd.tenant_id,
            role_id=cmd.role_id,
            permission_code=cmd.permission_code,
            created_at=now,
        )
        ctx.emit(
            PermissionAssignedToRole(
                tenant_id=tenant.tenant_id,
                correlation_id=ctx.request.correlation_id,
                role_id=cmd.role_id,
                permission_code=cmd.permission_code,
            )
        )
        return record

    async def _assign_role(
        self, cmd: AssignRoleToSubjectCommand, ctx: HandlingContext
    ) -> SubjectRoleAssignmentRecord:
        tenant = _require_tenant(ctx.request, cmd.tenant_id)
        await _require_role(ctx, cmd.tenant_id, cmd.role_id)
        _validate_scope(cmd.scope_type, cmd.scope_id)
        _validate_window(cmd.valid_from, cmd.valid_to)
        permission_rows = await ctx.unit_of_work.persistence.execute(
            select(ROLE_PERMISSIONS.c.permission_code)
            .select_from(
                SUBJECT_ROLE_ASSIGNMENTS.join(
                    ROLE_PERMISSIONS,
                    SUBJECT_ROLE_ASSIGNMENTS.c.role_id == ROLE_PERMISSIONS.c.role_id,
                )
            )
            .where(SUBJECT_ROLE_ASSIGNMENTS.c.tenant_id == cmd.tenant_id)
            .where(SUBJECT_ROLE_ASSIGNMENTS.c.subject_id == cmd.subject_id)
        )
        new_permission_rows = await ctx.unit_of_work.persistence.execute(
            select(ROLE_PERMISSIONS.c.permission_code)
            .where(ROLE_PERMISSIONS.c.tenant_id == cmd.tenant_id)
            .where(ROLE_PERMISSIONS.c.role_id == cmd.role_id)
        )
        candidate_permissions = {
            row[0] for row in [*permission_rows.fetchall(), *new_permission_rows.fetchall()]
        }
        rule_rows = await ctx.unit_of_work.persistence.execute(
            select(SOD_RULES).where(
                SOD_RULES.c.tenant_id == cmd.tenant_id,
                SOD_RULES.c.severity == SoDSeverity.PREVENTATIVE.value,
            )
        )
        rules = [
            SegregationOfDutiesRuleRecord.model_validate(dict(row)) for row in rule_rows.mappings()
        ]
        conflict = self.evaluator.check_sod_conflict(candidate_permissions, rules)
        if conflict.has_conflict:
            raise BusinessOSError(
                "segregation_of_duties_conflict",
                "Role assignment violates a preventative segregation-of-duties rule",
                status_code=409,
                details={"conflicts": conflict.conflicting_rules},
            )
        now = datetime.now(UTC)
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
        await ctx.unit_of_work.persistence.execute(stmt)
        record = SubjectRoleAssignmentRecord(
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
        ctx.emit(
            RoleAssignedToSubject(
                tenant_id=tenant.tenant_id,
                correlation_id=ctx.request.correlation_id,
                subject_id=cmd.subject_id,
                role_id=cmd.role_id,
                scope_type=cmd.scope_type.value,
                scope_id=cmd.scope_id,
            )
        )
        return record

    async def _set_field_policy(
        self, cmd: SetFieldPolicyCommand, ctx: HandlingContext
    ) -> FieldPolicyRecord:
        _require_tenant(ctx.request, cmd.tenant_id)
        if cmd.role_id is not None:
            await _require_role(ctx, cmd.tenant_id, cmd.role_id)
        now = datetime.now(UTC)
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
        await ctx.unit_of_work.persistence.execute(stmt)
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
        _require_tenant(ctx.request, cmd.tenant_id)
        if cmd.role_id is not None:
            await _require_role(ctx, cmd.tenant_id, cmd.role_id)
        _validate_window(cmd.valid_from, cmd.valid_to)
        now = datetime.now(UTC)
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
        await ctx.unit_of_work.persistence.execute(stmt)
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

    async def _set_record_policy(
        self, cmd: SetRecordPolicyCommand, ctx: HandlingContext
    ) -> RecordPolicyRecord:
        _require_tenant(ctx.request, cmd.tenant_id)
        if cmd.role_id is not None:
            await _require_role(ctx, cmd.tenant_id, cmd.role_id)
        now = datetime.now(UTC)
        policy_id = uuid4()
        await ctx.unit_of_work.persistence.execute(
            insert(RECORD_POLICIES).values(
                id=policy_id,
                tenant_id=cmd.tenant_id,
                resource_type=cmd.resource_type,
                role_id=cmd.role_id,
                access_scope=cmd.access_scope.value,
                condition_expression=cmd.condition_expression,
                created_at=now,
            )
        )
        return RecordPolicyRecord(
            id=policy_id,
            tenant_id=cmd.tenant_id,
            resource_type=cmd.resource_type,
            role_id=cmd.role_id,
            access_scope=cmd.access_scope,
            condition_expression=cmd.condition_expression,
            created_at=now,
        )

    async def _create_sod_rule(
        self, cmd: CreateSoDRuleCommand, ctx: HandlingContext
    ) -> SegregationOfDutiesRuleRecord:
        _require_tenant(ctx.request, cmd.tenant_id)
        now = datetime.now(UTC)
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
        await ctx.unit_of_work.persistence.execute(stmt)
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
        tenant = _require_tenant(ctx.request, cmd.tenant_id)
        if cmd.delegator_id == cmd.delegatee_id:
            raise BusinessOSError(
                "invalid_delegation", "Delegator and delegatee must differ", status_code=422
            )
        await _require_role(ctx, cmd.tenant_id, cmd.role_id)
        _validate_scope(cmd.scope_type, cmd.scope_id)
        _validate_window(cmd.valid_from, cmd.valid_to)
        authority = await ctx.unit_of_work.persistence.execute(
            select(SUBJECT_ROLE_ASSIGNMENTS.c.id)
            .where(SUBJECT_ROLE_ASSIGNMENTS.c.tenant_id == cmd.tenant_id)
            .where(SUBJECT_ROLE_ASSIGNMENTS.c.subject_id == cmd.delegator_id)
            .where(SUBJECT_ROLE_ASSIGNMENTS.c.role_id == cmd.role_id)
        )
        if authority.first() is None:
            raise BusinessOSError(
                "delegation_authority_missing",
                "Delegator does not hold the delegated role",
                status_code=403,
            )
        now = datetime.now(UTC)
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
        await ctx.unit_of_work.persistence.execute(stmt)
        record = DelegationGrantRecord(
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
        ctx.emit(
            DelegationGranted(
                tenant_id=tenant.tenant_id,
                correlation_id=ctx.request.correlation_id,
                delegation_id=del_id,
                delegator_id=cmd.delegator_id,
                delegatee_id=cmd.delegatee_id,
                role_id=cmd.role_id,
                valid_from=cmd.valid_from,
                valid_to=cmd.valid_to,
            )
        )
        return record

    async def _revoke_delegation(self, cmd: RevokeDelegationCommand, ctx: HandlingContext) -> None:
        tenant = _require_tenant(ctx.request, cmd.tenant_id)
        stmt = (
            update(DELEGATIONS)
            .where(DELEGATIONS.c.id == cmd.delegation_id)
            .where(DELEGATIONS.c.tenant_id == cmd.tenant_id)
            .values(is_revoked=True, revocation_reason=cmd.reason)
            .returning(DELEGATIONS.c.id)
        )
        res = await ctx.unit_of_work.persistence.execute(stmt)
        if res.scalar_one_or_none() is None:
            raise BusinessOSError(
                "not_found", f"Delegation grant {cmd.delegation_id} not found", status_code=404
            )
        ctx.emit(
            DelegationRevoked(
                tenant_id=tenant.tenant_id,
                correlation_id=ctx.request.correlation_id,
                delegation_id=cmd.delegation_id,
                reason=cmd.reason,
            )
        )

    async def _authorize_action(
        self, query: AuthorizeActionQuery, ctx: HandlingContext
    ) -> AuthorizationDecision:
        tenant = _require_tenant(ctx.request, query.tenant_id)
        _require_requested_scope(tenant, query)
        # Query roles, permissions, assignments, delegations
        roles_res = await ctx.unit_of_work.persistence.execute(
            select(ROLES).where(ROLES.c.tenant_id == query.tenant_id)
        )
        roles = [RoleRecord.model_validate(dict(row)) for row in roles_res.mappings()]

        assign_res = await ctx.unit_of_work.persistence.execute(
            select(SUBJECT_ROLE_ASSIGNMENTS)
            .where(SUBJECT_ROLE_ASSIGNMENTS.c.tenant_id == query.tenant_id)
            .where(SUBJECT_ROLE_ASSIGNMENTS.c.subject_id == query.subject_id)
        )
        assignments = [
            SubjectRoleAssignmentRecord.model_validate(dict(row)) for row in assign_res.mappings()
        ]

        rp_res = await ctx.unit_of_work.persistence.execute(
            select(ROLE_PERMISSIONS).where(ROLE_PERMISSIONS.c.tenant_id == query.tenant_id)
        )
        role_permissions = [
            RolePermissionRecord.model_validate(dict(row)) for row in rp_res.mappings()
        ]

        del_res = await ctx.unit_of_work.persistence.execute(
            select(DELEGATIONS)
            .where(DELEGATIONS.c.tenant_id == query.tenant_id)
            .where(DELEGATIONS.c.delegatee_id == query.subject_id)
            .where(DELEGATIONS.c.is_revoked.is_(False))
        )
        delegations = [
            DelegationGrantRecord.model_validate(dict(row)) for row in del_res.mappings()
        ]

        record_res = await ctx.unit_of_work.persistence.execute(
            select(RECORD_POLICIES)
            .where(RECORD_POLICIES.c.tenant_id == query.tenant_id)
            .where(RECORD_POLICIES.c.resource_type == query.resource)
        )
        record_policies = [
            RecordPolicyRecord.model_validate(dict(row)) for row in record_res.mappings()
        ]

        policy_ctx = PolicyContext(
            tenant_id=query.tenant_id,
            subject_id=query.subject_id,
            company_id=query.company_id,
            legal_entity_id=query.legal_entity_id,
            operating_site_id=query.operating_site_id,
            business_unit_id=query.business_unit_id,
            record_owner_id=query.record_owner_id,
            record_scope_type=query.record_scope_type,
            record_scope_id=query.record_scope_id,
            client_ip=query.client_ip,
            timestamp=query.timestamp or datetime.now(UTC),
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
            record_policies=record_policies,
        )

    async def _grant_support_access(
        self, cmd: GrantSupportAccessCommand, ctx: HandlingContext
    ) -> SupportAccessGrantRecord:
        tenant = _require_tenant(ctx.request, cmd.tenant_id)
        now = datetime.now(UTC)
        if cmd.valid_to <= now:
            raise BusinessOSError(
                "invalid_effective_window",
                "Support access must expire in the future",
                status_code=422,
            )
        grant_id = uuid4()
        await ctx.unit_of_work.persistence.execute(
            insert(SUPPORT_ACCESS_GRANTS).values(
                id=grant_id,
                tenant_id=tenant.tenant_id,
                support_principal_id=cmd.support_principal_id,
                approved_by=tenant.principal_id,
                reason=cmd.reason,
                valid_from=now,
                valid_to=cmd.valid_to,
                created_at=now,
            )
        )
        record = SupportAccessGrantRecord(
            id=grant_id,
            tenant_id=tenant.tenant_id,
            support_principal_id=cmd.support_principal_id,
            approved_by=tenant.principal_id,
            reason=cmd.reason,
            valid_from=now,
            valid_to=cmd.valid_to,
            created_at=now,
        )
        ctx.emit(
            SupportAccessGranted(
                tenant_id=tenant.tenant_id,
                correlation_id=ctx.request.correlation_id,
                grant_id=grant_id,
                support_principal_id=cmd.support_principal_id,
                approved_by=tenant.principal_id,
                valid_to=cmd.valid_to,
            )
        )
        return record

    async def _revoke_support_access(
        self, cmd: RevokeSupportAccessCommand, ctx: HandlingContext
    ) -> None:
        tenant = _require_tenant(ctx.request, cmd.tenant_id)
        result = await ctx.unit_of_work.persistence.execute(
            update(SUPPORT_ACCESS_GRANTS)
            .where(SUPPORT_ACCESS_GRANTS.c.id == cmd.grant_id)
            .where(SUPPORT_ACCESS_GRANTS.c.tenant_id == tenant.tenant_id)
            .where(SUPPORT_ACCESS_GRANTS.c.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC), revocation_reason=cmd.reason)
            .returning(SUPPORT_ACCESS_GRANTS.c.id)
        )
        if result.scalar_one_or_none() is None:
            raise BusinessOSError(
                "not_found", f"Active support grant {cmd.grant_id} not found", status_code=404
            )
        ctx.emit(
            SupportAccessRevoked(
                tenant_id=tenant.tenant_id,
                correlation_id=ctx.request.correlation_id,
                grant_id=cmd.grant_id,
                reason=cmd.reason,
            )
        )

    async def _authorize_support_access(
        self, query: AuthorizeSupportAccessQuery, ctx: HandlingContext
    ) -> AuthorizationDecision:
        _require_tenant(ctx.request, query.tenant_id)
        rows = await ctx.unit_of_work.persistence.execute(
            select(SUPPORT_ACCESS_GRANTS)
            .where(SUPPORT_ACCESS_GRANTS.c.tenant_id == query.tenant_id)
            .where(SUPPORT_ACCESS_GRANTS.c.support_principal_id == query.support_principal_id)
        )
        grants = [SupportAccessGrantRecord.model_validate(dict(row)) for row in rows.mappings()]
        return self.evaluator.authorize_support_access(
            PolicyContext(
                tenant_id=query.tenant_id,
                subject_id=query.support_principal_id,
                timestamp=query.timestamp or datetime.now(UTC),
            ),
            grants,
        )

    async def _evaluate_field_access(
        self, query: EvaluateFieldAccessQuery, ctx: HandlingContext
    ) -> FieldAccessDecision:
        _require_tenant(ctx.request, query.tenant_id)
        assign_res = await ctx.unit_of_work.persistence.execute(
            select(SUBJECT_ROLE_ASSIGNMENTS)
            .where(SUBJECT_ROLE_ASSIGNMENTS.c.tenant_id == query.tenant_id)
            .where(SUBJECT_ROLE_ASSIGNMENTS.c.subject_id == query.subject_id)
        )
        role_ids = {r.role_id for r in assign_res}

        fp_res = await ctx.unit_of_work.persistence.execute(
            select(FIELD_POLICIES)
            .where(FIELD_POLICIES.c.tenant_id == query.tenant_id)
            .where(FIELD_POLICIES.c.resource_type == query.resource_type)
            .where(FIELD_POLICIES.c.field_name == query.field_name)
        )
        policies = [FieldPolicyRecord.model_validate(dict(row)) for row in fp_res.mappings()]

        policy_ctx = PolicyContext(
            tenant_id=query.tenant_id,
            subject_id=query.subject_id,
            attributes=query.attributes,
        )
        return self.evaluator.evaluate_field_access(
            field_name=query.field_name,
            resource_type=query.resource_type,
            context=policy_ctx,
            policies=policies,
            active_role_ids=role_ids,
            requested_access=query.requested_access,
        )

    async def _evaluate_approval_limit(
        self, query: EvaluateApprovalLimitQuery, ctx: HandlingContext
    ) -> ApprovalAuthorityDecision:
        _require_tenant(ctx.request, query.tenant_id)
        assign_res = await ctx.unit_of_work.persistence.execute(
            select(SUBJECT_ROLE_ASSIGNMENTS)
            .where(SUBJECT_ROLE_ASSIGNMENTS.c.tenant_id == query.tenant_id)
            .where(SUBJECT_ROLE_ASSIGNMENTS.c.subject_id == query.subject_id)
        )
        role_ids = {r.role_id for r in assign_res}

        lim_res = await ctx.unit_of_work.persistence.execute(
            select(APPROVAL_LIMITS)
            .where(APPROVAL_LIMITS.c.tenant_id == query.tenant_id)
            .where(APPROVAL_LIMITS.c.action_type == query.action_type)
        )
        limits = [ApprovalLimitRecord.model_validate(dict(row)) for row in lim_res.mappings()]

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
        _require_tenant(ctx.request, query.tenant_id)
        rules_res = await ctx.unit_of_work.persistence.execute(
            select(SOD_RULES).where(SOD_RULES.c.tenant_id == query.tenant_id)
        )
        rules = [
            SegregationOfDutiesRuleRecord.model_validate(dict(row)) for row in rules_res.mappings()
        ]
        return self.evaluator.check_sod_conflict(set(query.candidate_permissions), rules)


def _require_tenant(request: RequestContext | None, target_tenant_id: UUID) -> TenantContext:
    if request is None or request.tenant is None:
        raise BusinessOSError(
            "tenant_context_required", "Tenant context is required", status_code=401
        )
    if request.tenant.tenant_id != target_tenant_id:
        raise BusinessOSError(
            "tenant_scope_mismatch",
            "Target tenant does not match active boundary",
            status_code=403,
        )
    return request.tenant


def _require_requested_scope(tenant: TenantContext, query: AuthorizeActionQuery) -> None:
    requested = (
        ("company", query.company_id, tenant.active_company_id),
        ("legal_entity", query.legal_entity_id, tenant.legal_entity_id),
        ("operating_site", query.operating_site_id, tenant.operating_site_id),
        ("business_unit", query.business_unit_id, tenant.business_unit_id),
    )
    for name, value, active in requested:
        if value is not None and value != active:
            raise BusinessOSError(
                "organization_scope_mismatch",
                f"Requested {name} does not match the trusted active scope",
                status_code=403,
            )


async def _require_role(ctx: HandlingContext, tenant_id: UUID, role_id: UUID) -> None:
    result = await ctx.unit_of_work.persistence.execute(
        select(ROLES.c.id).where(ROLES.c.tenant_id == tenant_id, ROLES.c.id == role_id)
    )
    if result.scalar_one_or_none() is None:
        raise BusinessOSError("invalid_role", "Role does not belong to the tenant", status_code=422)


def _validate_scope(scope_type: ScopeType, scope_id: UUID | None) -> None:
    if scope_type is ScopeType.TENANT and scope_id is not None:
        raise BusinessOSError(
            "invalid_scope", "Tenant scope must not include a scope identifier", status_code=422
        )
    if scope_type is not ScopeType.TENANT and scope_id is None:
        raise BusinessOSError(
            "invalid_scope", "Organizational scope requires a scope identifier", status_code=422
        )


def _validate_window(valid_from: datetime | None, valid_to: datetime | None) -> None:
    if valid_from is not None and valid_to is not None and valid_to <= valid_from:
        raise BusinessOSError(
            "invalid_effective_window", "Authority end must be after its start", status_code=422
        )
