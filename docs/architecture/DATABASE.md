# BusinessOS PostgreSQL Architecture

## Purpose

This document defines database rules that all BusinessOS platform, foundation, business and vertical modules must follow.

## Source of Truth

PostgreSQL is the authoritative transactional system of record.

Redis, search indexes, caches, reporting projections and event streams may contain derived state but are not replacements for authoritative transactional data unless a future ADR explicitly defines a bounded context otherwise.

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
- Production schema changes are explicit and versioned.
- ORM auto-sync is prohibited in production.
- Use expand-contract for rolling/compatible evolution.
- Destructive cleanup occurs only after old runtime/contracts are outside the supported compatibility window.
- Large backfills are resumable, observable and separately controlled from DDL where practical.

## Query Rules

- Prefer Psycopg 3 and explicit/generated SQL for critical paths.
- Every interactive endpoint has bounded queries and result sets.
- Avoid N+1 patterns.
- Large datasets use server-side filtering, pagination and indexes proven by query plans.
- New indexes require workload/query justification.

## Transactions and Outbox

When a domain transaction produces an integration/domain event, authoritative state and the outbox record commit in the same PostgreSQL transaction.

Publishing to NATS occurs after commit through the outbox publisher.

## Audit

Audit evidence is not a substitute for domain history. Critical domain histories, financial ledgers and inventory ledgers retain their own immutable business records in addition to security/business audit logs.