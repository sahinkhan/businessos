# BusinessOS Complete System Implementation Roadmap

Status: Master roadmap

This roadmap describes the full product sequence. Phases are dependency gates, not isolated product editions. Parallel work is allowed only when prerequisites and contracts are stable.

## Phase 0 - Architecture and Engineering Governance

Deliver:

- Python 3.13+/ASGI architecture baseline and superseding ADR
- custom BusinessOS framework responsibility map
- root/scoped AGENTS instructions
- ADR process
- repository boundaries
- coding/testing standards
- security baseline
- compatibility policy
- release/version policy
- contribution/ownership model

Gate: coding may start only after the Python architecture source of truth is internally consistent and the complete repository scan contains no unclassified legacy-technology assumptions.

## Phase 1 - Protected Kernel and Runtime

Deliver:

- Python 3.13+ project/runtime bootstrap
- custom BusinessOS ASGI framework bootstrap
- Uvicorn server integration
- configuration
- RequestContext/TenantContext
- routing and middleware
- dependency injection
- error model
- logging/telemetry
- PostgreSQL runtime through SQLAlchemy 2.x and psycopg 3
- framework-owned Unit of Work and transaction boundaries
- Alembic migration runtime
- module discovery, registry and lifecycle
- contract registry
- command/query dispatch
- event, metadata and permission registries
- provider registry
- feature flags
- compatibility runtime
- transactional outbox
- NATS runtime
- job abstraction
- authorization enforcement boundary
- identity facade
- secret-provider abstraction
- Redis/S3 providers
- health/readiness/version diagnostics
- Docker Compose
- pytest/Ruff/mypy CI baseline with approved Pyright support
- external Python SDK proof module

Gate: external proof module installs, migrates, runs tenant-aware API/event/UI/provider flow, upgrades and retires without protected-core edits.

## Phase 2 - Identity, Tenant and Organization Foundations

Deliver:

- tenant lifecycle
- subscriptions/entitlements abstraction
- users/principals
- memberships
- service accounts/devices
- OIDC
- SAML adapter boundary
- MFA policy
- Enterprise Group
- Legal Entity
- Company
- Business Unit
- Division
- Department
- Team
- Region
- Operating Site
- financial dimensions
- Warehouse/Location base identity
- organization memberships/assignments
- delegated scope

Gate: multinational organizational hierarchy and tenant isolation tests pass.

## Phase 3 - Party, Geography, Reference Data and UoM

Deliver:

- Party person/organization
- contacts
- addresses
- country/region/city/postal structures
- external IDs
- reference data
- identifier/number sequences
- UoM dimensions
- conversions
- precision/rounding
- currency master
- timezone/locale foundations

Gate: verticals can create profiles referencing generic masters without adding columns to them.

## Phase 4 - Authorization, Audit and Data Governance

Deliver:

- roles
- permissions
- ABAC policies
- record scope
- field-level rules
- approval authority
- segregation of duties
- delegated/time-bound authority
- immutable security/business audit
- retention policies
- export/delete hooks
- legal hold abstraction
- data classification
- support-access controls

Gate: policy engine covers tenant/company/site/record/field/action scope and privileged access is auditable.

## Phase 5 - Metadata, Studio and Dynamic UI

Deliver:

- custom fields
- custom entities within governed limits
- metadata registry
- list/form/detail/kanban/calendar/dashboard definitions
- menus/actions
- validation rules
- UI extension slots
- theme/design tokens
- metadata versioning
- safe customization upgrade model

Gate: a customer can customize ordinary records/forms/workflows without modifying source code.

## Phase 6 - Workflow, Rules, Resource and Scheduling

Deliver:

- workflow definitions/instances/tasks
- approvals
- rule engine
- timers/escalations
- SLA concepts
- durable orchestration abstraction
- Resource master
- calendars
- availability
- recurrence
- reservation
- capacity
- blackout periods
- conflict detection
- waitlist base

Gate: generic scheduling supports doctor, teacher, stylist, room, bed, table, machine and vehicle scenarios without industry-specific kernel code.

## Phase 7 - Documents, Collaboration and Notifications

Deliver:

