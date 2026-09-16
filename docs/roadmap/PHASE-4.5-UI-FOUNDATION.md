# Phase 4.5 — Enterprise UI Foundation v1

Status: Authoritative inter-phase delivery gate between certified Phase 4 and Phase 5.

This phase exists to establish a reusable enterprise frontend foundation before BusinessOS begins the Phase 5 Metadata, Studio and Dynamic UI runtime. It does not introduce business-module screens or metadata-driven rendering itself.

Phase 4.5 is downstream of the certified Phase 4 authorization/governance contracts and upstream of Phase 5. Phase 5 may depend on the UI Foundation; the UI Foundation must not depend on Phase 5 metadata contracts.

---

## Objective

Create the stable BusinessOS enterprise application shell, design system, interaction primitives and frontend platform conventions required by later metadata-driven and business-module UIs.

The foundation must support:

- heavy enterprise users
- long-lived business applications
- large datasets
- modular installation
- multi-tenant / multi-company / multi-site scope presentation
- internationalization and RTL
- permission-aware presentation
- accessible keyboard-first workflows
- responsive desktop/tablet/mobile layouts
- predictable upgrade behavior
- future Metadata/Studio/Dynamic UI rendering without source-code forks

The UI Foundation is infrastructure. It must avoid hardcoded domain workflows that would later be replaced by Phase 5 metadata definitions.

---

## Certified Dependency

Phase 4 must be certified and frozen before Phase 4.5 implementation begins.

The UI Foundation may consume published contracts from:

- Identity/Tenant/Organization
- Party/Geography/Reference Data/UoM where generic master-data examples are required
- Policy/Authorization
- Audit/Data Governance where presentation requires policy or governance hints

The frontend is never an authorization authority. Backend policy enforcement remains mandatory for every protected operation.

---

## Frontend Baseline

The authenticated BusinessOS enterprise backoffice uses:

- React
- TypeScript
- React Router
- Vite

Next.js remains optional for public storefronts, portals and SEO/SSR-heavy applications. It is not the default authenticated enterprise shell.

Use the architecture rules in `docs/architecture/FRONTEND.md` as the baseline. If implementation needs to contradict that document, create and approve an ADR before coding the conflicting architecture.

---

## Owned Area

The implementation should live under a dedicated frontend application boundary such as:

```text
apps/web/
├── src/
│   ├── app/
│   ├── shell/
│   ├── design-system/
│   ├── components/
│   ├── navigation/
│   ├── auth/
│   ├── layouts/
│   ├── themes/
│   ├── i18n/
│   ├── api/
│   ├── state/
│   ├── telemetry/
│   └── features/
├── tests/
└── package.json
```

The exact directory name may follow repository conventions when implementation starts. The architectural separation is mandatory even if the physical path differs.

Do not place protected Python backend code inside the frontend application tree.

---

# Required Capabilities

## 1. Application Bootstrap

Provide a production-ready Vite + React + TypeScript application bootstrap with:

- strict TypeScript configuration
- React Router application routing
- environment/config loading through an explicit typed boundary
- root error boundary
- root suspense/loading boundary where justified
- application providers composed in one controlled bootstrap location
- development and production build commands
- deterministic dependency locking
- source maps according to deployment/security policy

Avoid hidden global initialization spread across feature modules.

---

## 2. Design Tokens

Create semantic design tokens for at least:

- typography
- font sizes and line heights
- spacing
- sizing
- border radius
- borders
- elevation/shadow
- semantic colors
- focus indicators
- breakpoints
- motion duration/easing
- z-index layers

Components should consume semantic tokens rather than embedding arbitrary repeated values.

Token naming must represent purpose rather than one current visual value. Example categories:

- `surface.*`
- `text.*`
- `border.*`
- `action.*`
- `status.*`
- `focus.*`

Phase 5 metadata may reference stable presentation semantics but must not depend on private token implementation details.

---

## 3. Theme System

Support:

- light theme
- dark theme
- system preference
- runtime switching
- persistence of user preference through the supported preference mechanism
- accessible contrast

