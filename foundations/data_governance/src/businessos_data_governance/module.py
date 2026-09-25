"""Data governance, retention, and privacy module registration and handlers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib.resources import files
from uuid import UUID, uuid4

from businessos_policy.v2_contracts import POLICY_CLASSIFICATION_FACTS_V2
from pydantic import ConfigDict, Field
from sqlalchemy import or_, select, text, update
from sqlalchemy.dialects.postgresql import insert

from businessos.sdk import (
    BusinessOSError,
    Command,
    DependencyScope,
    HandlingContext,
    ModuleManifest,
    ModuleRegistration,
    PermissionDeclaration,
    Query,
    RequestContext,
    TenantContext,
)

from .classification_runtime import DataGovernanceClassificationV2
from .classification_v2 import (
    CANONICAL_NAMESPACE,
    CONTRACT_VERSION,
    ClassificationResolutionV2,
    SecurityControls,
    normalize_code,
    parse_ref,
    tenant_ref,
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
from .retention_v2 import (
    DECISIONS_V2,
    ExecuteDestructiveLifecycleV2,
    PlaceRetentionHoldV2,
    RecordDestructiveCleanupResultV2,
    ReleaseRetentionHoldV2,
    ReplaceRetentionPolicyV2,
    RetentionRuntimeV2,
    SetRetentionPolicyV2,
    lock_governance_scope,
)


class RegisterDataClassificationCommand(Command):
    code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    sensitivity_level: int = Field(ge=1, le=5)
    description: str = Field(default="", max_length=500)


class _ClassificationV2Command(Command):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CreateTenantClassificationV2Command(_ClassificationV2Command):
    code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=1, max_length=100)
    sensitivity_level: int = Field(ge=1, le=5)
    required_controls: frozenset[str] = frozenset()
    restrictions: frozenset[str] = frozenset()
    allowed_audience: frozenset[str] | None = None
    mandatory_masking: bool = False


class SetCanonicalOverlayV2Command(_ClassificationV2Command):
    canonical_ref: str
    sensitivity_level: int = Field(ge=1, le=5)
    required_controls: frozenset[str] = frozenset()
    restrictions: frozenset[str] = frozenset()
    allowed_audience: frozenset[str] | None = None
    mandatory_masking: bool | None = None


class DeactivateTenantClassificationV2Command(_ClassificationV2Command):
    qualified_ref: str


class ReviseTenantClassificationV2Command(_ClassificationV2Command):
    qualified_ref: str
    sensitivity_level: int = Field(ge=1, le=5)
    required_controls: frozenset[str] = frozenset()
    restrictions: frozenset[str] = frozenset()
    allowed_audience: frozenset[str] | None = None
    mandatory_masking: bool = False


class ResolveClassificationV2Query(Query):
    qualified_ref: str


class ResolveHistoricalClassificationV2Query(Query):
    qualified_ref: str
    at: datetime


class TagSensitiveFieldV2Command(_ClassificationV2Command):
    entity_type: str = Field(min_length=1, max_length=100)
    field_name: str = Field(min_length=1, max_length=100)
    classification_ref: str
    is_masked_by_default: bool = False
    description: str = Field(default="", max_length=500)


class CreateRetentionPolicyV2Command(_ClassificationV2Command):
    code: str = Field(min_length=2, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    entity_type: str = Field(min_length=1, max_length=100)
    classification_ref: str
    retention_period_days: int = Field(ge=1)
    action_on_expiry: ExpiryAction = ExpiryAction.ARCHIVE


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
        self.classification_v2 = DataGovernanceClassificationV2()
        self.retention_v2 = RetentionRuntimeV2()

    async def register(self, registration: ModuleRegistration) -> None:
        registration.contract(
            "foundation.governance.data-classification.v2", self.classification_v2
        )
        registration.resource_owner_facts(
            CANONICAL_NAMESPACE, CONTRACT_VERSION, self.classification_v2
        )
        registration.dependency(
            POLICY_CLASSIFICATION_FACTS_V2,
            lambda _: self.classification_v2,
            scope=DependencyScope.REQUEST,
        )
        registration.contract("foundation.governance.retention-policy.v1", self)
        registration.contract("foundation.governance.export-delete-hooks.v1", self.hooks)
        registration.contract("foundation.governance.retention-policy.v2", self.retention_v2)
        registration.contract("foundation.governance.purge-authority.v2", self.retention_v2)
        registration.contract("foundation.governance.destructive-lifecycle.v2", self.retention_v2)
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
                key="foundation.governance.classification.history.read",
                description="Read historical classification meaning for audit and review",
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
        registration.permission(
            PermissionDeclaration(
                key="foundation.governance.cleanup.report",
                description="Report externally verified destructive cleanup result",
            )
        )

        registration.command(
            RegisterDataClassificationCommand,
            self._register_classification,
            permission="foundation.governance.manage",
        )
        registration.command(
            CreateTenantClassificationV2Command,
            self._create_tenant_classification_v2,
            permission="foundation.governance.manage",
        )
        registration.command(
            SetCanonicalOverlayV2Command,
            self._set_canonical_overlay_v2,
            permission="foundation.governance.manage",
        )
        registration.command(
            DeactivateTenantClassificationV2Command,
            self._deactivate_tenant_classification_v2,
            permission="foundation.governance.manage",
        )
        registration.command(
            ReviseTenantClassificationV2Command,
            self._revise_tenant_classification_v2,
            permission="foundation.governance.manage",
        )
        registration.command(
            TagSensitiveFieldV2Command,
            self._tag_sensitive_field_v2,
            permission="foundation.governance.manage",
        )
        registration.command(
            CreateRetentionPolicyV2Command,
            self._create_retention_policy_v2,
            permission="foundation.governance.manage",
        )
        registration.command(
            SetRetentionPolicyV2,
            self.retention_v2.set_policy,
            permission="foundation.governance.manage",
        )
        registration.command(
            ReplaceRetentionPolicyV2,
            self.retention_v2.replace_policy,
            permission="foundation.governance.manage",
        )
        registration.command(
            PlaceRetentionHoldV2,
            self.retention_v2.place_hold,
            permission="foundation.governance.hold",
        )
        registration.command(
            ReleaseRetentionHoldV2,
            self.retention_v2.release_hold,
            permission="foundation.governance.hold",
        )
        registration.command(
            ExecuteDestructiveLifecycleV2,
            self.retention_v2.execute,
            permission="foundation.governance.erase",
        )
        registration.command(
            RecordDestructiveCleanupResultV2,
            self.retention_v2.record_cleanup_result,
            permission="foundation.governance.cleanup.report",
        )
        registration.query(
            ResolveClassificationV2Query,
            self._resolve_classification_v2,
            permission="foundation.governance.read",
        )
        registration.query(
            ResolveHistoricalClassificationV2Query,
            self._resolve_historical_classification_v2,
            permission="foundation.governance.classification.history.read",
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
        raise BusinessOSError(
            "classification_v1_write_retired",
            "Global V1 classification registration is retired; use tenant V2 classification",
            status_code=410,
        )

    async def _create_tenant_classification_v2(
        self, cmd: CreateTenantClassificationV2Command, ctx: HandlingContext
    ) -> ClassificationResolutionV2:
        tenant_id = _require_tenant_context(ctx.request)
        code = normalize_code(cmd.code)
        controls = SecurityControls(
            cmd.sensitivity_level,
            cmd.required_controls,
            cmd.restrictions,
            cmd.allowed_audience,
            cmd.mandatory_masking,
        )
        conflict = await ctx.unit_of_work.persistence.execute(
            text(
                "SELECT 1 FROM platform_gov.classification_definitions WHERE code = :code LIMIT 1"
            ),
            {"code": code},
        )
        if conflict.first() is not None:
            raise BusinessOSError(
                "classification_shadow", "Canonical code is reserved", status_code=409
            )
        definition_id = uuid4()
        now = datetime.now(UTC)
        reference = tenant_ref(tenant_id, code)
        await ctx.unit_of_work.persistence.execute(
            text(
                "INSERT INTO platform_gov.tenant_classifications "
                "(id, tenant_id, code, qualified_ref, name, is_active) "
                "VALUES (:id, :tenant, :code, :ref, :name, true)"
            ),
            {
                "id": definition_id,
                "tenant": tenant_id,
                "code": code,
                "ref": reference,
                "name": cmd.name,
            },
        )
        await ctx.unit_of_work.persistence.execute(
            text(
                "INSERT INTO platform_gov.tenant_classification_versions "
                "(id, tenant_id, definition_id, version, valid_from, valid_until, "
                "sensitivity_level, required_controls, restrictions, "
                "allowed_audience, mandatory_masking) "
                "VALUES (:id, :tenant, :definition, 1, :now, NULL, :sensitivity, "
                ":required, :restrictions, :audience, :masking)"
            ),
            {
                "id": uuid4(),
                "tenant": tenant_id,
                "definition": definition_id,
                "now": now,
                "sensitivity": controls.sensitivity_level,
                "required": sorted(controls.required_controls),
                "restrictions": sorted(controls.restrictions),
                "audience": None
                if controls.allowed_audience is None
                else sorted(controls.allowed_audience),
                "masking": controls.mandatory_masking,
            },
        )
        return ClassificationResolutionV2(
            tenant_id,
            reference,
            definition_id,
            "1",
            "tenant",
            None,
            True,
            now,
            None,
            controls,
            None,
            controls,
            "tenant_definition",
        )

    async def _set_canonical_overlay_v2(
        self, cmd: SetCanonicalOverlayV2Command, ctx: HandlingContext
    ) -> ClassificationResolutionV2:
        tenant_id = _require_tenant_context(ctx.request)
        kind, code = parse_ref(cmd.canonical_ref, tenant_id)
        if kind != "core":
            raise BusinessOSError(
                "classification_identity", "Overlay requires core identity", status_code=400
            )
        await ctx.unit_of_work.persistence.execute(
            text(
                "SELECT pg_advisory_xact_lock_shared("
                "hashtextextended('classification-core:' || :code, 0))"
            ),
            {"code": code},
        )
        await ctx.unit_of_work.persistence.execute(
            text(
                "SELECT pg_advisory_xact_lock(hashtextextended("
                "'classification-overlay:' || :tenant || ':' || :code, 0))"
            ),
            {"tenant": str(tenant_id), "code": code},
        )
        current = await self.classification_v2.resolve_current(
            cmd.canonical_ref, ctx.request, ctx.unit_of_work
        )
        if cmd.mandatory_masking is False and current.canonical_controls.mandatory_masking:
            raise BusinessOSError(
                "classification_weakening", "Canonical masking cannot be disabled", status_code=409
            )
        addition = SecurityControls(
            cmd.sensitivity_level,
            cmd.required_controls,
            cmd.restrictions,
            cmd.allowed_audience,
            cmd.mandatory_masking is True,
        )
        current.canonical_controls.compose(addition)
        now = datetime.now(UTC)
        old = await ctx.unit_of_work.persistence.execute(
            text(
                "SELECT id, version FROM platform_gov.classification_overlays "
                "WHERE tenant_id = :tenant AND canonical_definition_id = :definition "
                "AND valid_until IS NULL ORDER BY version DESC LIMIT 2 FOR UPDATE"
            ),
            {"tenant": tenant_id, "definition": current.definition_id},
        )
        rows = old.all()
        if len(rows) > 1:
            raise BusinessOSError(
                "classification_ambiguous", "Multiple live overlays", status_code=409
            )
        version = rows[0].version + 1 if rows else 1
        if rows:
            await ctx.unit_of_work.persistence.execute(
                text(
                    "UPDATE platform_gov.classification_overlays SET valid_until = :now "
                    "WHERE id = :id AND tenant_id = :tenant"
                ),
                {"now": now, "id": rows[0].id, "tenant": tenant_id},
            )
        await ctx.unit_of_work.persistence.execute(
            text(
                "INSERT INTO platform_gov.classification_overlays "
                "(id, tenant_id, canonical_definition_id, version, valid_from, valid_until, "
                "sensitivity_level, required_controls, restrictions, "
                "allowed_audience, mandatory_masking) "
                "VALUES (:id, :tenant, :definition, :version, :now, NULL, :sensitivity, "
                ":required, :restrictions, :audience, :masking)"
            ),
            {
                "id": uuid4(),
                "tenant": tenant_id,
                "definition": current.definition_id,
                "version": version,
                "now": now,
                "sensitivity": addition.sensitivity_level,
                "required": sorted(addition.required_controls),
                "restrictions": sorted(addition.restrictions),
                "audience": None
                if addition.allowed_audience is None
                else sorted(addition.allowed_audience),
                "masking": addition.mandatory_masking,
            },
        )
        return await self.classification_v2.resolve_current(
            cmd.canonical_ref, ctx.request, ctx.unit_of_work
        )

    async def _deactivate_tenant_classification_v2(
        self, cmd: DeactivateTenantClassificationV2Command, ctx: HandlingContext
    ) -> None:
        tenant_id = _require_tenant_context(ctx.request)
        kind, code = parse_ref(cmd.qualified_ref, tenant_id)
        if kind != "tenant":
            raise BusinessOSError(
                "classification_identity",
                "Only tenant definitions may be deactivated",
                status_code=400,
            )
        result = await ctx.unit_of_work.persistence.execute(
            text(
                "UPDATE platform_gov.tenant_classifications SET is_active = false "
                "WHERE tenant_id = :tenant AND code = :code AND qualified_ref = :ref "
                "RETURNING id"
            ),
            {"tenant": tenant_id, "code": code, "ref": cmd.qualified_ref},
        )
        if result.first() is None:
            raise BusinessOSError(
                "classification_unavailable", "Tenant definition unavailable", status_code=404
            )

    async def _revise_tenant_classification_v2(
        self, cmd: ReviseTenantClassificationV2Command, ctx: HandlingContext
    ) -> ClassificationResolutionV2:
        tenant_id = _require_tenant_context(ctx.request)
        kind, code = parse_ref(cmd.qualified_ref, tenant_id)
        if kind != "tenant":
            raise BusinessOSError(
                "classification_identity", "Only tenant definitions can be revised", status_code=400
            )
        controls = SecurityControls(
            cmd.sensitivity_level,
            cmd.required_controls,
            cmd.restrictions,
            cmd.allowed_audience,
            cmd.mandatory_masking,
        )
        definition = await ctx.unit_of_work.persistence.execute(
            text(
                "SELECT id FROM platform_gov.tenant_classifications "
                "WHERE tenant_id = :tenant AND code = :code AND qualified_ref = :ref "
                "AND is_active = true LIMIT 2 FOR UPDATE"
            ),
            {"tenant": tenant_id, "code": code, "ref": cmd.qualified_ref},
        )
        definitions = definition.all()
        if len(definitions) != 1:
            raise BusinessOSError(
                "classification_unavailable", "Tenant definition is unavailable", status_code=409
            )
        definition_id = definitions[0].id
        current = await ctx.unit_of_work.persistence.execute(
            text(
                "SELECT id, version, valid_from FROM platform_gov.tenant_classification_versions "
                "WHERE tenant_id = :tenant AND definition_id = :definition "
                "AND valid_until IS NULL ORDER BY version DESC LIMIT 2 FOR UPDATE"
            ),
            {"tenant": tenant_id, "definition": definition_id},
        )
        rows = current.all()
        if len(rows) != 1:
            raise BusinessOSError(
                "classification_ambiguous", "Current tenant version is unavailable", status_code=409
            )
        now = datetime.now(UTC)
        if now <= rows[0].valid_from:
            raise BusinessOSError(
                "classification_clock",
                "New semantic version requires a later instant",
                status_code=409,
            )
        await ctx.unit_of_work.persistence.execute(
            text(
                "UPDATE platform_gov.tenant_classification_versions SET valid_until = :now "
                "WHERE id = :id AND tenant_id = :tenant"
            ),
            {"now": now, "id": rows[0].id, "tenant": tenant_id},
        )
        await ctx.unit_of_work.persistence.execute(
            text(
                "INSERT INTO platform_gov.tenant_classification_versions "
                "(id, tenant_id, definition_id, version, valid_from, valid_until, "
                "sensitivity_level, required_controls, restrictions, allowed_audience, "
                "mandatory_masking) VALUES (:id, :tenant, :definition, :version, :now, NULL, "
                ":sensitivity, :required, :restrictions, :audience, :masking)"
            ),
            {
                "id": uuid4(),
                "tenant": tenant_id,
                "definition": definition_id,
                "version": rows[0].version + 1,
                "now": now,
                "sensitivity": controls.sensitivity_level,
                "required": sorted(controls.required_controls),
                "restrictions": sorted(controls.restrictions),
                "audience": None
                if controls.allowed_audience is None
                else sorted(controls.allowed_audience),
                "masking": controls.mandatory_masking,
            },
        )
        return await self.classification_v2.resolve_current(
            cmd.qualified_ref, ctx.request, ctx.unit_of_work
        )

    async def _resolve_classification_v2(
        self, query: ResolveClassificationV2Query, ctx: HandlingContext
    ) -> ClassificationResolutionV2:
        return await self.classification_v2.resolve_current(
            query.qualified_ref, ctx.request, ctx.unit_of_work
        )

    async def _resolve_historical_classification_v2(
        self, query: ResolveHistoricalClassificationV2Query, ctx: HandlingContext
    ) -> ClassificationResolutionV2:
        return await self.classification_v2.resolve_historical(
            query.qualified_ref, query.at, ctx.request, ctx.unit_of_work
        )

    async def _create_retention_policy(
        self, cmd: CreateRetentionPolicyCommand, ctx: HandlingContext
    ) -> RetentionPolicyRecord:
        tenant = _require_tenant(ctx.request, cmd.tenant_id)
        classification = await self._approved_legacy_classification(cmd.classification_code, ctx)
        now = datetime.now(UTC)
        policy_id = uuid4()
        stmt = insert(RETENTION_POLICIES).values(
            id=policy_id,
            tenant_id=cmd.tenant_id,
            code=cmd.code,
            name=cmd.name,
            entity_type=cmd.entity_type,
            classification_code=cmd.classification_code,
            classification_ref=classification.qualified_ref,
            classification_version=int(classification.definition_version),
            classification_definition_id=classification.definition_id,
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
            classification_ref=classification.qualified_ref,
            classification_version=int(classification.definition_version),
            classification_definition_id=classification.definition_id,
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
        await lock_governance_scope(
            ctx.unit_of_work, "legacy-hold-entity", cmd.tenant_id, cmd.entity_type
        )
        if cmd.entity_id is not None:
            try:
                record_id = UUID(cmd.entity_id)
            except ValueError:
                record_id = None
            if record_id is not None:
                prior = await ctx.unit_of_work.persistence.execute(
                    select(DECISIONS_V2.c.id).where(
                        DECISIONS_V2.c.tenant_id == cmd.tenant_id,
                        DECISIONS_V2.c.entity_type == cmd.entity_type,
                        DECISIONS_V2.c.record_id == record_id,
                    )
                )
                if prior.first() is not None:
                    raise BusinessOSError(
                        "post_destruction_hold",
                        "A hold cannot protect an already destroyed record",
                        status_code=409,
                    )
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
            hold_scope="ALL" if cmd.entity_id is None else "RECORD",
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
        hint_result = await ctx.unit_of_work.persistence.execute(
            select(LEGAL_HOLDS.c.entity_type).where(
                LEGAL_HOLDS.c.id == cmd.hold_id,
                LEGAL_HOLDS.c.tenant_id == cmd.tenant_id,
            )
        )
        hint = hint_result.first()
        if hint is None:
            raise BusinessOSError("not_found", "Legal hold not found", status_code=404)
        await lock_governance_scope(
            ctx.unit_of_work, "legacy-hold-entity", cmd.tenant_id, hint.entity_type
        )
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
        classification = await self._approved_legacy_classification(cmd.classification_code, ctx)
        masked = cmd.is_masked_by_default or classification.effective_controls.mandatory_masking
        tag_id = uuid4()
        stmt = (
            insert(SENSITIVE_FIELD_TAGS)
            .values(
                id=tag_id,
                tenant_id=cmd.tenant_id,
                entity_type=cmd.entity_type,
                field_name=cmd.field_name,
                classification_code=cmd.classification_code,
                classification_ref=classification.qualified_ref,
                classification_version=int(classification.definition_version),
                classification_definition_id=classification.definition_id,
                is_masked_by_default=masked,
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
                    classification_ref=classification.qualified_ref,
                    classification_version=int(classification.definition_version),
                    classification_definition_id=classification.definition_id,
                    is_masked_by_default=masked,
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
            classification_ref=classification.qualified_ref,
            classification_version=int(classification.definition_version),
            classification_definition_id=classification.definition_id,
            is_masked_by_default=masked,
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
                f"Informational estimate only for {policy.action_on_expiry}: record age "
                f"{query.record_age_days} exceeds {policy.retention_period_days} days; "
                "destructive authority requires destructive-lifecycle.v2"
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
            .limit(101)
        )
        res = await ctx.unit_of_work.persistence.execute(stmt)
        rows = res.mappings().all()
        if len(rows) > 100 or any(row["classification_ref"] is None for row in rows):
            raise BusinessOSError(
                "classification_unavailable",
                "Sensitive field classifications are unresolved or exceed the read bound",
                status_code=409,
            )
        tags: list[SensitiveFieldTagRecord] = []
        for row in rows:
            resolved = await self.classification_v2.resolve_current(
                row["classification_ref"], ctx.request, ctx.unit_of_work
            )
            if resolved.definition_id != row["classification_definition_id"]:
                raise BusinessOSError(
                    "classification_unavailable",
                    "Sensitive field classification identity has changed",
                    status_code=409,
                )
            values = dict(row)
            values["is_masked_by_default"] = (
                values["is_masked_by_default"] or resolved.effective_controls.mandatory_masking
            )
            tags.append(SensitiveFieldTagRecord.model_validate(values))
        return tags

    async def _approved_legacy_classification(
        self, code: str, ctx: HandlingContext
    ) -> ClassificationResolutionV2:
        tenant_id = _require_tenant_context(ctx.request)
        result = await ctx.unit_of_work.persistence.execute(
            text(
                "SELECT qualified_ref, definition_id, definition_version, tenant_id "
                "FROM platform_gov.classification_legacy_mappings "
                "WHERE legacy_code = :code LIMIT 2"
            ),
            {"code": code},
        )
        rows = result.all()
        if len(rows) != 1 or rows[0].tenant_id not in (None, tenant_id):
            raise BusinessOSError(
                "classification_unavailable",
                "Legacy classification has no unambiguous approved mapping",
                status_code=409,
            )
        mapping = rows[0]
        resolved = await self.classification_v2.resolve_assignable(
            mapping.qualified_ref, ctx.request, ctx.unit_of_work
        )
        if (
            resolved.definition_id != mapping.definition_id
            or int(resolved.definition_version) != mapping.definition_version
            or not resolved.active
        ):
            raise BusinessOSError(
                "classification_unavailable",
                "Legacy mapping is stale or cannot authorize a new assignment",
                status_code=409,
            )
        return resolved

    async def _tag_sensitive_field_v2(
        self, cmd: TagSensitiveFieldV2Command, ctx: HandlingContext
    ) -> SensitiveFieldTagRecord:
        tenant_id = _require_tenant_context(ctx.request)
        classification = await self.classification_v2.resolve_assignable(
            cmd.classification_ref, ctx.request, ctx.unit_of_work
        )
        if not classification.active:
            raise BusinessOSError(
                "classification_inactive",
                "Inactive classification cannot be newly assigned",
                status_code=409,
            )
        masked = cmd.is_masked_by_default or classification.effective_controls.mandatory_masking
        tag_id = uuid4()
        stmt = (
            insert(SENSITIVE_FIELD_TAGS)
            .values(
                id=tag_id,
                tenant_id=tenant_id,
                entity_type=cmd.entity_type,
                field_name=cmd.field_name,
                classification_code=None,
                classification_ref=classification.qualified_ref,
                classification_version=int(classification.definition_version),
                classification_definition_id=classification.definition_id,
                is_masked_by_default=masked,
                description=cmd.description,
            )
            .on_conflict_do_update(
                index_elements=[
                    SENSITIVE_FIELD_TAGS.c.tenant_id,
                    SENSITIVE_FIELD_TAGS.c.entity_type,
                    SENSITIVE_FIELD_TAGS.c.field_name,
                ],
                set_={
                    "classification_code": None,
                    "classification_ref": classification.qualified_ref,
                    "classification_version": int(classification.definition_version),
                    "classification_definition_id": classification.definition_id,
                    "is_masked_by_default": masked,
                    "description": cmd.description,
                },
            )
            .returning(SENSITIVE_FIELD_TAGS.c.id)
        )
        result = await ctx.unit_of_work.persistence.execute(stmt)
        row = result.first()
        if row is None:
            raise BusinessOSError(
                "classification_unavailable", "Field tag write failed", status_code=409
            )
        return SensitiveFieldTagRecord(
            id=row.id,
            tenant_id=tenant_id,
            entity_type=cmd.entity_type,
            field_name=cmd.field_name,
            classification_code=None,
            classification_ref=classification.qualified_ref,
            classification_version=int(classification.definition_version),
            classification_definition_id=classification.definition_id,
            is_masked_by_default=masked,
            description=cmd.description,
        )

    async def _create_retention_policy_v2(
        self, cmd: CreateRetentionPolicyV2Command, ctx: HandlingContext
    ) -> RetentionPolicyRecord:
        tenant_id = _require_tenant_context(ctx.request)
        classification = await self.classification_v2.resolve_assignable(
            cmd.classification_ref, ctx.request, ctx.unit_of_work
        )
        if not classification.active:
            raise BusinessOSError(
                "classification_inactive",
                "Inactive classification cannot be newly assigned",
                status_code=409,
            )
        now = datetime.now(UTC)
        policy_id = uuid4()
        await ctx.unit_of_work.persistence.execute(
            insert(RETENTION_POLICIES).values(
                id=policy_id,
                tenant_id=tenant_id,
                code=cmd.code,
                name=cmd.name,
                entity_type=cmd.entity_type,
                classification_code=None,
                classification_ref=classification.qualified_ref,
                classification_version=int(classification.definition_version),
                classification_definition_id=classification.definition_id,
                retention_period_days=cmd.retention_period_days,
                action_on_expiry=cmd.action_on_expiry.value,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
        ctx.emit(
            RetentionPolicyChanged(
                tenant_id=tenant_id,
                correlation_id=ctx.request.correlation_id,
                policy_id=policy_id,
                code=cmd.code,
                entity_type=cmd.entity_type,
            )
        )
        return RetentionPolicyRecord(
            id=policy_id,
            tenant_id=tenant_id,
            code=cmd.code,
            name=cmd.name,
            entity_type=cmd.entity_type,
            classification_code=None,
            classification_ref=classification.qualified_ref,
            classification_version=int(classification.definition_version),
            classification_definition_id=classification.definition_id,
            retention_period_days=cmd.retention_period_days,
            action_on_expiry=cmd.action_on_expiry,
            is_active=True,
            created_at=now,
            updated_at=now,
        )


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


def _require_tenant_context(request: RequestContext | None) -> UUID:
    if request is None or request.tenant is None:
        raise BusinessOSError(
            "tenant_context_required", "Tenant context is required", status_code=401
        )
    return request.tenant.tenant_id
