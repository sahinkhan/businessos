# Phase 4 preventative segregation-of-duties closeout

Status: locally certified implementation candidate; hosted exact-head CI and
owner attestation pending.

Base main: `ac3b73e505f4165c2d94da8f2d9631dc089ed730`. Phase 4 remains in
CLOSEOUT mode. ADR-017 and ADR-022 are already implemented, certified, and
merged. This batch changes the Policy owning domain's supported mutations;
it does not revise an accepted ADR or introduce a new authorization framework.

## Mutation boundary

Before this batch, `AssignRoleToSubject` checked only direct permissions of
already assigned and candidate roles. `AssignPermissionToRole`,
`CreateDelegation`, and preventative `CreateSoDRule` could commit a conflicting
pair without that check. All four authority-increasing paths now acquire the
existing ADR-010 Policy tenant transaction advisory lock before reading the
authority graph and before inserting. `CreateRole` already uses that lock;
its parent walk now rejects a missing, cyclic, or over-depth hierarchy before
creating a child. Detective rule creation stays non-blocking.

One private Policy projection reads bounded tenant roles, role permissions,
typed assignments, non-revoked delegations, and preventative rules through
the caller's active transaction. It projects the candidate mutation before
writing. Role inheritance follows the parent chain. Delegation source proof
reuses ADR-010/011's typed, same-role, scope, validity-window, and transitive
source helper. Legacy untyped rows cannot add trusted effective permissions.
Delegation source proof reads that same row-bounded graph and uses the same
traversal budget before it projects the candidate delegation.
For a rule without a scope or time field, incompatibility is tenant-wide;
the implementation adds no scope, amount, workflow, or approval syntax.

The projection evaluates current and future validity start boundaries, so a
future effective assignment or delegation cannot silently create a latent
permission pair. It checks only subjects whose effective permission set gains
authority for an existing rule, and all typed subjects for a proposed new
preventative rule. A conflict raises `segregation_of_duties_conflict` with
bounded rule codes and typed subject identifiers. Missing role parents,
cycles, depth beyond 16, more than 256 rows per relevant authority relation,
more than 4096 subject/instant evaluations, or more than 16384 delegation
source traversal steps per projection fail closed with
`authority_unbounded`. The projection is a conservative mutation guard; it
does not itself authorize a Policy V2 request or replace live Identity
membership, owner facts, scope, and record-policy evaluation.

An exact-commit audit found that the initial candidate could insert the
257th row of a bounded relation and then leave subsequent Policy mutations
unable to load that tenant's graph. The remediated projection checks the
post-mutation row count before insertion for roles, role permissions,
assignments, delegations, and preventative rules. `CreateRole` now projects
its new role under the same tenant lock. Focused unit and PostgreSQL tests
prove the 257th row is rejected without a write.

## Concurrency and transaction evidence

PostgreSQL tests hold the exact Policy tenant advisory lock independently and
observe waiting command sessions before releasing it. They exercise
assignment versus permission addition, assignment versus preventative rule,
delegation versus permission addition, delegation versus preventative rule,
two assignments, and parent-role permission addition versus descendant-role
assignment. Each opposing mutation is safe alone; exactly one conflicting
mutation is denied after serialization. Additional tests check rollback leaves
no assignment or rule, lock release after rollback, and a different tenant's
mutation proceeding while the first tenant's lock is held. The existing
ADR-010/011 delegation files and Policy V2 compatibility tests are part of
focused regression evidence.

## Migration and SQL boundary

No persistent schema, index, or data transition is needed. Migration: NONE.
Historical `policy_0001` through `policy_0004` are unchanged.

The accepted Phase 4 contract requires supported Policy mutations to use the
tenant lock and forbids other modules from writing Policy private tables.
The independent direct-SQL review found that `policy_0002` grants the shared
`businessos_app` role same-tenant DML on existing Policy tables. Tenant RLS
does not prevent a trusted first-party handler issuing raw SQL from bypassing
application-level SoD. This candidate therefore claims enforcement for
supported Policy mutations only; it does not claim PostgreSQL-enforced SoD
against arbitrary same-process first-party SQL. ADR-022 approved an exact
protected Governance profile, not a Policy profile. A stronger Policy SQL
boundary would need separate architecture approval.

## Certification evidence

Local certification on the remediated candidate worktree:

- Focused post-remediation SoD tests: 11 unit and 10 PostgreSQL integration
  cases passed. The wider Policy/SoD PostgreSQL set passed 47 tests before
  the bounded-row remediation.
- Full integration: 204 passed in 33m40s, exit 0.
- Full pytest: 750 passed in 35m01s, exit 0.
- Repository CI Ruff format and lint: PASS. Mypy: 336 source files, PASS.
  Pyright: 0 errors, PASS. Phase 0 governance gate: PASS.
- Installed-wheel migration smoke: PASS; installed graph retained
  `policy_0004`; migration replay and current safe downgrade refusal passed.
- Development, production, and migration-smoke images: PASS.
- Existing Phase 0-3 coverage ran within the full integration and pytest
  suites. No separate migration-graph-changing replay is required because
  this batch adds no migration.

Independent read-only remediation preflight: Critical 0, High 0, Medium 0,
Low 0. The first exact-commit audit's one Medium was remediated before this
certification. A new exact-commit audit is required on the new candidate SHA.
Hosted exact-head CI and independent exact-commit audit remain candidate PR
gates. No owner attestation has been posted; no merge is authorized by this
document.