Theme choice must not create duplicated component implementations.

Business modules must consume the shared theme rather than shipping independent page-level themes.

---

## 4. Enterprise Application Shell

Create the authenticated shell with reusable regions for:

- primary navigation/sidebar
- header/top bar
- breadcrumbs/context trail
- tenant/company/site context display or switcher
- global command/search trigger
- notifications/inbox trigger
- user/account menu
- page title/actions area
- main content area
- contextual panels where needed

The shell must support:

- collapsed and expanded navigation
- responsive behavior
- keyboard navigation
- persisted user layout preference where approved
- module-contributed navigation through a registry/contract

Do not hardcode all future BusinessOS modules into the shell.

---

## 5. Navigation Registry

Provide a typed navigation contribution contract so installed modules can contribute navigation without modifying protected shell code.

The navigation model should support stable concepts such as:

- route identifier
- translation key
- icon reference
- parent/group
- ordering
- required permission/capability hint
- feature/entitlement visibility hint
- scope requirements

The UI may hide or disable items based on policy hints, but direct route/API access remains protected by backend authorization.

Phase 5 may later generate or resolve menu/action metadata into this registry.

---

## 6. Authentication and Session Shell

Provide frontend boundaries for:

- authenticated session state
- unauthenticated/login route shell
- session expiry handling
- logout
- authentication error handling
- return-to route handling where safe
- identity/principal display

Do not implement authentication security by trusting browser state alone.

OIDC/SAML/MFA security decisions belong to the backend/identity architecture; the frontend renders supported flows and state.

---

## 7. Active Business Scope

Provide a single canonical frontend representation of the active business context consumed from supported backend contracts.

The UI should be able to present/switch permitted scope such as:

- tenant
- legal entity/company
- business unit where supported
- operating site

Requirements:

- switching must use supported backend contracts
- invalid/stale scope must fail safely
- scope must be visible when operationally important
- feature modules must not invent their own unrelated company/site selectors as the authoritative application scope

Warehouse/location and future module-local context may remain feature-specific where appropriate.

---

## 8. Permission-Aware Presentation

Create reusable presentation helpers/components that consume Phase 4 policy decisions, for example:

- permission boundary
- action visibility
- action disabled state with reason where appropriate
- field visibility hint
- field read-only hint
- approval-authority hint

The frontend must not duplicate the policy engine.

Do not evaluate security-critical ABAC expressions in ad hoc React code.

Do not infer permission from hidden buttons.

Protected commands/queries must still be enforced by the backend.

---

## 9. Core Component Primitives

Provide reusable, accessible primitives suitable for dense enterprise software.

Minimum component families:

### Actions

- Button
- IconButton
- SplitButton or action menu pattern where required

### Inputs

- TextInput
- TextArea
- NumberInput
- MoneyInput presentation primitive
- Select
- MultiSelect
- Checkbox
- RadioGroup
- Switch
- Date input/picker abstraction
- DateTime input/picker abstraction
- Search input

### Structure

- Card/Panel
- Divider
- Stack/Inline/Grid layout primitives or equivalent
- Tabs
- Accordion/Disclosure where justified

### Overlays

- Dialog/Modal
- Drawer/Sheet
- Popover
- Dropdown/Menu
- Tooltip

### Feedback

- Toast/notification
- Alert
- Progress indicator
- Spinner
- Skeleton
- Empty state
- Error state

Components must expose stable public props/contracts. Feature modules must not depend on undocumented private internals.

---

## 10. Form Foundation

Create reusable form primitives and layout conventions, including:

- field label
- description/help text
- required/optional presentation
- validation state
- error message
- read-only/disabled state
- section/group layout
- responsive field grids
- form-level error summary where appropriate
- unsaved-change protection pattern
- submit/cancel/action layout

The UI Foundation may use a form-state library if architecture review approves it, but Phase 5 metadata rendering must not be coupled to an unstable library-specific form schema.

Do not implement final dynamic metadata forms in Phase 4.5.

---

## 11. Enterprise Data Table Foundation