- attachment/document metadata
- S3 storage integration
- versioning
- access control
- comments
- mentions
- activities/tasks
- followers/subscriptions
- templates
- email
- SMS provider
- push/web notifications
- notification preferences
- inbox/activity center

Gate: all modules can attach documents and create auditable collaborative activities through common contracts.

## Phase 8 - Search, Reporting, Import/Export and Analytics Foundations

Deliver:

- global search abstraction
- module search indexing
- saved filters/views
- report definitions
- operational reports
- dashboards/KPIs
- exports
- CSV/XLSX import/export pipeline
- mapping/validation
- scheduled reports
- analytics projection contracts
- data warehouse/BI connector boundary

Gate: reporting does not require unrestricted cross-module table writes or business logic duplication.

## Phase 9 - Integration Platform

Deliver:

- provider registry maturity
- outbound HTTP clients
- webhooks
- inbound webhook verification
- API keys/service credentials
- OAuth connector credentials
- integration mappings
- retry/dead-letter handling
- idempotency
- rate limits
- connector health
- external-ID mapping
- API gateway policies

Gate: third-party systems integrate without changes to protected core.

## Phase 10 - Product Catalog, Pricing and Tax

Deliver:

- products/services
- variants
- categories
- attributes
- bundles/kits
- units
- price lists
- customer/segment pricing
- promotions/discount rules
- tax engine contract
- tax categories/rates
- inclusive/exclusive taxes
- localization tax providers

Gate: Sales, Procurement, POS, E-commerce and Manufacturing can reuse common catalog/pricing/tax contracts.

## Phase 11 - CRM and Sales

Deliver:

- leads
- opportunities
- pipelines
- activities
- quotations
- sales orders
- contracts/subscriptions base
- fulfillment requests
- returns/cancellations
- sales commissions extension points
- customer credit integration points

Gate: Quote-to-Order is complete and tenant/company/site scoped.

## Phase 12 - Procurement

Deliver:

- supplier relationships
- RFQ
- purchase quotations
- purchase orders
- approvals
- receiving integration
- supplier returns
- landed-cost inputs
- vendor performance
- procurement agreements

Gate: Purchase-to-Receipt contracts are stable.

## Phase 13 - Inventory, Warehouse and Logistics

Deliver:

- inventory item/location balance projections
- immutable stock movement ledger
- reservations
- lots/batches
- serials
- expiry
- warehouse locations
- receiving
- putaway
- picking
- packing
- transfers
- transit
- replenishment
- cycle counts
- adjustments
- valuation integration points
- shipping/carrier providers
- routes

Gate: stock can be reconstructed from authoritative movements and warehouse operations scale to large datasets.

## Phase 14 - Billing and Payments

Deliver:

- billing documents
- invoices/credit notes
- payment intents
- payment attempts
- payment transactions
- multiple gateway providers
- merchant-account routing
- cash/bank/offline methods
- split tender
- partial/full refunds
- void/reversal
- disputes
- settlements
- reconciliation feeds
- multi-currency payment support

Gate: adding a new payment gateway requires an adapter, not changes to Sales/POS/E-commerce business logic.

## Phase 15 - Accounting and Finance

Deliver:

- chart of accounts
- fiscal years/periods
- journals
- posting engine
- double-entry ledger
- AR/AP
- payment allocation
- bank/cash
- reconciliation
- exchange rates
- realized/unrealized FX
- tax posting
- cost/profit dimensions
- budgets
- intercompany
- consolidation foundations
- period close
- financial statements
- audit trail

Gate: posted ledger is immutable and core commercial flows post balanced entries.

## Phase 16 - Assets, Expenses and Treasury Foundations

Deliver:

- fixed assets
- capitalization
- depreciation
- disposal
- employee expenses
- advances
- approvals
- bank account management
- cash management
- treasury provider boundary

## Phase 17 - HR and Payroll

Deliver:

- employee profile
- employment
- organization assignment
- attendance/time
- shifts
- leave
- recruitment base
- onboarding/offboarding
- performance base
- benefits base
- payroll engine
- earning/deduction rules
- payroll localization extension points
- payslips
- accounting posting

Gate: country payroll rules remain localization modules.

