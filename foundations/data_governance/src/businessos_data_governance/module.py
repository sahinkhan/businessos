"""Data governance, retention, and privacy module registration and handlers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib.resources import files
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert

from businessos.sdk import (
    BusinessOSError,
    Command,
    HandlingContext,
    ModuleManifest,
    ModuleRegistration,
    PermissionDeclaration,
    Query,
    RequestContext,
    TenantContext,
)

from .contracts import (
    ConsentRecorded,
    ConsentRevoked,
    DataGovernanceHooks,
    LegalHoldPlaced,
    LegalHoldReleased,
    RetentionPolicyChanged,
)
from .models import (
    CONSENT_RECORDS,
    DATA_CLASSIFICATIONS,
    LEGAL_HOLDS,
    RETENTION_POLICIES,
    SENSITIVE_FIELD_TAGS,
    ConsentRecordModel,
    ConsentVerificationResult,
    DataClassificationRecord,
    ExpiryAction,
    LegalHoldRecord,
    PurgeEligibilityResult,
    RetentionPolicyRecord,
    SensitiveFieldTagRecord,
)


class RegisterDataClassificationCommand(Command):
    code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    sensitivity_level: int = Field(ge=1, le=5)
    description: str = Field(default="", max_length=500)


class CreateRetentionPolicyCommand(Command):
    tenant_id: UUID
    code: str = Field(min_length=2, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    entity_type: str = Field(min_length=1, max_length=100)
    classification_code: str = Field(min_length=2, max_length=50)
    retention_period_days: int = Field(ge=1)
    action_on_expiry: ExpiryAction = ExpiryAction.ARCHIVE


class PlaceLegalHoldCommand(Command):
    tenant_id: UUID
    code: str = Field(min_length=2, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=1000)
    entity_type: str = Field(min_length=1, max_length=100)
    entity_id: str | None = Field(default=None, max_length=255)
    placed_by: str = Field(min_length=1, max_length=100)


class ReleaseLegalHoldCommand(Command):
    tenant_id: UUID
    hold_id: UUID
    released_by: str = Field(min_length=1, max_length=100)


class RecordConsentCommand(Command):
    tenant_id: UUID
    subject_id: UUID
    purpose_code: str = Field(min_length=1, max_length=100)
    expires_at: datetime | None = None


class RevokeConsentCommand(Command):
    tenant_id: UUID
    consent_id: UUID


class TagSensitiveFieldCommand(Command):
    tenant_id: UUID
    entity_type: str = Field(min_length=1, max_length=100)
    field_name: str = Field(min_length=1, max_length=100)
    classification_code: str = Field(min_length=2, max_length=50)
    is_masked_by_default: bool = False
    description: str = Field(default="", max_length=500)


class CheckPurgeEligibilityQuery(Query):
    tenant_id: UUID
    entity_type: str
    entity_id: str
    record_age_days: int


class VerifyConsentQuery(Query):
    tenant_id: UUID
    subject_id: UUID
    purpose_code: str


class GetSensitiveFieldTagsQuery(Query):
    tenant_id: UUID
    entity_type: str


class DataGovernanceModule:
    version: str = "1"

    def __init__(self) -> None:
        data = json.loads(
            files("businessos_data_governance")
            .joinpath("manifest.json")
            .read_text(encoding="utf-8")
        )
        self.manifest = ModuleManifest.model_validate(data)
        self.hooks = DataGovernanceHooks()

    async def register(self, registration: ModuleRegistration) -> None:
        registration.contract("foundation.governance.retention-policy.v1", self)
        registration.contract("foundation.governance.export-delete-hooks.v1", self.hooks)
        registration.permission(
            PermissionDeclaration(
                key="foundation.governance.read",
                description="Read governance rules and classifications",
            )
        )
        registration.permission(
            PermissionDeclaration(
                key="foundation.governance.manage",
                description="Manage retention policies and field tags",
            )
        )
        registration.permission(
            PermissionDeclaration(
                key="foundation.governance.hold", description="Place and release legal holds"
            )
        )
        registration.permission(
            PermissionDeclaration(
                key="foundation.governance.erase",
                description="Authorize and execute subject data erasure",
            )
        )

        registration.command(
            RegisterDataClassificationCommand,
            self._register_classification,
            permission="foundation.governance.manage",
        )
        registration.command(
            CreateRetentionPolicyCommand,
            self._create_retention_policy,
            permission="foundation.governance.manage",
        )
        registration.command(
            PlaceLegalHoldCommand, self._place_legal_hold, permission="foundation.governance.hold"
        )
        registration.command(
            ReleaseLegalHoldCommand,
            self._release_legal_hold,
            permission="foundation.governance.hold",
        )
        registration.command(
            RecordConsentCommand, self._record_consent, permission="foundation.governance.manage"
        )
        registration.command(
            RevokeConsentCommand, self._revoke_consent, permission="foundation.governance.manage"
        )
        registration.command(
            TagSensitiveFieldCommand,
            self._tag_sensitive_field,
            permission="foundation.governance.manage",
        )

        registration.query(
            CheckPurgeEligibilityQuery,
            self._check_purge_eligibility,
            permission="foundation.governance.read",
        )
        registration.query(
            VerifyConsentQuery, self._verify_consent, permission="foundation.governance.read"
        )
        registration.query(
            GetSensitiveFieldTagsQuery,
            self._get_sensitive_fields,
            permission="foundation.governance.read",
        )

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def _register_classification(
        self, cmd: RegisterDataClassificationCommand, ctx: HandlingContext
    ) -> DataClassificationRecord:
        stmt = (
            insert(DATA_CLASSIFICATIONS)
            .values(
                code=cmd.code,
                name=cmd.name,
                sensitivity_level=cmd.sensitivity_level,
                description=cmd.description,
            )
            .on_conflict_do_update(
                index_elements=[DATA_CLASSIFICATIONS.c.code],
                set_=dict(
                    name=cmd.name,
                    sensitivity_level=cmd.sensitivity_level,
                    description=cmd.description,
                ),
            )
        )
        await ctx.unit_of_work.persistence.execute(stmt)
        return DataClassificationRecord(
            code=cmd.code,
            name=cmd.name,
            sensitivity_level=cmd.sensitivity_level,
            description=cmd.description,
        )

    async def _create_retention_policy(
        self, cmd: CreateRetentionPolicyCommand, ctx: HandlingContext
    ) -> RetentionPolicyRecord:
        tenant = _require_tenant(ctx.request, cmd.tenant_id)
        now = datetime.now(UTC)
        policy_id = uuid4()
        stmt = insert(RETENTION_POLICIES).values(
            id=policy_id,
            tenant_id=cmd.tenant_id,
            code=cmd.code,
            name=cmd.name,
            entity_type=cmd.entity_type,
            classification_code=cmd.classification_code,
            retention_period_days=cmd.retention_period_days,
            action_on_expiry=cmd.action_on_expiry.value,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        await ctx.unit_of_work.persistence.execute(stmt)
        record = RetentionPolicyRecord(
            id=policy_id,
            tenant_id=cmd.tenant_id,
            code=cmd.code,
            name=cmd.name,
            entity_type=cmd.entity_type,
            classification_code=cmd.classification_code,
            retention_period_days=cmd.retention_period_days,
            action_on_expiry=cmd.action_on_expiry,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        ctx.emit(
            RetentionPolicyChanged(
                tenant_id=tenant.tenant_id,
                correlation_id=ctx.request.correlation_id,
                policy_id=policy_id,
                code=cmd.code,
                entity_type=cmd.entity_type,
            )
        )
        return record

    async def _place_legal_hold(
        self, cmd: PlaceLegalHoldCommand, ctx: HandlingContext
    ) -> LegalHoldRecord:
        tenant = _require_tenant(ctx.request, cmd.tenant_id)
        now = datetime.now(UTC)
        hold_id = uuid4()
        stmt = insert(LEGAL_HOLDS).values(
            id=hold_id,
            tenant_id=cmd.tenant_id,
            code=cmd.code,
            name=cmd.name,
            reason=cmd.reason,
            entity_type=cmd.entity_type,
            entity_id=cmd.entity_id,
            placed_by=cmd.placed_by,
            placed_at=now,
            is_active=True,
        )
        await ctx.unit_of_work.persistence.execute(stmt)
        record = LegalHoldRecord(
            id=hold_id,
            tenant_id=cmd.tenant_id,
            code=cmd.code,
            name=cmd.name,
            reason=cmd.reason,
            entity_type=cmd.entity_type,
            entity_id=cmd.entity_id,
            placed_by=cmd.placed_by,
            placed_at=now,
            is_active=True,
        )
        ctx.emit(
            LegalHoldPlaced(
                tenant_id=tenant.tenant_id,
                correlation_id=ctx.request.correlation_id,
                hold_id=hold_id,
                code=cmd.code,
                entity_type=cmd.entity_type,
                entity_id=cmd.entity_id,
            )
        )
        return record

    async def _release_legal_hold(self, cmd: ReleaseLegalHoldCommand, ctx: HandlingContext) -> None:
        tenant = _require_tenant(ctx.request, cmd.tenant_id)
        now = datetime.now(UTC)
        stmt = (
            update(LEGAL_HOLDS)
            .where(LEGAL_HOLDS.c.id == cmd.hold_id)
            .where(LEGAL_HOLDS.c.tenant_id == cmd.tenant_id)
            .where(LEGAL_HOLDS.c.is_active.is_(True))
            .values(is_active=False, released_by=cmd.released_by, released_at=now)
            .returning(LEGAL_HOLDS.c.code)
        )
        res = await ctx.unit_of_work.persistence.execute(stmt)
        row = res.first()
        if row is None:
            raise BusinessOSError(
                "not_found", f"Active legal hold {cmd.hold_id} not found", status_code=404
            )
        ctx.emit(
            LegalHoldReleased(
                tenant_id=tenant.tenant_id,
                correlation_id=ctx.request.correlation_id,
                hold_id=cmd.hold_id,
                code=row.code,
                released_by=cmd.released_by,
            )
        )

    async def _record_consent(
        self, cmd: RecordConsentCommand, ctx: HandlingContext
    ) -> ConsentRecordModel:
        tenant = _require_tenant(ctx.request, cmd.tenant_id)
        now = datetime.now(UTC)
        consent_id = uuid4()
        stmt = insert(CONSENT_RECORDS).values(
            id=consent_id,
            tenant_id=cmd.tenant_id,
            subject_id=cmd.subject_id,
            purpose_code=cmd.purpose_code,
            granted_at=now,
            expires_at=cmd.expires_at,
            is_active=True,
        )
        await ctx.unit_of_work.persistence.execute(stmt)
        record = ConsentRecordModel(
            id=consent_id,
            tenant_id=cmd.tenant_id,
            subject_id=cmd.subject_id,
            purpose_code=cmd.purpose_code,
            granted_at=now,
            expires_at=cmd.expires_at,
            is_active=True,
        )
        ctx.emit(
            ConsentRecorded(
                tenant_id=tenant.tenant_id,
                correlation_id=ctx.request.correlation_id,
                consent_id=consent_id,
                subject_id=cmd.subject_id,
                purpose_code=cmd.purpose_code,
            )
        )
        return record

    async def _revoke_consent(self, cmd: RevokeConsentCommand, ctx: HandlingContext) -> None:
        tenant = _require_tenant(ctx.request, cmd.tenant_id)
        now = datetime.now(UTC)
        stmt = (
            update(CONSENT_RECORDS)
            .where(CONSENT_RECORDS.c.id == cmd.consent_id)
            .where(CONSENT_RECORDS.c.tenant_id == cmd.tenant_id)
            .where(CONSENT_RECORDS.c.is_active.is_(True))
            .values(is_active=False, revoked_at=now)
            .returning(CONSENT_RECORDS.c.subject_id, CONSENT_RECORDS.c.purpose_code)
        )
        res = await ctx.unit_of_work.persistence.execute(stmt)
        row = res.first()
        if row is None:
            raise BusinessOSError(
                "not_found", f"Active consent record {cmd.consent_id} not found", status_code=404
            )
        ctx.emit(
            ConsentRevoked(
                tenant_id=tenant.tenant_id,
                correlation_id=ctx.request.correlation_id,
                consent_id=cmd.consent_id,
                subject_id=row.subject_id,
                purpose_code=row.purpose_code,
            )
        )

    async def _tag_sensitive_field(
        self, cmd: TagSensitiveFieldCommand, ctx: HandlingContext
    ) -> SensitiveFieldTagRecord:
        _require_tenant(ctx.request, cmd.tenant_id)
        tag_id = uuid4()
        stmt = (
            insert(SENSITIVE_FIELD_TAGS)
            .values(
                id=tag_id,
                tenant_id=cmd.tenant_id,
                entity_type=cmd.entity_type,
                field_name=cmd.field_name,
                classification_code=cmd.classification_code,
                is_masked_by_default=cmd.is_masked_by_default,
                description=cmd.description,
            )
            .on_conflict_do_update(
                index_elements=[
                    SENSITIVE_FIELD_TAGS.c.tenant_id,
                    SENSITIVE_FIELD_TAGS.c.entity_type,
                    SENSITIVE_FIELD_TAGS.c.field_name,
                ],
                set_=dict(
                    classification_code=cmd.classification_code,
                    is_masked_by_default=cmd.is_masked_by_default,
                    description=cmd.description,
                ),
            )
        )
        await ctx.unit_of_work.persistence.execute(stmt)
        return SensitiveFieldTagRecord(
            id=tag_id,
            tenant_id=cmd.tenant_id,
            entity_type=cmd.entity_type,
            field_name=cmd.field_name,
            classification_code=cmd.classification_code,
            is_masked_by_default=cmd.is_masked_by_default,
            description=cmd.description,
        )

    async def _check_purge_eligibility(
        self, query: CheckPurgeEligibilityQuery, ctx: HandlingContext
    ) -> PurgeEligibilityResult:
        _require_tenant(ctx.request, query.tenant_id)
        # First check active legal holds
        holds_stmt = (
            select(LEGAL_HOLDS)
            .where(LEGAL_HOLDS.c.tenant_id == query.tenant_id)
            .where(LEGAL_HOLDS.c.entity_type == query.entity_type)
            .where(LEGAL_HOLDS.c.is_active.is_(True))
            .where(
                or_(
                    LEGAL_HOLDS.c.entity_id == query.entity_id,
                    LEGAL_HOLDS.c.entity_id.is_(None),
                )
            )
        )
        holds_res = await ctx.unit_of_work.persistence.execute(holds_stmt)
        active_holds = [f"[{h.code}] {h.name}: {h.reason}" for h in holds_res]
        if active_holds:
            return PurgeEligibilityResult(
                can_purge=False,
                reason="Cannot purge: entity is protected under active legal hold",
                active_holds=active_holds,
            )

        # Check retention policy
        pol_stmt = (
            select(RETENTION_POLICIES)
            .where(RETENTION_POLICIES.c.tenant_id == query.tenant_id)
            .where(RETENTION_POLICIES.c.entity_type == query.entity_type)
            .where(RETENTION_POLICIES.c.is_active.is_(True))
        )
        pol_res = await ctx.unit_of_work.persistence.execute(pol_stmt)
        policy = pol_res.first()
        if not policy:
            return PurgeEligibilityResult(
                can_purge=False,
                reason="No active retention policy defined for entity type",
                active_holds=[],
            )

        if query.record_age_days < policy.retention_period_days:
            return PurgeEligibilityResult(
                can_purge=False,
                reason=(
                    f"Record age ({query.record_age_days} days) has not exceeded retention "
                    f"period ({policy.retention_period_days} days)"
                ),
                active_holds=[],
            )

        return PurgeEligibilityResult(
            can_purge=True,
            reason=(
                f"Eligible for {policy.action_on_expiry}: record age "
                f"{query.record_age_days} exceeds {policy.retention_period_days} days"
            ),
            active_holds=[],
        )

    async def _verify_consent(
        self, query: VerifyConsentQuery, ctx: HandlingContext
    ) -> ConsentVerificationResult:
        _require_tenant(ctx.request, query.tenant_id)
        now = datetime.now(UTC)
        stmt = (
            select(CONSENT_RECORDS)
            .where(CONSENT_RECORDS.c.tenant_id == query.tenant_id)
            .where(CONSENT_RECORDS.c.subject_id == query.subject_id)
            .where(CONSENT_RECORDS.c.purpose_code == query.purpose_code)
            .where(CONSENT_RECORDS.c.is_active.is_(True))
        )
        res = await ctx.unit_of_work.persistence.execute(stmt)
        row = res.first()
        if not row:
            return ConsentVerificationResult(
                has_consent=False, reason="No active consent record for subject and purpose"
            )

        if row.expires_at and row.expires_at < now:
            return ConsentVerificationResult(has_consent=False, reason="Consent has expired")

        return ConsentVerificationResult(has_consent=True, reason="Valid active consent verified")

    async def _get_sensitive_fields(
        self, query: GetSensitiveFieldTagsQuery, ctx: HandlingContext
    ) -> list[SensitiveFieldTagRecord]:
        _require_tenant(ctx.request, query.tenant_id)
        stmt = (
            select(SENSITIVE_FIELD_TAGS)
            .where(SENSITIVE_FIELD_TAGS.c.tenant_id == query.tenant_id)
            .where(SENSITIVE_FIELD_TAGS.c.entity_type == query.entity_type)
        )
        res = await ctx.unit_of_work.persistence.execute(stmt)
        return [SensitiveFieldTagRecord.model_validate(dict(row)) for row in res.mappings()]


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
