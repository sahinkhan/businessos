# ADR-009 Revision 2 audit and validation record

Date: 2026-09-07
Status: documentation-only proposal; ADR-009 remains Proposed.
Audited base: `ef8ccc8bac25147200d2f8a69d9cf638a0b128f0`.
Revision branch: `codex/adr-009-revision-2`.
Preserved review branch: `codex/adr-009-security-review` at the audited base.

## Scope and prior verdicts

The clean detached worktree HEAD matched the exact audited base before creating
the requested branch. No preserved WIP or Phase 2 branch/source was used, inspected
or modified. Changes are limited to ADR-009 and this audit/validation document.
The regression file, runtime, migration sources, CI and infrastructure are unchanged.
There was no PostgreSQL execution or role/database/volume provisioning in Revision 2.
Existing vulnerability remains deliberately unfixed, decisive regression remains
red by historical evidence, Phase 1 correction incomplete and Phase 2 frozen.

The prior audit dispositions below are supplied by the requesting task's audit
record, not represented as new independently executed findings:

| Auditor of ef8ccc8 | Verdict | Required amendments | Reproduction assessment |
| --- | --- | --- | --- |
| Astra Extra High | REVISE ADR | One P2 subscriber capability inconsistency (R2-1) | Valid recorded PostgreSQL 17.11 deliberately red demonstration; no independent test rerun |
| GPT-5.6 Sol Ultra | REVISE ADR | Five P1 (R2-2 through R2-6), three P2 (R2-7 through R2-9) | Valid recorded PostgreSQL 17.11 deliberately red demonstration; no independent test rerun |

Neither verdict was REJECT ADR; both found the session_user design viable.
These were proposal/reproduction/acceptance-criteria audits, not Phase 1 release
certification. No finding or approval accepts the ADR on behalf of the user.

## Requirement traceability

All clause links refer to [ADR-009](ADR-009-trusted-database-tenant-binding.md).
Acceptance IDs name required future implementation tests; none ran in this task.

