"""Transaction-bound retention authority and destructive lifecycle coordination.

The owner operation provider owns its row and mutation. Governance owns only
policy, hold, and decision state. All three use the handler's existing UOW.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import cast
from uuid import UUID, uuid4

from businessos_audit.v2_contracts import AUDIT_APPENDER_V2, AuditEvidenceV2
from businessos_identity import AUTHENTICATED_PRINCIPAL
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    func,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from businessos.sdk import (
    RESOURCE_OWNER_RESOLVER,
    BusinessOSError,
    Command,
    DomainEvent,
    HandlerInvocationKind,
    HandlerTransaction,
    HandlingContext,
    ResourceLocator,
    ResourceOwnerFacts,
    validate_handler_invocation,
)

from .models import LEGAL_HOLDS, ExpiryAction

metadata = MetaData()

POLICIES_V2 = Table(
    "retention_policies_v2",
    metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", PG_UUID(as_uuid=True), nullable=False),
    Column("owner_module_id", String(150), nullable=False),
    Column("resource_namespace", String(200), nullable=False),
    Column("entity_type", String(100), nullable=False),
    Column("retention_category", String(100), nullable=False),
    Column("retention_period_days", Integer, nullable=False),
    Column("action_on_expiry", String(20), nullable=False),
    Column("valid_from", DateTime(timezone=True), nullable=False),
    Column("valid_until", DateTime(timezone=True)),
    Column("is_active", Boolean, nullable=False, server_default="true"),
    CheckConstraint("retention_period_days > 0", name="ck_retention_v2_positive_days"),
    CheckConstraint(
        "valid_until IS NULL OR valid_until > valid_from", name="ck_retention_v2_interval"
    ),
    schema="platform_gov",
)

HOLDS_V2 = Table(
    "legal_holds_v2",
    metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", PG_UUID(as_uuid=True), nullable=False),
    Column("owner_module_id", String(150), nullable=False),
    Column("resource_namespace", String(200), nullable=False),
    Column("entity_type", String(100), nullable=False),
    Column("hold_scope", String(10), nullable=False),
    Column("record_id", PG_UUID(as_uuid=True)),
    Column("retention_category", String(100)),
    Column("reason", Text, nullable=False),
    Column("placed_at", DateTime(timezone=True), nullable=False),
    Column("released_at", DateTime(timezone=True)),
    Column("is_active", Boolean, nullable=False, server_default="true"),
    CheckConstraint(
        "(hold_scope = 'ALL' AND record_id IS NULL) OR "
        "(hold_scope = 'RECORD' AND record_id IS NOT NULL)",
        name="ck_hold_v2_scope",
    ),
    schema="platform_gov",
)

DECISIONS_V2 = Table(
    "destructive_decisions_v2",
    metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", PG_UUID(as_uuid=True), nullable=False),
    Column("owner_module_id", String(150), nullable=False),
    Column("resource_namespace", String(200), nullable=False),
    Column("entity_type", String(100), nullable=False),
    Column("record_id", PG_UUID(as_uuid=True), nullable=False),
    Column("policy_id", PG_UUID(as_uuid=True), nullable=False),
    Column("action", String(20), nullable=False),
    Column("decided_at", DateTime(timezone=True), nullable=False),
    Column("external_cleanup_status", String(20), nullable=False),
    schema="platform_gov",
)


class RetentionSubjectKey(BaseModel):
    """Category-independent canonical identity supplied before owner facts."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    tenant_id: UUID
    owner_module_id: str = Field(min_length=1, max_length=150)
    resource_namespace: str = Field(min_length=1, max_length=200)
    contract_version: str = Field(min_length=1, max_length=30)
    entity_type: str = Field(min_length=1, max_length=100)
    record_id: UUID

    def locator(self) -> ResourceLocator:
        return ResourceLocator(
            self.resource_namespace, self.contract_version, self.record_id, self.tenant_id
        )


