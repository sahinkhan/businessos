# ADR-008: Python and ASGI Technology Baseline

Status: Accepted

Supersedes: [ADR-001](ADR-001-technology-baseline.md)

## Context

The original Go/Gin/pgx baseline no longer represents the approved direction for BusinessOS. BusinessOS needs a Python-first backend that retains explicit platform boundaries, enterprise-grade data integrity, typed public contracts and predictable module upgrades without delegating core platform behavior to a general-purpose web framework.

## Decision

Use:

- Python 3.13 or newer as the primary backend and worker language
- a custom BusinessOS framework built on the ASGI protocol
- Uvicorn as the default ASGI server
- PostgreSQL as the authoritative transactional source of truth
- SQLAlchemy 2.x as the standard persistence and SQL toolkit
- psycopg 3 as the PostgreSQL driver
- Alembic for explicit, versioned database migrations
- Pydantic 2 for validation and serialization at API, command, query, event, configuration and manifest boundaries
- pytest for tests
- Ruff for formatting and linting
- mypy as the required CI type checker, with Pyright approved for secondary/editor type checking

The BusinessOS framework, rather than Uvicorn or an adopted web framework, owns:

- module discovery and lifecycle
- routing
- middleware
- dependency injection
- command and query dispatch
- event registration, dispatch and outbox integration
- metadata registration and resolution
- permission registration and enforcement integration
- unit-of-work and transaction boundaries
- the module SDK and upgrade coordination

Uvicorn hosts the ASGI application but does not define application architecture. Raw ASGI scope and server objects stop at the framework transport boundary. Application and domain code use typed BusinessOS contexts and contracts.

SQLAlchemy sessions and transactions are created and closed through framework-owned units of work. Each bounded context owns its mappings, repositories and Alembic revisions. Production schema creation or synchronization from ORM metadata is prohibited. Reviewed SQLAlchemy Core or explicit SQL may be used for measured critical paths while remaining inside the owning module and active unit of work.

Pydantic models are boundary contracts by default; they do not replace domain models or SQLAlchemy persistence models.

Go is not an alternative primary backend or in-process module runtime. It remains an optional future language for isolated, performance-sensitive microservices only when profiling and architecture review justify extraction. Those services must communicate through versioned BusinessOS contracts and follow the same tenancy, security, observability and upgrade rules.

## Consequences

- Phase 1 begins with the BusinessOS ASGI framework and Python runtime contracts; it does not begin with business-module implementation.
- Framework conformance tests must prove lifecycle, routing, middleware ordering, dependency scopes, context propagation, transaction handling, permissions and upgrade behavior.
- First-party in-process modules use the versioned BusinessOS Python SDK and must not couple to Uvicorn internals or bypass framework registries.
- Customer and marketplace executable modules continue to default to isolated processes or OCI containers under ADR-004.
- Adding another application framework, database ORM/driver, migration system or primary backend language requires a superseding ADR.
