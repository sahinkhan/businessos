"""Audit foundation module registration, commands, and query handlers."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from typing import Any
from uuid import UUID, uuid4

from businessos_identity import TenantExecutionBinding
from businessos_policy import PolicyDecisionRecordedV2
from pydantic import Field
from sqlalchemy import insert, select, text

from businessos.sdk import (
    BusinessOSError,
    Command,
    DependencyResolver,
    DependencyScope,
    EventHandlingContext,
    HandlerTransaction,
    HandlingContext,
    ModuleManifest,
    ModuleRegistration,
    PermissionDeclaration,
    Query,
    RequestContext,
    TenantContext,
)

from .models import (
    AUDIT_LOGS,
    AuditRecord,
    AuditVerificationResult,
    compute_audit_checksum,
    compute_audit_checksum_v3,
)
from .v2_contracts import AUDIT_APPENDER_V2, AuditAppenderV2, AuditEvidenceV2, RecordAuditLogV2
from .v2_runtime import AuditAppenderProvider, trusted_interactive_actor


class RecordAuditLogCommand(Command):
    tenant_id: UUID
    actor_id: str = Field(min_length=1, max_length=100)
    actor_type: str = Field(default="user", max_length=50)
    action: str = Field(min_length=1, max_length=100)
    resource_type: str = Field(min_length=1, max_length=100)
    resource_id: str | None = Field(default=None, max_length=255)
    scope_type: str | None = Field(default=None, max_length=50)
    scope_id: UUID | None = None
    before_state: dict[str, Any] | None = None
    after_state: dict[str, Any] | None = None
    correlation_id: str | None = Field(default=None, max_length=100)
    client_ip: str | None = Field(default=None, max_length=50)
    user_agent: str | None = Field(default=None, max_length=255)
    decision_metadata: dict[str, Any] | None = None
    status: str = Field(default="success", max_length=30)


class QueryAuditLogsQuery(Query):
    tenant_id: UUID
    actor_id: str | None = None
    action: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    correlation_id: str | None = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class VerifyAuditIntegrityQuery(Query):
    tenant_id: UUID


class AuditModule:
    version: str = "1"

    def __init__(self) -> None:
        data = json.loads(
            files("businessos_audit").joinpath("manifest.json").read_text(encoding="utf-8")
        )
        self.manifest = ModuleManifest.model_validate(data)

    async def register(self, registration: ModuleRegistration) -> None:
        registration.contract("foundation.audit.write-facade.v1", self)
        registration.contract("foundation.audit.write-facade.v2", self)
        registration.permission(
            PermissionDeclaration(
                key="foundation.audit.read", description="Read audit logs and verify integrity"
            )
        )
        registration.permission(
            PermissionDeclaration(
                key="foundation.audit.write", description="Append audit log events"
            )
        )
        registration.permission(
            PermissionDeclaration(
                key="foundation.audit.export", description="Export tenant audit logs"
            )
        )

        registration.command(
            RecordAuditLogCommand, self._record_audit_log, permission="foundation.audit.write"
        )
        registration.command(
            RecordAuditLogV2, self._record_audit_log_v2, permission="foundation.audit.write"
        )
        registration.dependency(
            AUDIT_APPENDER_V2, self._provide_appender, scope=DependencyScope.REQUEST
        )
        registration.event(
            PolicyDecisionRecordedV2,
            "policy_decision_v2",
            self._materialize_policy_decision,
            permission="foundation.audit.write",
        )
        registration.query(
            QueryAuditLogsQuery, self._query_audit_logs, permission="foundation.audit.read"
        )
        registration.query(
            VerifyAuditIntegrityQuery, self._verify_integrity, permission="foundation.audit.read"
        )

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def _record_audit_log(
        self, cmd: RecordAuditLogCommand, ctx: HandlingContext
    ) -> AuditRecord:
        raise BusinessOSError(
            "audit_v1_write_disabled",
            "Caller-supplied Audit V1 provenance is no longer accepted; use RecordAuditLogV2",
            status_code=410,
        )

    @asynccontextmanager
    async def _provide_appender(
        self, resolver: DependencyResolver
    ) -> AsyncGenerator[AuditAppenderV2]:
        appender = AuditAppenderProvider(self, resolver)
        try:
            yield appender
        finally:
            appender.active = False

    async def _record_audit_log_v2(
        self, cmd: RecordAuditLogV2, ctx: HandlingContext
    ) -> AuditRecord:
        actor = await trusted_interactive_actor(ctx)
        return await self._append_v3(
            ctx.request,
            ctx.unit_of_work,
            cmd.evidence,
            provenance={
                "version": "audit.provenance.v3",
                "path": "manual-command",
                "actual_actor": actor,
                "origin_actor": None,
                "support": None,
                "correlation_source": "request-context",
                "trace_source": "request-context",
            },
        )

    async def _materialize_policy_decision(
        self, event: PolicyDecisionRecordedV2, ctx: EventHandlingContext
    ) -> None:
        binding = ctx.workload_binding
        tenant = _require_tenant(ctx.request, event.tenant_id)
        if type(binding) is not TenantExecutionBinding:
            raise PermissionError("Trusted workload binding required for Audit projection")
        binding.assert_active(ctx.unit_of_work)
        if (
            binding.tenant_id != event.tenant_id
            or binding.source_event_id != event.event_id
            or binding.subscriber != "foundation.audit.policy_decision_v2"
            or binding.purpose != "event-delivery"
            or binding.workload.purpose != "event-delivery"
            or binding.workload.principal_type != "service_account"
            or binding.workload.installation_id != tenant.installation_id
        ):
            raise PermissionError("Workload delivery does not match the committed Policy event")
        await self._append_v3(
            ctx.request,
            ctx.unit_of_work,
            AuditEvidenceV2(
                action=event.action,
                resource_type=f"{event.resource_namespace}@{event.resource_version}",
                resource_id=str(event.record_id),
                status="allowed" if event.allowed else "denied",
                details={
                    "mode": event.mode,
                    "reason_code": event.reason_code,
                    "policy_ids": [str(value) for value in event.policy_ids],
                    "decision_at": event.decision_at.isoformat(),
                },
            ),
            provenance={
                "version": "audit.provenance.v3",
                "path": "committed-policy-event",
                "actual_actor": {
                    "type": binding.workload.principal_type,
                    "id": str(binding.workload.workload_id),
                    "source": "identity.tenant_execution_binding.v1",
                    "scope": {"installation_id": str(binding.workload.installation_id)},
                    "workload": {
                        "process_class": binding.workload.process_class,
                        "credential_generation": binding.workload.credential_generation,
                        "verification_reference": str(binding.workload.verification_reference),
                    },
                },
                "origin_actor": {
                    "type": event.principal_type,
                    "id": str(event.principal_id),
                    "source": "committed-policy-decision-v2",
                },
                "support": None,
                "delivery": {
                    "source_event_id": str(event.event_id),
                    "source_occurred_at": event.occurred_at.isoformat(),
                    "subscriber": binding.subscriber,
                    "attempt_id": str(binding.attempt_id),
                    "causation_id": event.causation_id,
                },
                "correlation_source": "committed-policy-event",
                "trace_source": "verified-event-trace",
            },
            source_event_id=event.event_id,
            projection_kind="policy-decision-v2",
        )

    async def _append_v3(
        self,
        request: RequestContext,
        transaction: HandlerTransaction,
        evidence: AuditEvidenceV2,
        *,
        provenance: dict[str, Any],
        source_event_id: UUID | None = None,
        projection_kind: str | None = None,
    ) -> AuditRecord:
        if request.tenant is None:
            raise BusinessOSError(
                "tenant_context_required", "Tenant context required", status_code=401
            )
        tenant_id = request.tenant.tenant_id
        await transaction.persistence.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant_id, 0))"),
            {"tenant_id": str(tenant_id)},
        )
        if source_event_id is not None:
            existing = await transaction.persistence.execute(
                select(AUDIT_LOGS).where(
                    AUDIT_LOGS.c.tenant_id == tenant_id,
                    AUDIT_LOGS.c.source_event_id == source_event_id,
                    AUDIT_LOGS.c.projection_kind == projection_kind,
                )
            )
            row = existing.mappings().one_or_none()
            if row is not None:
                return AuditRecord.model_validate(dict(row))
        previous = await transaction.persistence.execute(
            select(AUDIT_LOGS.c.occurred_at, AUDIT_LOGS.c.checksum)
            .where(AUDIT_LOGS.c.tenant_id == tenant_id)
            .order_by(AUDIT_LOGS.c.occurred_at.desc(), AUDIT_LOGS.c.id.desc())
            .limit(1)
        )
        prior = previous.first()
        occurred_at = datetime.now(UTC)
        if prior is not None and occurred_at <= prior[0]:
            occurred_at = prior[0] + timedelta(microseconds=1)
        actual_actor = provenance["actual_actor"]
        if not isinstance(actual_actor, dict):
            raise BusinessOSError(
                "invalid_audit_provenance", "Trusted actor missing", status_code=500
            )
        values: dict[str, Any] = {
            "id": uuid4(),
            "tenant_id": tenant_id,
            "occurred_at": occurred_at,
            "actor_id": actual_actor["id"],
            "actor_type": actual_actor["type"],
            "action": evidence.action,
            "resource_type": evidence.resource_type,
            "resource_id": evidence.resource_id,
            "scope_type": None,
            "scope_id": None,
            "before_state": None,
            "after_state": None,
            "client_ip": None,
            "user_agent": None,
            "decision_metadata": None,
            "status": evidence.status,
            "correlation_id": request.correlation_id,
            "trace_id": request.trace_id,
            "previous_checksum": prior[1] if prior else "",
            "integrity_version": "3",
            "provenance_v3": provenance,
            "evidence_v3": evidence.model_dump(mode="json"),
            "source_event_id": source_event_id,
            "projection_kind": projection_kind,
        }
        values["checksum"] = compute_audit_checksum_v3(_v3_envelope(values))
        await transaction.persistence.execute(insert(AUDIT_LOGS).values(**values))
        return AuditRecord.model_validate(values)

    async def _query_audit_logs(
        self, query: QueryAuditLogsQuery, ctx: HandlingContext
    ) -> list[AuditRecord]:
        _require_tenant(ctx.request, query.tenant_id)
        stmt = select(AUDIT_LOGS).where(AUDIT_LOGS.c.tenant_id == query.tenant_id)
        if query.actor_id:
            stmt = stmt.where(AUDIT_LOGS.c.actor_id == query.actor_id)
        if query.action:
            stmt = stmt.where(AUDIT_LOGS.c.action == query.action)
        if query.resource_type:
            stmt = stmt.where(AUDIT_LOGS.c.resource_type == query.resource_type)
        if query.resource_id:
            stmt = stmt.where(AUDIT_LOGS.c.resource_id == query.resource_id)
        if query.correlation_id:
            stmt = stmt.where(AUDIT_LOGS.c.correlation_id == query.correlation_id)

        stmt = (
            stmt.order_by(AUDIT_LOGS.c.occurred_at.desc()).limit(query.limit).offset(query.offset)
        )
        res = await ctx.unit_of_work.persistence.execute(stmt)
        return [AuditRecord.model_validate(dict(row)) for row in res.mappings()]

    async def _verify_integrity(
        self, query: VerifyAuditIntegrityQuery, ctx: HandlingContext
    ) -> AuditVerificationResult:
        _require_tenant(ctx.request, query.tenant_id)
        stmt = (
            select(AUDIT_LOGS)
            .where(AUDIT_LOGS.c.tenant_id == query.tenant_id)
            .order_by(AUDIT_LOGS.c.occurred_at.asc(), AUDIT_LOGS.c.id.asc())
        )
        res = await ctx.unit_of_work.persistence.execute(stmt)
        rows = list(res.mappings())
        if not rows:
            return AuditVerificationResult(total_records=0, is_valid=True, tampered_ids=[])

        prev_checksum = ""
        tampered: list[UUID] = []

        for row in rows:
            m = dict(row)
            integrity_version = m.get("integrity_version") or "1"
            stored_previous = m.get("previous_checksum") or ""
            if integrity_version not in {"1", "2", "3"}:
                tampered.append(m["id"])
                prev_checksum = m["checksum"]
                continue
            if integrity_version == "3":
                expected_v3 = compute_audit_checksum_v3(_v3_envelope(m))
                if expected_v3 != m["checksum"] or stored_previous != prev_checksum:
                    tampered.append(m["id"])
                prev_checksum = m["checksum"]
                continue
            expected = compute_audit_checksum(
                tenant_id=m["tenant_id"],
                occurred_at=m["occurred_at"],
                actor_id=m["actor_id"],
                action=m["action"],
                resource_type=m["resource_type"],
                resource_id=m["resource_id"],
                status=m["status"],
                previous_checksum=stored_previous if integrity_version == "2" else prev_checksum,
                actor_type=m["actor_type"],
                scope_type=m["scope_type"],
                scope_id=m["scope_id"],
                before_state=m["before_state"],
                after_state=m["after_state"],
                correlation_id=m["correlation_id"],
                trace_id=m.get("trace_id"),
                decision_metadata=m["decision_metadata"],
                integrity_version=integrity_version,
            )
            if expected != m["checksum"] or (
                integrity_version == "2" and stored_previous != prev_checksum
            ):
                tampered.append(m["id"])
            prev_checksum = m["checksum"]

        return AuditVerificationResult(
            total_records=len(rows),
            is_valid=len(tampered) == 0,
            tampered_ids=tampered,
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


_V3_ENVELOPE_FIELDS = (
    "id",
    "tenant_id",
    "occurred_at",
    "actor_id",
    "actor_type",
    "action",
    "resource_type",
    "resource_id",
    "scope_type",
    "scope_id",
    "before_state",
    "after_state",
    "client_ip",
    "user_agent",
    "decision_metadata",
    "status",
    "correlation_id",
    "trace_id",
    "previous_checksum",
    "provenance_v3",
    "evidence_v3",
    "source_event_id",
    "projection_kind",
)


def _v3_envelope(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in _V3_ENVELOPE_FIELDS}
