# BusinessOS Canonical Module Catalog

Status: Target module map

This catalog defines target bounded contexts. Names may evolve through ADR/design review, but implementations must preserve ownership and dependency principles.

## Protected Platform

- runtime
- context
- configuration
- module registry
- contract registry
- provider registry
- Unit of Work
- authorization enforcement
- migration/compatibility runtime
- event/outbox runtime
- diagnostics

## Platform Foundations

### Tenant and Identity
- Tenant Management
- Identity
- Membership
- Service Account / Device Identity
- Entitlements / Feature Access

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
- Financial Dimensions

### Shared Masters
- Party / Contacts
- Address / Geography
- Reference Data
- External IDs
- Number Sequences
- UoM / Precision
- Currency / Exchange Rate Foundation

### Platform Services
- Policy / RBAC / ABAC
- Metadata / Studio
- Workflow / Rules / Case
- Resource Management
- Scheduling / Reservation
- Documents
- Collaboration / Activities
- Notifications
- Search
- Reporting
- Import / Export
- Internationalization
- Data Governance
- Integrations
- Background Jobs
- Hierarchical Configuration

## Shared Business Modules

### Commercial
- CRM
- Catalog
- Pricing
- Promotion
- Tax
- Sales
- Subscription / Contract Management

### Procurement and Supply Chain
- Procurement
- Inventory
- Warehouse
- Logistics / Shipping

### Finance
- Billing
- Payments
- Accounting
- Fixed Assets
- Expenses
- Budgeting
- Treasury Foundation
- Consolidation Foundation

### People
- HR
- Attendance / Time
- Leave
- Recruitment
- Payroll
- Performance / Benefits foundations

### Operations
- Projects
- Timesheets
- Helpdesk
- Field Service
- Maintenance
- Quality

### Production
- Manufacturing
- Planning / MRP
- Costing

### Channels
- POS
- E-commerce

## Industry Solutions

### Healthcare
- Patient Profile
- Practitioner
- Appointment
- Encounter
- Clinical Records
- Admission/Discharge/Transfer
- Bed/Facility Operations
- Healthcare Billing Extensions
- Pharmacy

### Education
- Student / Guardian
- Academic Structure
- Enrollment
- Timetable
- Attendance
- Examination / Assessment
- Fees

### Salon / Spa / Gym
- Service Operations
- Membership
- Booking
- Packages
- Commission
- Check-in

### Restaurant
- Menu
- Table / Reservation
- Kitchen Operations
- Food Service POS Extensions
- Recipe / Ingredient Integration

### Hospitality
- Property
- Room Inventory
- Rate Plan
- Reservation
- Guest / Stay
- Folio
- Housekeeping

### Garments / Apparel
- Style / Matrix
- Tech Pack Integration
- Sample
- Material Planning
- Production Stages
- Apparel Costing
- Compliance

### Construction
- BOQ
- Estimate
- Contract
- Subcontract
- Progress Billing
- Site Operations
- Project Costing

### Real Estate
- Property
- Unit
- Lease
- Rent
- Maintenance Extensions

### Fleet / Logistics
- Vehicle
- Driver
- Trip
- Dispatch
- Fuel
- Fleet Maintenance
- Telematics Integration

### Microfinance / Financial Services
- KYC Extensions
- Financial Product
- Loan
- Schedule
- Disbursement
- Collection
- Delinquency
- Teller/Cash Extensions
- Risk/Approval

### Legal
- Matter
- Case
- Legal Calendar
- Legal Documents
- Time/Billing Extensions
- Conflict Check

### Travel / Air Ticketing
- Traveler
- Itinerary
- Booking
- Fare / Ancillary
- Ticket / Document
- Refund / Exchange
- Supplier Settlement
- GDS/NDC Integration

## Localization Modules

Each country pack may provide:

- tax rules
- statutory document rules
- e-invoicing
- withholding
- payroll localization
- bank/payment formats
- statutory reports
- address/name conventions

## Connector Modules

Examples:

- payment gateways
- banks
- couriers
- shipping carriers
- email/SMS/push
- identity providers
- government/e-invoicing
- healthcare interoperability
- GDS/NDC
- telematics
- marketplace/channel integrations

## Ownership Rule

A concept belongs in the lowest reusable layer that expresses it correctly without importing higher-layer semantics.

Do not promote a vertical concept into foundation/core merely because one implementation needs it.