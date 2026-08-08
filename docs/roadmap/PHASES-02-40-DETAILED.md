# BusinessOS Detailed Implementation Specifications — Phases 2 through 40

Status: Authoritative detailed roadmap supplement

This document gives the same implementation depth to the later BusinessOS phases that `PHASE-1.md` gives to the protected-kernel phase.

Every phase below defines:

- objective
- owned modules/subsystems
- required domain/data model
- contracts/APIs/events
- tenancy/security requirements
- testing requirements
- exit criteria

The full ordering remains defined by `FULL-SYSTEM.md`. This file adds engineering detail.

---

# Phase 2 — Identity, Tenant and Organization Foundations

## Objective

Create the authoritative tenant, identity and organization model used by every later module.

## Owned Modules

- `foundations/tenant`
- `foundations/identity`
- `foundations/organization`

## Required Capabilities

### Tenant Management

- tenant lifecycle: requested, provisioning, active, suspended, retention-hold, terminating, deleted
- deployment mode metadata
- data residency/region metadata
- entitlements/capability references
- quotas
- tenant configuration defaults
- export/delete/restore lifecycle hooks

### Identity

- user/principal
- external identity mapping
- tenant membership
- service accounts
- device identity
- session/authentication context
- MFA/authentication-strength representation
- local break-glass administrative identity for self-hosted installations

### Organization

- Enterprise Group
- Legal Entity
- Company
- Business Unit
- Division
- Department
- Team
- Region
- Operating Site
- site type registry
- organization relationships
- effective-dated assignments
- financial-dimension references

## Data Model

Minimum owned tables should include concepts equivalent to:

- `tenant.tenants`
- `tenant.tenant_status_history`
- `tenant.tenant_entitlements`
- `identity.users`
- `identity.external_identities`
- `identity.memberships`
- `identity.service_accounts`
- `identity.devices`
- `organization.enterprise_groups`
- `organization.legal_entities`
- `organization.companies`
- `organization.org_units`
- `organization.regions`
- `organization.site_types`
- `organization.operating_sites`
- `organization.relationships`

All tenant-owned tables preserve `tenant_id`.

## Public Contracts

- tenant provisioning contract
- tenant status/lifecycle contract
- principal identity contract
- membership query contract
- active scope selection contract
- organization read contract
- organization lifecycle events

## Events

Examples:

- `tenant.created.v1`
- `tenant.activated.v1`
- `tenant.suspended.v1`
- `organization.legal_entity.created.v1`
- `organization.company.created.v1`
- `organization.site.created.v1`
- `identity.membership.granted.v1`
- `identity.membership.revoked.v1`

## Security / Tenancy

- tenant identity may never be inferred only from company/site IDs
- principal must be validated against tenant membership
- scope-switch operations must be authorized and auditable
- organization references must be tenant-consistent
- support/admin overrides must be explicit and audited

## Tests

- tenant lifecycle tests
- cross-tenant organization negative tests
- membership scope tests
- effective-date tests
- duplicate code/uniqueness tests
- organization hierarchy consistency tests

## Exit Criteria

A multinational tenant can represent multiple legal entities, companies, regions and operating sites while preserving isolation and explicit user scope.

---

# Phase 3 — Party, Geography, Reference Data and UoM

## Objective

Create reusable master-data foundations so vertical modules never duplicate person, organization, address, identifier, unit or reference structures.

## Owned Modules

- `foundations/party`
- `foundations/geography`
- `foundations/reference-data`
- `foundations/uom`

## Required Domain Model

### Party

- Party
- Person profile
- Organization profile
- Party relationship
- Contact point
- Address assignment
- External identifier
- preferred locale/timezone/currency references where appropriate

Profiles such as Customer, Employee, Patient, Student, Guest and Passenger are not stored here; they belong to their owning business/vertical modules.

### Geography

- country
- subdivision/state/province
- city/locality
- postal code support
- address format metadata
- country-specific address extensions through localization

### Reference Data

- reference set
- reference value
- module ownership
- stable external ID
- seed version
- active/effective date
- localized label key

### UoM

- measurement category/dimension
- unit
- base unit
- conversion ratio/rule
- precision
- rounding mode
- effective date where needed

## Contracts

- Party read/write application contracts
- Party search contract
- stable external-ID resolution
- reference-data registration
- UoM conversion service
- address-format/validation provider contract

## Events

- `party.created.v1`
- `party.updated.v1`
- `party.relationship.created.v1`
- `reference_data.value.changed.v1`
- `uom.unit.changed.v1`

## Security / Tenancy

- Party is tenant-owned unless a future explicit shared-master ADR exists
- sensitive identifiers are field-classified and policy-controlled
- external IDs must be tenant/provider scoped

