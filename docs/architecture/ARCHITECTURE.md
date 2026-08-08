# BusinessOS Architecture Baseline

Status: Approved implementation baseline  
Architecture ID: BOS-ARCH-002  
Version: 2.0

## 1. Architecture Promise

BusinessOS is a business application platform, not a single hard-coded ERP application.

A new business or industry domain must be implementable through published platform contracts, foundation modules, business modules, declarative metadata or isolated services without modifying protected BusinessOS kernel source.

## 2. Technology Baseline

- Backend and workers: Go
- HTTP adapter: Gin
- Internal RPC when justified: gRPC + Protocol Buffers
- Transactional database: PostgreSQL
- Database access: pgx + explicit/generated SQL
- Cache/transient state: Redis
- Durable messaging/jobs: NATS JetStream
- Object storage: S3-compatible
- Enterprise backoffice: React + TypeScript + React Router + Vite
- Public/SEO applications: optional Next.js
- Observability: OpenTelemetry
- Development/small deployment: Docker Compose
- Enterprise HA: Kubernetes + Helm

## 3. Layer Model

### Layer 1 - Protected Kernel

Generic runtime only:

- bootstrap
- TenantContext/RequestContext
- module registry
- contract registry
- Unit of Work
- authorization enforcement
- event/outbox runtime
- provider registry
- configuration
- migration/compatibility runtime
- diagnostics

### Layer 2 - Platform Foundations

- Tenant
- Identity
- Organization
- Party
- Geography
- Policy
- Reference Data
- Metadata/Studio
- Workflow/Rules/Case
- UoM/Precision
- Resource
- Scheduling/Reservation
- Collaboration
- Documents
- Notifications
- Reporting
- Import/Export
- Search
- Internationalization
- Data Governance
- Integrations
- Background Jobs

### Layer 3 - Shared Business Modules

CRM, Catalog, Pricing, Tax, Sales, Procurement, Inventory, Warehouse, Logistics, Billing, Payments, Accounting, Assets, HR, Payroll, Projects, Manufacturing, POS and E-commerce.

### Layer 4 - Industry Solutions

Healthcare, Education, Salon/Spa, Gym, Restaurant, Hotel/Hospitality, Garments, Microfinance, Fleet, Legal, Real Estate, Construction, Travel/Air Ticketing and future verticals.

### Layer 5 - Localization and Connectors

Country packs, payment gateways, banks, government services, GDS/NDC, shipping, healthcare exchanges and customer-specific integrations.

## 4. Modular Monolith First

BusinessOS starts as a domain-structured modular monolith.

Module boundaries must be strong enough that a module can later be extracted into a service without changing its domain contract.

Service extraction requires measured justification. Microservices are not the default mechanism for code organization.

## 5. Domain Ownership

Every table, command, event and invariant has one owner.

A bounded context may read another context only through published contracts, approved projections or APIs. It must not directly mutate another context's private tables.

## 6. Extension Architecture

Customer and marketplace extensibility is contract-first.

Preferred order:

1. configuration
2. metadata
3. workflow/rules
4. extension hooks
5. declarative module
6. isolated executable service

Go native plugins are not the marketplace architecture.

## 7. Upgrade Principle

Public contracts are explicitly versioned and governed. Database changes use explicit migrations and expand-contract evolution where compatibility matters.

An upgrade is preflighted against installed modules, contracts, migrations and infrastructure prerequisites before activation.

## 8. Runtime Autonomy

A customer installation must continue core business operations if the BusinessOS vendor control plane is unavailable.

Air-gapped enterprise deployment is a supported architecture goal through signed offline artifacts and local runtime dependencies.

## 9. Architecture Governance

Accepted ADRs and this architecture baseline govern implementation. Contradictory implementation changes require a superseding ADR and review.