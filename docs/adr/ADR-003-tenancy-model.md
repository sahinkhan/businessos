# ADR-003: BusinessOS Tenancy Model

Status: Accepted

## Decision

Tenant is the highest customer-owned security/lifecycle boundary.

Supported modes:

1. Dedicated enterprise installation - primary self-hosted model.
2. Database-per-tenant - default BusinessOS Cloud enterprise model.
3. Shared-schema - optional certified model requiring `tenant_id`, PostgreSQL RLS, tenant-aware constraints and subsystem isolation.

Tenant identity remains distinct from enterprise group, legal entity, company, site, warehouse and user.

## Consequences

All platform contracts remain tenant-aware even when an installation currently hosts one customer. Tenant context must propagate across data, cache, events, jobs, files, search, workflows and audit.