## Tests

- duplicate party matching rules
- relationship tenant safety
- UoM round-trip conversion tests
- precision/rounding tests
- reference-data upgrade tests
- localization/address format tests

## Exit Criteria

A vertical can create `PatientProfile`, `StudentProfile`, `GuestProfile`, etc. by referencing Party without adding columns to Party tables.

---

# Phase 4 — Authorization, Audit and Data Governance

## Objective

Create the enterprise authorization and governance layer used by every later business module.

## Owned Modules

- `foundations/policy`
- `foundations/audit`
- `foundations/data-governance`

## Required Capabilities

### Authorization

- roles
- permission registry
- role permissions
- user/subject assignments
- tenant/company/site/business-scope constraints
- ABAC condition model
- record ownership/scope policies
- field-level read/write policies
- approval limits
- segregation-of-duties policies
- delegated/time-limited authority

### Audit

- append-only audit events
- actor/principal
- tenant/scope
- action/resource
- before/after summary where appropriate
- correlation/trace
- decision and policy result metadata

### Data Governance

- data classification
- retention policy
- legal hold
- consent/purpose references
- anonymization/delete workflow hooks
- tenant export hooks
- sensitive field tagging

## Contracts

- `Authorize(action, resource, context)`
- field-policy evaluation
- approval authority evaluation
- audit write facade
- retention policy query
- export/delete extension hooks

## Events

- permission assignment changed
- role changed
- delegation granted/revoked
- legal hold placed/released
- retention policy changed

## Security

- deny by default where policy requires explicit grant
- support/admin access uses separate privileged flow
- policy engine must be deterministic/testable
- UI is not authoritative

## Tests

- positive/negative permission matrices
- cross-company/site scope tests
- field-level policy tests
- SoD conflict tests
- delegation expiry tests
- audit immutability tests

## Exit Criteria

Every later module can enforce action, record, field and organizational scope through the shared policy service without custom authorization frameworks.

---

# Phase 5 — Metadata, Studio and Dynamic UI

## Objective

Enable customer customization without source-code forks.

## Owned Modules

- `foundations/metadata`
- `platform/frontend` metadata runtime

## Required Capabilities

- entity metadata registry
- custom field definitions
- safe custom entity definitions
- validation metadata
- list view definitions
- form/detail definitions
- kanban
- calendar
- dashboard
- menu/action registry
- wizard definitions
- extension slots
- metadata versioning
- tenant/company/site scoped configuration where allowed
- safe migration of custom definitions across platform upgrades

## Data Model

- entity definitions
- field definitions
- view definitions
- menu definitions
- action definitions
- dashboard definitions
- customization packages
- customization versions

## Contracts

- metadata registration API
- metadata resolver
- UI schema API
- custom-field persistence contract
- index-request contract for searchable custom fields

## Security

- custom metadata cannot create arbitrary SQL/code execution
- custom fields inherit entity authorization
- unsafe field types/providers require capability approval

## Tests

- metadata schema validation
- custom field add/remove lifecycle
- tenant isolation
- upgrade compatibility
- UI rendering contract tests
- index migration tests

## Exit Criteria

A tenant can add fields/forms/views/workflows/reports using supported mechanisms without patching vendor code.

---

# Phase 6 — Workflow, Rules, Resource and Scheduling

## Objective

Create common orchestration, approval, resource and booking primitives reused by healthcare, salon, education, hotel, restaurant, manufacturing and field-service domains.

## Owned Modules

- `foundations/workflow`
- `foundations/rules`
- `foundations/resource`
- `foundations/scheduling`

## Workflow Capabilities

- workflow definitions/versioning
- state machine
- human tasks
- approval steps
- timers
- escalation
- retry/failure
- compensation hooks
- workflow history
- subject/resource reference

## Rules

- rule definitions
- condition expression model
- deterministic evaluation
- effective dating
- priority
- explanation/audit result

## Resource

- resource type registry
- human/physical/capacity resources
- capabilities/skills
- company/site assignment
- capacity
- lifecycle/status

## Scheduling

- calendar
- working hours
- availability
- recurring availability
- blackout period
- reservation
- reservation participants/resources
- capacity
- conflict detection
- recurrence
- waitlist base

## Contracts

- start/advance/cancel workflow
- create/evaluate rule
- find resource availability
- create/change/cancel reservation
- conflict check

## Events

- workflow started/completed/failed
- task assigned/completed
- reservation created/changed/cancelled
- resource availability changed

## Tests

- durable workflow restart tests
- rule determinism
- timezone/DST scheduling tests
- recurrence tests
- capacity/conflict tests
- multi-tenant isolation

## Exit Criteria

The same Resource/Scheduling contracts can schedule a doctor, teacher, stylist, room, hospital bed, restaurant table, vehicle and machine.