Provide a reusable table/grid foundation designed for large business datasets.

Required capabilities:

- server-side pagination
- server-side sorting
- server-side filtering
- server-side search integration
- column definitions
- column visibility
- density options where appropriate
- row selection
- bulk-action surface
- loading state
- empty state
- error state
- keyboard-accessible interaction
- sticky header where appropriate
- horizontal overflow behavior
- large dataset virtualization when justified

Do not load unbounded enterprise tables into browser memory.

Phase 5 will later map list-view metadata to this table foundation.

---

## 12. Filtering, Search and Pagination Primitives

Create consistent shared patterns for:

- quick search
- structured filter controls
- active filter chips/summary
- clear/reset
- sort state
- page size
- page navigation
- total/result count where available

The URL should carry shareable/recoverable list state when appropriate and safe.

Future saved filters/views belong to later roadmap phases unless explicitly pulled forward by an approved change.

---

## 13. Standard Page Layouts

Provide reusable layout patterns such as:

- list page shell
- record/detail page shell
- create/edit page shell
- settings page shell
- dashboard page shell
- wizard page shell structure only

These are layout primitives, not domain-specific implementations.

Do not add Sales, Purchase, Inventory, Accounting, HR or other business workflows in Phase 4.5.

---

## 14. Loading, Error and Empty-State Standards

Every asynchronous page/component pattern must have deliberate states for:

- initial loading
- refreshing
- no data
- filtered-no-results
- recoverable error
- authorization/forbidden
- not found
- service unavailable where relevant

Avoid blank pages and ambiguous indefinite spinners.

---

## 15. Notification Shell

Provide a shell-level notification/inbox surface capable of consuming future notification APIs.

Phase 4.5 should define the frontend contract and presentation primitives only unless an authoritative notification backend already exists.

Full notification domain capabilities remain in the roadmap phase that owns them.

---

## 16. Command Palette / Global Command Surface

Provide the shell infrastructure for a keyboard-accessible command palette or equivalent global command surface.

It should support registered commands/routes through a typed contribution contract.

Do not hardcode business operations that bypass normal authorization or workflow APIs.

Global search backend maturity remains owned by the search roadmap phase.

---

## 17. Internationalization

All official user-visible application strings must use translation keys/resources rather than hardcoded production text inside reusable components.

Support:

- runtime locale switching
- fallback locale
- RTL layouts
- locale-aware number formatting
- locale-aware date formatting
- currency display
- timezone-aware instant display
- pluralization

Backend-transmitted stable codes should be mapped to translated labels through supported resources rather than converted into English-only UI text ad hoc.

---

## 18. Accessibility

Target WCAG-compatible enterprise interaction patterns.

At minimum:

- keyboard operation
- visible focus state
- semantic HTML
- associated labels
- accessible validation/errors
- dialog focus management
- screen-reader-friendly navigation landmarks
- sufficient contrast
- reduced-motion support where applicable
- non-color-only status indicators

Accessibility must be part of component acceptance, not a final visual cleanup task.

---

## 19. Responsive Layout

The authenticated application must remain usable across supported desktop, tablet and mobile viewport ranges.

Enterprise desktop density is important, but small-screen behavior must be intentional.

Responsive behavior should include:

- collapsible navigation
- adaptive page action layout
- scroll-safe data tables
- form field reflow
- modal/drawer adaptation
- touch target sizing where appropriate

Phase 4.5 does not require every future complex ERP workflow to become mobile-first; it establishes reusable responsive behavior.

---

## 20. Frontend Data Access Boundary

Create a typed frontend client/data-access abstraction for supported BusinessOS APIs.

Requirements:

- no feature should scatter raw fetch logic across view components
- standard request/response error handling
- cancellation where appropriate
- authentication/session integration
- correlation/request metadata where exposed
- typed pagination/filter/sort contracts
- stable server-state cache/query abstraction
- mutation invalidation conventions

Do not expose database concepts or direct SQL semantics to the browser.

---

## 21. Client State Rules

Separate:

- server state/cache
- authenticated/session state
- active business scope
- transient UI state
- persisted user presentation preferences

