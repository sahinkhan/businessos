# BusinessOS Phase 1 - Protected Kernel Roadmap

Status: Planning baseline

Prerequisite: Phase 0 documentation cutover and ADR-008 are accepted. This roadmap does not authorize Python scaffolding during Phase 0.

## Goal

Create the minimum protected platform runtime on which foundation and business modules can safely depend.

Do not build Sales, Accounting, Hospital, School, POS, Manufacturing or other business modules during this phase.

## Phase 1A - Runtime Skeleton

Deliver:

- Python 3.13+ project/package boundary conventions
- custom BusinessOS ASGI application framework bootstrap
- Uvicorn process/server configuration boundary
- application bootstrap
- configuration loader and validation
- graceful startup/shutdown
- RequestContext/TenantContext primitives
- ASGI routing and middleware pipeline
- dependency-injection scopes
- command/query dispatch contracts
- structured errors
- structured logging facade
- OpenTelemetry bootstrap
- health/readiness/version endpoints
- Docker Compose developer environment

Exit criteria:

- raw ASGI scope and Uvicorn objects do not leak into application/domain code
- route handlers resolve typed BusinessOS contexts and dependencies through the framework
- middleware ordering and dependency-scope teardown tests pass
- context propagation tests pass
- invalid configuration fails fast
- runtime shuts down gracefully
- health/version diagnostics are testable

## Phase 1B - PostgreSQL Runtime

Deliver:

- SQLAlchemy 2.x engine/session management using psycopg 3
- framework-owned transaction/Unit of Work abstraction
- Alembic migration runtime and module revision conventions
- tenant-aware data access primitives
- transaction integration tests
- migration test harness

Exit criteria:

- no SQL or SQLAlchemy session management from ASGI route handlers
- transaction boundaries are explicit
- sessions and transactions close or roll back reliably on failure/cancellation
- tenant scope cannot be accidentally omitted from tenant-aware primitives
- migrations are deterministic and versioned

## Phase 1C - Module Runtime

Deliver:

- module manifest schema/parser
- deterministic module discovery and registry
- dependency graph validation
- compatibility checks
- module lifecycle state model
- contract registry
- provider registry
- route/middleware/dependency registration
- command/query/event registration
- metadata and permission registration
- BusinessOS Python module SDK compatibility checks
- upgrade coordination hooks

Exit criteria:

- invalid dependency graph is rejected
- incompatible platform range is rejected
- duplicate contract ownership is rejected
- duplicate route, command/query, metadata or permission ownership is rejected
- module state is observable through diagnostics

## Phase 1D - Events and Jobs

Deliver:

- outbox schema/runtime
- framework command/query and event dispatch
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
- framework permission registry and enforcement integration
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
- dependency, command and query registration
- metadata registration
- permission registration
- TenantContext access
- event publish/consume
- object storage use
- v1 -> v2 upgrade
- disable/retire lifecycle

No protected kernel edits are permitted to make the demo module work.

The proof module is a first-party test of the published Python SDK. Customer/marketplace executable code remains isolated by default under ADR-004.

## Phase 1 Definition of Done

Phase 1 is complete only when the external proof module passes conformance and the kernel/foundation contracts required by Phase 2 are documented and tested.