---

# Phase 7 — Documents, Collaboration and Notifications

## Objective

Provide shared enterprise document and collaboration capabilities.

## Owned Modules

- `foundations/documents`
- `foundations/collaboration`
- `foundations/notifications`

## Documents

- object-storage metadata
- document version
- checksum
- classification
- retention
- subject/resource linkage
- template registry
- generated document tracking

## Collaboration

- thread
- note/comment
- mention
- follower/subscription
- activity/reminder
- attachment linkage

## Notifications

- in-app
- email
- SMS
- push provider interfaces
- notification preferences
- templates
- retries/status

## Security

- signed/temporary object URLs
- document access follows subject/resource policy
- notifications must not leak cross-tenant data
- provider credentials use secret references

## Tests

- access-control tests
- versioning tests
- notification retry/idempotency
- object-key tenant namespace tests
- template localization tests

## Exit Criteria

Any business entity can attach documents, produce activities/comments and emit user notifications through common contracts.

---

# Phase 8 — Search, Reporting, Import/Export and Analytics Foundations

## Objective

Provide enterprise data discovery, reporting and onboarding tools without making search/BI stores authoritative.

## Owned Modules

- `foundations/search`
- `foundations/reporting`
- `foundations/import-export`
- analytics provider contracts

## Search

- searchable entity registration
- indexing events
- tenant/company/site filtering
- permissions-aware search
- result projection

## Reporting

- dataset registry
- report definition
- parameters
- grouping/aggregation
- export formats
- scheduled reports
- report distribution
- permission context
- multi-currency/reporting-currency context

## Import/Export

- upload/staging
- column mapping
- transformation
- validation
- duplicate detection
- dry run
- approval option
- resumable commit
- error export
- external-ID matching

## Tests

- permission-aware search
- stale-index recovery
- large import resume
- invalid row isolation
- report scope/currency/timezone correctness
- tenant export boundary tests

## Exit Criteria

A tenant can onboard and report on large datasets without direct ad hoc production SQL as the standard product mechanism.

---

# Phase 9 — Integration Platform

## Objective

Create consistent external integration patterns.

## Owned Modules

- `foundations/integration`

## Capabilities

- connector instance
- provider registry binding
- API client credentials
- webhook endpoint
- signature verifier contract
- external mapping
- retries/backoff
- circuit breaker policy
- dead letter
- rate limiting
- idempotency
- connector health
- outbound request telemetry

## Contracts

- HTTP provider
- webhook registration/verification
- credential/secret reference
- external-ID mapping
- connector configuration schema

## Security

- per-tenant credentials
- SSRF/network restrictions
- webhook signature verification
- redacted payload logging

## Tests

- retry/idempotency
- webhook replay protection
- credential isolation
- timeout/circuit behavior

## Exit Criteria

New couriers, payment providers, banks, government APIs and other connectors can be installed without protected-core edits.

---

# Phase 10 — Catalog, Pricing and Tax

## Objective

Provide shared commercial item and pricing concepts for Sales, Procurement, POS, E-commerce, Manufacturing and service industries.

## Owned Modules

- `modules/catalog`
- `modules/pricing`
- `modules/tax`

## Catalog Domain

- product/service
- variant
- category
- attribute/attribute value
- bundle/kit
- barcode/SKU references
- UoM
- lifecycle/status

## Pricing

- price list
- price rule
- customer/segment price
- quantity breaks
- date ranges
- channel/site scope
- promotion/discount rule
- tax-inclusive/exclusive context

## Tax

- tax category
- rate/rule abstraction
- jurisdiction/provider interface
- localization extension points

## Contracts

- resolve sell price
- resolve purchase price where appropriate
- calculate discount
- calculate tax through localized provider

## Tests

- rounding
- overlapping price rules
- multi-currency
- effective date
- tenant/site/channel scope
- tax localization adapter tests

## Exit Criteria

Commercial modules use the same catalog/pricing/tax services rather than duplicating product/price logic.

---

# Phase 11 — CRM and Sales

## Objective

Implement lead-to-order commercial workflow.

## Owned Modules

- `modules/crm`
- `modules/sales`

## CRM

- lead
- opportunity
- pipeline/stage
- activity
- source/campaign references
- customer Party references

## Sales

- quotation
- quotation line
- sales order
- sales order line
- terms
- approval
- discount authorization
- fulfillment request
- cancellation
- return authorization references
- commission extension points

## Contracts

- create/approve quotation
- confirm sales order
- cancel order
- request fulfillment
- pricing/tax integration
- credit policy integration point

## Events

- opportunity won/lost
- quotation accepted
- sales order confirmed/cancelled
- fulfillment requested

