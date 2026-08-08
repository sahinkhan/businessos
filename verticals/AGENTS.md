# Industry Solution Instructions

These instructions apply under `verticals/` and supplement the root `AGENTS.md`.

Industry modules compose platform foundations and shared business modules, then add vertical-owned concepts.

## Rules

- Never modify protected kernel source for a vertical feature.
- Never add vertical-specific columns to generic Party, Organization, Resource, Tenant or other foundation tables.
- Use profile/extension entities referencing stable foundation IDs.
- Reuse generic Resource and Scheduling for appointments/reservations/capacity where semantics fit.
- Reuse Party for people/organizations and add vertical profiles such as PatientProfile, StudentProfile or GuestProfile.
- Reuse Operating Site for facilities/outlets/properties and add vertical site profiles.
- Own vertical schema, migrations, permissions, APIs/events and tests.
- Integrate with business modules through published contracts.

## Architecture Escalation

If a vertical needs a capability missing from foundations, first determine whether the need is reusable across unrelated domains.

If yes, propose a generalized foundation contract through ADR/design review.

If no, keep it inside the vertical.