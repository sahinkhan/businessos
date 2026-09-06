# BusinessOS Engineering Contract for Codex

## Mandatory Reading Order

Before substantial implementation, Codex must read in this order:

1. `AGENTS.md` - this engineering contract
2. `docs/codex/MASTER-BUILD-INSTRUCTIONS.md` - complete BusinessOS product destination
3. `docs/roadmap/FULL-SYSTEM.md` - complete implementation sequence from kernel to enterprise ecosystem
4. `docs/architecture/MODULE-CATALOG.md` - canonical bounded-context/module map
5. architecture documents relevant to the task under `docs/architecture/`
6. accepted ADRs relevant to the task under `docs/adr/`
7. nearest scoped `AGENTS.md` for the directory being changed

`docs/roadmap/PHASE-1.md` is a detailed sub-roadmap for the first implementation phase. It is not the complete BusinessOS scope.

Architecture documentation and accepted ADRs are authoritative. Do not silently replace architectural decisions with convenience-driven implementation choices.

---

## Mission

BusinessOS is an international, enterprise-grade, modular business application platform designed for self-hosted enterprise deployment and optional vendor-hosted cloud deployment.

The platform must support:

- multi-tenant operation
- multi-enterprise and multi-legal-entity organizations
- multi-company, region, branch, shop, factory, operating-site and warehouse structures
- multi-language, RTL, multi-currency and multi-timezone operation
- safe customer and partner extensibility
- predictable long-term upgrades
- high-performance enterprise workloads
- business modules and industry solutions without protected-core forks

---

## Final Technology Baseline

### Backend
- Python is the primary backend and worker language.
- The custom BusinessOS HTTP framework uses ASGI with Starlette as a replaceable transport substrate and Uvicorn as the default server.
- Business and application code must depend on immutable BusinessOS `RequestContext` / `TenantContext` contracts, not Starlette request objects.
- gRPC + Protocol Buffers may be used at genuine internal service boundaries.

### Database
- PostgreSQL is the authoritative transactional source of truth.
- Prefer Psycopg 3 and explicit SQL or generated SQL for critical data paths.
- Production schema changes use explicit versioned migrations.

### Infrastructure
- Redis: cache, rate limiting, short-lived state and approved coordination.
- NATS JetStream: durable events, commands and background work distribution.
- S3-compatible object storage: documents, attachments, exports and archives.
- OpenTelemetry: traces, metrics and logs.

### Frontend
- React + TypeScript.
- React Router + Vite for authenticated enterprise backoffice.
- Next.js may be used for public storefronts/portals when SSR/SEO is justified.

### Deployment
- Docker / Docker Compose for development and small/single-server installations.
- Kubernetes + Helm for enterprise HA deployments.

---

## Architecture Layers

BusinessOS uses five layers:

1. Protected Kernel
2. Platform Foundation Modules
3. Shared Business Modules
4. Industry Solutions
5. Localization and Connectors

Dependencies must flow downward. A lower layer must never depend on a higher layer.

---

## Protected Kernel

The protected kernel may contain only generic runtime concerns:

- bootstrap/runtime
- TenantContext and RequestContext
- module registry and loader
- contract registry
- entity runtime primitives
- Unit of Work
- authorization enforcement entry point
- event/outbox runtime
- provider registry
- configuration runtime
- feature flags
- migration runtime
- compatibility runtime
- diagnostics/health/version

Do not add business-domain concepts to the protected kernel.

Prohibited kernel concepts include, but are not limited to:

- sales
- procurement
- accounting
- payroll
- hospital/patient
- school/student
- hotel/guest
- restaurant/menu
- POS
- manufacturing
- garments
- construction
- travel/ticketing

---

## Platform Foundation Modules

Reuse foundation modules before creating duplicate capabilities:

- Tenant Management
- Identity
- Organization
- Party / Contacts
- Address / Geography
- Policy / RBAC / ABAC
- Reference Data / External IDs
- Metadata / Studio
- Workflow / Rules / Case
- UoM / Precision
- Resource Management
- Scheduling / Reservation
- Collaboration / Activities
- Documents
- Notifications
- Reporting
- Import / Export
- Search
- Internationalization
- Data Governance
- Integrations
- Background Jobs
- Hierarchical Configuration

Foundation modules must remain industry-neutral.

---

## Shared Business Modules

Examples include:

