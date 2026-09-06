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
| Backend / Workers | Python 3.13+ |
| Application Framework | Custom BusinessOS framework built on ASGI |
| ASGI Server | Uvicorn |
| Internal RPC | gRPC + Protocol Buffers when justified |
| Database | PostgreSQL |
| Data Access | SQLAlchemy 2.x + psycopg 3 |
| Migrations | Alembic |
| Boundary Validation | Pydantic 2 |
| Backend Quality | pytest + Ruff + mypy; Pyright supported |
| Cache | Redis |
| Durable Events / Jobs | NATS JetStream |
| Object Storage | S3-compatible |
| Enterprise Frontend | React + TypeScript + React Router + Vite |
| Public Web | Next.js when SSR/SEO is justified |
| Observability | OpenTelemetry |
| Development Deployment | Docker Compose |
| Enterprise HA | Kubernetes + Helm |

The Python/ASGI runtime is the only approved primary backend and in-process module model. Go is reserved for a possible future isolated, performance-sensitive microservice when measurement and architecture review justify it.

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

## Mandatory Starting Documents

Codex and developers should start with these documents:

1. [`AGENTS.md`](AGENTS.md) - mandatory engineering contract
2. [`docs/codex/MASTER-BUILD-INSTRUCTIONS.md`](docs/codex/MASTER-BUILD-INSTRUCTIONS.md) - complete BusinessOS product/build instructions
3. [`docs/roadmap/FULL-SYSTEM.md`](docs/roadmap/FULL-SYSTEM.md) - complete roadmap from kernel through ERP, verticals, marketplace, cloud and LTS
4. [`docs/architecture/MODULE-CATALOG.md`](docs/architecture/MODULE-CATALOG.md) - canonical module/bounded-context catalog

## Architecture Documentation

- [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md) - architecture baseline
- [`docs/architecture/TENANCY.md`](docs/architecture/TENANCY.md) - tenancy and organization model
- [`docs/architecture/DATABASE.md`](docs/architecture/DATABASE.md) - PostgreSQL rules
- [`docs/architecture/MODULES.md`](docs/architecture/MODULES.md) - module/extension model
- [`docs/architecture/EVENTS.md`](docs/architecture/EVENTS.md) - event/job model
- [`docs/architecture/SECURITY.md`](docs/architecture/SECURITY.md) - security baseline
- [`docs/architecture/FRONTEND.md`](docs/architecture/FRONTEND.md) - frontend architecture
- [`docs/architecture/UPGRADES.md`](docs/architecture/UPGRADES.md) - upgrade/compatibility model
- [`docs/architecture/DEVELOPMENT.md`](docs/architecture/DEVELOPMENT.md) - engineering workflow
- [`docs/development/SETUP.md`](docs/development/SETUP.md) - Python 3.13, Docker and validation setup
- [`docs/adr/`](docs/adr/) - accepted architecture decisions
- [`docs/adr/ADR-008-python-asgi-technology-baseline.md`](docs/adr/ADR-008-python-asgi-technology-baseline.md) - current Python/ASGI technology decision

## Roadmaps

- [`docs/roadmap/FULL-SYSTEM.md`](docs/roadmap/FULL-SYSTEM.md) - authoritative complete system roadmap
- [`docs/roadmap/PHASE-1.md`](docs/roadmap/PHASE-1.md) - detailed protected-kernel sub-roadmap

`PHASE-1.md` is not the complete product scope. It is the detailed first implementation stage of the full roadmap.

## Full Product Destination

The master roadmap covers the complete product lifecycle, including:

- protected kernel/runtime
- tenant/identity/organization
- Party/Geography/UoM/Reference Data
- authorization/audit/data governance
- metadata/studio/dynamic UI
- workflow/rules/resource/scheduling
- documents/collaboration/notifications
- search/reporting/import/export
- integration platform
- catalog/pricing/tax
- CRM/Sales
- Procurement
- Inventory/Warehouse/Logistics
- Billing/Payments
- Accounting/Finance
- Assets/Expenses/Treasury
- HR/Payroll
- Project/Helpdesk/Field Service
- Manufacturing/Maintenance/Quality
- POS
- E-commerce
- Healthcare/Hospital/Clinic/Pharmacy
- Education/School
- Salon/Spa/Gym
- Restaurant
- Hotel/Hospitality
- Garments/Apparel
- Construction/Real Estate
- Fleet/Logistics
- Microfinance/Financial Services
- Legal
- Travel/Air Ticketing
- country localization
- marketplace/developer platform
- self-hosted enterprise operations
- BusinessOS Cloud control plane
- performance certification
- security/compliance maturity
- LTS/compatibility/partner ecosystem

## Repository Direction

```text
businessos/
├── platform/       # protected platform/kernel, contracts, SDKs, frontend shell
├── foundations/    # reusable industry-neutral foundations
├── modules/        # shared business modules
├── verticals/      # industry solutions
├── services/       # independently deployed first-party services
├── deployment/     # compose/helm/operator/air-gap assets
├── docs/           # architecture, ADRs, standards, Codex instructions and roadmap
└── tests/          # cross-cutting conformance/integration suites
```

## Current Status

Phase 0's Python/ASGI documentation cutover is complete. Phase 1 now provides the protected custom ASGI framework foundation, PostgreSQL/Alembic runtime and an external SDK proof module. No business modules or later roadmap foundations are implemented.

The external proof module demonstrates discovery, installation, tenant-aware API operation, module-owned migrations, metadata, permissions, commands/queries/events, object storage, v1-to-v2 upgrade and lifecycle without modifying protected kernel source.

## Development Rule

Codex must understand the full-system roadmap before implementing individual work units. Implementation still proceeds incrementally so architecture, migrations, security, tests and compatibility can be validated at each dependency boundary.

Architecture changes require an ADR rather than silent implementation divergence.
