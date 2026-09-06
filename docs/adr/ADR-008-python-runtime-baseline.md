# ADR-008: Python Runtime and Service Extraction Baseline

Status: Accepted  
Supersedes: ADR-001

## Context

BusinessOS needs fast, maintainable development for a very broad modular business platform while preserving strict tenancy, module ownership, upgrade compatibility, self-hosting and enterprise operational requirements.

The repository is still an architecture bootstrap and has no Go/Gin implementation. The backend baseline can therefore change before production code, public runtime contracts or deployed modules exist.

A “custom Python framework” must concentrate custom code on BusinessOS-specific behavior. Reimplementing HTTP parsing, TLS, cryptography, identity protocols, PostgreSQL drivers or message brokers would increase security and maintenance risk without creating BusinessOS value.

## Decision

### Primary runtime

Python is the sole primary language for the protected kernel, API application, workers, trusted first-party foundation modules and trusted first-party business modules.

The default runtime is async-first. Blocking work must be isolated from the event loop, and API and durable-worker processes remain independently scalable.

### BusinessOS framework boundary

BusinessOS will build a custom application framework that owns:

- immutable `RequestContext` and `TenantContext`
- application bootstrap and lifecycle
- module manifest, registry, dependency graph and lifecycle
- contract and provider registries
- Unit of Work conventions
- authorization enforcement boundary
- tenant-aware data-access primitives
- transactional outbox/inbox and job abstractions
- migration coordination and compatibility checks
- configuration, feature flags, diagnostics and conformance tests

The framework uses the ASGI standard, Starlette as a replaceable HTTP transport substrate and Uvicorn as the default ASGI server.

Application and domain code must not depend on Starlette request objects or other transport-specific types. Context is passed explicitly through published BusinessOS contracts. Python `contextvars` may support logging and tracing but are not a security or authorization boundary.

### Data and infrastructure adapters

- PostgreSQL remains authoritative.
- Psycopg 3 with asynchronous pooling and explicit parameterized/generated SQL is the primary database-access strategy.
- Production schema changes remain explicit, versioned and module-owned. ORM metadata synchronization is prohibited.
- Redis, NATS JetStream, S3-compatible storage and OpenTelemetry remain behind BusinessOS provider contracts.
- Identity continues to use proven OIDC/OAuth 2.x and SAML implementations. BusinessOS will not implement cryptography or identity protocols from scratch.

### Module execution

Audited first-party Python modules may run in-process through published framework and SDK contracts.

Customer and marketplace executable modules are not imported into the protected Python runtime. They remain declarative or execute as isolated OCI containers/processes with least-privileged identities and versioned REST/OpenAPI, gRPC/Protobuf, NATS/AsyncAPI, provider and frontend-extension contracts.

### Future Go services

BusinessOS will not maintain duplicate Python and Go implementations of the protected kernel or the same bounded context.

Go may be introduced later only for an independently deployable service when profiling and representative load tests demonstrate a material need such as CPU throughput, high-concurrency streaming, memory density, independent scaling, failure isolation or security isolation.

A Go extraction requires:

- a clear bounded-context or infrastructure-service owner
- stable language-neutral APIs/events
- an ADR and measured SLO/cost evidence
- contract and tenant-isolation tests
- shadow/canary rollout and rollback
- single-writer data ownership

A future Go service must not share uncontrolled writes to Python-owned private tables.

### Engineering toolchain

The Python workspace uses `pyproject.toml` with a committed dependency lockfile. The baseline quality gates are Ruff, strict static type checking, pytest, architecture/import-boundary tests, dependency and secret scanning, migration tests, contract tests and tenant-isolation tests.

## Consequences

Python improves development speed and access to business, data and AI libraries while retaining the existing modular-monolith and contract-first architecture.

The protected runtime must enforce import boundaries, explicit context propagation, async safety and tenant-scoped provider use. Python process/GIL characteristics are handled through async I/O, multiple worker processes, batching and measured optimization before service extraction.

Low-level infrastructure remains replaceable. Business modules depend on BusinessOS contracts rather than Starlette, Psycopg, Redis, NATS, S3 or identity-client internals.

This decision preserves the option to add Go services later without making Go part of the initial core or creating two BusinessOS implementations.
