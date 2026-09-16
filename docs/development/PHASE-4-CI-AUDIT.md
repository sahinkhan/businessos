# Phase 4 certification audit

Audited baseline: `8ecddc381456297f3400958253d3c07bde140bb2`.

## Original failure

Post-merge BusinessOS CI run `35107596299` stopped at Ruff formatting. Ruff
reported 16 Phase 4 files that required deterministic formatting. The three
Phase 4 `0001` revisions retained identical AST hashes, revision metadata, SQL,
tables, constraints, indexes, and RLS behavior after formatting. All Phase 1–3
migrations remain byte-for-byte identical to the audited baseline.

The formatter-only change is isolated in commit `bf4eab7`.

## Roadmap and security audit

The initial implementation provided the Phase 4 models but did not satisfy the
complete roadmap exit criterion. The audit found and corrected these material
gaps:

- Policy handlers used a nonexistent session attribute instead of the framework
  unit of work, and PostgreSQL upserts used the generic SQLAlchemy insert.
- Policy lacked company scope, deterministic ABAC, record ownership/scope
  policies, explicit support access, safe wildcard boundaries, and fail-closed
  field-policy evaluation. Preventative SoD was advisory rather than enforced at
  assignment, and delegation did not prove the delegator held the role.
- Phase 4 handlers did not consistently reject tenant-context mismatches.
- Public policy, audit, retention, and export/delete contracts were not
  registered. Declared domain events were not emitted.
- Audit evidence was mutable, its checksum omitted required evidence fields, and
  concurrent appends were not serialized per tenant.
- Governance export/anonymization hooks were protocols without a deterministic
  registry, and lifecycle events were not emitted.
- Module manifests and Python package dependencies omitted cross-owner
  dependencies used by the migration graph.
- Phase 4 schemas created RLS policies but did not grant the application role
  schema/table access, leaving the modules unusable through the runtime role.

The correction adds deterministic authorization for tenant, company, legal
entity, operating-site, and business-unit scope; record and field policy; ABAC;
approval limits; preventative SoD; bounded delegation; and tenant-approved,
time-limited support access. Permission matching accepts exact permissions and
resource-scoped wildcards only. Explicit policies fail closed.

Audit records now use versioned canonical checksums that retain actor, tenant,
scope, action, resource, before/after evidence, correlation, trace, decision
metadata, status, and the previous checksum. Tenant-scoped advisory locking
serializes chain appends. The runtime role has `SELECT`/`INSERT` only, and a
database trigger rejects historical `UPDATE` and `DELETE` operations.

Governance now exposes ordered export/anonymization hooks and emits retention,
legal-hold, and consent lifecycle events. Active legal holds block purge;
retention windows and consent expiry/revocation remain authoritative.

No Phase 5, UI Foundation, Metadata, Studio, or Dynamic UI implementation was
introduced.

## Additive migrations

Semantic database corrections are isolated in new revisions:

- `policy_0002` follows `policy_0001`: tenant-role integrity, scope/window
  constraints, record policies, support grants, RLS, and runtime grants.
- `audit_0002` follows `audit_0001`: integrity-chain fields, immutable trigger,
  and append-only runtime grants.
- `gov_0002` follows `gov_0001`: tenant-isolated runtime access grants.

The complete terminal heads are:

```text
audit_0002
gov_0002
policy_0002
proof_0003
```

Module and wheel dependencies agree: Policy depends on Party, Audit depends on
Policy, and Data Governance depends on Audit and Policy. Cross-owner migration
parents are declared and the installed graph matches the build graph and stored
fingerprints.

## Local certification

Verification used the pinned Python 3.13 development image and Compose services.

| Gate | Result |
| --- | --- |
| Ruff format | PASS; 162 files formatted |
| Ruff lint | PASS |
| mypy | PASS; 204 source files |
| Pyright | PASS; zero errors and warnings |
| Phase 4 unit tests | PASS; 13 tests |
| Full unit suite | PASS; 161 tests |
| Whole-suite collection | PASS; 225 tests |
| PostgreSQL/provider integration | PASS; 51 tests |
| External-module conformance | PASS; 13 tests |
| Installed-wheel migration smoke | PASS |
| Development image | PASS |
| Production image | PASS |
| Migration-smoke image | PASS |
| Production-derived upgrade/downgrade/replay | PASS |
| `git diff --check` | PASS |

PostgreSQL coverage verifies all 14 tenant-owned Phase 4 tables use enabled and
forced RLS, cross-tenant reads are empty, the runtime role can use Policy and
Governance storage, and audit update/delete privileges are absent. It also
exercises retention eligibility, legal-hold placement/release, active and revoked
consent, and the full additive migration graph.

Phase 4 remains unfrozen until PR CI and the independent post-merge `main` CI are
green and the final read-only roadmap audit passes. The historical
`v0.4.0-phase4` tag remains untouched; after certification, the authoritative
corrective checkpoint is `v0.4.1-phase4`.
