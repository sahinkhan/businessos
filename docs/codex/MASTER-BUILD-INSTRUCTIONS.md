# BusinessOS Master Build Instructions for Codex

Status: Authoritative implementation guidance

This document describes the complete BusinessOS destination. It is not a single-task prompt. Codex must use it together with root/scoped `AGENTS.md`, architecture documents, ADRs and the roadmap.

## 1. Product Mission

Build BusinessOS as an international enterprise business application platform comparable in breadth to Odoo-class platforms, while emphasizing stronger self-hosting, safer extension isolation, upgrade compatibility, multi-tenancy, multinational organizations, performance, enterprise security and customer module development.

The product must support both self-hosted enterprise installations and an optional vendor-hosted cloud model without separate product forks.

## 2. Core Product Capabilities

BusinessOS must support:

- multi-tenant
- multi-enterprise group
- multi-legal entity
- multi-company
- multi-business unit/division/department/team
- multi-region
- multi-branch
- multi-shop
- multi-factory
- multi-operating-site
- multi-warehouse/location
- multi-cost-center
- multi-profit-center
- multi-currency
- multi-language
- RTL
- multi-timezone
- country localization
- customer-specific extensions
- on-premise, private cloud, public cloud and air-gapped deployment

## 3. Final Technology Baseline

Backend and workers:
- Go

HTTP:
- Gin as transport adapter only

Internal RPC:
- gRPC + Protocol Buffers only at justified service boundaries

Database:
- PostgreSQL

Database access:
- pgx
- explicit SQL/generated SQL

Cache/transient coordination:
- Redis

Durable messaging/jobs:
- NATS JetStream

Object storage:
- S3-compatible

Enterprise frontend:
- React
- TypeScript
- React Router
- Vite

Optional public/storefront frontend:
- Next.js when SSR/SEO is justified

Observability:
- OpenTelemetry

Development deployment:
- Docker Compose

Enterprise HA:
- Kubernetes + Helm

## 4. Architecture Layers

### Layer 1 - Protected Kernel

Build only generic platform runtime concerns:

- bootstrap
- configuration runtime
- TenantContext / RequestContext
- module registry/loader
- contract registry
- Unit of Work
- authorization enforcement boundary
- event/outbox runtime
- provider registry
- feature flags
- migration runtime
- compatibility/runtime version checks
- diagnostics and health

No business-domain logic belongs here.

### Layer 2 - Platform Foundations

Build reusable industry-neutral modules:

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
- Integration Framework
- Background Jobs
- Hierarchical Configuration

### Layer 3 - Shared Business Modules

Build reusable business domains:

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
- Fixed Assets
- HR
- Payroll
- Projects
- Manufacturing
- POS
- E-commerce
- Maintenance
- Quality
- Helpdesk
- Field Service

### Layer 4 - Industry Solutions

Build industry-specific modules by composing foundations/business modules:

- Education / School Management
- Hospital / Healthcare / Clinic
- Pharmacy
- Salon / Spa
- Gym / Fitness
- Restaurant
- Hotel / Hospitality
- Garments / Apparel
- Microfinance
- Core Banking extensions
- Fleet
- Legal Practice
- Real Estate / Property
- Construction
- Travel / Air Ticketing
- additional future verticals

### Layer 5 - Localization and Connectors

Build replaceable country/integration modules:

- Bangladesh localization
- UK localization
- UAE localization
- US localization
- country tax packs
- payroll localization
- e-invoicing/local reporting
- payment gateways
- banks
- courier/logistics providers
- GDS/NDC
- government services
- healthcare exchanges
- messaging/email/SMS providers

## 5. Mandatory Foundation Abstractions Before Vertical Growth

The following must become stable public contracts before large-scale vertical development:

1. TenantContext
2. Organization and Operating Site
3. Party
4. Address/Geography
5. Resource
6. Scheduling/Reservation
7. UoM/Precision
8. Reference Data/External IDs
9. Metadata/Dynamic UI
10. Workflow/Rules
11. Authorization Policy
12. Documents
13. Notifications/Activities
14. Reporting
15. Import/Export
16. Jobs
17. Provider Registry
18. Configuration Inheritance
19. Audit/Data Governance
20. Internationalization/Currency

## 6. Data and Database Rules

- PostgreSQL is authoritative.
- Each bounded context owns its schema/tables/migrations.
- Cross-module direct writes are prohibited.
- Tenant-owned data preserves tenant identity.
- Shared-schema mode requires RLS and tenant-aware constraints.
- Money uses exact NUMERIC plus currency code.
- Use TIMESTAMPTZ for instants and DATE for business dates.
- JSONB is not a substitute for relational modeling.
- No global EAV model.
- Production migrations are explicit/versioned.
- Use expand-contract evolution.
- Financial/inventory posted ledgers are immutable.
- Derived caches/search/report projections are not authoritative.

## 7. Extension Model

BusinessOS must enable customers to create modules without editing core.

Extension priority:

1. configuration
2. metadata
3. workflow/rules
4. supported hooks
5. declarative module
6. isolated executable service

Do not use Go native plugins as the marketplace mechanism.

Third-party executable modules normally run in isolated OCI containers/processes and interact through:

- REST/OpenAPI
- gRPC/Protobuf
- NATS events/AsyncAPI
- provider contracts
- frontend extension slots

## 8. Dynamic UI / Studio

BusinessOS should support metadata-driven:

- entities/custom fields
- menus
- list views
- forms
- details
- kanban
- calendars
- dashboards
- actions
- wizards
- reports
- validation rules
- workflows

Dynamic UI definitions are versioned data/contracts, not arbitrary code stored in the DB.

## 9. Organization and Multinational Model

Canonical structure:

