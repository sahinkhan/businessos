"""SQLAlchemy and Pydantic boundary models for authorization policies."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

metadata = MetaData()

PERMISSIONS = Table(
    "permissions",
    metadata,
    Column("code", String(100), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("category", String(100), nullable=False),
    Column("description", Text(), nullable=False, server_default=""),
    schema="platform_policy",
)

ROLES = Table(
    "roles",
    metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", PG_UUID(as_uuid=True), nullable=False),
    Column("code", String(100), nullable=False),
    Column("name", String(200), nullable=False),
    Column("description", Text(), nullable=False, server_default=""),
    Column("is_system", Boolean(), nullable=False, server_default="false"),
    Column("parent_role_id", PG_UUID(as_uuid=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "code", name="uq_roles_tenant_code"),
    schema="platform_policy",
)

ROLE_PERMISSIONS = Table(
    "role_permissions",
    metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", PG_UUID(as_uuid=True), nullable=False),
    Column("role_id", PG_UUID(as_uuid=True), ForeignKey("platform_policy.roles.id", ondelete="CASCADE"), nullable=False),
    Column("permission_code", String(100), ForeignKey("platform_policy.permissions.code", ondelete="CASCADE"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "role_id", "permission_code", name="uq_role_permissions_assignment"),
    schema="platform_policy",
)

SUBJECT_ROLE_ASSIGNMENTS = Table(
    "subject_role_assignments",
    metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", PG_UUID(as_uuid=True), nullable=False),
    Column("subject_id", PG_UUID(as_uuid=True), nullable=False),
    Column("role_id", PG_UUID(as_uuid=True), ForeignKey("platform_policy.roles.id", ondelete="CASCADE"), nullable=False),
    Column("scope_type", String(50), nullable=False, server_default="tenant"),
    Column("scope_id", PG_UUID(as_uuid=True), nullable=True),
    Column("valid_from", DateTime(timezone=True), nullable=True),
    Column("valid_to", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="platform_policy",
)

FIELD_POLICIES = Table(
    "field_policies",
    metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", PG_UUID(as_uuid=True), nullable=False),
    Column("resource_type", String(100), nullable=False),
    Column("field_name", String(100), nullable=False),
    Column("role_id", PG_UUID(as_uuid=True), ForeignKey("platform_policy.roles.id", ondelete="CASCADE"), nullable=True),
    Column("access_type", String(30), nullable=False, server_default="read"),
    Column("mask_pattern", String(100), nullable=True),
    Column("condition_expression", Text(), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="platform_policy",
)

APPROVAL_LIMITS = Table(
    "approval_limits",
    metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", PG_UUID(as_uuid=True), nullable=False),
    Column("action_type", String(100), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("amount_limit", Numeric(18, 4), nullable=False),
    Column("role_id", PG_UUID(as_uuid=True), ForeignKey("platform_policy.roles.id", ondelete="CASCADE"), nullable=True),
    Column("subject_id", PG_UUID(as_uuid=True), nullable=True),
    Column("valid_from", DateTime(timezone=True), nullable=True),
    Column("valid_to", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="platform_policy",
)

SOD_RULES = Table(
    "sod_rules",
    metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", PG_UUID(as_uuid=True), nullable=False),
    Column("code", String(100), nullable=False),
    Column("name", String(200), nullable=False),
    Column("permission_a", String(100), nullable=False),
    Column("permission_b", String(100), nullable=False),
    Column("severity", String(30), nullable=False, server_default="preventative"),
    Column("description", Text(), nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "code", name="uq_sod_rules_tenant_code"),
    schema="platform_policy",
)

DELEGATIONS = Table(
    "delegations",
    metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", PG_UUID(as_uuid=True), nullable=False),
    Column("delegator_id", PG_UUID(as_uuid=True), nullable=False),
    Column("delegatee_id", PG_UUID(as_uuid=True), nullable=False),
    Column("role_id", PG_UUID(as_uuid=True), ForeignKey("platform_policy.roles.id", ondelete="CASCADE"), nullable=False),
    Column("scope_type", String(50), nullable=False, server_default="tenant"),
    Column("scope_id", PG_UUID(as_uuid=True), nullable=True),
    Column("valid_from", DateTime(timezone=True), nullable=False),
    Column("valid_to", DateTime(timezone=True), nullable=False),
    Column("is_revoked", Boolean(), nullable=False, server_default="false"),
    Column("revocation_reason", Text(), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="platform_policy",
)


class ScopeType(str, Enum):
    GLOBAL = "global"
    TENANT = "tenant"
    LEGAL_ENTITY = "legal_entity"
    OPERATING_SITE = "operating_site"
    BUSINESS_UNIT = "business_unit"


class FieldAccessType(str, Enum):
    READ = "read"
    WRITE = "write"
    MASK = "mask"
    DENY = "deny"


class SoDSeverity(str, Enum):
    PREVENTATIVE = "preventative"
    DETECTIVE = "detective"


class PermissionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    name: str
    category: str
    description: str = ""


class RoleRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    code: str
    name: str
    description: str = ""
    is_system: bool = False
    parent_role_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class RolePermissionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    role_id: UUID
    permission_code: str
    created_at: datetime


class SubjectRoleAssignmentRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    subject_id: UUID
    role_id: UUID
    scope_type: ScopeType = ScopeType.TENANT
    scope_id: UUID | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    created_at: datetime


class FieldPolicyRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    resource_type: str
    field_name: str
    role_id: UUID | None = None
    access_type: FieldAccessType = FieldAccessType.READ
    mask_pattern: str | None = None
    condition_expression: str | None = None
    created_at: datetime


class ApprovalLimitRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    action_type: str
    currency: str
    amount_limit: Decimal
    role_id: UUID | None = None
    subject_id: UUID | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    created_at: datetime


class SegregationOfDutiesRuleRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    code: str
    name: str
    permission_a: str
    permission_b: str
    severity: SoDSeverity = SoDSeverity.PREVENTATIVE
    description: str = ""
    created_at: datetime


class DelegationGrantRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    delegator_id: UUID
    delegatee_id: UUID
    role_id: UUID
    scope_type: ScopeType = ScopeType.TENANT
    scope_id: UUID | None = None
    valid_from: datetime
    valid_to: datetime
    is_revoked: bool = False
    revocation_reason: str | None = None
    created_at: datetime


# Commands & Evaluation Inputs
class RegisterPermission(BaseModel):
    code: str = Field(min_length=3, max_length=100, pattern=r"^[a-z0-9_.-]+$")
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)


class CreateRole(BaseModel):
    tenant_id: UUID
    code: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=500)
    is_system: bool = False
    parent_role_id: UUID | None = None


class AssignPermissionToRole(BaseModel):
    tenant_id: UUID
    role_id: UUID
    permission_code: str


class AssignRoleToSubject(BaseModel):
    tenant_id: UUID
    subject_id: UUID
    role_id: UUID
    scope_type: ScopeType = ScopeType.TENANT
    scope_id: UUID | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class CreateFieldPolicy(BaseModel):
    tenant_id: UUID
    resource_type: str = Field(min_length=1, max_length=100)
    field_name: str = Field(min_length=1, max_length=100)
    role_id: UUID | None = None
    access_type: FieldAccessType = FieldAccessType.READ
    mask_pattern: str | None = None
    condition_expression: str | None = None


class CreateApprovalLimit(BaseModel):
    tenant_id: UUID
    action_type: str = Field(min_length=1, max_length=100)
    currency: str = Field(min_length=3, max_length=3)
    amount_limit: Decimal = Field(ge=0)
    role_id: UUID | None = None
    subject_id: UUID | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class CreateSoDRule(BaseModel):
    tenant_id: UUID
    code: str = Field(min_length=2, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    permission_a: str
    permission_b: str
    severity: SoDSeverity = SoDSeverity.PREVENTATIVE
    description: str = ""


class CreateDelegation(BaseModel):
    tenant_id: UUID
    delegator_id: UUID
    delegatee_id: UUID
    role_id: UUID
    scope_type: ScopeType = ScopeType.TENANT
    scope_id: UUID | None = None
    valid_from: datetime
    valid_to: datetime


class RevokeDelegation(BaseModel):
    tenant_id: UUID
    delegation_id: UUID
    reason: str = Field(min_length=1, max_length=500)


# Policy Context & Decisions
class PolicyContext(BaseModel):
    tenant_id: UUID
    subject_id: UUID
    legal_entity_id: UUID | None = None
    operating_site_id: UUID | None = None
    business_unit_id: UUID | None = None
    client_ip: str | None = None
    timestamp: datetime = Field(default_factory=datetime.now)
    attributes: dict[str, Any] = Field(default_factory=dict)


class AuthorizationDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    allowed: bool
    reason: str
    matched_policy: str | None = None


class FieldAccessDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    allowed: bool
    access_type: FieldAccessType
    mask_pattern: str | None = None


class ApprovalAuthorityDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    has_authority: bool
    limit: Decimal
    currency: str
    reason: str


class SoDConflictResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    has_conflict: bool
    conflicting_rules: list[str] = Field(default_factory=list)