## Phase 18 - Project, Service, Helpdesk and Field Service

Deliver:

- projects
- tasks
- milestones
- timesheets
- budgets/costs
- helpdesk tickets
- SLAs
- service contracts
- field-service work orders
- technician scheduling
- parts consumption
- service billing integration

## Phase 19 - Manufacturing, Maintenance and Quality

Deliver:

- BOM
- routings
- work centers
- work orders
- material requirements
- production planning
- consumption/output
- scrap/by-products
- subcontracting
- costing
- maintenance assets
- preventive maintenance
- quality plans/checks
- nonconformance
- traceability

Gate: manufacturing uses Inventory/UoM/Accounting contracts rather than private cross-module writes.

## Phase 20 - POS

Deliver:

- terminal/device registration
- cashier sessions
- offline-tolerant transaction model
- barcode/search
- pricing/promotions/tax
- split payments
- returns/exchanges
- cash drawer
- receipt printing abstraction
- shift close
- stock/accounting synchronization
- multi-shop/site operation

Gate: POS can continue bounded operations through temporary network interruption and reconcile safely.

## Phase 21 - E-commerce

Deliver:

- storefront APIs
- optional Next.js reference storefront
- catalog/search
- cart
- checkout
- customer account
- pricing/promotion/tax
- payment
- shipping
- orders
- returns/exchanges
- marketplace extension points where approved
- SEO/content integration

## Phase 22 - Industry Solution SDK

Before broad verticals, formalize reusable vertical patterns:

- Party profile pattern
- Operating Site profile pattern
- Resource specialization pattern
- Scheduling specialization
- industry permissions
- industry reference data
- industry documents
- industry workflow templates
- industry reports
- localization hooks

Gate: a new vertical does not require protected-kernel modifications.

## Phase 23 - Healthcare / Hospital / Clinic / Pharmacy

Deliver through vertical-owned schemas:

- patient profile
- providers/practitioners
- facilities
- appointments
- encounters
- clinical records architecture
- orders/results integration boundary
- bed/room resources
- admissions/discharges/transfers
- billing/insurance integration points
- pharmacy dispensing/inventory integration
- consent/privacy controls
- healthcare interoperability adapters as separate connectors

Do not place healthcare-specific fields in Party/Resource/Operating Site core tables.

## Phase 24 - Education / School

Deliver:

- student/guardian profiles
- campus
- academic year/term
- programs/classes/sections
- enrollment
- subjects
- timetable
- attendance
- examinations/assessment
- grading
- fees/billing
- teacher/resource scheduling
- library/transport extension points

## Phase 25 - Salon, Spa, Gym and Membership Businesses

Deliver:

- member/client profiles
- service catalog
- staff/resources
- appointment booking
- rooms/chairs/equipment
- packages
- memberships
- recurring billing integration
- commissions
- check-in
- waitlist

## Phase 26 - Restaurant and Food Service

Deliver:

- outlet profile
- menu/recipe integration
- tables/resources
- reservations/waitlist
- kitchen order workflow
- dine-in/takeaway/delivery
- POS specialization
- ingredient inventory
- recipe/BOM consumption
- modifiers
- kitchen display integration

## Phase 27 - Hotel and Hospitality

Deliver:

- property profile
- room/resource inventory
- rate plans
- availability
- reservation
- guest profile
- check-in/check-out
- folio
- housekeeping
- maintenance
- deposits/payments
- channel-manager integration boundary

## Phase 28 - Garments and Apparel

Deliver:

- style/color/size matrix
- tech packs/PLM integration boundary
- seasonal collections
- sample development
- order planning
- fabric/trims
- marker/cutting/sewing/finishing workflows
- subcontracting
- quality
- production costing
- compliance documents

## Phase 29 - Construction and Real Estate

Deliver:

- project/site profiles
- BOQ
- estimates
- contracts
- subcontractors
- progress billing
- material planning
- equipment/resource scheduling
- project costing
- property/unit management
- lease/rent extension

## Phase 30 - Fleet and Logistics Vertical

Deliver:

- vehicle profile
- driver profile
- trip
- route
- dispatch
- fuel
- maintenance
- telematics connector boundary
- shipment/consignment
- proof of delivery
- fleet costing

