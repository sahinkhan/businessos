# ADR-009 Revision 3 audit and validation record

Date: 2026-09-07
Status: documentation-only proposal; ADR-009 remains Proposed.
Revision 3 base: `6ec71db0ba30760245bfaae4ca0797fd73ba4a67`.
Revision branch: `codex/adr-009-revision-3`.
Preserved branches: `codex/adr-009-revision-2` at the Revision 3 base and
`codex/adr-009-security-review` at
`ef8ccc8bac25147200d2f8a69d9cf638a0b128f0`.

## Scope and Revision 2 audit disposition

The detached worktree was clean and its HEAD matched the exact Revision 3 base
before the requested branch was created. The preserved WIP and Phase 2 branches
were not inspected, used or modified. Revision 3 changes only ADR-009 and this
validation record. Runtime code, the deliberately red regression, migrations, CI
jobs and infrastructure are unchanged. There was no PostgreSQL execution,
provisioning, database/volume removal, runtime correction, ADR acceptance, merge
or Phase 2 work.

The following audit dispositions of the frozen Revision 2 commit were supplied by
the requesting task. They are not new independently executed findings:

| Revision 2 auditor | Verdict | Retained requirements | Reproduction assessment |
| --- | --- | --- | --- |
| Astra Extra High (`gpt-6-astra`, xhigh) | APPROVE ADR | No remaining P0/P1/P2 | `session_user` architecture viable; recorded PostgreSQL 17.11 deliberately red reproduction valid; no independent rerun |
| GPT-5.6 Sol Ultra (`gpt-5.6-sol`, ultra) | REVISE ADR | Two P1, three P2 and two nonblocking precision corrections | `session_user` architecture viable; recorded PostgreSQL 17.11 deliberately red reproduction valid; no independent rerun |

The combined disposition was **REVISE ADR**. Astra approval does not override
Sol's stricter retained requirements. Revision 3 preserves the no-argument
`session_user` resolver architecture and addresses the seven retained items below.

## Revision 3 finding and acceptance traceability

All clause links refer to
[ADR-009](ADR-009-trusted-database-tenant-binding.md). Acceptance IDs identify
future implementation/certification tests; none was executed in Revision 3.

