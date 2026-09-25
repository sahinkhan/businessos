# Audit V2 Runtime Implementation Record

Base: `1c6d0eafb5cde8688b44c9ac88ae65f9ad15beb7`

Branch: `phase4/audit-v2-runtime`

Authority: accepted ADR-016 (except worker binding), ADR-019, ADR-020.
Migration: `audit_0003_trusted_provenance.py` (`audit_0003`).

## Contracts and paths

`RecordAuditLogV2` is a separately authorized manual command. It accepts only
bounded `AuditEvidenceV2`; its actor comes from the exact request's Identity
`AuthenticatedPrincipalBinding`. Its normal command permission is
`foundation.audit.write`. The V2 contract is published as
`foundation.audit.write-facade.v2`.

`AuditAppenderV2` is an Audit-owned, first-party, owner-restricted request
dependency. Each call checks the live ADR-020 command invocation against the
exact request and restricted transaction, its owner/generation, and the
admitted manifest's direct Audit dependency. It derives the actor from Identity,
then inserts within the handler's existing unit of work. The end user does not
need the Audit write permission for mandatory handler evidence. A query or
direct/unregistered handler has no appender authority.

The installation's protected approved-module inventory must include the exact
first-party `foundation.audit` artifact before Audit can register this reserved
provider. The repository CI inventory includes only a test installation grant.

Audit subscribes downstream to `PolicyDecisionRecordedV2`. The worker first
verifies the committed outbox source; the Audit subscriber requires an active,
Identity-issued ADR-019 `TenantExecutionBinding` matching the event, delivery
subscriber, task, transaction, tenant and installation. The actual actor is the
verified workload. The separate origin actor is the typed principal in the
committed Policy event. Policy has no Audit dependency. The Audit projection
commits in the delivery transaction after the Policy source commit. A failed
append rolls back the inbox claim and retries. A partial unique index over
`(tenant_id, source_event_id, projection_kind)` enforces one projection.

## Storage and integrity

Version 3 stores the trusted structured provenance and bounded evidence next
to legacy fields. The checksum canonically covers the V3 envelope, including
actor, origin, event/delivery IDs, outcome, tenant, correlation/trace source,
and previous checksum. Historical integrity versions 1 and 2 retain their
original encodings and rows. Writes take a per-tenant transaction advisory lock
before selecting the predecessor and assign an instant strictly greater than
the predecessor to preserve chain order. The current Audit RLS and append-only
trigger remain in force. `audit_0003` refuses downgrade when V3 rows exist.

The current Policy public support contract does not prove a target and grant
reference, so V2 does not accept on-behalf-of writes. The V1 write command is
disabled with a 410 response because it accepted caller-chosen actor facts;
V1 read and integrity verification remain available. No first-party production
V1 write consumer was found.

## Validation and scope

The focused PostgreSQL tests exercise manual authority, actor spoof rejection,
same-unit-of-work commit and rollback, direct dependency denial, verified
workload/origin separation, duplicate delivery, mixed historical/V3 chain
verification, and distinct concurrent chain appends. The Phase 0 gate, Ruff,
mypy, Pyright, unit, integration, conformance, wheel/image, web, and exact-head
CI results are reported in the implementation PR.
This batch does not implement ADR-017, preventative SoD, or broad V1 retirement.
Phase 0–3 remain final pass and frozen. Remaining Phase 4 gaps are ADR-017
runtime and future ADR-021 V1 runtime elimination.
