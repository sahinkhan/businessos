"""Audit foundation module registration, commands, and query handlers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import insert, select, text

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

from .contracts import AuditEventRecorded
from .models import (
    AUDIT_LOGS,
    AuditRecord,
    AuditVerificationResult,
    compute_audit_checksum,
)


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
        tenant = _require_tenant(ctx.request, cmd.tenant_id)
        audit_id = uuid4()
        occurred_at = datetime.now(UTC)
        correlation_id = cmd.correlation_id or ctx.request.correlation_id
        trace_id = ctx.request.trace_id

        await ctx.unit_of_work.persistence.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant_id, 0))"),
            {"tenant_id": str(cmd.tenant_id)},
        )

        # Retrieve previous record's checksum for hash chaining
        prev_res = await ctx.unit_of_work.persistence.execute(
            select(AUDIT_LOGS.c.checksum)
            .where(AUDIT_LOGS.c.tenant_id == cmd.tenant_id)
            .order_by(AUDIT_LOGS.c.occurred_at.desc(), AUDIT_LOGS.c.id.desc())
            .limit(1)
        )
        prev_row = prev_res.first()
        prev_checksum = prev_row[0] if prev_row else ""

        checksum = compute_audit_checksum(
            tenant_id=cmd.tenant_id,
            occurred_at=occurred_at,
            actor_id=cmd.actor_id,
            action=cmd.action,
            resource_type=cmd.resource_type,
            resource_id=cmd.resource_id,
            status=cmd.status,
            previous_checksum=prev_checksum,
            actor_type=cmd.actor_type,
            scope_type=cmd.scope_type,
            scope_id=cmd.scope_id,
            before_state=cmd.before_state,
            after_state=cmd.after_state,
            correlation_id=correlation_id,
            trace_id=trace_id,
            decision_metadata=cmd.decision_metadata,
            integrity_version="2",
        )

        stmt = insert(AUDIT_LOGS).values(
            id=audit_id,
            tenant_id=cmd.tenant_id,
            occurred_at=occurred_at,
            actor_id=cmd.actor_id,
            actor_type=cmd.actor_type,
            action=cmd.action,
            resource_type=cmd.resource_type,
            resource_id=cmd.resource_id,
            scope_type=cmd.scope_type,
            scope_id=cmd.scope_id,
            before_state=cmd.before_state,
            after_state=cmd.after_state,
            correlation_id=correlation_id,
            client_ip=cmd.client_ip,
            user_agent=cmd.user_agent,
            decision_metadata=cmd.decision_metadata,
            trace_id=trace_id,
            status=cmd.status,
            previous_checksum=prev_checksum,
            integrity_version="2",
            checksum=checksum,
        )
        await ctx.unit_of_work.persistence.execute(stmt)

        record = AuditRecord(
            id=audit_id,
            tenant_id=cmd.tenant_id,
            occurred_at=occurred_at,
            actor_id=cmd.actor_id,
            actor_type=cmd.actor_type,
            action=cmd.action,
            resource_type=cmd.resource_type,
            resource_id=cmd.resource_id,
            scope_type=cmd.scope_type,
            scope_id=cmd.scope_id,
            before_state=cmd.before_state,
            after_state=cmd.after_state,
            correlation_id=correlation_id,
            client_ip=cmd.client_ip,
            user_agent=cmd.user_agent,
            decision_metadata=cmd.decision_metadata,
            trace_id=trace_id,
            status=cmd.status,
            previous_checksum=prev_checksum,
            integrity_version="2",
            checksum=checksum,
        )

        ctx.emit(
            AuditEventRecorded(
                tenant_id=tenant.tenant_id,
                correlation_id=ctx.request.correlation_id,
                audit_id=audit_id,
                actor_id=cmd.actor_id,
                action=cmd.action,
                resource_type=cmd.resource_type,
                resource_id=cmd.resource_id,
                status=cmd.status,
            )
        )
        return record

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