@dataclass(frozen=True, slots=True)
class PurgeSubjectFacts:
    key: RetentionSubjectKey
    retention_category: str
    retention_anchor_at: datetime
    lifecycle: str
    supported_actions: frozenset[str]


def normalize_owner_facts(key: RetentionSubjectKey, value: ResourceOwnerFacts) -> PurgeSubjectFacts:
    """Reject missing or forged facts from an otherwise admitted owner provider."""
    category = value.facts.get("retention_category")
    anchor = value.facts.get("retention_anchor_at")
    entity_type = value.facts.get("entity_type")
    supported_actions = value.facts.get("supported_actions")
    if (
        value.tenant_id != key.tenant_id
        or value.namespace != key.resource_namespace
        or value.owner_module_id != key.owner_module_id
        or value.record_id != key.record_id
        or value.contract_version != key.contract_version
        or value.lifecycle != "current"
        or type(entity_type) is not str
        or entity_type != key.entity_type
        or type(category) is not str
        or not category
        or len(category) > 100
        or type(anchor) is not datetime
        or anchor.tzinfo is None
        or anchor.utcoffset() != timedelta(0)
        or type(supported_actions) is not frozenset
        or not supported_actions.issubset({action.value for action in ExpiryAction})
    ):
        raise BusinessOSError(
            "retention_facts_invalid",
            "Locked owner facts are incomplete or inconsistent",
            status_code=409,
        )
    return PurgeSubjectFacts(
        key,
        category,
        anchor.astimezone(UTC),
        value.lifecycle,
        cast(frozenset[str], supported_actions),
    )


class HoldScope(StrEnum):
    ALL = "all"
    RECORD = "record"


class SetRetentionPolicyV2(Command):
    model_config = ConfigDict(frozen=True, extra="forbid")
    tenant_id: UUID
    owner_module_id: str
    resource_namespace: str
    contract_version: str
    entity_type: str
    retention_category: str
    retention_period_days: int = Field(ge=1)
    action_on_expiry: ExpiryAction
    valid_from: datetime
    valid_until: datetime | None = None

    @model_validator(mode="after")
    def valid_interval(self) -> SetRetentionPolicyV2:
        _utc(self.valid_from)
        if self.valid_until is not None and _utc(self.valid_until) <= _utc(self.valid_from):
            raise ValueError("Policy interval must be nonempty")
        return self