- CRM
- Catalog
- Pricing
- Tax
- Sales
- Procurement
- Inventory
- Warehouse
- Logistics
- Billing
- Payments
- Accounting
- Assets
- HR
- Payroll
- Projects
- Manufacturing
- Maintenance
- Quality
- Helpdesk
- Field Service
- POS
- E-commerce

Each bounded context owns its:

- business invariants
- tables and schema
- migrations
- application services
- commands
- events
- APIs
- permissions
- tests

A module must not directly modify another module's private tables.

---

## Industry Solutions

Examples:

- Healthcare / Hospital / Clinic / Pharmacy
- Education / School
- Salon / Spa
- Gym / Fitness
- Restaurant
- Hospitality / Hotel
- Garments / Apparel
- Microfinance / Financial Services
- Fleet
- Legal
- Real Estate
- Construction
- E-commerce
- Travel / Air Ticketing

Industry modules must use public BusinessOS contracts and foundation/business modules.

They must not require protected-core modifications.

Industry-specific data belongs in vertical-owned schemas/profiles, not generic platform tables.

---

## Multi-Tenancy Rules

Tenant is the highest customer-owned security, lifecycle, quota, residency, backup, export and deletion boundary.

Never confuse:

- `installation_id`
- `tenant_id`
- `enterprise_group_id`
- `legal_entity_id`
- `company_id`
- `business_unit_id`
- `region_id`
- `operating_site_id`
- `warehouse_id`
- `user_id`

TenantContext must propagate through:

API -> application -> domain -> database -> Redis -> events -> jobs -> workflows -> object storage -> search -> audit.

Cross-tenant data access is a critical release-blocking defect.

BusinessOS must support:

- dedicated enterprise installation
- database-per-tenant cloud deployment
- certified shared-schema deployment

For shared-schema deployment, tenant-owned tables require RLS and database-level cross-tenant protection.

---

## Organization Model

The platform must support these distinct concepts:

Tenant -> Enterprise Group -> Legal Entity -> Company.

Additional organizational and operational structures include:

- Business Unit
- Division
- Department
- Team
- Region
- Operating Site
- Warehouse

Operating Site types may include:

- Branch
- Shop
- Factory
- Office
- Hospital Facility
- School Campus
- Restaurant Outlet
- Hotel Property
- Construction Site
- Service Center

Do not create a new core hierarchy for each industry. New site types should register profiles/extensions around the generic operating-site model.

---

## Database Rules

PostgreSQL is authoritative.

Every table has exactly one owning bounded context.

Rules:

- Tenant-owned records preserve `tenant_id`.
- A module must not directly update another module's private tables.
- Use immutable technical IDs (UUID strategy defined by architecture/ADR).
- Keep human/business numbers separate from technical IDs.
- Use exact `NUMERIC` values for money and precision-sensitive values.
- Store explicit currency codes with monetary values.
- Use `TIMESTAMPTZ` for instants.
- Use `DATE` for business/fiscal dates.
- Do not use FLOAT/REAL for money.
- Do not use a global EAV data model.
- Do not use JSONB as a replacement for relational modeling.
- JSONB is appropriate for metadata, controlled custom fields, configuration, contracts, UI/workflow definitions and integration/event payloads.
- Production schema synchronization from ORM metadata is prohibited.
- Use explicit migrations and expand-contract evolution for compatibility-sensitive changes.
- Posted financial and inventory ledger records are immutable; corrections use reversals/compensating entries.

---

## Python Architecture Rules

Default layering:

`transport -> application -> domain -> repository/provider`

Rules:

- Domain and application packages depend only on Python standard-library types and published BusinessOS contracts.
- Never pass Starlette `Request` objects into application/domain code.
- Pydantic models are boundary DTOs; domain models use framework-neutral Python types.
- Do not put business logic in HTTP handlers.
- Do not issue SQL directly from HTTP handlers.
- Repositories/data adapters are owned by their bounded context.
- Tenant and request context are immutable and explicitly propagated; `contextvars` may enrich telemetry but are not an authorization boundary.
- Avoid global mutable state and request-created fire-and-forget tasks.
- Prefer explicit constructor injection and composition roots over hidden service locators.
- Async code must not call blocking infrastructure clients on the event loop.
- Enforce module and layer dependencies with architecture/import tests.
- Default deployment architecture is a modular monolith.