Avoid one unbounded global state store containing unrelated domain data.

Business modules should own feature-local UI state unless it is truly shell-wide.

---

## 22. Telemetry and Diagnostics

Provide frontend integration points for:

- error reporting
- route/page telemetry
- interaction/performance measurement where approved
- correlation with backend request/trace identifiers where available
- build/version display in diagnostics

Do not log secrets, access tokens, sensitive personal data or unredacted protected business records.

---

## 23. Performance Baseline

Required principles:

- route/module code splitting
- lazy loading where appropriate
- avoid unnecessary global rerenders
- stable query/cache behavior
- server-side operations for large datasets
- virtualization for very large grids when justified
- production bundle analysis capability
- measurable performance budgets

At minimum the UI Foundation implementation should establish CI-visible or reproducible checks for:

- production build success
- bundle size reporting/budget policy
- critical shell interaction responsiveness

Exact numerical budgets should be recorded during implementation using measured baseline artifacts rather than invented in this document.

---

## 24. Extension-Slot Foundation

Define controlled, typed UI extension-slot contracts for later module and marketplace contributions.

The Phase 4.5 contract should define safe attachment points such as:

- shell navigation contribution
- page action contribution
- record/detail region contribution
- toolbar contribution
- settings contribution

Phase 4.5 defines the base interface and isolation expectations.

Phase 5 owns metadata-driven extension-slot definitions/resolution.

Specialized executable micro-app isolation remains subject to frontend architecture and marketplace security rules.

---

## 25. Module Route Contribution

Provide a controlled route registration model so installed modules can add frontend routes without editing the root router source for every module.

Requirements:

- stable route identifiers
- collision detection
- lazy module loading
- permission/capability presentation hints
- error boundary per module/route where appropriate
- no unrestricted access to private shell internals

---

## 26. Icons and Visual Assets

Define one approved icon strategy and shared asset conventions.

Requirements:

- consistent sizing/alignment
- accessible labels for icon-only actions
- tree-shakeable or otherwise performance-conscious loading
- no arbitrary per-feature icon systems
- no base64-heavy or duplicated production assets without justification

---

## 27. Enterprise UX Conventions

Document and enforce shared behavior for:

- destructive-action confirmation
- unsaved changes
- optimistic vs confirmed updates
- inline vs page-level validation
- save/submit progress
- retry
- bulk actions
- selection persistence
- disabled actions and explanatory feedback
- read-only records
- forbidden states

Consistency across modules is more important than per-screen novelty.

---

# Explicit Non-Goals

Phase 4.5 must NOT implement the Phase 5 metadata engine.

Do not implement:

- metadata entity registry
- custom-field persistence
- custom-entity persistence
- dynamic form schema runtime
- dynamic list schema runtime
- metadata-driven detail renderer
- Studio/form designer
- metadata menu/action persistence
- customization packages/version migrations

Phase 4.5 must also NOT implement hardcoded business-module workflows such as:

- `SalesOrderForm`
- `PurchaseOrderForm`
- `InventoryTransferForm`
- `JournalEntryForm`
- `EmployeeForm`

Generic component demonstrations and non-production fixture/example pages are allowed when needed to certify the design system.

---

# Phase 5 Integration Contract

Phase 5 should consume Phase 4.5 primitives rather than replacing them.

Example conceptual flow:

```text
Phase 4.5
Design System + Shell + DataTable + Form Primitives
                         ↓
Phase 5
Metadata Registry → UI Schema Resolver → Dynamic Renderer
                         ↓
                Phase 4.5 Components
```

Example metadata in Phase 5 may describe:

```json
{
  "view": "list",
  "entity": "party",
  "columns": ["code", "name", "type", "status"]
}
```

The Phase 5 runtime interprets the schema and supplies stable column definitions to the Phase 4.5 DataTable. The DataTable itself must not depend on Party-specific metadata.

---

# Security Requirements