## Tests

- pricing snapshot correctness
- authorization/approval limits
- idempotent confirmation
- concurrency/version tests
- multi-company/site/currency

## Exit Criteria

Quote-to-Order is production-ready and does not directly write Inventory, Billing or Accounting tables.

---

# Phase 12 — Procurement

## Objective

Implement purchase-to-receipt procurement workflows.

## Owned Module

- `modules/procurement`

## Domain

- requisition
- RFQ
- supplier quotation
- purchase order
- purchase agreement
- approval
- receiving request
- supplier return request
- vendor performance projection

## Contracts

- create/approve PO
- request receiving
- cancel PO
- supplier Party profile integration
- pricing/tax/currency integration

## Events

- PO approved
- receiving requested
- supplier return requested

## Tests

- approval limits
- partial receiving state
- cancellation after partial receipt
- multi-currency
- tenant/company scope

## Exit Criteria

Procurement can coordinate with Inventory through published contracts/events only.

---

# Phase 13 — Inventory, Warehouse and Logistics

## Objective

Implement enterprise stock, warehouse execution and logistics foundations.

## Owned Modules

- `modules/inventory`
- `modules/warehouse`
- `modules/logistics`

## Inventory Domain

- item inventory profile
- stock movement ledger
- reservation
- balance projection
- lot/batch
- serial
- expiry
- adjustment
- valuation references

## Warehouse Domain

- warehouse
- location tree
- receiving
- putaway
- picking
- packing
- staging
- dispatch
- cycle count
- replenishment

## Logistics

- logistics node
- shipment
- package
- carrier/service
- transit route
- route leg
- tracking

## Contracts

- reserve/release stock
- post movement
- receive
- transfer
- ship
- query availability

## Events

- stock reserved/released
- movement posted
- goods received
- shipment dispatched/delivered

## Security / Integrity

- movement ledger immutable
- negative-stock policy explicit
- lot/serial uniqueness scoped appropriately
- expiry policies configurable

## Tests

- concurrent reservation
- stock reconstruction
- lot/serial/expiry
- partial receiving/shipping
- warehouse location permissions
- high-volume movement performance

## Exit Criteria

Inventory can reconstruct authoritative stock from movement history, and warehouse operations scale without using `product.stock` as the source of truth.

---

# Phase 14 — Billing and Payments

## Objective

Implement invoice-facing billing and provider-neutral payment orchestration.

## Owned Modules

- `modules/billing`
- `modules/payments`

## Billing

- invoice
- invoice line
- credit note
- billing schedule/reference
- receivable amount/status

## Payments

- provider registry integration
- merchant account
- scope/routing rule
- payment method
- payment intent
- attempt
- transaction
- allocation
- refund
- dispute
- settlement
- settlement line
- reconciliation run
- webhook event

## Contracts

- create payment intent
- authorize/capture/sale
- refund
- void
- query status
- verify webhook
- allocate payment

## Security

- secrets are external references
- no CVV/raw sensitive card data in normal DB/logs
- webhook tenant resolution is trusted-server-side
- idempotency mandatory

## Tests

- duplicate-submit protection
- gateway retry
- partial refund
- split tender
- multi-currency
- settlement reconciliation
- webhook replay

## Exit Criteria

A new payment gateway can be added as an adapter without changes to Sales, POS, E-commerce, Hotel or Healthcare core logic.

---

# Phase 15 — Accounting and Finance

## Objective

Implement enterprise financial accounting with immutable double-entry posting.

## Owned Modules

- `modules/accounting`
- finance shared contracts

## Domain

- chart of accounts
- account
- fiscal year
- fiscal period
- journal
- journal entry
- journal line
- AR/AP subledger references
- payment allocation
- bank/cash account
- reconciliation
- exchange rate
- realized/unrealized FX
- tax posting
- financial dimension
- budget
- intercompany entry
- consolidation/elimination foundation
- period close

## Invariants

- posted debit = posted credit
- posted entry immutable
- fiscal period status enforced
- currency/base amounts consistent
- corrections use reversal/adjustment

## Contracts

- post journal
- reverse journal
- open/close period
- reconcile
- query balances
- posting interfaces for Sales/Purchases/Payroll/Inventory/Assets

## Events

- journal posted/reversed
- period closed/reopened
- reconciliation completed

## Tests

- balancing/property tests
- FX calculations
- close controls
- concurrent posting
- dimension requirements
- intercompany
- financial statement reconstruction

## Exit Criteria

Reference business flows post balanced, traceable accounting entries without other modules writing journal tables directly.

---

# Phase 16 — Assets, Expenses and Treasury Foundations

## Objective

Extend finance into fixed assets, expenses and basic treasury/cash operations.

## Owned Modules

