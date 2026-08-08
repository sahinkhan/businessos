# BusinessOS Phase 1 - Protected Kernel Roadmap

Status: Planning baseline

## Goal

Create the minimum protected platform runtime on which foundation and business modules can safely depend.

Do not build Sales, Accounting, Hospital, School, POS, Manufacturing or other business modules during this phase.

## Phase 1A - Runtime Skeleton

Deliver:

- Go workspace/module structure
- package/dependency boundary conventions
- application bootstrap
- configuration loader and validation
- graceful startup/shutdown
- RequestContext/TenantContext primitives
- structured errors
- structured logging facade
- OpenTelemetry bootstrap
- health/readiness/version endpoints
- Docker Compose developer environment

Exit criteria:

- transport code does not leak Gin context into application/domain code
- context propagation tests pass
- invalid configuration fails fast
- runtime shuts down gracefully
- health/version diagnostics are testable

## Phase 1B - PostgreSQL Runtime

Deliver:

- pgx connection/pool management
- transaction/Unit of Work abstraction
- migration runtime
- tenant-aware data access primitives
- transaction integration tests
- migration test harness

Exit criteria:

- no SQL from HTTP handlers
- transaction boundaries are explicit
- tenant scope cannot be accidentally omitted from tenant-aware primitives
- migrations are deterministic and versioned

## Phase 1C - Module Runtime

Deliver:

- module manifest schema/parser
- module registry
- dependency graph validation
- compatibility checks
- module lifecycle state model
- contract registry
- provider registry

Exit criteria:

- invalid dependency graph is rejected
- incompatible platform range is rejected
- duplicate contract ownership is rejected
- module state is observable through diagnostics

## Phase 1D - Events and Jobs

Deliver:

- outbox schema/runtime
- NATS JetStream provider
- outbox publisher
- inbox/idempotency primitive
- background job contract
- retry/dead-letter conventions
- correlation/trace propagation

Exit criteria:

- state + outbox commit atomically
- publisher failure does not lose committed events
- redelivery does not duplicate certified side effects

## Phase 1E - Security Boundary

Deliver:

- identity/authentication facade
- OIDC boundary
- principal/service-account representation
- authorization enforcement facade
- policy contract
- secret-provider abstraction
- security audit hooks

Exit criteria:

- protected operations require backend authorization
- tenant identity comes from trusted membership/context
- secrets are not stored in normal config/manifests/logs

## Phase 1F - Infrastructure Providers

Deliver:

- Redis provider abstraction
- S3-compatible object-storage provider
- NATS provider health
- provider capability registry
- per-tenant key/namespace conventions

Exit criteria:

- infrastructure implementations can be replaced without changing business modules
- tenant namespaces are covered by isolation tests

## Phase 1G - Architecture Proof Module

Build a small external demo module using only published platform contracts.

It must demonstrate:

- manifest installation
- module-owned schema/migration
- API registration
- permission registration
- TenantContext access
- event publish/consume
- object storage use
- v1 -> v2 upgrade
- disable/retire lifecycle

No protected kernel edits are permitted to make the demo module work.

## Phase 1 Definition of Done

Phase 1 is complete only when the external proof module passes conformance and the kernel/foundation contracts required by Phase 2 are documented and tested.