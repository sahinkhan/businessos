# Shared Business Module Instructions

These instructions apply under `modules/` and supplement the root `AGENTS.md`.

Business modules implement reusable commercial/operational bounded contexts such as Sales, Inventory, Accounting, HR or Manufacturing.

## Rules

- Each module owns its business invariants, schema, migrations, commands, events, APIs, permissions and tests.
- Never directly update another module's private tables.
- Depend on platform/foundation public contracts.
- Cross-module side effects use application contracts, commands/events or approved orchestration.
- Keep vertical-specific fields out of generic business modules unless they are genuinely reusable business concepts.
- Financial and inventory posting rules must preserve immutable ledger/history principles.
- Tenant, company/site and authorization scope must be explicit.

## Integration

Prefer loose coupling through published contracts. Avoid circular dependencies. Optional integrations should use events/providers rather than hard bidirectional imports.