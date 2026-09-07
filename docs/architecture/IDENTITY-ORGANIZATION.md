# BusinessOS Phase 2 Identity and Organization Architecture

Status: Phase 2 implementation specification

## Ownership

Phase 2 consists of three first-party in-process foundation distributions:

- `foundation.tenant` owns `platform_tenant`.
- `foundation.identity` owns `platform_identity` and depends on Tenant.
- `foundation.organization` owns `platform_org` and depends on Tenant and Identity.

They consume protected-platform capabilities only through `businessos.sdk`. Later modules consume
their published commands, queries, records and events; they do not write these schemas directly.

## Tenant lifecycle

The lifecycle is:

```text
requested -> provisioning -> active
provisioning -> terminating
active <-> suspended
active|suspended -> retention_hold
retention_hold -> active|terminating
active|suspended -> terminating -> deleted
```

Every change records actor, reason and time. Provisioning, state/history and its event outbox entry
share one tenant-scoped Unit of Work. Export, delete and restore are ordered lifecycle hook contracts;
their business-specific implementations remain owned by participating modules.

## Authentication trust

An HTTP tenant header is never authoritative. OIDC processing follows this order:

1. accept a bearer credential at the transport boundary;
2. resolve an approved HTTPS JWK set;
3. verify signature against an explicit asymmetric algorithm allowlist;
4. verify issuer, audience, expiry, issued-at and tenant claim;
5. verify that tenant is active under tenant RLS;
6. resolve issuer/subject to an active principal and effective membership under identity RLS;
7. create the immutable BusinessOS `RequestContext`/`TenantContext`.

SAML is exposed as a validation adapter contract. Local break-glass identities are local-only and
store only a secret-provider reference, never credential material. Service-account and device
identities remain tenant-scoped principals.

## Organization and scope

The canonical parentage is Tenant -> Enterprise Group -> Legal Entity -> Company. Business Unit,
Division, Department, Team, Region, Operating Site, financial dimensions and Warehouse/Location
identity are company-scoped. Composite tenant/parent constraints prevent a row from referencing a
parent in another tenant.

Active scope selection is immutable. Every selected record must belong to the tenant, selected
parent/child values must describe one consistent hierarchy, and the principal must have an
effective assignment or matching time-bounded delegation. Assignment/delegation representation in
Phase 2 does not replace the Phase 4 policy engine.

## Isolation and migrations

All 25 Phase 2 tables preserve `tenant_id`, enable and force PostgreSQL RLS, and are owned by
`businessos_migrator`. `businessos_app` has only ordinary DML privileges and cannot own or bypass
RLS. The three packaged Alembic chains participate in framework graph/inventory preflight and are
validated through upgrade, downgrade, replay, clean wheel and production-image tests.