| Retained finding or correction | Priority | Amendment clause | Required future acceptance evidence |
| --- | --- | --- | --- |
| PostgreSQL large objects | P1 | [R3-1](ADR-009-trusted-database-tenant-binding.md#r3-1--certified-databases-contain-no-postgresql-large-objects-p1), refining R2-4 and R2-8 | AT-R3-1: zero-object provisioning/activation/backup/restore checks; adversarial other-role owner; quarantine; S3 conversion; no temporary broad backup grants |
| `lo_compat_privileges=off` | P1 | [R3-2](ADR-009-trusted-database-tenant-binding.md#r3-2--lo_compat_privileges-must-remain-off-p1) | AT-R3-2: system/database/role/session/failover/restore fixtures; connect/checkout/readiness/drift quarantine and clean-generation repair |
| Resolver upgrade authority and atomic cutover | P2 | [R3-3](ADR-009-trusted-database-tenant-binding.md#r3-3--fenced-forward-only-resolver-upgrades-p2), refining R2-6 and R2-7 | AT-R3-3: runtime/owner replacement SQLSTATE `42501`; fenced version creation; atomic policy cutover; post-upgrade definition/owner/ACL/dependency validation |
| Sequence backup semantics | P2 | [R3-4](ADR-009-trusted-database-tenant-binding.md#r3-4--sequence-consistent-backup-and-collision-free-restore-p2), refining R2-4 | AT-R3-4: physical+WAL recovery; fenced logical backup; concurrent `nextval`/`setval`; cached sequences; separately verified frontier; collision-free restore with harmless gaps |
| Quantitative load gate | P2 | [R3-5](ADR-009-trusted-database-tenant-binding.md#r3-5--quantitative-mandatory-load-gate-p2), refining R2-9 | AT-R3-5: exact offered rates/durations/concurrency/distribution/operations; admission, completion, throughput, latency, fairness, starvation/wait, worker, binding/readiness and nearly-all-rejection failure thresholds; numeric release evidence |
| PostgreSQL 17 prepared-transaction SQLSTATE | Precision | [R3-6](ADR-009-trusted-database-tenant-binding.md#r3-6--postgresql-17-disabled-prepared-transaction-sqlstate-precision), correcting R2-5 | AT-R3-6: exact SQLSTATE `55000`, rollback and empty prepared-transaction catalog on every certified PostgreSQL 17 minor |
| LISTEN/NOTIFY isolation limit | Precision | [R3-7](ADR-009-trusted-database-tenant-binding.md#r3-7--listennotify-boundary-and-prohibition-precision), correcting R2-8 | AT-R3-7: supported-surface prohibition, expected raw cross-role notification observation, no invented channel ACL, and separate database/role certification for any approved use |

## Preserved R2 amendments and earlier safeguards

Revision 3 supplements rather than replaces all nine R2 amendment families and the
preexisting eight numbered certification families.

| Preserved family | Unchanged requirement | Future coverage retained or added |
| --- | --- | --- |
| R2-1 | Invocation matrix; atomic inbox/state/outgoing work; no module transaction or acknowledgement authority | AT-R2-1 |
| R2-2 | External password-ineligible authentication; no password fallback; bounded drift quarantine and repair | AT-R2-2 and AT-R3-2 |
| R2-3 | No-argument full deployment-binding attestation anchored outside the database; clone/failover fencing | AT-R2-3 and AT-R3-2/3/5 |
| R2-4 | Exact separated migrator, maintenance, publisher, logical-backup and physical-backup profiles; fenced operations and tested restore | AT-R2-4 and AT-R3-1/4 |
| R2-5 | `max_prepared_transactions=0`, empty residue and quarantine | AT-R2-5 and AT-R3-6 |
| R2-6 | Global routine PUBLIC default revoke, existing-ACL repair and atomic protected-routine creation | AT-R2-6 and AT-R3-3 |
| R2-7 | Distinct owners; resolver owner USAGE/no CREATE; exact SELECT/EXECUTE; no runtime owner path | AT-R2-7 and AT-R3-3 |
| R2-8 | Honest non-RLS boundary and closed SDK; unsafe surface inventory | AT-R2-8 and AT-R3-1/7 |
| R2-9 | Mandatory non-skippable PostgreSQL certification, two tenant logins, MERGE/RETURNING matrix and bounded connection envelope | AT-R2-9 and AT-R3-5 |

The following architecture safeguards also remain unchanged:

| Safeguard | ADR location and future coverage |
| --- | --- |
| Dedicated, database-per-tenant and certified shared-schema modes; immutable-to-runtime `session_user`; no GUC/current-user identity | Deployment modes, protected resolver and R2-3; existing certification 1/2/5; AT-R2-2/3/7/9 |
| FORCE RLS with restrictive USING/WITH CHECK, explicit permissive policies, tenant-aware integrity and complete role topology including INHERIT/SET/ADMIN | Roles/grants/policies; existing 2/3/4/8; AT-R2-2/4/6/7/9 |
| Bounded pools, instance-global budget, fair backpressure, rotation and retirement | Connection pools and R2-9; existing 5/7/8; AT-R2-2/3/5/9 and AT-R3-5 |
| Closed SDK epoch 2 with deterministic rejection and no legacy escape or mixed epoch | Replacement SDK; existing 4/7/8; AT-R2-1/8 |
| Forward-only retained-data transition, secure rollback/restore and no insecure live downgrade | Provisioning/transition/recovery; existing 7/8; AT-R2-3/4/5 and AT-R3-1/3/4 |
| Tenant propagation through jobs/events/cache/storage/search/audit plus authorization, production composition and observability | SDK/certification; existing 4/6/8; AT-R2-1/2/4/8/9 and AT-R3-5/7 |

## Historical evidence (not Revision 3 execution)

The ADR's historical section records the prior
`bos-review-118:development` image identity and read-only `/app`, network-none,
read-only-root, `/tmp` tmpfs workflow. It records regression AST/type checks, 111
unit tests and the decisive PostgreSQL 17.11 failure after GUC mutation while
`session_user` remained unchanged. Those facts are historical evidence only.
Revision 3 does not rerun PostgreSQL, execute future acceptance tests or use image
source in place of checkout runtime.

## Executed Revision 3 validation

The existing validation image resolved to the required
`sha256:86f1ab0fe683967601c11df31dc0268f974cf0092852b098d753d12fd83e6422`.
It mounted this exact checkout read-only at `/app` with `--network none`, a
read-only root, `/tmp` tmpfs, `PYTHONDONTWRITEBYTECODE=1` and
`PYTHONPATH=/app/platform/src:/app/examples/proof_module/src`. Results:

- Documentation scope/structure check: passed. The diff contains only the two
  permitted ADR/validation files; ADR status remains Proposed; R3 has exactly
  seven amendment headings, seven `AT-R3-*` families and seven traceability rows.
- Relative Markdown link inventory: the only new local target is the existing
  ADR-009 file; passed.
- `ast.parse` on
  `tests/integration/test_release_hardening_tenant_binding.py`: passed.
- `mypy --cache-dir=/tmp/mypy tests/integration/test_release_hardening_tenant_binding.py`:
  passed, no issues in one source file.
- `pytest -q -p no:cacheprovider tests/unit`: passed, 111 tests.
- `git diff --check`: passed after the final documentation update.

No PostgreSQL regression, infrastructure provisioning, future acceptance test,
full integration/conformance suite, load test or restore drill ran. The decisive
historical regression remains deliberately red and the runtime vulnerability
remains unfixed.

## Freeze and independent audits

After the limited checks pass, commit only the two permitted documentation files,
push only `codex/adr-009-revision-3`, verify its exact remote HEAD and freeze that
commit. Run the requested GPT-5.6 Sol Ultra closure audit and Astra Extra High
delta/regression audit read-only against that exact SHA. Their reports do not amend
the frozen commit automatically.

Even two **APPROVE ADR** verdicts make the exact commit eligible only for the
user's separate explicit approval. They do not mark ADR-009 Accepted, authorize
runtime/migration/CI/infrastructure work, resume Phase 1 correction or Phase 2,
permit WIP use, or merge/change main, tags or frozen branches.
