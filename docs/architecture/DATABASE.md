# BusinessOS PostgreSQL Architecture

## Purpose

This document defines database rules that all BusinessOS platform, foundation, business and vertical modules must follow.

## Source of Truth

PostgreSQL is the authoritative transactional system of record.

Redis, search indexes, caches, reporting projections and event streams may contain derived state but are not replacements for authoritative transactional data unless a future ADR explicitly defines a bounded context otherwise.

## Persistence Baseline

- SQLAlchemy 2.x is the standard persistence and SQL toolkit.
- psycopg 3 is the PostgreSQL driver used through SQLAlchemy.
- The BusinessOS framework owns engine/session configuration, dependency scopes, Unit of Work and transaction boundaries.
- ORM mappings and repositories belong to their bounded context and are not public cross-module contracts.
- Pydantic 2 boundary models do not replace domain models or SQLAlchemy persistence mappings.

## Schema Ownership

Use bounded-context-owned schemas. Example direction:

```text
platform_tenant
platform_identity
platform_org
platform_policy
platform_module
platform_metadata
platform_workflow
platform_audit
platform_i18n
platform_docs
platform_integration
platform_ops
eventing

party
resource
scheduling
catalog
finance
logistics

crm
sales
procurement
inventory
warehouse
manufacturing
billing
payments
accounting
hr
payroll
projects
pos
ecommerce

healthcare
education
hospitality
restaurant
garments
construction
travel
mod_<publisher>_<module>
```

Every table has exactly one owner.

Cross-module direct writes are prohibited.

## Identifier Rules

- Technical identifiers are immutable UUIDs; UUIDv7 is the preferred strategy unless superseded by ADR.
- Human-readable/business document numbers are separate from technical IDs.
- External-system identifiers are stored through explicit external-ID/reference-data contracts rather than replacing internal identity.

## Tenant Rules

Tenant-owned data preserves `tenant_id` even in database-per-tenant deployments.

For shared-schema mode:

- enable RLS for tenant-owned tables
- use database roles that do not bypass RLS
- include tenant-aware unique constraints where uniqueness is tenant-scoped
- include tenant ownership in cross-table integrity strategy
- test cross-tenant reads and writes negatively

Database administration, migration ownership, runtime access and approved cross-tenant operations
use distinct roles. Administrative role creation/ownership transition is an explicit deployment
operation, never application startup. The runtime role is non-owner, `NOSUPERUSER`, `NOINHERIT`
and `NOBYPASSRLS`; it cannot assume the separately credentialed operations role. Retained
installations transition ownership and grants idempotently before migration continues.

## Financial Precision

- Never use floating-point types for money.
- Use exact `NUMERIC` values with explicit currency context.
- Currency-specific rounding/precision belongs to the monetary/UoM/localization rules.
- Posted accounting entries are immutable; corrections use reversal/adjustment entries.

## Inventory Integrity

Authoritative stock movements/ledger entries are immutable after posting. Corrections are compensating movements.

Derived on-hand balances may be cached/projected but must be reproducible from authoritative movements according to the inventory design.

## Time Rules

- Use `TIMESTAMPTZ` for instants.
- Use `DATE` for business dates such as invoice date, fiscal date or service date when time-of-day is not part of the meaning.
- Do not store local wall-clock timestamps without explicit timezone semantics.

## JSONB Rules

JSONB is permitted for:

- metadata definitions
- controlled custom attributes
- configuration
- workflow/UI definitions
- integration payloads
- event payloads
- provider-specific non-authoritative data

JSONB must not become a global escape hatch that replaces relational domain modeling.

Global EAV is prohibited.

## Migration Rules

- Every owning module owns its migrations.
- Alembic revisions are the explicit, versioned production migration mechanism.
- The BusinessOS framework builds one canonical graph across core and every discovered module,
  rejects cycles and shared revision/branch-label symbol collisions before connecting to the
  database, and intentionally supports deterministic multiple heads.
- Installed-module inventory is append-compatible and tamper-detecting. It records stable module,
  namespace, packaged-resource location, distribution, version, ancestry, dependency, branch-label
  and SHA-256 revision facts. Historical removal or rewrite fails preflight.
- Migration execution and inventory advancement use one PostgreSQL transaction protected by a
  transaction-scoped advisory lock. Failure or cancellation advances neither schema history nor
  inventory.
- SQLAlchemy `create_all`, metadata diff application or any other runtime ORM auto-sync is prohibited in production.
- Use expand-contract for rolling/compatible evolution.
- Destructive cleanup occurs only after old runtime/contracts are outside the supported compatibility window.
- Large backfills are resumable, observable and separately controlled from DDL where practical.

## Query Rules

- Prefer SQLAlchemy 2.x ORM or Core within module-owned repositories.
- Reviewed SQLAlchemy Core or explicit SQL is allowed for measured critical paths, but it must use the configured psycopg 3-backed engine/connection and participate in the active BusinessOS Unit of Work.
- Direct driver access outside an owning repository/provider requires explicit architecture justification.
- Every interactive endpoint has bounded queries and result sets.
- Avoid N+1 patterns.
- Large datasets use server-side filtering, pagination and indexes proven by query plans.
- New indexes require workload/query justification.

## Transactions and Outbox

The BusinessOS framework opens and closes Unit of Work scopes around command/query execution and never exposes ambient global sessions. Route handlers do not create sessions or control commits.

When a domain command produces an integration/domain event, authoritative state and the outbox record commit in the same PostgreSQL transaction and SQLAlchemy session/connection scope.

Publishing to NATS occurs after commit through the outbox publisher.

## Audit

Audit evidence is not a substitute for domain history. Critical domain histories, financial ledgers and inventory ledgers retain their own immutable business records in addition to security/business audit logs.
