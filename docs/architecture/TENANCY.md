# BusinessOS Tenancy and Organization Architecture

## Tenant Boundary

Tenant is the highest customer-owned security and lifecycle boundary.

Tenant owns or scopes:

- data isolation
- entitlements
- quotas
- encryption/residency policies
- backup/restore
- export
- deletion
- module activation
- configuration

Tenant is not Company, Legal Entity, Branch, Warehouse or User.

## Supported Deployment Models

### Dedicated Enterprise

Primary self-hosted model. A customer receives a dedicated installation/data plane. Tenant-aware contracts remain mandatory so modules remain portable.

### Database per Tenant

Default BusinessOS Cloud enterprise model. Stateless runtime may be shared, while tenant database placement is independently routed and lifecycle-managed.

### Shared Schema

Optional certified model only. Every tenant-owned table requires `tenant_id`, PostgreSQL RLS, tenant-aware constraints and negative isolation tests.

## Canonical Organization Model

```text
Installation
└── Tenant
    ├── Enterprise Group
    │   └── Legal Entity
    │       └── Company
    │           ├── Business Unit
    │           ├── Division
    │           ├── Department
    │           ├── Team
    │           ├── Region assignments
    │           └── Operating Sites
    │               ├── Branch
    │               ├── Shop
    │               ├── Factory
    │               ├── Office
    │               ├── Hospital Facility
    │               ├── School Campus
    │               ├── Restaurant Outlet
    │               ├── Hotel Property
    │               └── Construction Site
    ├── Financial Dimensions
    │   ├── Cost Center
    │   ├── Profit Center
    │   ├── Project
    │   └── Channel / Responsibility Center
    └── Logistics
        ├── Warehouse
        ├── Warehouse Location
        ├── Logistics Node
        └── Transit Route
```

Legal Entity and Company remain distinct concepts.

Operating Site is generic and extensible. New verticals register site profiles rather than redesigning the organization core.

## TenantContext

Trusted execution context should carry at least:

```text
installation_id
tenant_id
principal_id
active_company_id?
authentication_strength
correlation_id
trace_id
```

Business scope may additionally contain:

```text
enterprise_group_id?
legal_entity_id?
company_id?
business_unit_id?
region_id?
operating_site_id?
warehouse_id?
cost_center_id?
profit_center_id?
project_id?
```

TenantContext is resolved from trusted authentication/membership and is immutable for a request, transaction, command, job, event-consumer invocation or workflow task.

Never trust tenant identity solely because a client supplied a tenant header.

The BusinessOS ASGI framework resolves the trusted context in middleware and injects typed `RequestContext`/`TenantContext` values into route, command and query handlers. Application/domain code does not read tenant identity directly from raw ASGI scope, request headers or ambient server state.

## Isolation Surfaces

Tenant isolation must cover more than PostgreSQL:

- database
- Redis keys
- NATS subjects/messages
- background jobs
- workflow instances
- object-storage prefixes/buckets
- search indexes/documents
- analytics exports
- audit records
- integration credentials
- support/admin tooling

## Conformance Rule

A cross-tenant exposure is a release-blocking critical defect. Every tenant-aware subsystem must have positive and negative isolation tests.