```text
Tenant
├── Enterprise Group
│   └── Legal Entity
│       └── Company
│           ├── Business Unit / Division / Department / Team
│           ├── Regions
│           └── Operating Sites
│               ├── Branch
│               ├── Shop
│               ├── Factory
│               ├── Office
│               ├── Hospital Facility
│               ├── School Campus
│               ├── Restaurant Outlet
│               ├── Hotel Property
│               └── Construction Site
├── Financial Dimensions
│   ├── Cost Center
│   ├── Profit Center
│   ├── Project
│   └── Channel / Responsibility Center
└── Logistics
    ├── Warehouse
    ├── Warehouse Location
    ├── Logistics Node
    └── Transit Route
```

Do not collapse Legal Entity and Company.

## 10. Generic Shared Foundations for Verticals

### Party

Base person/organization master used by customer, supplier, employee, patient, student, guest, passenger and other profiles.

### Resource

Represents human, physical and capacity resources such as doctor, teacher, stylist, room, bed, table, machine or vehicle.

### Scheduling

Handles calendars, availability, reservations, recurrence, capacity and blackout periods for all industries.

### Operating Site

Generic site model extended through industry profiles.

## 11. Financial Architecture

Accounting must support:

- chart of accounts
- fiscal years/periods
- journals
- double-entry posting
- AR/AP
- reconciliation
- multi-currency
- exchange gain/loss
- cost/profit dimensions
- intercompany
- consolidation capability
- immutable posted entries
- reversal/adjustment corrections

Do not put financial posting logic in protected kernel.

## 12. Inventory/Warehouse Architecture

Support:

- stock movement ledger
- reservations
- lots/batches
- serials
- expiry
- warehouse locations
- transfer/transit
- picking/packing
- putaway
- replenishment
- valuation integration
- manufacturing consumption/output

Authoritative inventory history is movement-ledger based.

## 13. Payments Architecture

Support:

- multiple gateways/providers
- multiple merchant accounts
- tenant/company/site/channel routing
- payment intents
- attempts
- transactions
- split tender
- partial/full refunds
- void/reversal
- disputes
- settlement
- reconciliation
- multi-currency
- offline payment methods

New gateways must be adapter/provider modules without Sales/POS/E-commerce core changes.

## 14. Security Architecture

Support:

- OIDC/OAuth2
- SAML where required
- MFA
- service accounts/devices
- RBAC
- ABAC
- record scopes
- field permissions
- approval authority
- segregation of duties
- secret-provider integration
- signed artifacts
- SBOM/provenance
- least-privileged third-party modules

Backend authorization is authoritative.

## 15. Internationalization

Support:

- translation keys/resources
- runtime language switching
- RTL
- locale-aware dates/numbers/names/addresses
- multiple transaction/base/reporting currencies
- historical exchange rates
- timezone-aware display/scheduling
- country localization packs

Country-specific rules belong in localization modules, not kernel branches.

## 16. Event / Jobs / Workflow

Use transactional outbox for durable domain events.

NATS JetStream is the event/job backbone.

Consumers are idempotent.

Long-running technical/business processes use the BusinessOS workflow abstraction.

Modules do not independently introduce queue/workflow frameworks without ADR approval.

## 17. Upgrade Model

Every release must support:

- signed immutable artifacts
- checksums
- SBOM/provenance
- installed-module inventory
- compatibility preflight
- migration preflight
- backup/restore checkpoint
- expand migrations
- resumable backfills
- health/smoke/conformance checks
- delayed destructive cleanup

No incompatible module is silently enabled.

## 18. Deployment Targets

Support:

- local developer environment
- single-server enterprise installation
- enterprise HA Kubernetes
- air-gapped deployment
- BusinessOS Cloud database-per-tenant cells

Business operations must continue if vendor control plane is temporarily unavailable.

## 19. Observability

Every request/command/event/job/workflow/integration must support correlated:

- trace ID
- correlation ID
- tenant ID
- module/service identity
- structured logs
- metrics

OpenTelemetry is the instrumentation standard.

## 20. Testing and Release Gates

Required test families as applicable:

- unit tests
- integration tests
- migration tests
- tenant isolation tests
- authorization tests
- contract compatibility tests
- event idempotency tests
- performance/load tests
- recovery/backup tests
- frontend accessibility/type tests
- security scans
- module conformance tests

A cross-tenant leak is release-blocking.

## 21. Coding Strategy for Codex

Codex must never implement the full system in one uncontrolled task.

For each bounded task:

1. read AGENTS + relevant architecture + ADR
2. inspect repository
3. identify owner/layer
4. identify dependency/contracts
5. identify tenancy/security/migration impact
6. present short plan for substantial tasks
7. implement smallest coherent unit
8. run applicable validation
9. report files, commands, contracts, migrations and risks

## 22. Architecture Escalation

If a feature cannot be implemented without violating protected-core, ownership, tenancy or compatibility rules, Codex must stop and propose an ADR/design change rather than silently bypassing the architecture.

## 23. Product Completion Definition

BusinessOS is considered a mature platform only when all of the following are proven:

- external/customer module can install/upgrade without core edits
- multinational hierarchy works
- tenant isolation is certified
- multi-language/currency/timezone/localization works
- reference Sales-to-Cash flow is complete
- Purchase-to-Pay is complete
- Inventory/Warehouse is complete
- Accounting integration is complete
- HR/Payroll base is complete
- Manufacturing base is complete
- POS/E-commerce works
- at least one scheduling-heavy vertical works
- at least one healthcare/regulated vertical works
- at least one ERP/manufacturing vertical works
- update/backup/restore/air-gap works
- marketplace/private module lifecycle works
- LTS compatibility process works

This master document defines the destination. Detailed implementation order is defined in `docs/roadmap/FULL-SYSTEM.md`.