- `modules/assets`
- `modules/expenses`
- `modules/treasury`

## Domain

- asset category
- asset
- capitalization
- depreciation schedule
- depreciation posting
- transfer/disposal
- expense claim
- expense line
- advance
- approval/reimbursement
- bank account
- cash account
- bank statement import contract
- treasury provider boundary

## Tests

- depreciation methods
- asset disposal
- expense approval limits
- currency handling
- posting integration

## Exit Criteria

Asset and expense accounting posts through Accounting public contracts.

---

# Phase 17 — HR and Payroll

## Objective

Implement workforce management and a localization-friendly payroll engine.

## Owned Modules

- `modules/hr`
- `modules/payroll`

## HR Domain

- employee profile referencing Party
- employment contract
- org/site assignment
- work schedule
- attendance/time
- shifts
- leave
- recruitment/onboarding/offboarding
- performance/benefits extension points

## Payroll Domain

- payroll calendar
- salary structure
- earning/deduction rule
- payroll input
- payroll run
- payslip
- employer contribution
- tax/localization hooks
- accounting posting

## Rules

Country payroll calculations must be localization modules/providers, not protected kernel code.

## Tests

- effective-dated employment
- leave balances
- shift/timezone
- payroll determinism
- retro adjustments
- posting
- country extension conformance

## Exit Criteria

Base payroll can run with multiple country localization packs without changing payroll core.

---

# Phase 18 — Projects, Helpdesk and Field Service

## Objective

Implement reusable project/service operations.

## Owned Modules

- `modules/projects`
- `modules/helpdesk`
- `modules/field-service`

## Domain

- project
- task
- WBS/milestone
- assignment
- timesheet
- project budget/cost refs
- ticket
- queue/category
- SLA
- service contract
- field work order
- technician/resource scheduling
- consumed parts
- service billing references

## Tests

- project permissions
- SLA timers
- scheduling conflicts
- parts consumption integration
- service billing

## Exit Criteria

Service industries can reuse Projects/Helpdesk/Field Service instead of creating new generic task systems.

---

# Phase 19 — Manufacturing, Maintenance and Quality

## Objective

Implement manufacturing planning/execution with maintenance and quality.

## Owned Modules

- `modules/manufacturing`
- `modules/maintenance`
- `modules/quality`

## Domain

- BOM/version
- routing
- operation
- work center/resource
- work order
- production order
- MRP requirement
- capacity plan
- consumption/output
- scrap/by-product
- subcontracting
- production costing references
- maintenance asset
- maintenance plan/order
- quality plan/check
- nonconformance

## Contracts

- reserve materials
- issue/consume material
- receive production output
- post manufacturing costs

## Tests

- BOM versioning
- MRP calculation
- concurrent material reservation
- production traceability
- maintenance scheduling
- quality holds

## Exit Criteria

Manufacturing uses Inventory/UoM/Accounting public contracts and can be specialized later by garments or other verticals.

---

# Phase 20 — POS

## Objective

Create high-performance multi-shop POS with offline-tolerant operation.

## Owned Module

- `modules/pos`

## Domain

- terminal/device
- register
- cashier session
- POS sale
- sale line
- tender/payment
- cash movement
- shift close
- return/exchange
- local sync state

## Requirements

- barcode/search
- local price/tax cache
- split tender
- receipt printing provider
- cash drawer provider
- offline queue
- conflict-safe synchronization
- site/terminal configuration

## Security

- device identity
- terminal entitlement
- cashier authorization
- offline operation bounded by configurable risk limits

## Tests

- offline/reconnect
- duplicate sync
- split payment
- return across branches according to policy
- concurrent stock synchronization
- high-throughput checkout

## Exit Criteria

POS operates safely through short network interruptions and reconciles inventory/payment/accounting effects idempotently.

---

# Phase 21 — E-commerce

## Objective

Provide commerce channel APIs and a reference public storefront.

## Owned Module

- `modules/ecommerce`

## Domain

- storefront/site/channel
- cart
- cart line
- checkout
- customer account/profile refs
- order channel metadata
- promotion/application
- shipping selection
- payment flow
- returns/exchanges

## Frontend

- optional Next.js reference storefront
- SEO/catalog pages
- account/order pages
- checkout

## Contracts

Reuse Catalog, Pricing, Tax, Inventory, Sales, Payments, Logistics and CRM.

## Tests

- price consistency
- stock race
- abandoned/retry checkout
- payment idempotency
- multi-language/currency
- site/channel isolation

## Exit Criteria

E-commerce is a channel composition, not a duplicate sales/inventory/payment implementation.

---

# Phase 22 — Industry Solution SDK

## Objective

Formalize reusable patterns before scaling vertical development.

## Deliverables

