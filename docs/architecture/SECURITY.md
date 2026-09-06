# BusinessOS Security Architecture Baseline

## Security Principles

- tenant isolation by design
- least privilege
- backend-authoritative authorization
- explicit trust boundaries
- secure defaults
- auditable privileged actions
- signed software supply chain
- customer-controlled self-hosted operation

## Identity

BusinessOS integrates with enterprise identity through standards:

- OIDC / OAuth 2.x
- SAML where required by customer identity providers
- MFA policy support
- service accounts and device identities for non-human workloads

Authentication mechanism details remain behind platform identity contracts.

## Authorization

Authorization must support combinations of:

- RBAC
- ABAC
- tenant membership
- company/legal-entity/site scope
- record scope
- field permissions
- approval authority
- segregation of duties
- delegated/time-bound authority

Frontend permission checks improve UX only. Backend policy enforcement is authoritative.

The BusinessOS framework owns permission registration and the authorization enforcement integration across ASGI routes, commands, queries, events and jobs. Modules declare permissions through the SDK and must not bypass framework enforcement middleware or trusted context resolution.

## Tenant Isolation

Tenant isolation applies to:

- PostgreSQL
- Redis
- NATS
- jobs/workflows
- object storage
- search
- analytics/exports
- integrations
- audit/support tooling

Cross-tenant access is a critical release-blocking defect.

## Secrets

Secrets must not be committed to Git or stored in normal module manifests/config JSON/logs/events.

Use secret references backed by an approved secret provider. Self-hosted installations must be able to select an appropriate provider without changing business modules.

## Third-Party Modules

Executable third-party modules default to isolated containers/processes with:

- scoped identity
- explicit capabilities
- no unrestricted DB access
- resource limits
- network restrictions where supported
- signed artifacts
- vulnerability scanning

## Supply Chain

Every production release should include:

- cryptographic signature
- checksums
- SBOM
- build provenance
- dependency/vulnerability scan results

## Support Access

Vendor/partner support access to customer data must be:

- explicit
- time-limited
- tenant-approved where required
- least privilege
- auditable

Self-hosted customers must retain the ability to operate without permanent vendor privileged access.

## Logging

Never log secrets, raw credentials, session tokens or unnecessarily sensitive business/health/financial content.

Security/business audit records should include actor, tenant, relevant scope, action, resource, decision time and correlation identifier.

## Security Review Triggers

Require explicit security review for:

- new authentication flows
- authorization model changes
- tenant-boundary changes
- payment credential handling
- encryption/key-management changes
- new third-party executable module capabilities
- public webhook/integration endpoints
- support/admin bypass capabilities
- changes affecting sensitive healthcare/financial/identity data.
