"""Policy and authorization foundation module registration, commands, and query handlers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from importlib.resources import files
from typing import Any, Literal, NoReturn, cast
from uuid import UUID, uuid4

from businessos_identity import (
    AUTHENTICATED_PRINCIPAL,
    MEMBERSHIP_AUTHORITY,
    SESSION_COOKIE,
    PrincipalReference,
    PrincipalType,
    cookie_value,
)
from businessos_organization import DELEGATION_ACTION_AUTHORITY
from pydantic import Field
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from businessos.sdk import (
    AUTHORIZER,
    RESOURCE_OWNER_RESOLVER,
    UNIT_OF_WORK_FACTORY,
    BusinessOSError,
    Command,
    DependencyScope,
    HandlingContext,
    ModuleManifest,
    ModuleRegistration,
    PermissionDeclaration,
    Query,
    Request,
    RequestContext,
    RequestDependencyScope,
    ResourceLocator,
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
from .delegation_authority import (
    MAX_SOURCE_TRAVERSALS,
    PolicyDelegationActionAuthority,
    has_effective_role_source,
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
from .sod_authority import SoDAuthority
from .v2_contracts import POLICY_AUTHORIZATION_V2
from .v2_runtime import PolicyV2Service


class _RetiredV1Authority:
    """Public V1 contract remains addressable but cannot grant live authority."""

    version = "1"

    @staticmethod
    def deny() -> NoReturn:
        raise BusinessOSError(
            "policy_v1_retired",
            "Policy V1 lacks trusted live authority; use Policy V2",
            status_code=403,
        )

    def authorize(self, *args: object, **kwargs: object) -> None:
        self.deny()

    def evaluate_field_access(self, *args: object, **kwargs: object) -> None:
        self.deny()

    def evaluate_approval_authority(self, *args: object, **kwargs: object) -> None:
        self.deny()

    def authorize_support_access(self, *args: object, **kwargs: object) -> None:
        self.deny()


class _PolicyV2PublicContract:
    """Discoverable contract; executable authority is the request-scoped port."""

    version = "2"
    dependency_key = POLICY_AUTHORIZATION_V2


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
    subject_type: Literal["user", "service_account", "device"] | None = None
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
    delegator_type: Literal["user", "service_account", "device"] | None = None
    delegatee_id: UUID
    delegatee_type: Literal["user", "service_account", "device"] | None = None
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
    support_principal_type: Literal["user", "service_account", "device"]
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
    def __init__(
        self,
        *,
        action_resources: Mapping[str, str] | None = None,
        v2_action_resources: Mapping[str, tuple[str, str]] | None = None,
    ) -> None:
        data = json.loads(
            files("businessos_policy").joinpath("manifest.json").read_text(encoding="utf-8")
        )
        self.manifest = ModuleManifest.model_validate(data)
        self.evaluator = PolicyEvaluationService()
        self._v1_authority = _RetiredV1Authority()
        self.delegation_authority = PolicyDelegationActionAuthority(action_resources)
        self._v2_action_resources = dict(v2_action_resources or {})

    async def register(self, registration: ModuleRegistration) -> None:
        registration.dependency(
            DELEGATION_ACTION_AUTHORITY,
            lambda _resolver: self.delegation_authority,
            scope=DependencyScope.REQUEST,
        )

        async def v2_factory(resolver: Any) -> PolicyV2Service:
            return PolicyV2Service(
                await resolver.resolve(AUTHENTICATED_PRINCIPAL),
                await resolver.resolve(MEMBERSHIP_AUTHORITY),
                await resolver.resolve(RESOURCE_OWNER_RESOLVER),
                self.delegation_authority,
                self._v2_action_resources,
                resolver,
            )

        registration.dependency(POLICY_AUTHORIZATION_V2, v2_factory, scope=DependencyScope.REQUEST)
        registration.contract("foundation.policy.authorization.v1", self._v1_authority)
        registration.contract("foundation.policy.field-policy.v1", self._v1_authority)
        registration.contract("foundation.policy.approval-authority.v1", self._v1_authority)
        public_v2 = _PolicyV2PublicContract()
        registration.contract("foundation.policy.authorization.v2", public_v2)
        registration.contract("foundation.policy.field-policy.v2", public_v2)
        registration.contract("foundation.policy.approval-authority.v2", public_v2)
        registration.route(
            "POST", "/api/v1/policy/authorize", self._http_authorize, name="web-authorize"
        )
        registration.route(
            "POST",
            "/api/v1/policy/field-access",
            self._http_field_access,
            name="web-field-access",
        )
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

    @staticmethod
    def _web_tenant(request: Request) -> TenantContext:
        tenant = request.context.tenant
        if cookie_value(request.headers, SESSION_COOKIE) is None or tenant is None:
            raise BusinessOSError("unauthenticated", "Authentication required", status_code=401)
        if tenant.active_company_id is None:
            raise BusinessOSError("scope_required", "Active company is required", status_code=403)
        return tenant

    @staticmethod
    async def _web_payload(request: Request) -> dict[str, object]:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise BusinessOSError("invalid_request", "Request must be an object", status_code=400)
        return cast(dict[str, object], payload)

    @staticmethod
    def _web_locator(payload: dict[str, object], tenant: TenantContext) -> ResourceLocator | None:
        namespace = payload.get("namespace")
        contract = payload.get("contract_version")
        record = payload.get("record_id")
        if namespace is None and contract is None and record is None:
            return None
        if (
            not isinstance(namespace, str)
            or not isinstance(contract, str)
            or not isinstance(record, str)
        ):
            raise BusinessOSError("invalid_locator", "Resource locator is invalid", status_code=400)
        try:
            return ResourceLocator(namespace, contract, UUID(record), tenant.tenant_id)
        except (ValueError, TypeError):
            raise BusinessOSError(
                "invalid_locator", "Resource locator is invalid", status_code=400
            ) from None

    async def _http_authorize(
        self, request: Request, dependencies: RequestDependencyScope
    ) -> Response:
        tenant = self._web_tenant(request)
        payload = await self._web_payload(request)
        action = payload.get("action")
        resource = payload.get("resource_type")
        if (
            not isinstance(action, str)
            or not action
            or not isinstance(resource, str)
            or not resource
            or len(action) > 100
            or len(resource) > 100
        ):
            raise BusinessOSError("invalid_request", "Action is invalid", status_code=400)
        locator = self._web_locator(payload, tenant)
        if locator is None:
            authorizer = await dependencies.resolve(AUTHORIZER)
            try:
                await authorizer.require(request.context, f"{resource}:{action}")
            except BusinessOSError as error:
                if error.status_code not in {401, 403}:
                    raise
                return Response.json({"allowed": False})
            return Response.json({"allowed": True})
        policy = await dependencies.resolve(POLICY_AUTHORIZATION_V2)
        factory = await dependencies.resolve(UNIT_OF_WORK_FACTORY)
        async with factory.for_tenant(tenant) as transaction:
            decision = await policy.authorize_read(request.context, transaction, action, locator)
        return Response.json({"allowed": decision.evidence.allowed})

    async def _http_field_access(
        self, request: Request, dependencies: RequestDependencyScope
    ) -> Response:
        tenant = self._web_tenant(request)
        payload = await self._web_payload(request)
        field = payload.get("field_name")
        if not isinstance(field, str) or not field or len(field) > 100:
            raise BusinessOSError("invalid_request", "Field is invalid", status_code=400)
        locator = self._web_locator(payload, tenant)
        if locator is None:
            return Response.json({"readable": False, "writable": False, "masked": True})
        policy = await dependencies.resolve(POLICY_AUTHORIZATION_V2)
        factory = await dependencies.resolve(UNIT_OF_WORK_FACTORY)
        async with factory.for_tenant(tenant) as transaction:
            read = await policy.evaluate_field(
                request.context, transaction, locator, field, FieldAccessType.READ
            )
            write = await policy.evaluate_field(
                request.context, transaction, locator, field, FieldAccessType.WRITE
            )
        return Response.json(
            {
                "readable": read.evidence.allowed and read.field_access is not FieldAccessType.DENY,
                "writable": write.evidence.allowed and write.field_access is FieldAccessType.WRITE,
                "masked": read.field_access is FieldAccessType.MASK,
            }
        )

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
        await self.delegation_authority.acquire(cmd.tenant_id, ctx.unit_of_work.persistence)
        if cmd.parent_role_id is not None:
            await _validate_new_role_parent(ctx, cmd.tenant_id, cmd.parent_role_id)
        now = datetime.now(UTC)
        role_id = uuid4()
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
        authority = await SoDAuthority.load(ctx.unit_of_work.persistence, cmd.tenant_id)
        authority.with_role(record)
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
        await self.delegation_authority.acquire(cmd.tenant_id, ctx.unit_of_work.persistence)
        await _require_role(ctx, cmd.tenant_id, cmd.role_id)
        now = datetime.now(UTC)
        rp_id = uuid4()
        record = RolePermissionRecord(
            id=rp_id,
            tenant_id=cmd.tenant_id,
            role_id=cmd.role_id,
            permission_code=cmd.permission_code,
            created_at=now,
        )
        authority = await SoDAuthority.load(ctx.unit_of_work.persistence, cmd.tenant_id)
        authority.reject_new_conflicts(authority.with_permission(record))
        stmt = insert(ROLE_PERMISSIONS).values(
            id=rp_id,
            tenant_id=cmd.tenant_id,
            role_id=cmd.role_id,
            permission_code=cmd.permission_code,
            created_at=now,
        )
        await ctx.unit_of_work.persistence.execute(stmt)
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
        await self.delegation_authority.acquire(cmd.tenant_id, ctx.unit_of_work.persistence)
        await _require_role(ctx, cmd.tenant_id, cmd.role_id)
        _validate_scope(cmd.scope_type, cmd.scope_id)
        _validate_window(cmd.valid_from, cmd.valid_to)
        now = datetime.now(UTC)
        assignment_id = uuid4()
        record = SubjectRoleAssignmentRecord(
            id=assignment_id,
            tenant_id=cmd.tenant_id,
            subject_id=cmd.subject_id,
            subject_type=cmd.subject_type,
            role_id=cmd.role_id,
            scope_type=cmd.scope_type,
            scope_id=cmd.scope_id,
            valid_from=cmd.valid_from,
            valid_to=cmd.valid_to,
            created_at=now,
        )
        authority = await SoDAuthority.load(ctx.unit_of_work.persistence, cmd.tenant_id)
        authority.reject_new_conflicts(authority.with_assignment(record))
        stmt = insert(SUBJECT_ROLE_ASSIGNMENTS).values(
            id=assignment_id,
            tenant_id=cmd.tenant_id,
            subject_id=cmd.subject_id,
            subject_type=cmd.subject_type,
            role_id=cmd.role_id,
            scope_type=cmd.scope_type.value,
            scope_id=cmd.scope_id,
            valid_from=cmd.valid_from,
            valid_to=cmd.valid_to,
            created_at=now,
        )
        await ctx.unit_of_work.persistence.execute(stmt)
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
        await self.delegation_authority.acquire(cmd.tenant_id, ctx.unit_of_work.persistence)
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
        await self.delegation_authority.acquire(cmd.tenant_id, ctx.unit_of_work.persistence)
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
        await self.delegation_authority.acquire(cmd.tenant_id, ctx.unit_of_work.persistence)
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
        if cmd.severity is SoDSeverity.PREVENTATIVE:
            await self.delegation_authority.acquire(cmd.tenant_id, ctx.unit_of_work.persistence)
        now = datetime.now(UTC)
        rule_id = uuid4()
        record = SegregationOfDutiesRuleRecord(
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
        if cmd.severity is SoDSeverity.PREVENTATIVE:
            authority = await SoDAuthority.load(ctx.unit_of_work.persistence, cmd.tenant_id)
            authority.reject_new_conflicts(authority.with_rule(record), new_rule=True)
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
        return record

    async def _create_delegation(
        self, cmd: CreateDelegationCommand, ctx: HandlingContext
    ) -> DelegationGrantRecord:
        tenant = _require_tenant(ctx.request, cmd.tenant_id)
        await self.delegation_authority.acquire(cmd.tenant_id, ctx.unit_of_work.persistence)
        if cmd.delegator_id == cmd.delegatee_id:
            raise BusinessOSError(
                "invalid_delegation", "Delegator and delegatee must differ", status_code=422
            )
        await _require_role(ctx, cmd.tenant_id, cmd.role_id)
        _validate_scope(cmd.scope_type, cmd.scope_id)
        _validate_window(cmd.valid_from, cmd.valid_to)
        if (
            cmd.delegator_type not in {"user", "service_account", "device"}
            or cmd.delegatee_type not in {"user", "service_account", "device"}
            or cmd.valid_from.tzinfo is None
            or cmd.valid_to.tzinfo is None
        ):
            raise BusinessOSError(
                "delegation_authority_missing",
                "Delegation requires verified typed and timezone-aware authority",
                status_code=403,
            )
        authority = await SoDAuthority.load(ctx.unit_of_work.persistence, cmd.tenant_id)
        now = datetime.now(UTC)
        if not has_effective_role_source(
            tenant_id=cmd.tenant_id,
            subject_id=cmd.delegator_id,
            subject_type=cmd.delegator_type,
            role_id=cmd.role_id,
            scope_type=cmd.scope_type,
            scope_id=cmd.scope_id,
            valid_from=cmd.valid_from,
            valid_until=cmd.valid_to,
            evaluated_at=now,
            assignments=list(authority.assignments),
            delegations=list(authority.delegations),
            traversal_budget=[MAX_SOURCE_TRAVERSALS],
        ):
            raise BusinessOSError(
                "delegation_authority_missing",
                "Delegator lacks effective role authority for scope and period",
                status_code=403,
            )
        del_id = uuid4()
        record = DelegationGrantRecord(
            id=del_id,
            tenant_id=cmd.tenant_id,
            delegator_id=cmd.delegator_id,
            delegator_type=cmd.delegator_type,
            delegatee_id=cmd.delegatee_id,
            delegatee_type=cmd.delegatee_type,
            role_id=cmd.role_id,
            scope_type=cmd.scope_type,
            scope_id=cmd.scope_id,
            valid_from=cmd.valid_from,
            valid_to=cmd.valid_to,
            is_revoked=False,
            revocation_reason=None,
            created_at=now,
        )
        authority.reject_new_conflicts(authority.with_delegation(record))
        stmt = insert(DELEGATIONS).values(
            id=del_id,
            tenant_id=cmd.tenant_id,
            delegator_id=cmd.delegator_id,
            delegator_type=cmd.delegator_type,
            delegatee_id=cmd.delegatee_id,
            delegatee_type=cmd.delegatee_type,
            role_id=cmd.role_id,
            scope_type=cmd.scope_type.value,
            scope_id=cmd.scope_id,
            valid_from=cmd.valid_from,
            valid_to=cmd.valid_to,
            is_revoked=False,
            created_at=now,
        )
        await ctx.unit_of_work.persistence.execute(stmt)
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
        await self.delegation_authority.acquire(cmd.tenant_id, ctx.unit_of_work.persistence)
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
        _RetiredV1Authority.deny()

    async def _grant_support_access(
        self, cmd: GrantSupportAccessCommand, ctx: HandlingContext
    ) -> SupportAccessGrantRecord:
        tenant = _require_tenant(ctx.request, cmd.tenant_id)
        await self.delegation_authority.acquire(cmd.tenant_id, ctx.unit_of_work.persistence)
        approver = await ctx.dependencies.resolve(AUTHENTICATED_PRINCIPAL)
        if (
            approver.request is not ctx.request
            or approver.principal.tenant_id != tenant.tenant_id
            or approver.principal.principal_id != tenant.principal_id
            or approver.principal.principal_type not in ("user", "service_account", "device")
        ):
            raise BusinessOSError(
                "principal_mismatch", "Trusted typed approver required", status_code=403
            )
        membership_authority = await ctx.dependencies.resolve(MEMBERSHIP_AUTHORITY)
        approver_type: PrincipalType
        if approver.principal.principal_type == "user":
            approver_type = "user"
        elif approver.principal.principal_type == "service_account":
            approver_type = "service_account"
        else:
            approver_type = "device"
        await membership_authority.lock_current(
            ctx.unit_of_work.persistence,
            tenant.tenant_id,
            PrincipalReference(approver_type, approver.principal.principal_id),
        )
        await membership_authority.lock_current(
            ctx.unit_of_work.persistence,
            tenant.tenant_id,
            PrincipalReference(cmd.support_principal_type, cmd.support_principal_id),
        )
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
                support_principal_type=cmd.support_principal_type,
                approved_by=tenant.principal_id,
                approved_by_type=approver.principal.principal_type,
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
            support_principal_type=cmd.support_principal_type,
            approved_by=tenant.principal_id,
            approved_by_type=approver.principal.principal_type,
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
        await self.delegation_authority.acquire(cmd.tenant_id, ctx.unit_of_work.persistence)
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
        _RetiredV1Authority.deny()

    async def _evaluate_field_access(
        self, query: EvaluateFieldAccessQuery, ctx: HandlingContext
    ) -> FieldAccessDecision:
        _RetiredV1Authority.deny()

    async def _evaluate_approval_limit(
        self, query: EvaluateApprovalLimitQuery, ctx: HandlingContext
    ) -> ApprovalAuthorityDecision:
        _RetiredV1Authority.deny()

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


async def _require_role(ctx: HandlingContext, tenant_id: UUID, role_id: UUID) -> None:
    result = await ctx.unit_of_work.persistence.execute(
        select(ROLES.c.id).where(ROLES.c.tenant_id == tenant_id, ROLES.c.id == role_id)
    )
    if result.scalar_one_or_none() is None:
        raise BusinessOSError("invalid_role", "Role does not belong to the tenant", status_code=422)


async def _validate_new_role_parent(ctx: HandlingContext, tenant_id: UUID, parent_id: UUID) -> None:
    """Keep the new child plus its existing parent chain within V2's bound."""
    seen: set[UUID] = set()
    current: UUID | None = parent_id
    while current is not None:
        if current in seen or len(seen) >= 15:
            raise BusinessOSError(
                "authority_unbounded",
                "Policy role hierarchy is cyclic or too deep",
                status_code=403,
            )
        seen.add(current)
        result = await ctx.unit_of_work.persistence.execute(
            select(ROLES.c.parent_role_id).where(
                ROLES.c.tenant_id == tenant_id, ROLES.c.id == current
            )
        )
        row = result.first()
        if row is None:
            raise BusinessOSError(
                "invalid_role", "Role does not belong to the tenant", status_code=422
            )
        current = row[0]


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
