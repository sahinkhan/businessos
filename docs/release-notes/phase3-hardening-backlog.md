# Phase 3 non-blocking Medium hardening backlog

The completed full Phase 3 independent audit classified the following two
findings as **non-blocking Medium**. They remain open and are not fixed by the
UoM precision remediation.

| Finding | Affected surface | Risk | Recommended future remediation |
| --- | --- | --- | --- |
| Party number collision | `foundations/party/src/businessos_party/module.py` person and organization creation | Eight UUID hex digits supply only 32 random bits; a collision under the tenant uniqueness constraint fails a create without retry. | Adopt an owner-reviewed, collision-safe business-number allocation contract with retry or sequence semantics and concurrency tests. |
| Ambiguous locality selection | `foundations/geography/src/businessos_geography/module.py` address validation | Duplicate city names can have different postal patterns; an unordered first match can validate the same address inconsistently. | Define the canonical locality identity or deterministic ambiguity policy, then enforce it in queries and database constraints with migration preflight and tests. |

Any implementation of these items requires its own scoped compatibility and
data-integrity review. Their current classification does not block the Phase 3
certification gate.