- Party profile SDK
- Operating Site profile SDK
- Resource specialization SDK
- Scheduling extension points
- vertical reference-data pattern
- industry permission pattern
- industry workflow templates
- industry report conventions
- industry document conventions
- localization hooks
- vertical module template/scaffolding
- vertical conformance tests

## Exit Criteria

A new vertical team can start from a supported template without asking for protected-kernel changes.

---

# Phase 23 — Healthcare / Hospital / Clinic / Pharmacy

## Objective

Build healthcare operations as vertical-owned domains on top of generic foundations.

## Owned Vertical Modules

- `verticals/healthcare-core`
- `verticals/hospital`
- `verticals/clinic`
- `verticals/pharmacy`

## Domain

- patient profile -> Party
- practitioner profile -> Party/Resource
- healthcare facility profile -> Operating Site
- appointment -> Scheduling
- encounter
- clinical note/record abstraction
- admission/discharge/transfer
- ward/bed -> Resource
- order/result integration boundary
- prescription
- dispensing
- medication inventory integration
- payer/insurance integration points
- consent/privacy metadata

## Security

- stronger sensitive-data classification
- clinical access policy
- break-glass access capability with audit if product requirements justify it
- consent/purpose hooks

## Integration

Healthcare interoperability standards/connectors are separate adapters, not kernel code.

## Tests

- patient isolation
- clinical access policy
- appointment/bed conflicts
- medication lot/expiry
- privacy/audit

## Exit Criteria

Healthcare vertical operates without adding patient/doctor/clinical fields to generic Party/Resource/Site tables.

---

# Phase 24 — Education / School

## Objective

Build SIS/SMS capabilities using Party, Organization, Resources and Scheduling.

## Domain

- student profile
- guardian relationship
- teacher profile/reference
- campus profile
- academic year/term
- program/course
- class/section
- enrollment
- subject
- timetable
- attendance
- exam/assessment
- grade/result
- fee/billing integration
- library/transport extension points

## Tests

- guardian/student relationships
- timetable conflicts
- enrollment effective dates
- grading rules
- fee billing
- campus/tenant scope

## Exit Criteria

Education does not duplicate identity/contact/scheduling/billing foundations.

---

# Phase 25 — Salon, Spa, Gym and Membership Businesses

## Objective

Build scheduling-heavy service businesses.

## Domain

- client/member profile
- service/treatment
- staff profile -> Resource
- chair/room/equipment -> Resource
- booking -> Scheduling
- package
- membership/subscription
- check-in
- commission
- waitlist
- POS/billing/payment integration

## Tests

- double-booking prevention
- recurring membership billing
- package consumption
- staff commission
- multi-site scheduling

## Exit Criteria

The vertical proves generic Resource/Scheduling foundations across service industries.

---

# Phase 26 — Restaurant and Food Service

## Objective

Build restaurant operations by extending POS, Catalog, Resource, Inventory and Manufacturing-style recipe consumption.

## Domain

- outlet profile
- menu
- menu category
- modifier/options
- recipe/ingredient mapping
- table -> Resource
- reservation/waitlist -> Scheduling
- kitchen order/ticket
- kitchen station
- dine-in/takeaway/delivery modes
- course/fire status
- food-service POS extension

## Tests

- table reservation conflicts
- modifier pricing/tax
- recipe consumption
- kitchen workflow
- partial payment/split bill

## Exit Criteria

Restaurant-specific operations remain vertical-owned while reusing generic POS/Inventory/Payments.

---

# Phase 27 — Hotel and Hospitality

## Objective

Build property-management capabilities on Resource/Scheduling/Billing foundations.

## Domain

- property profile -> Operating Site
- room type
- room -> Resource
- rate plan
- availability
- reservation
- guest profile -> Party
- stay
- check-in/check-out
- folio
- deposit
- housekeeping
- room status
- maintenance linkage
- channel manager integration

## Tests

- room inventory overbooking
- rate plan/effective dates
- multi-currency folio
- deposit/refund
- housekeeping state
- channel-sync idempotency

## Exit Criteria

Hotel room availability uses the same resource/scheduling architecture while preserving hospitality-specific semantics.

---

# Phase 28 — Garments and Apparel

## Objective

Extend Manufacturing for apparel-specific planning/PLM/production workflows.

## Domain

- style
- season/collection
- color-size matrix
- tech-pack reference
- sample/development stage
- fabric/trims
- consumption
- marker/cutting batch
- sewing line
- finishing/packing
- subcontract process
- quality checkpoints
- production costing
- compliance documents

## Tests

- matrix variant explosion limits
- fabric UoM conversions
- production traceability
- subcontract inventory
- costing

## Exit Criteria

