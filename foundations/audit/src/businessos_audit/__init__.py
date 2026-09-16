"""Audit and immutable evidence foundation module."""
from .contracts import AuditEventRecorded
from .models import (
    AUDIT_LOGS,
    AuditRecord,
    AuditVerificationResult,
    RecordAuditEvent,
    compute_audit_checksum,
    metadata,
)
from .module import (
    AuditModule,
    QueryAuditLogsQuery,
    RecordAuditLogCommand,
    VerifyAuditIntegrityQuery,
)

__all__ = [
    "AUDIT_LOGS",
    "AuditEventRecorded",
    "AuditModule",
    "AuditRecord",
    "AuditVerificationResult",
    "QueryAuditLogsQuery",
    "RecordAuditEvent",
    "RecordAuditLogCommand",
    "VerifyAuditIntegrityQuery",
    "compute_audit_checksum",
    "metadata",
]
