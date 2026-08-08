# BusinessOS

BusinessOS is an enterprise-grade modular business application platform designed for international organizations, self-hosted enterprise customers and optional vendor-hosted cloud deployments.

The objective is to provide an extensible platform capable of supporting ERP, retail, scheduling, hospitality, healthcare, education, manufacturing, financial-service and other industry applications without customer modifications to protected core source.

## Architecture Principles

- protected, deliberately small kernel
- domain-structured modular monolith first
- module-owned data and migrations
- multi-tenant by design
- multinational organization model
- public versioned contracts
- customer extensions without core forks
- predictable upgrades
- internationalization/localization as foundations
- performance and observability from the beginning

## Technology Baseline

| Area | Technology |
| --- | --- |
| Backend / Workers | Go |
| HTTP | Gin as transport adapter |
| Internal RPC | gRPC + Protocol Buffers when justified |
| Database | PostgreSQL |
| Data Access | pgx + explicit/generated SQL |
| Cache | Redis |
| Durable Events / Jobs | NATS JetStream |
| Object Storage | S3-compatible |
| Enterprise Frontend | React + TypeScript + React Router + Vite |
| Public Web | Next.js when SSR/SEO is justified |
| Observability | OpenTelemetry |
| Development Deployment | Docker Compose |
| Enterprise HA | Kubernetes + Helm |

## Architecture Layers

```text
Protected Kernel
    ↓
Platform Foundation Modules
    ↓
Shared Business Modules
    ↓
Industry Solutions
    ↓
Localization / Connectors
```

## Documentation

Start here:

- [`AGENTS.md`](AGENTS.md) - mandatory engineering/Codex contract
- [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md) - architecture baseline
- [`docs/architecture/TENANCY.md`](docs/architecture/TENANCY.md) - tenancy and organization model
- [`docs/architecture/DATABASE.md`](docs/architecture/DATABASE.md) - PostgreSQL rules
- [`docs/architecture/MODULES.md`](docs/architecture/MODULES.md) - module/extension model
- [`docs/architecture/EVENTS.md`](docs/architecture/EVENTS.md) - event/job model
- [`docs/architecture/SECURITY.md`](docs/architecture/SECURITY.md) - security baseline
- [`docs/architecture/FRONTEND.md`](docs/architecture/FRONTEND.md) - frontend architecture
- [`docs/architecture/UPGRADES.md`](docs/architecture/UPGRADES.md) - upgrade/compatibility model
- [`docs/architecture/DEVELOPMENT.md`](docs/architecture/DEVELOPMENT.md) - engineering workflow
- [`docs/roadmap/PHASE-1.md`](docs/roadmap/PHASE-1.md) - protected-kernel roadmap
- [`docs/adr/`](docs/adr/) - accepted architecture decisions

## Repository Direction

```text
businessos/
├── platform/       # protected platform/kernel, contracts, SDKs, frontend shell
├── foundations/    # reusable industry-neutral foundations
├── modules/        # shared business modules
├── verticals/      # industry solutions
├── services/       # independently deployed first-party services
├── deployment/     # compose/helm/operator/air-gap assets
├── docs/           # architecture, ADRs, standards and roadmap
└── tests/          # cross-cutting conformance/integration suites
```

## Current Status

Architecture bootstrap and Phase 1 planning.

The first implementation milestone is the protected kernel/runtime and an external proof module that demonstrates installation, tenant-aware operation, migrations, API/UI extension, events, upgrade and lifecycle without modifying protected kernel source.

## Development Rule

Before substantial implementation, read `AGENTS.md` and the architecture/ADR documents relevant to the task. Architecture changes require an ADR rather than silent implementation divergence.