Garments specializes Manufacturing/Inventory rather than forking them.

---

# Phase 29 — Construction and Real Estate

## Objective

Build project/site-driven construction and property operations.

## Construction Domain

- construction-site profile
- BOQ
- estimate
- WBS extension
- tender/contract
- subcontractor
- material request
- site inventory
- equipment scheduling
- progress measurement
- progress billing
- project costing

## Real Estate Domain

- property
- unit
- owner/tenant Party relationships
- lease
- rent schedule
- deposit
- service charge
- maintenance linkage

## Tests

- BOQ revisions
- progress billing
- subcontract retention
- project cost allocation
- lease billing

## Exit Criteria

Both verticals reuse Projects/Finance/Party/Resource while owning industry semantics.

---

# Phase 30 — Fleet and Logistics Vertical

## Objective

Extend Resource/Logistics/Maintenance for fleet operations.

## Domain

- vehicle profile -> Resource
- driver profile -> Party/Resource
- trip
- dispatch
- route
- fuel transaction
- odometer/usage
- maintenance schedule
- telematics external mapping
- proof of delivery
- fleet cost projection

## Tests

- driver/vehicle assignment conflicts
- maintenance due calculations
- telematics duplicate event handling
- trip costing

## Exit Criteria

Fleet-specific logic remains vertical while generic route/maintenance/resource services are reused.

---

# Phase 31 — Microfinance / Financial Services

## Objective

Build high-control financial-service workflows without assuming generic ERP GL is a complete core-banking engine.

## Domain

- KYC/customer profile extensions
- product definition
- loan application
- approval
- loan account
- amortization schedule
- disbursement
- repayment/collection
- fees/penalties
- delinquency
- restructuring/reschedule
- savings/account concepts only if separately specified
- teller/cash integration
- risk score/provider hooks
- regulatory reporting/localization hooks

## Accounting

Use explicit subledger-to-GL posting contracts.

## Security

- stronger maker-checker
- transaction limits
- audit
- privileged operation controls
- immutable account transaction history

## Tests

- schedule calculations
- early/late payment
- delinquency
- reversal
- concurrent posting
- approval limits

## Exit Criteria

Microfinance is operationally correct and auditable. Any full core-banking expansion requires separate architecture/compliance specifications.

---

# Phase 32 — Legal Practice

## Objective

Build legal-practice workflows on Party/Documents/Scheduling/Billing.

## Domain

- client profile/reference
- matter
- case
- opposing party
- conflict-check record
- court/event calendar
- document bundle
- legal task/workflow
- time entry
- expense
- billing arrangement
- trust-account integration boundary

## Tests

- conflict matching
- document access
- legal-calendar reminders
- time billing

## Exit Criteria

Legal-specific matters/cases remain vertical-owned.

---

# Phase 33 — Travel / Air Ticketing

## Objective

Build travel agency/ticketing capabilities using integration-first architecture.

## Domain

- traveler/passenger profile -> Party
- itinerary
- booking/order
- segment
- fare reference
- ancillary
- ticket/document
- exchange
- refund
- supplier settlement
- commission
- agency billing

## Integrations

- GDS connector
- NDC connector
- airline/supplier adapter

Protocols remain connectors, not kernel dependencies.

## Tests

- external ID mapping
- duplicate booking/event handling
- exchange/refund accounting
- multi-currency settlement

## Exit Criteria

Travel providers can be replaced/added through connectors without platform core changes.

---

# Phase 34 — Localization Framework and Initial Country Packs

## Objective

Make international deployment practical without country forks.

## Framework

- localization module manifest
- country applicability
- tax provider registration
- payroll rule registration
- statutory report registration
- fiscal document numbering
- bank/export formats
- e-invoicing connector registration
- address/name formats
- localized chart/templates

## Initial Country Packs

Prioritize based on commercial strategy, but architecture should support examples such as:

- Bangladesh
- UAE
- UK
- US

## Tests

- parallel legal entities in different countries
- localization enable/disable compatibility
- statutory configuration isolation
- language/currency/timezone

## Exit Criteria

A multinational tenant can run different legal entities under different localization packs in one BusinessOS installation.

---

# Phase 35 — Marketplace and Developer Platform

## Objective

Create a real external developer ecosystem.

## Deliverables

- Go SDK
- TypeScript SDK
- CLI
- module scaffolding
- manifest schema
- local sandbox
- migration tooling
- API/event contract generator
- mock providers
- test data factories
- conformance suite
- package builder
- OCI packaging for isolated services
- signing
- SBOM/provenance
- permission/capability review
- private module registry
- marketplace metadata
- module install/upgrade/disable/remove

## Certification

- tenancy certification
- security scan
- compatibility tests
- migration tests
- performance/resource profile

