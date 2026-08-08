# Platform Foundation Module Instructions

These instructions apply under `foundations/` and supplement the root `AGENTS.md`.

Foundation modules provide reusable capabilities for unrelated business and industry domains.

## Rules

- Keep terminology industry-neutral.
- Reuse Party, Organization, Operating Site, Resource, Scheduling, UoM and Reference Data rather than duplicating masters.
- A foundation owns its own schema and migrations.
- Do not write another foundation/business module's private tables.
- Publish stable application interfaces/events when other modules require interaction.
- Avoid dependencies on business modules or industry solutions.
- Tenant isolation and authorization are mandatory for tenant-owned operations.

## Design Test

Before adding a concept to a foundation ask:

1. Is this required by multiple unrelated domains?
2. Can it be expressed without one industry's terminology?
3. Does it have stable semantics independent of a specific business workflow?

If not, it probably belongs in a business or vertical module instead.