Do not introduce a microservice without an architecture reason such as:

- independently measured scaling requirement
- failure isolation requirement
- security isolation requirement
- runtime/dependency conflict
- high-concurrency/streaming requirement
- separately managed lifecycle

---

## Event and Job Rules

Use a transactional outbox.

A business transaction that publishes an event must:

1. update authoritative domain state
2. write the outbox record in the same PostgreSQL transaction
3. commit
4. publish asynchronously to NATS JetStream

Consumers must be idempotent.

Commands request an action. Events describe facts that already happened.

Published events are versioned public contracts.

Modules must use the BusinessOS background-job abstraction instead of independently choosing queue frameworks.

---

## Extension Model

Preferred extension order:

1. configuration
2. metadata
3. workflow/rules
4. supported extension hooks
5. declarative module
6. isolated service module

Customer and partner modules must not edit protected core source.

Do not load untrusted customer or marketplace Python packages into the protected runtime. In-process Python modules are restricted to audited first-party code.

Executable customer/marketplace modules normally run in isolated OCI containers and communicate through supported contracts:

- REST/OpenAPI
- gRPC/Protobuf where appropriate
- NATS/AsyncAPI events
- provider interfaces
- frontend extension contracts

---

## Frontend Rules

Enterprise UI uses React + TypeScript.

Requirements:

- module route registration
- permission-aware presentation
- backend-authoritative authorization
- translation keys instead of hard-coded user-visible text
- RTL-aware layouts/components
- dynamic forms/lists where appropriate
- controlled extension slots
- server-side pagination/filtering for large datasets
- accessibility and keyboard support
- standardized BusinessOS design system

Do not import undocumented private frontend components across module boundaries.

A hidden button is not a security control.

---

## International Requirements

BusinessOS must support:

- multiple languages
- RTL
- multiple currencies
- multiple timezones
- multiple legal entities and fiscal contexts
- country localization modules

Country-specific statutory rules must not be hardcoded into protected kernel logic.

---

## Security Rules

Use enterprise identity standards:

- OIDC / OAuth 2.x
- SAML where required
- MFA policies
- service accounts/device identities for non-human workloads

Never commit secrets.

Use secret references and approved secret stores.

Third-party executable modules receive least privilege and no unrestricted database credentials.

Backend authorization is authoritative.

Support access to customer data must be explicit, time-limited and auditable.

---

## Full-System Planning Rule

The complete destination is defined in `docs/codex/MASTER-BUILD-INSTRUCTIONS.md` and `docs/roadmap/FULL-SYSTEM.md`.

Codex must understand the complete system before implementing individual phases, but must not generate the whole platform in one uncontrolled change.

Each phase must preserve future requirements of later phases. Never make a local shortcut that blocks a later business module, vertical, localization, marketplace module, tenancy mode or upgrade path already defined in the master roadmap.

---

## Coding Process

Before substantial coding:

1. read the mandatory documents listed at the top of this file
2. inspect existing patterns/code
3. determine the bounded-context owner
4. identify affected public contracts
5. identify tenancy/security/data ownership impact
6. identify impact on later roadmap phases
7. provide a concise implementation plan when the task is substantial

During coding:

- preserve architecture boundaries
- implement the smallest coherent change
- avoid unrelated refactors
- add tests
- add explicit migrations where required
- add telemetry/error handling appropriate to the feature

After coding:

1. run formatting
2. run static analysis/linting
3. run unit tests
4. run integration tests where applicable
5. run tenant-isolation tests where applicable
6. run contract/conformance tests where applicable
7. report commands executed
8. report files changed
9. report migrations and contract changes
10. report unresolved risks

Never claim a command/test passed unless it actually ran successfully.

---

## Architecture Changes

Do not silently change architecture.

If an implementation request conflicts with an accepted architecture rule, stop and report:

- current architecture rule
- discovered limitation
- proposed alternative
- tenancy impact
- security impact
- compatibility impact
- migration impact
- later-roadmap impact

Then propose an ADR before implementing the architecture change.

---

## Definition of Done

A feature is not complete until applicable checks pass:

- unit tests
- integration tests
- tenant-isolation tests
- authorization tests
- explicit migrations
- API/event compatibility checks
- observability/error behavior
- documentation
- formatting/lint/static analysis
- architecture/conformance checks

Architecture compliance is part of Definition of Done.