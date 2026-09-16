"""Audit foundation module registration, commands, and query handlers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from importlib.resources import files
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import insert, select

from businessos.sdk import (
    Command,
    HandlingContext,
    ModuleManifest,
    ModuleRegistration,
    PermissionDeclaration,
    Query,
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
    def __init__(self) -> None:
        data = json.loads(
            files("businessos_audit").joinpath("manifest.json").read_text(encoding="utf-8")
        )
        self.manifest = ModuleManifest.model_validate(data)

    async def register(self, registration: ModuleRegistration) -> None:
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

    async def _record_audit_log(
        self, cmd: RecordAuditLogCommand, ctx: HandlingContext
    ) -> AuditRecord:
        audit_id = uuid4()
        occurred_at = datetime.now(timezone.utc)

        # Retrieve previous record's checksum for hash chaining
        prev_res = await ctx.session.execute(
            select(AUDIT_LOGS.c.checksum)
            .where(AUDIT_LOGS.c.tenant_id == cmd.tenant_id)
            .order_by(AUDIT_LOGS.c.occurred_at.desc())
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
            correlation_id=cmd.correlation_id,
            client_ip=cmd.client_ip,
            user_agent=cmd.user_agent,
            decision_metadata=cmd.decision_metadata,
            status=cmd.status,
            checksum=checksum,
        )
        await ctx.session.execute(stmt)

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
            correlation_id=cmd.correlation_id,
            client_ip=cmd.client_ip,
            user_agent=cmd.user_agent,
            decision_metadata=cmd.decision_metadata,
            status=cmd.status,
            checksum=checksum,
        )

        return record

    async def _query_audit_logs(
        self, query: QueryAuditLogsQuery, ctx: HandlingContext
    ) -> list[AuditRecord]:
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
        res = await ctx.session.execute(stmt)
        return [AuditRecord.model_validate(dict(r._mapping)) for r in res]

    async def _verify_integrity(
        self, query: VerifyAuditIntegrityQuery, ctx: HandlingContext
    ) -> AuditVerificationResult:
        stmt = (
            select(AUDIT_LOGS)
            .where(AUDIT_LOGS.c.tenant_id == query.tenant_id)
            .order_by(AUDIT_LOGS.c.occurred_at.asc())
        )
        res = await ctx.session.execute(stmt)
        rows = list(res)
        if not rows:
            return AuditVerificationResult(total_records=0, is_valid=True, tampered_ids=[])

        prev_checksum = ""
        tampered: list[UUID] = []

        for row in rows:
            m = dict(row._mapping)
            expected = compute_audit_checksum(
                tenant_id=m["tenant_id"],
                occurred_at=m["occurred_at"],
                actor_id=m["actor_id"],
                action=m["action"],
                resource_type=m["resource_type"],
                resource_id=m["resource_id"],
                status=m["status"],
                previous_checksum=prev_checksum,
            )
            if expected != m["checksum"]:
                tampered.append(m["id"])
            prev_checksum = m["checksum"]

        return AuditVerificationResult(
            total_records=len(rows),
            is_valid=len(tampered) == 0,
            tampered_ids=tampered,
        )