class ReplaceRetentionPolicyV2(Command):
    """Future-only, non-weakening transition within one policy scope."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    tenant_id: UUID
    old_policy_id: UUID
    owner_module_id: str
    resource_namespace: str
    contract_version: str
    entity_type: str
    retention_category: str
    retention_period_days: int = Field(ge=1)
    action_on_expiry: ExpiryAction
    effective_at: datetime

    @model_validator(mode="after")
    def valid_instant(self) -> ReplaceRetentionPolicyV2:
        _utc(self.effective_at)
        return self


class PlaceRetentionHoldV2(Command):
    model_config = ConfigDict(frozen=True, extra="forbid")
    subject: RetentionSubjectKey
    scope: HoldScope
    reason: str = Field(min_length=1, max_length=1000)
    retention_category: str | None = None


class ReleaseRetentionHoldV2(Command):
    model_config = ConfigDict(frozen=True, extra="forbid")
    tenant_id: UUID
    hold_id: UUID


class ExecuteDestructiveLifecycleV2(Command):
    model_config = ConfigDict(frozen=True, extra="forbid")
    subject: RetentionSubjectKey
    action: ExpiryAction


class DestructiveCleanupRequestedV2(DomainEvent):
    event_type = "governance.destructive.cleanup_requested.v2"
    decision_id: UUID
    owner_module_id: str
    resource_namespace: str
    entity_type: str
    record_id: UUID
    action: ExpiryAction


class RecordDestructiveCleanupResultV2(Command):
    model_config = ConfigDict(frozen=True, extra="forbid")
    tenant_id: UUID
    decision_id: UUID
    completed: bool


def _utc(instant: datetime) -> datetime:
    if instant.tzinfo is None or instant.utcoffset() != timedelta(0):
        raise ValueError("An aware UTC instant is required")
    return instant.astimezone(UTC)


def _tenant(ctx: HandlingContext, tenant_id: UUID) -> None:
    if ctx.request.tenant is None or ctx.request.tenant.tenant_id != tenant_id:
        raise BusinessOSError("tenant_mismatch", "Tenant identity mismatch", status_code=403)


def _require_governance_invocation(ctx: HandlingContext) -> None:
    binding = validate_handler_invocation(
        ctx.invocation,
        ctx.request,
        ctx.unit_of_work,
        invocation_kind=HandlerInvocationKind.COMMAND,
    )
    if binding.owner_module_id != "foundation.data_governance":
        raise PermissionError("Retention V2 requires its owning Governance command")


async def lock_governance_scope(
    transaction: HandlerTransaction, scope: str, *parts: object
) -> None:
    # A hash collision only causes extra serialization. It cannot weaken exclusion.
    key = "\x1f".join(("adr017", scope, *(str(part) for part in parts)))
    await transaction.persistence.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key}
    )


async def lock_retention_subject(
    transaction: HandlerTransaction, subject: RetentionSubjectKey
) -> None:
    """Public owner-mutation lock: entity gate, then category-free subject lock.

    Owners changing category, anchor, or destructive lifecycle facts must call
    this before locking their own row. It is also used by Governance.
    """
    await lock_governance_scope(
        transaction, "entity", subject.tenant_id, subject.owner_module_id, subject.entity_type
    )
    await lock_governance_scope(
        transaction,
        "subject",
        subject.tenant_id,
        subject.owner_module_id,
        subject.resource_namespace,
        subject.entity_type,
        subject.record_id,
    )
    await lock_governance_scope(
        transaction, "legacy-hold-entity", subject.tenant_id, subject.entity_type
    )


async def _policy_lock(
    transaction: HandlerTransaction, subject: RetentionSubjectKey, category: str
) -> None:
    await lock_governance_scope(
        transaction,
        "policy",
        subject.tenant_id,
        subject.owner_module_id,
        subject.resource_namespace,
        subject.entity_type,
        category,
    )


class RetentionRuntimeV2:
    """Three separate public contracts, each bound to the active handler UOW."""

    version: str = "2"

    async def set_policy(self, cmd: SetRetentionPolicyV2, ctx: HandlingContext) -> UUID:
        _require_governance_invocation(ctx)
        _tenant(ctx, cmd.tenant_id)
        resolver = await ctx.dependencies.resolve(RESOURCE_OWNER_RESOLVER)
        binding = resolver.resolve_owner(cmd.resource_namespace, cmd.contract_version)
        if binding.ownership.owner_module_id != cmd.owner_module_id:
            raise BusinessOSError("owner_mismatch", "Unknown canonical owner", status_code=409)
        key = RetentionSubjectKey(
            tenant_id=cmd.tenant_id,
            owner_module_id=cmd.owner_module_id,
            resource_namespace=cmd.resource_namespace,
            contract_version=cmd.contract_version,
            entity_type=cmd.entity_type,
            record_id=UUID(int=0),
        )
        facts_provider = await resolver.resolve_provider(
            key.locator(), "facts", ctx.request, ctx.unit_of_work
        )
        if key.entity_type not in facts_provider.declared_entity_types:
            raise BusinessOSError(
                "entity_type_unclaimed",
                "Owner did not declare this entity type",
                status_code=409,
            )
        await _policy_lock(ctx.unit_of_work, key, cmd.retention_category)
        policy_id = uuid4()
        try:
            await ctx.unit_of_work.persistence.execute(
                insert(POLICIES_V2).values(
                    id=policy_id,
                    tenant_id=cmd.tenant_id,
                    owner_module_id=cmd.owner_module_id,
                    resource_namespace=cmd.resource_namespace,
                    entity_type=cmd.entity_type,
                    retention_category=cmd.retention_category,
                    retention_period_days=cmd.retention_period_days,
                    action_on_expiry=cmd.action_on_expiry.value,
                    valid_from=_utc(cmd.valid_from),
                    valid_until=_utc(cmd.valid_until) if cmd.valid_until else None,
                    is_active=True,
                )
            )
        except IntegrityError as exc:
            raise BusinessOSError(
                "retention_policy_conflict",
                "Retention policy interval overlaps or is invalid",
                status_code=409,
            ) from exc
        return policy_id

    async def replace_policy(self, cmd: ReplaceRetentionPolicyV2, ctx: HandlingContext) -> UUID:
        _require_governance_invocation(ctx)
        _tenant(ctx, cmd.tenant_id)
        resolver = await ctx.dependencies.resolve(RESOURCE_OWNER_RESOLVER)
        binding = resolver.resolve_owner(cmd.resource_namespace, cmd.contract_version)
        if binding.ownership.owner_module_id != cmd.owner_module_id:
            raise BusinessOSError("owner_mismatch", "Unknown canonical owner", status_code=409)
        key = RetentionSubjectKey(
            tenant_id=cmd.tenant_id,
            owner_module_id=cmd.owner_module_id,
            resource_namespace=cmd.resource_namespace,
            contract_version=cmd.contract_version,
            entity_type=cmd.entity_type,
            record_id=UUID(int=0),
        )
        facts_provider = await resolver.resolve_provider(
            key.locator(), "facts", ctx.request, ctx.unit_of_work
        )
        if key.entity_type not in facts_provider.declared_entity_types:
            raise BusinessOSError(
                "entity_type_unclaimed",
                "Owner did not declare this entity type",
                status_code=409,
            )
        await _policy_lock(ctx.unit_of_work, key, cmd.retention_category)
        now = datetime.now(UTC)
        transition_at = _utc(cmd.effective_at)
        result = await ctx.unit_of_work.persistence.execute(
            select(POLICIES_V2)
            .where(
                POLICIES_V2.c.id == cmd.old_policy_id,
                POLICIES_V2.c.tenant_id == cmd.tenant_id,
                POLICIES_V2.c.owner_module_id == cmd.owner_module_id,
                POLICIES_V2.c.resource_namespace == cmd.resource_namespace,
                POLICIES_V2.c.entity_type == cmd.entity_type,
                POLICIES_V2.c.retention_category == cmd.retention_category,
                POLICIES_V2.c.is_active.is_(True),
            )
            .with_for_update()
        )
        old = result.first()
        if (
            old is None
            or transition_at <= now
            or transition_at <= old.valid_from
            or (old.valid_until is not None and transition_at >= old.valid_until)
            or cmd.retention_period_days < old.retention_period_days
            or cmd.action_on_expiry.value != old.action_on_expiry
        ):
            raise BusinessOSError(
                "retention_transition_invalid",
                "Policy replacement must be future-only and non-weakening",
                status_code=409,
            )
        await ctx.unit_of_work.persistence.execute(
            update(POLICIES_V2)
            .where(POLICIES_V2.c.id == cmd.old_policy_id, POLICIES_V2.c.tenant_id == cmd.tenant_id)
            .values(valid_until=transition_at)
        )
        new_id = uuid4()
        await ctx.unit_of_work.persistence.execute(
            insert(POLICIES_V2).values(
                id=new_id,
                tenant_id=cmd.tenant_id,
                owner_module_id=cmd.owner_module_id,
                resource_namespace=cmd.resource_namespace,
                entity_type=cmd.entity_type,
                retention_category=cmd.retention_category,
                retention_period_days=cmd.retention_period_days,
                action_on_expiry=cmd.action_on_expiry.value,
                valid_from=transition_at,
                valid_until=old.valid_until,
                is_active=True,
            )
        )
        return new_id

    async def place_hold(self, cmd: PlaceRetentionHoldV2, ctx: HandlingContext) -> UUID:
        _require_governance_invocation(ctx)
        key = cmd.subject
        _tenant(ctx, key.tenant_id)
        resolver = await ctx.dependencies.resolve(RESOURCE_OWNER_RESOLVER)
        binding = resolver.resolve_owner(key.resource_namespace, key.contract_version)
        if binding.ownership.owner_module_id != key.owner_module_id:
            raise BusinessOSError("owner_mismatch", "Unknown canonical owner", status_code=409)
        # Entity-wide placement serializes with every subject operation.
        await lock_governance_scope(
            ctx.unit_of_work, "entity", key.tenant_id, key.owner_module_id, key.entity_type
        )
        if cmd.scope is HoldScope.RECORD:
            await lock_governance_scope(
                ctx.unit_of_work,
                "subject",
                key.tenant_id,
                key.owner_module_id,
                key.resource_namespace,
                key.entity_type,
                key.record_id,
            )
        provider = await resolver.resolve_provider(
            key.locator(), "facts", ctx.request, ctx.unit_of_work
        )
        if key.entity_type not in provider.declared_entity_types:
            raise BusinessOSError(
                "entity_type_unclaimed",
                "Owner did not declare this entity type",
                status_code=409,
            )
        if cmd.scope is HoldScope.RECORD:
            facts = normalize_owner_facts(key, await provider.read_locked_facts("hold"))
            if (
                cmd.retention_category is not None
                and facts.retention_category != cmd.retention_category
            ):
                raise BusinessOSError(
                    "hold_category_mismatch",
                    "Hold category differs from owner facts",
                    status_code=409,
                )
        hold_id = uuid4()
        await ctx.unit_of_work.persistence.execute(
            insert(HOLDS_V2).values(
                id=hold_id,
                tenant_id=key.tenant_id,
                owner_module_id=key.owner_module_id,
                resource_namespace=key.resource_namespace,
                entity_type=key.entity_type,
                hold_scope=cmd.scope.value.upper(),
                record_id=key.record_id if cmd.scope is HoldScope.RECORD else None,
                retention_category=cmd.retention_category,
                reason=cmd.reason,
                placed_at=datetime.now(UTC),
                is_active=True,
            )
        )
        return hold_id

    async def release_hold(self, cmd: ReleaseRetentionHoldV2, ctx: HandlingContext) -> None:
        _require_governance_invocation(ctx)
        _tenant(ctx, cmd.tenant_id)
        # The lookup is a hint only; re-read after acquiring the canonical gate.
        result = await ctx.unit_of_work.persistence.execute(
            select(HOLDS_V2).where(
                HOLDS_V2.c.id == cmd.hold_id, HOLDS_V2.c.tenant_id == cmd.tenant_id
            )
        )
        hint = result.first()
        if hint is None:
            raise BusinessOSError("hold_missing", "Hold not found", status_code=404)
        await lock_governance_scope(
            ctx.unit_of_work, "entity", cmd.tenant_id, hint.owner_module_id, hint.entity_type
        )
        if hint.hold_scope == HoldScope.RECORD.value.upper():
            await lock_governance_scope(
                ctx.unit_of_work,
                "subject",
                cmd.tenant_id,
                hint.owner_module_id,
                hint.resource_namespace,
                hint.entity_type,
                hint.record_id,
            )
        result = await ctx.unit_of_work.persistence.execute(
            update(HOLDS_V2)
            .where(
                HOLDS_V2.c.id == cmd.hold_id,
                HOLDS_V2.c.tenant_id == cmd.tenant_id,
                HOLDS_V2.c.is_active.is_(True),
            )
            .values(is_active=False, released_at=datetime.now(UTC))
            .returning(HOLDS_V2.c.id)
        )
        if result.first() is None:
            raise BusinessOSError("hold_released", "Hold was already released", status_code=409)

    async def execute(self, cmd: ExecuteDestructiveLifecycleV2, ctx: HandlingContext) -> UUID:
        _require_governance_invocation(ctx)
        key = cmd.subject
        _tenant(ctx, key.tenant_id)
        await lock_retention_subject(ctx.unit_of_work, key)
        resolver = await ctx.dependencies.resolve(RESOURCE_OWNER_RESOLVER)
        facts_provider = await resolver.resolve_provider(
            key.locator(), "facts", ctx.request, ctx.unit_of_work
        )
        if key.entity_type not in facts_provider.declared_entity_types:
            raise BusinessOSError(
                "entity_type_unclaimed",
                "Owner did not declare this entity type",
                status_code=409,
            )
        provider = await resolver.resolve_provider(
            key.locator(), "operation", ctx.request, ctx.unit_of_work
        )
        if provider.binding.ownership.owner_module_id != key.owner_module_id:
            raise BusinessOSError("owner_mismatch", "Unknown canonical owner", status_code=409)
        facts = normalize_owner_facts(key, await provider.validate_operation(cmd.action.value))
        if cmd.action.value not in facts.supported_actions:
            raise BusinessOSError(
                "owner_action_unsupported",
                "Owner facts do not support requested action",
                status_code=409,
            )
        await _policy_lock(ctx.unit_of_work, key, facts.retention_category)
        now = datetime.now(UTC)
        policies = (
            await ctx.unit_of_work.persistence.execute(
                select(POLICIES_V2)
                .where(
                    POLICIES_V2.c.tenant_id == key.tenant_id,
                    POLICIES_V2.c.owner_module_id == key.owner_module_id,
                    POLICIES_V2.c.resource_namespace == key.resource_namespace,
                    POLICIES_V2.c.entity_type == key.entity_type,
                    POLICIES_V2.c.retention_category == facts.retention_category,
                    POLICIES_V2.c.is_active.is_(True),
                    POLICIES_V2.c.valid_from <= now,
                    or_(POLICIES_V2.c.valid_until.is_(None), POLICIES_V2.c.valid_until > now),
                )
                .with_for_update()
            )
        ).all()
        if len(policies) != 1:
            raise BusinessOSError(
                "retention_policy_ambiguous",
                "Exactly one effective policy is required",
                status_code=409,
            )
        policy = policies[0]
        if policy.action_on_expiry != cmd.action.value:
            raise BusinessOSError(
                "retention_action_mismatch",
                "Policy does not authorize requested action",
                status_code=409,
            )
        try:
            eligible_at = facts.retention_anchor_at + timedelta(days=policy.retention_period_days)
        except OverflowError as exc:
            raise BusinessOSError(
                "retention_interval_invalid",
                "Retention eligibility cannot be computed",
                status_code=409,
            ) from exc
        if now < eligible_at:
            raise BusinessOSError(
                "retention_not_elapsed", "Retention period has not elapsed", status_code=409
            )
        holds = (
            await ctx.unit_of_work.persistence.execute(
                select(HOLDS_V2.c.id).where(
                    HOLDS_V2.c.tenant_id == key.tenant_id,
                    HOLDS_V2.c.owner_module_id == key.owner_module_id,
                    HOLDS_V2.c.resource_namespace == key.resource_namespace,
                    HOLDS_V2.c.entity_type == key.entity_type,
                    HOLDS_V2.c.is_active.is_(True),
                    or_(
                        HOLDS_V2.c.hold_scope == HoldScope.ALL.value.upper(),
                        (HOLDS_V2.c.hold_scope == HoldScope.RECORD.value.upper())
                        & (HOLDS_V2.c.record_id == key.record_id),
                    ),
                    or_(
                        HOLDS_V2.c.retention_category.is_(None),
                        HOLDS_V2.c.retention_category == facts.retention_category,
                    ),
                )
            )
        ).first()
        legacy_holds = (
            await ctx.unit_of_work.persistence.execute(
                select(LEGAL_HOLDS.c.id).where(
                    LEGAL_HOLDS.c.tenant_id == key.tenant_id,
                    LEGAL_HOLDS.c.entity_type == key.entity_type,
                    LEGAL_HOLDS.c.is_active.is_(True),
                    or_(
                        LEGAL_HOLDS.c.entity_id.is_(None),
                        func.lower(LEGAL_HOLDS.c.entity_id) == str(key.record_id),
                        ~LEGAL_HOLDS.c.entity_id.op("~*")(
                            "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
                        ),
                    ),
                )
            )
        ).first()
        if holds is not None or legacy_holds is not None:
            raise BusinessOSError(
                "legal_hold_active", "Active legal hold blocks destruction", status_code=409
            )
        decision_id = uuid4()
        appender = await ctx.dependencies.resolve(AUDIT_APPENDER_V2)
        await appender.append(
            AuditEvidenceV2(
                action=f"governance.destructive.{cmd.action.value}",
                resource_type=key.entity_type,
                resource_id=str(key.record_id),
                details={
                    "decision_id": str(decision_id),
                    "policy_id": str(policy.id),
                    "owner_module_id": key.owner_module_id,
                    "resource_namespace": key.resource_namespace,
                    "retention_category": facts.retention_category,
                    "retention_anchor_at": facts.retention_anchor_at.isoformat(),
                    "eligible_at": eligible_at.isoformat(),
                    "decided_at": now.isoformat(),
                    "hold_result": "none_applicable",
                    "owner_lifecycle": facts.lifecycle,
                    "provider_generation": provider.binding.generation.number,
                    "cleanup_status": "pending",
                },
            ),
            ctx,
        )
        # Apply is one-use and bound by ADR-018 to this admitted owner and UOW.
        await provider.apply_operation(cmd.action.value)
        await ctx.unit_of_work.persistence.execute(
            insert(DECISIONS_V2).values(
                id=decision_id,
                tenant_id=key.tenant_id,
                owner_module_id=key.owner_module_id,
                resource_namespace=key.resource_namespace,
                entity_type=key.entity_type,
                record_id=key.record_id,
                policy_id=policy.id,
                action=cmd.action.value,
                decided_at=now,
                external_cleanup_status="pending",
            )
        )
        ctx.emit(
            DestructiveCleanupRequestedV2(
                tenant_id=key.tenant_id,
                correlation_id=ctx.request.correlation_id,
                decision_id=decision_id,
                owner_module_id=key.owner_module_id,
                resource_namespace=key.resource_namespace,
                entity_type=key.entity_type,
                record_id=key.record_id,
                action=cmd.action,
            )
        )
        return decision_id

    async def record_cleanup_result(
        self, cmd: RecordDestructiveCleanupResultV2, ctx: HandlingContext
    ) -> None:
        _require_governance_invocation(ctx)
        _tenant(ctx, cmd.tenant_id)
        principal = await ctx.dependencies.resolve(AUTHENTICATED_PRINCIPAL)
        if (
            principal.request is not ctx.request
            or principal.principal.tenant_id != cmd.tenant_id
            or principal.principal.principal_type != "service_account"
        ):
            raise BusinessOSError(
                "cleanup_actor_invalid", "Trusted cleanup service account required", status_code=403
            )
        status = "completed" if cmd.completed else "failed"
        result = await ctx.unit_of_work.persistence.execute(
            update(DECISIONS_V2)
            .where(
                DECISIONS_V2.c.tenant_id == cmd.tenant_id,
                DECISIONS_V2.c.id == cmd.decision_id,
                DECISIONS_V2.c.external_cleanup_status.in_(("pending", "failed")),
            )
            .values(external_cleanup_status=status)
            .returning(DECISIONS_V2.c.entity_type, DECISIONS_V2.c.record_id)
        )
        decision = result.first()
        if decision is None:
            raise BusinessOSError(
                "cleanup_decision_unavailable",
                "Pending cleanup decision not found",
                status_code=409,
            )
        appender = await ctx.dependencies.resolve(AUDIT_APPENDER_V2)
        await appender.append(
            AuditEvidenceV2(
                action="governance.destructive.cleanup_result",
                resource_type=decision.entity_type,
                resource_id=str(decision.record_id),
                status=status,
                details={"decision_id": str(cmd.decision_id), "cleanup_status": status},
            ),
            ctx,
        )
