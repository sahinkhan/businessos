# Canonical Protected-Kernel Responsibility Map

Status: Active architecture source of truth under [BOS-ARCH-003](ARCHITECTURE.md) and [ADR-008](../adr/ADR-008-python-asgi-technology-baseline.md).

The protected kernel owns only generic runtime primitives. This is the authoritative responsibility inventory; shorter lists in the engineering contract, architecture overview, module catalog, master build instructions, and roadmap are descriptions at different levels of detail, not alternative ownership maps.

## Responsibilities

- bootstrap/runtime
- RequestContext / TenantContext
- configuration
- module discovery / registry / lifecycle
- ASGI routing / middleware
- dependency injection
- contract registry
- command/query dispatch
- Unit of Work / framework-owned transaction boundary
- authorization enforcement boundary
- event / transactional-outbox runtime
- provider registry
- feature flags
- metadata / permission registration primitives
- migration runtime
- compatibility runtime
- module SDK / upgrade coordination
- diagnostics / health / version

Entity runtime primitives, job scheduling abstractions, security context, and telemetry are generic implementation details within these responsibilities. Foundation-owned Policy, Identity, Tenant, Organization, and business concepts remain outside the kernel; the kernel supplies generic enforcement and registration mechanisms, not their domain decisions.

Changing ownership or the technology baseline requires the [ADR governance procedure](../governance/ADR-GOVERNANCE.md). A documentation correction that preserves this meaning may use ordinary review.
