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
share one tenant-scoped Unit of Work. A transition that requires export, delete or restore work
writes a durable `tenant.lifecycle.work-requested.v1` event in that same transaction. The event is
delivered only after commit, and its durable consumer invokes ordered lifecycle hooks with the event
ID as a stable operation ID. Hook implementations must be idempotent because a failed delivery is
retried with the same operation ID. External side effects cannot occur before the database
transition commits; a hook failure leaves retryable durable work.

Tenant entitlements are the Phase 2 subscription abstraction: their effective period and external
`reference` identify the plan/subscription authority without making billing a Tenant concern.
Quota records remain a separate public read model.

## Authentication trust

An HTTP tenant header is never authoritative. OIDC processing follows this order:

1. accept a bearer credential at the transport boundary;
2. resolve an approved HTTPS JWK set;
3. verify signature against an explicit asymmetric algorithm allowlist;
4. verify issuer, audience, expiry, issued-at and tenant claim;
5. verify that tenant is active under tenant RLS;
6. resolve issuer/subject to an active principal and effective membership under identity RLS;
7. create the immutable BusinessOS `RequestContext`/`TenantContext`.

The shipped ASGI composition discovers exactly one trusted context-resolver entry point. Installing
Identity supplies the OIDC resolver, wired to the framework-owned Unit of Work; configured providers
and MFA policy therefore govern normal Uvicorn requests. An installation with multiple resolver
providers fails startup composition instead of choosing one implicitly.

SAML is exposed as a validation adapter contract. Local break-glass identities are local-only and
store only a secret-provider reference, never credential material. Service-account and device
identities remain tenant-scoped principals. These federation/credential adapters feed validated
`PrincipalIdentity` values into the same application boundary; Phase 2 does not define browser or
protocol transport endpoints. Authentication-session commands create, validate, query and revoke
tenant-scoped session context for users, service accounts and devices, and emit start/revoke events.
Session creation derives the principal and authentication strength exclusively from the trusted
`RequestContext`; callers cannot target another principal or assert their own assurance level. MFA
policy minimum strength is a closed `AuthenticationStrength` value at the command and database
boundaries. The Phase 2 upgrade rejects unsupported historical values rather than accepting a policy
the runtime cannot enforce.

## Organization and scope

The canonical parentage is Tenant -> Enterprise Group -> Legal Entity -> Company. Business Unit,
Division, Department, Team, Region, Operating Site, financial dimensions and Warehouse/Location
identity are company-scoped. Composite tenant/parent constraints prevent a row from referencing a
parent in another tenant.

Active scope selection is an auditable command because it writes a durable selection event. Command
dispatch commits the selection and event atomically; the handler does not own a separate transaction
boundary. Every selected record must belong to the tenant, selected
parent/child values must describe one consistent hierarchy, and the principal must have an
effective assignment or matching time-bounded delegation. Assignment/delegation representation in
Phase 2 does not replace the Phase 4 policy engine. A delegation must cover every explicitly selected
record and include the requested action. A child-only grant cannot authorize an explicitly selected
ancestor, while an ancestor grant may authorize its consistent descendants.

## Isolation and migrations

All 25 Phase 2 tables preserve `tenant_id`, enable and force PostgreSQL RLS, and are owned by
`businessos_migrator`. `businessos_app` has only ordinary DML privileges and cannot own or bypass
RLS. The three packaged Alembic chains participate in framework graph/inventory preflight and are
validated through upgrade, downgrade, replay, clean wheel and production-image tests.
