# Protected Platform Instructions

These instructions apply under `platform/` and supplement the root `AGENTS.md`.

This directory contains high-trust protected BusinessOS platform code.

## Hard Rules

- No industry-specific concepts or imports.
- No dependencies on Sales, Accounting, Healthcare, Education, Hospitality, POS, Manufacturing or other higher-layer modules.
- No customer-specific behavior.
- No country-specific statutory business rules.
- Public contracts require explicit ownership/versioning/tests.
- Tenant context is mandatory for tenant-owned operations.
- Do not introduce a breaking public contract without an approved ADR/versioning plan.
- Do not expose unrestricted database or host access to marketplace modules.
- Keep transport, application/runtime and infrastructure concerns separated.

## Kernel Quality Bar

Kernel changes require extra scrutiny because every module may depend on them.

For substantial changes, report:

- why the capability belongs in protected platform rather than a foundation module
- public contract impact
- tenant/security impact
- upgrade/compatibility impact
- performance impact
- conformance tests added

If a capability can live in a replaceable foundation module instead of protected kernel, prefer the foundation module.