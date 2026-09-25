"""Audit and immutable evidence foundation module."""

from .contracts import AuditEventRecorded
from .models import (
    AUDIT_LOGS,
    AuditRecord,
    AuditVerificationResult,
    RecordAuditEvent,
    compute_audit_checksum,
    compute_audit_checksum_v3,
    metadata,
)
from .module import (
    AuditModule,
    QueryAuditLogsQuery,
    RecordAuditLogCommand,
    VerifyAuditIntegrityQuery,
)
from .v2_contracts import AUDIT_APPENDER_V2, AuditAppenderV2, AuditEvidenceV2, RecordAuditLogV2

__all__ = [
    "AUDIT_APPENDER_V2",
    "AUDIT_LOGS",
    "AuditAppenderV2",
    "AuditEventRecorded",
    "AuditEvidenceV2",
    "AuditModule",
    "AuditRecord",
    "AuditVerificationResult",
    "QueryAuditLogsQuery",
    "RecordAuditEvent",
    "RecordAuditLogCommand",
    "RecordAuditLogV2",
    "VerifyAuditIntegrityQuery",
    "compute_audit_checksum",
    "compute_audit_checksum_v3",
    "metadata",
]
