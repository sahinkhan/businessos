# Phase 3 hardening backlog

The full Phase 3 independent audit identified two non-blocking Medium findings.
Both historical findings are retained below and are now closed by the focused
Party and Geography hardening candidate. Final zero-Medium certification still
requires exact-head validation and independent verification.

| Finding | Affected surface and original risk | Status and closure evidence |
| --- | --- | --- |
| Party number collision | `foundations/party/src/businessos_party/module.py` person and organization creation used eight UUID hex digits (32 bits) and a collision failed without retry. | **CLOSED** — new generation uses 16 uppercase random hex digits (64 bits), preserves `PRT-` and existing numbers, and retries the tenant-scoped `uq_party_tenant_number` conflict up to five insert attempts. `tests/integration/test_phase3_zero_medium_hardening.py` covers forced collisions, exhaustion, unrelated integrity errors, tenant scope, and concurrent creation. |
| Ambiguous locality selection | `foundations/geography/src/businessos_geography/module.py` address validation selected an unordered first city with a matching name, so duplicate names could validate inconsistently. | **CLOSED** — a hierarchy-scoped, deterministically ordered `LIMIT 2` query distinguishes zero, one, and multiple cities. Multiple matches return `ambiguous_city`; no arbitrary winner is selected. The same PostgreSQL regression file covers duplicate names across subdivisions/countries and normalized address creation. |

Known Phase 3 certification finding count after these changes: Critical **0**,
High **0**, Blocking Medium **0**, Non-blocking Medium **0**, Low **0**, subject
to final independent verification.
