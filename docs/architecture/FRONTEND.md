# BusinessOS Frontend Architecture

## Baseline

The authenticated enterprise backoffice uses:

- React
- TypeScript
- React Router
- Vite

Next.js is optional for public storefronts, portals and SEO/SSR-heavy applications.

## UI Foundation Gate

The dedicated enterprise frontend foundation is defined in `docs/roadmap/PHASE-4.5-UI-FOUNDATION.md`.

Phase 4.5 is an inter-phase dependency gate after certified Phase 4 and before Phase 5 Metadata, Studio and Dynamic UI. It owns the reusable shell, design-system primitives, theme/tokens, routing/navigation contribution contracts, scope presentation, permission-aware presentation helpers, form/table foundations, i18n, accessibility, responsive behavior, data-access conventions and frontend CI baseline.

Phase 5 consumes these stable primitives for metadata-driven rendering. Phase 4.5 must not implement the Phase 5 metadata registry, dynamic renderer or Studio, and Phase 5 must not replace the shared shell/design-system architecture with a parallel private UI framework.

## Goals

The frontend must support a large modular enterprise application without forcing every module to own an independent frontend shell.

The BusinessOS shell owns common concerns:

- authentication/session integration
- active tenant/company/site scope
- navigation shell
- module route registration
- design system/theme
- translation/locale
- permission-aware presentation
- notifications
- global command/search surfaces
- error boundaries
- telemetry

## Module UI Contributions

Supported contribution levels:

1. declarative metadata-driven UI
2. controlled component extension slots
3. isolated UI micro-application for specialized experiences

Modules must not depend on undocumented private component internals.

## Dynamic UI

BusinessOS should support metadata-driven definitions for common enterprise experiences:

- list/table
- form
- detail
- kanban
- calendar
- dashboard
- wizard
- actions
- menus

Dynamic UI must remain schema/version controlled. It must not become arbitrary executable code stored in the database.

## Data Access

Frontend modules consume supported APIs through BusinessOS client/data abstractions.

Large datasets use server-side:

- pagination
- filtering
- sorting
- search
- aggregation where appropriate

Do not load unbounded enterprise tables into the browser.

## Authorization

UI permissions are presentation hints only. The backend must enforce every protected operation.

## Internationalization

All official user-visible strings use translation keys/resources.

Frontend components must support:

- runtime locale switching
- RTL layouts
- locale-aware numbers/dates
- currency display
- timezone-aware instant display

## Accessibility

The design system should target WCAG-compatible enterprise interaction patterns, including keyboard navigation, labels, focus states and semantic components.

## Performance

- route/module code splitting
- avoid unnecessary global state
- virtualize very large grids where appropriate
- server-side data operations for enterprise datasets
- measure bundle sizes and interaction latency
- use stable query/cache abstractions for server state

## Extension Safety

Marketplace UI code must not receive unrestricted access to secrets, privileged browser storage or internal application state. Specialized executable UI should be isolated and communicate through versioned extension contracts.