## Exit Criteria

An external developer can build, test, package and install a useful module without protected-core source access.

---

# Phase 36 — Self-Hosted Enterprise Operations

## Objective

Make BusinessOS professionally operable on customer infrastructure.

## Deliverables

- installer/bootstrap
- environment validation
- configuration wizard
- TLS/edge guidance
- database bootstrap
- Redis/NATS/S3 configuration
- backup jobs
- restore workflow
- DR runbook
- upgrade preflight
- signed release bundles
- maintenance mode
- diagnostics/support bundle
- log/telemetry configuration
- air-gap bundle
- HA deployment guides

## Tests

- clean install
- upgrade from supported versions
- failed upgrade recovery
- backup restore
- node replacement
- air-gap install/update

## Exit Criteria

An enterprise customer can install, upgrade, back up and recover the product without vendor engineers editing production databases manually.

---

# Phase 37 — BusinessOS Cloud Control Plane

## Objective

Operate a vendor-hosted SaaS model without changing the customer data-plane product.

## Owned Control-Plane Domains

- tenant provisioning
- tenant directory
- region/cell placement
- database-per-tenant routing
- entitlement/subscription
- metering
- release orchestration
- fleet health
- backup policy
- region/residency policy
- support workflow

## Rules

- control plane is separate from customer business data plane
- business runtime tolerates control-plane outage
- no unnecessary customer data replicated to control plane

## Tests

- tenant placement/relocation
- control-plane outage
- provisioning rollback
- region isolation

## Exit Criteria

BusinessOS Cloud can manage many tenant databases/cells while preserving the same module/runtime contracts as self-hosted installations.

---

# Phase 38 — Performance and Scale Certification

## Objective

Turn performance expectations into measurable certified workload profiles.

## Workload Profiles

- interactive backoffice
- POS checkout
- inventory movement
- warehouse picking
- accounting posting
- payroll run
- manufacturing planning
- reporting/export
- event backlog recovery
- large imports
- concurrent tenant/cloud cell usage

## Engineering

- p50/p95/p99 budgets
- DB query plans
- connection-pool tuning
- Redis/cache hit effectiveness
- NATS throughput/backlog
- partitioning where proven
- read projections/materialized views
- horizontal worker/API scaling
- service extraction only where justified

## Exit Criteria

Published reference hardware/topology meets defined workload SLOs, and bottlenecks have evidence-backed remediation plans.

---

# Phase 39 — Security and Compliance Maturity

## Objective

Mature the secure SDLC and control framework for international enterprise customers.

## Deliverables

- product threat models
- module threat-model template
- secure coding standards
- SAST/DAST where applicable
- dependency scanning
- secret scanning
- SBOM/provenance enforcement
- penetration testing
- vulnerability disclosure/advisory process
- privileged support controls
- encryption/key-management profiles
- privacy/data-governance evidence
- backup/DR evidence
- tenant isolation certification

## Compliance

Map technical controls to target frameworks only after legal/compliance review. Architecture alone does not imply certification.

## Exit Criteria

Security evidence is repeatable per release and critical controls are automated in CI/CD/operations.

---

# Phase 40 — LTS, Compatibility and Enterprise Ecosystem

## Objective

Create the long-term product lifecycle needed to compete internationally.

## Deliverables

- stable/LTS/security release channels
- support windows
- compatibility matrix
- deprecation registry
- migration assistant
- upgrade rehearsal tooling
- module certification lifecycle
- partner certification
- implementation templates
- customer success/support runbooks
- architecture conformance checks
- marketplace governance

## LTS Rules

- public contract removal only after documented deprecation window
- security fixes can be backported according to supported channel policy
- module compatibility is machine-readable
- enterprise customers can preflight upgrades before maintenance windows

## Exit Criteria

Customers and partners can operate supported BusinessOS versions over multi-year lifecycles with predictable upgrade and module compatibility processes.

---

# Global Rules Across Phases 2–40

Every implementation phase must explicitly answer:

1. Which bounded context owns each new table/entity?
2. Does the change preserve tenant isolation in DB/cache/messages/files/search/jobs/workflows?
3. Which public API/event/provider/UI contracts are introduced or modified?
4. How will the data migrate in a future upgrade?
5. Can a customer extension use the capability without private imports?
6. Does the design preserve multinational/multi-company/multi-site behavior?
7. Does the design support multi-language/currency/timezone where relevant?
8. What are the authorization and audit requirements?
9. What tests prove invariants and cross-tenant safety?
10. What is the rollback/forward-repair strategy?
11. Does the phase create a shortcut that blocks a later phase in `FULL-SYSTEM.md`?

Codex must not mark a phase complete unless its phase exit criteria and applicable architecture release gates are satisfied.