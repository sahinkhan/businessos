# ADR-006: Module-Owned Data and Migrations

Status: Accepted

## Decision

Every PostgreSQL table has exactly one bounded-context owner. The owning module controls schema, migrations and write invariants.

Other modules must not directly mutate private tables. Cross-module behavior uses published application contracts, commands/events, APIs or approved projections.

## Consequences

Direct foreign-key coupling across bounded contexts should be used cautiously because it can prevent independent lifecycle/service extraction. Stable IDs and application-level contracts are preferred across module boundaries unless an explicitly approved same-lifecycle relationship justifies stronger database coupling.