## Phase 31 - Microfinance / Financial Services

Deliver as a high-control vertical:

- customer/KYC profile extensions
- product definitions
- loan lifecycle
- schedules
- disbursement
- collection
- delinquency
- fees/penalties
- savings/account concepts where legally/product appropriate
- teller/cash integration
- accounting integration
- risk/approval workflows
- regulatory/localization connectors

Core banking expansion requires separate architecture/security/regulatory ADRs rather than treating generic ERP accounting as a bank ledger.

## Phase 32 - Legal Practice

Deliver:

- client/matter
- case
- court/calendar
- documents
- time/expense
- billing
- trust-account integration boundary
- conflict checking
- legal workflow/templates

## Phase 33 - Travel / Air Ticketing

Deliver:

- traveler/passenger profiles
- itinerary
- booking/order
- fare/ancillary representation
- ticket/document records
- refunds/exchanges
- agency/customer billing
- GDS/NDC connectors
- supplier settlement
- commissions

Do not hardcode airline/GDS protocols into kernel.

## Phase 34 - Localization Framework and Initial Country Packs

Deliver framework plus prioritized countries:

- tax/local statutory configuration
- fiscal document numbering
- e-invoicing connector model
- withholding
- payroll localization
- bank/payment localization
- address/name formats
- statutory reports

Country packs are independently versioned modules.

## Phase 35 - Marketplace and Developer Platform

Deliver:

- Python module SDK and generated client SDKs
- module CLI
- scaffolding/templates
- local dev sandbox
- manifest validator
- contract generator
- test harness
- conformance suite
- module signing
- SBOM/provenance
- marketplace package format
- install/upgrade/disable/remove lifecycle
- permissions/capabilities review
- private enterprise module registry
- public marketplace foundations

Gate: external developer can build a module from docs/SDK without access to protected core internals.

## Phase 36 - Self-Hosted Enterprise Operations

Deliver:

- installer
- configuration wizard
- TLS/reverse proxy guidance/automation
- backup/restore
- disaster recovery
- upgrade preflight
- signed release bundles
- air-gap bundles
- diagnostics/support bundles
- HA deployment
- scaling guidance
- observability stack integration
- license/entitlement offline capability where commercial model requires it

## Phase 37 - BusinessOS Cloud Control Plane

Deliver separately from customer data-plane runtime:

- tenant provisioning
- cell/region placement
- database-per-tenant routing
- entitlements
- release orchestration
- fleet health
- backup policy
- region/residency controls
- metering/billing
- support workflow

Data-plane business operations must tolerate control-plane outage.

## Phase 38 - Performance and Scale Certification

Establish workload profiles and certify:

- interactive API latency
- concurrent users
- large tenant datasets
- POS concurrency
- warehouse throughput
- posting throughput
- report workloads
- event backlog recovery
- job throughput
- failover/recovery

Optimize only with measured evidence. Extract services when justified by architecture criteria.

Go may be evaluated here only for an isolated, performance-sensitive microservice whose measured workload justifies extraction. It does not replace the Python backend or BusinessOS in-process module runtime.

## Phase 39 - Security and Compliance Maturity

Deliver:

- threat models
- secure SDLC
- dependency scanning
- secret scanning
- SAST/DAST where applicable
- penetration testing
- audit evidence
- encryption/key management maturity
- privacy/data governance maturity
- tenant support-access controls
- compliance mappings appropriate to target markets

Industry compliance claims require formal legal/compliance validation and are not implied merely by architecture.

## Phase 40 - LTS, Compatibility and Enterprise Ecosystem

Deliver:

- stable/LTS release trains
- documented support windows
- deprecation lifecycle
- compatibility matrices
- upgrade rehearsals
- migration tooling
- ecosystem certification
- partner program
- implementation tooling
- enterprise support lifecycle

## Final Platform Acceptance

The platform is mature when multiple unrelated verticals can be developed, installed, upgraded and operated through published BusinessOS contracts without protected-core forks, while maintaining certified tenant isolation, transactional integrity, international operation, enterprise deployment and backward-compatible upgrade paths.