| Amendment | Priority / source | ADR clause | Future acceptance family |
| --- | --- | --- | --- |
| Invocation-specific capabilities; subscriber outgoing work and proof projection conversion | P2 / Astra | [R2-1](ADR-009-trusted-database-tenant-binding.md#r2-1--invocation-capability-matrix-p2) and replacement SDK table | AT-R2-1: five invocation rows, inbox/state/outgoing atomicity, downstream retry/order/crash behavior |
| Password-ineligible login, no fallback, drift/quarantine/repair | P1 / Sol | [R2-2](ADR-009-trusted-database-tenant-binding.md#r2-2--password-ineligible-authentication-and-drift-p1) and role topology | AT-R2-2: self-password/default mutation, every authentication path, catalog authority, generation and readiness checks |
| Full binding with external expectations and clone fencing | P1 / Sol | [R2-3](ADR-009-trusted-database-tenant-binding.md#r2-3--full-deployment-binding-attestation-p1) and all deployment modes | AT-R2-3: every tuple field, connect/checkout, copied database, split brain, restore identity and stale generations |
| Isolated maintenance/migration/backfill/backup authority | P1 / Sol | [R2-4](ADR-009-trusted-database-tenant-binding.md#r2-4--isolated-operational-authority-p1) and transition/recovery | AT-R2-4: exact privilege matrix, FORCE RLS operation scope, fencing, interruption, counts, logical/physical completeness |
| Disable prepared transactions and detect residue | P1 / Sol | [R2-5](ADR-009-trusted-database-tenant-binding.md#r2-5--no-prepared-transactions-p1) | AT-R2-5: zero setting, denied prepare/no residue, retirement, restore and bad-config quarantine |
| Global routine defaults and existing ACL repair | P1 / Sol | [R2-6](ADR-009-trusted-database-tenant-binding.md#r2-6--global-routine-privilege-defaults-p1) and resolver creation | AT-R2-6: direct/SET ROLE creation, transfer, replacement, overloads, atomic PUBLIC revoke and catalog defaults |
| Exact resolver owner permissions | P2 / Sol | [R2-7](ADR-009-trusted-database-tenant-binding.md#r2-7--resolver-owner-access-p2) and resolver/role topology | AT-R2-7: USAGE without CREATE, distinct owners, exact mapping/function grants and positive/negative resolution |
| Explicit non-RLS boundary | P2 / Sol | [R2-8](ADR-009-trusted-database-tenant-binding.md#r2-8--non-rls-channels-and-honest-isolation-scope-p2) and threat model/closed SDK grammar | AT-R2-8: notification residual limits, no sensitive channels, large-object and unsafe routine/view exposure |
| Mandatory execution, PostgreSQL 17 MERGE/RETURNING and proposed envelope | P2 / Sol | [R2-9](ADR-009-trusted-database-tenant-binding.md#r2-9--mandatory-execution-and-proposed-scale-envelope-p2) and certification | AT-R2-9: two physical tenant pools, missing-config/skip/xfail failures and numeric load envelope |

## Preserved requirements and acceptance coverage

The preexisting eight numbered certification families remain mandatory. R2 tests
supplement them and do not replace release/conformance gates after implementation.

| Preserved requirement | ADR location | Future certification coverage |
| --- | --- | --- |
| Dedicated, database-per-tenant and optional shared schema; immutable-to-runtime session_user; no current_user/GUC identity | Deployment modes, resolver, R2-3 | Existing 1, 2, 5; AT-R2-2/3/7/9 |
| FORCE RLS, restrictive USING/WITH CHECK, permissive policies, module ownership and tenant-aware constraints | Roles/grants/policies | Existing 2, 3, 4; AT-R2-4/6/7/8/9 |
| No direct/transitive privilege escape; complete INHERIT/SET/ADMIN safeguards | Roles/grants/policies | Existing 2, 8; AT-R2-2/4/6/7 |
| Bounded pools/global budget, fair backpressure, eviction, failover, rotation and retirement | Connection pools; R2-2/3/5/9 | Existing 5, 7, 8; AT-R2-2/3/5/9 |
| Atomic transactions/outbox/inbox, no module transaction authority | SDK; R2-1 | Existing 4, 6, 8; AT-R2-1/5 |
| Closed SDK, deterministic epoch 2 with no legacy aliases/escape hatch or mixed epochs | Replacement SDK/compatibility | Existing 4, 7, 8; AT-R2-1/8 |
| Retained-data forward-only transition, inventory, secure restore/rollback, no insecure live downgrade | Provisioning/transition/recovery | Existing 7, 8; AT-R2-3/4/5 |
| Cache/storage/jobs/search/audit tenant propagation, authorization, installed proof, production composition and observability | SDK and certification | Existing 4, 6, 8; AT-R2-1/2/4/8/9 |

## Historical evidence at ef8ccc8 (not rerun here)

The committed ADR historical section records Ruff formatting/lint, strict mypy and
Pyright passing; 111 unit tests passing; PostgreSQL 17.11 failing at the final
A-only visibility assertion after successful GUC mutation/readback and unchanged
session_user checks. That red result demonstrated B visibility under A's invocation.
Neither prior auditor independently executed these tests. The older Batch A
validation file is also historical; it is unchanged in Revision 2.

## Executed Revision 2 validation

The existing image `bos-review-118:development` was inspected as
`sha256:86f1ab0fe683967601c11df31dc0268f974cf0092852b098d753d12fd83e6422`.
The validation container used `--network none --read-only --tmpfs /tmp`, exact
checkout mounted read-only at `/app`, `PYTHONDONTWRITEBYTECODE=1`, and
`PYTHONPATH=/app/platform/src:/app/examples/proof_module/src`. No image snapshot or
preserved WIP source supplied the BusinessOS runtime. Only these allowed checks ran:

- Python `ast.parse` on the existing regression source: passed (syntax only).
- `mypy --cache-dir=/tmp/mypy tests/integration/test_release_hardening_tenant_binding.py`:
  passed, one target source file, strict repository settings.
- `pytest -q -p no:cacheprovider tests/unit`: **111 passed**.
- Documentation structural/format check: balanced fenced blocks, table columns,
  no trailing whitespace and valid local document/heading links; passed.
- `git diff --check` and staged `git diff --cached --check`: passed before commit.

No new PostgreSQL, integration, tenant-isolation, conformance, load, restore or CI
certification test ran. No new full Ruff/Pyright run is claimed. Numeric connection,
pool, latency and scale envelopes in R2-9 are proposed certification requirements,
not invented measurements. No migration or implemented contract changed; the
proposed epoch-2 SDK and database authority contracts remain pending user approval.

## Freeze and re-audit protocol

The public destination was reverified as `https://github.com/sahinkhan/businessos`,
viewer permission ADMIN; the remote security-review branch still matched ef8ccc8
and the requested Revision 2 branch did not exist before this push.
Commit only the two documentation files and push only `codex/adr-009-revision-2`.
Verify remote HEAD equals local commit and preserve the original review branch.
The resulting exact SHA is recorded in task output and passed to both auditors;
this avoids a self-referential commit identifier in its own content.

After freezing, request read-only architecture re-audit with gpt-6-astra/xhigh and
PostgreSQL security re-audit with gpt-5.6-sol/ultra. Both assess only design safety
and operational feasibility, validity of existing vulnerability reproduction, and
sufficiency of future acceptance criteria. No release audit or PostgreSQL execution.
Full verdicts are reported in task output against the frozen SHA; do not amend
this commit afterward to insert verdicts or fix findings.

APPROVE ADR means eligible for explicit user implementation approval, not Accepted.
REVISE ADR means amendments and re-audit; REJECT ADR means another tenant-binding
design is needed. The stricter combined requirements govern disagreement. Even two
APPROVE verdicts do not authorize ADR acceptance, implementation, Phase 2, WIP use
or main merge. All of those remain stopped pending the user's separate decision.