- browser state is not authoritative for permissions
- backend authorization remains mandatory
- no access tokens/secrets in logs
- no unrestricted marketplace code access to privileged state/storage
- external links and rendered rich content must use safe policies
- unsafe arbitrary HTML/script execution is prohibited in shared primitives
- scope switching must use supported backend contracts
- frontend caching must not leak data across tenant/scope/session boundaries
- sensitive values must not be persisted to browser storage unless an explicit architecture/security rule permits it

---

# Testing Requirements

## Unit / Component

Cover shared components for:

- rendering
- states/variants
- keyboard interaction
- accessibility semantics
- error states
- RTL where relevant
- permission presentation behavior

## Integration

Cover at least:

- authenticated shell bootstrap
- route registration
- active scope switching behavior
- permission-aware presentation
- API error/session-expiry behavior
- server-side table query state
- theme switching
- locale switching

## Accessibility

Use automated accessibility checks where practical, plus manual keyboard/focus verification for critical primitives.

## Responsive

Test representative breakpoints/viewports for shell, forms, dialogs/drawers and data table overflow behavior.

## Production Build

CI must prove:

- dependency install from lockfile
- formatting
- linting
- TypeScript typecheck
- unit/component tests
- production build
- bundle/report policy

If Storybook or an equivalent component workbench is adopted, it must follow repository architecture and CI policy. It is not mandatory merely by this document.

---

# Quality Gates

Phase 4.5 cannot be certified if any of these are unresolved:

- TypeScript errors
- lint/format failures
- failing component/integration tests
- production build failure
- critical accessibility defects in foundation primitives
- frontend permission logic treated as security authority
- unbounded enterprise table loading
- hardcoded business-module UI architecture that conflicts with Phase 5
- undocumented shell/module coupling
- unstable extension contracts
- tenant/scope cache isolation defect

---

# Suggested Implementation Order

1. frontend project/bootstrap and CI
2. design tokens and theme
3. low-level accessible primitives
4. application shell
5. routing/navigation contribution contracts
6. auth/session and active-scope integration
7. permission presentation boundaries
8. form foundation
9. data table/filter/pagination foundation
10. standard page layouts and async states
11. i18n/RTL
12. notifications/command shell surfaces
13. API/server-state boundary
14. telemetry and performance checks
15. extension-slot contracts
16. integration/accessibility/responsive certification

Keep commits bounded and auditable.

---

# Exit Criteria

Phase 4.5 is COMPLETE / CERTIFIED / FROZEN only when all of the following are true:

1. React/TypeScript/React Router/Vite authenticated shell builds in production mode.
2. Shared design tokens/theme and accessible component primitives are implemented and documented.
3. Navigation and module-route contribution contracts work without protected-shell edits for each module.
4. Active tenant/company/site scope presentation consumes supported backend contracts.
5. Phase 4 policy decisions can drive presentation hints without duplicating backend authorization logic.
6. Forms, tables, filters, pagination, overlays and standard page layouts are reusable and domain-neutral.
7. i18n, RTL, accessibility and responsive requirements are demonstrably covered.
8. Large datasets use server-side pagination/filtering/sorting/search patterns.
9. API/client state boundaries prevent ad hoc data-access patterns and tenant/scope cache leakage.
10. Frontend quality gates and production build are green in CI.
11. No Phase 5 metadata runtime, Studio or Dynamic UI implementation has been started inside this phase.
12. No hardcoded business-module workflow architecture creates a dependency that Phase 5 must later undo.

Gate: Phase 5 may start only after the UI Foundation contracts required by its dynamic renderer are intentionally accepted and frozen, or after an explicit architecture decision documents a narrower dependency.

---

# Freeze / Upgrade Rule

After Phase 4.5 certification:

- treat public design-system, shell, route, navigation, data-access and extension contracts as compatibility-sensitive
- evolve them additively where practical
- use deprecation instead of silent breaking changes
- do not allow business modules to depend on private component internals
- Phase 5 must extend the foundation through published contracts rather than forking/replacing it

This phase does not freeze visual design forever. It freezes the supported architectural contracts and quality expectations on which Phase 5 and later modules depend.
