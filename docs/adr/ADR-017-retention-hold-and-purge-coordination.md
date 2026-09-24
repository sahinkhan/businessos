# ADR-017: Retention, Legal Hold, and Transaction-Bound Purge

Status: ACCEPTED

Decision date: 2026-09-24

Approving roles required: Architecture Maintainer; Security Maintainer; Data Governance Owning Domain Maintainer; SDK/Contract Maintainer; Migration Safety Reviewer; Release Maintainer; each affected Data Owning Domain Maintainer for its purge-facts/operation contract

Approval pull request: [#27](https://github.com/sahinkhan/businessos/pull/27) — MERGED as `c732c66b8cba83b2dc896c069f78b3766d4993dd`

Approved semantic proposal SHA: `3fd1e2b34e727da6297f2c1346d53174e3d41d49`

Final acceptance candidate SHA: `fcbc4b3fc7762652bad1502e07eaedf31e8e69ab`

Proposal owner attestation: [@sahinkhan's exact-proposal attestation](https://github.com/sahinkhan/businessos/pull/27#issuecomment-5808045815) — Solo Maintainer Owner Attestation; independent human review NOT PERFORMED

Review model: SOLO MAINTAINER OWNER ATTESTATION by `@sahinkhan`

Independent human review: NOT PERFORMED

Proposal independent technical/read-only review: PERFORMED — PASS; Critical 0; High 0; Medium 0; Low 0

Proposal exact-head CI: [35956550876](https://github.com/sahinkhan/businessos/actions/runs/35956550876) — PASS

Final owner acceptance attestation: COMPLETE — [@sahinkhan's exact-candidate attestation](https://github.com/sahinkhan/businessos/pull/27#issuecomment-5813217450)

Independent technical/read-only acceptance review: PERFORMED — PASS; Critical 0; High 0; Medium 0; Low 0

Acceptance exact-head CI: [35991783982](https://github.com/sahinkhan/businessos/actions/runs/35991783982) — PASS (`python-quality`, `windows-typing`, `web-quality`)

Accepted main merge SHA: `c732c66b8cba83b2dc896c069f78b3766d4993dd`

Authoritative reconciliation baseline: [main `706bd1d4fffaef92cc32682c404d2c5b224ada28`](https://github.com/sahinkhan/businessos/commit/706bd1d4fffaef92cc32682c404d2c5b224ada28)

Accepted architecture prerequisites: ADR-014 — ACCEPTED / AUTHORITATIVE / EVIDENCE CLEAN; ADR-015 — ACCEPTED / AUTHORITATIVE / EVIDENCE CLEAN; ADR-016 — ACCEPTED / AUTHORITATIVE / EVIDENCE CLEAN; ADR-018 — ACCEPTED / AUTHORITATIVE / EVIDENCE CLEAN. ADR-018's architecture prerequisite is satisfied, but its owner/provider runtime extension is NOT IMPLEMENTED.

Implementation/certification gates carried forward: ADR-014 Policy V2, ADR-015 classification runtime, ADR-016 Audit V2, ADR-018 owner/provider runtime, retention-policy.v2, `RetentionSubjectFactsProvider`/`PurgeSubjectFacts`, purge-authority.v2, destructive-lifecycle.v2, entity/subject lock implementation, legal-hold serialization, v1 compatibility transition, and asynchronous external cleanup are NOT IMPLEMENTED. A new forward Governance migration is NOT CREATED; the dirty-data preflight is NOT EXECUTED. Before any destructive operation, implementation must certify trusted owner facts and exact requested action, one effective policy at the trusted UTC instant, same-UOW authority, tenant isolation, both hold/purge commit orders, and one deterministic combined lock order with ADR-010/011 and ADR-018 provider admission. V1 eligibility remains informational only and legacy destructive hooks cannot bypass v2. Historical `gov_0001`/`gov_0002` are not rewritten. Phases 0–3 remain FINAL PASS / FROZEN with no general reopening.

Formal authority: ACCEPTED / AUTHORITATIVE ON MAIN

Supersedes: None

Superseded by: None

## Context

`foundation.governance.retention-policy.v1` exposes
`CheckPurgeEligibilityQuery`, whose `record_age_days` comes from the caller
and whose Boolean result can be reused after legal-hold state changes. The
check occurs outside the owning deletion transaction. Several retention
policies can match one entity type without an authoritative winner. This
permits a stale purge decision and ambiguous retention. The full-system
roadmap requires retention and legal holds before later business, health,
privacy, and data-governance workloads depend on deletion.

## Options considered

| Model | Assessment |
| --- | --- |
| One effective policy per tenant/resource class/instant | Deterministic, auditable meaning; explicit future transitions. Chosen. |
| Multiple with precedence | Needs a global precedence language and can quietly weaken a higher obligation. |
| Most restrictive wins | Safe-looking but ambiguous when expiry actions differ or legal regimes conflict; cannot replace owner/legal classification. |

## Proposed decision

Data Governance owns one effective retention policy for a trusted tenant,
qualified resource/entity type, and retention category at a given instant.
The category is an explicit owner-provided dimension, not a caller-selected
override; a record resolves to exactly one category. Policy validity is
`[valid_from, valid_until)` in UTC, with a nullable unbounded end. A future
policy cannot authorize today's purge; an expired policy cannot silently
continue. Zero or multiple effective policies deny destructive purge and
produce a bounded diagnostic. Policy creation/update rejects overlapping
intervals for the same tenant/resource/category under a database exclusion
constraint or equivalent serialized invariant. A read-only dirty-data
preflight must identify existing overlaps and missing categories with record
identifiers; it fails the migration until owners resolve them. No automatic
winner, deletion, or shortening of an existing obligation is allowed.

The public `RetentionSubjectKey` identifies trusted tenant, canonical owner
module/resource namespace, entity/resource type, and stable record ID **before**
retention category is known. Owner identity and facts-provider registration
are verified through the neutral canonical resource ownership boundary
proposed in ADR-018, **subject to acceptance of ADR-018**, not caller input
or the frozen generic provider registry alone. The record-owning module implements the typed public
`RetentionSubjectFactsProvider`/`PurgeSubjectFacts` port. Within the active
coordinator unit of work and under an owner-record lock or equivalent concurrency
protection, it supplies trusted tenant/key, aware UTC `retention_anchor_at`,
current category, lifecycle state, and supported delete/anonymize/archive
mode. Data Governance does not privately read owner tables; caller-supplied
`record_age_days` is never authority. Missing, mismatched, or stale owner
facts deny.

For v2's existing integer `retention_period_days`, a day is exactly 24
elapsed hours. `eligible_at = retention_anchor_at +
retention_period_days * 24 hours`; purge becomes time-eligible only when the
trusted UTC decision instant is **at or after** `eligible_at`. All instants
are aware UTC. This fixes the boundary independently of local calendar dates,
timezones, daylight-saving changes, and leap days. Jurisdiction-specific
calendar-period retention requires an additive/versioned semantic extension,
not reinterpretation of v2. Unknown anchor or policy denies.

The destructive lifecycle request enters a Data Governance-owned coordinator,
not a universal owner command calling Governance. Subject to acceptance of
ADR-018, Governance resolves and admits the canonical owner's neutral
operation provider. This avoids Party -> Governance -> Policy -> Party: Party
implements the lower neutral owner contract without importing Governance.
The coordinator invokes `foundation.governance.purge-authority.v2` in the
**same framework unit of work/transaction** as archive, anonymization, or
purge. The authority port and owner provider use the restricted active
`HandlerTransaction`, not nested ordinary command dispatch, which would open
another unit of work. The owner provider locks its own record and returns
current facts; Governance resolves current policy and holds and authorizes
only the requested operation for that subject and transaction. The owner
validates its own lifecycle/invariants and executes exactly that operation
before the outer commit. Governance does not issue SQL against owner-private
tables. No Boolean or decision token is reusable in another transaction. A
worker/job carries only the
subject key and operation/request identity; at execution it reruns full v2
coordination. Long external object-store or search cleanup uses the
transactional outbox after authoritative state commits, with truthful
pending/completed status and retryable failure.

The requested operation uses the current `ExpiryAction` values `archive`,
`anonymize`, and `purge` (`purge` is the destructive delete action). Time
eligibility is necessary but does not authorize another action. The locked
effective policy's `action_on_expiry` **must equal** the requested operation;
an approved versioned policy compatibility/substitution rule would have to be
explicit and separately reviewed. There is no implicit escalation:
`archive` policy plus `purge` request denies, as does `anonymize` policy plus
`purge` request. A `purge` policy plus `purge` request continues only after
all other eligibility checks. The owner provider must independently confirm
that the exact requested action is supported for the locked record's current
lifecycle. Both policy permission **and** owner capability are required;
either mismatch denies.

### Legal-hold serialization

One mandatory lock order governs participating paths:

1. A category-independent entity-scope gate keyed by trusted tenant, owner,
   and entity type. Purges, record hold changes, and owner fact/category
   changes take its shared transaction advisory form; an entity-wide hold placement/release takes
   its exclusive form. Where shared advisory locking is unavailable, all
   take the exclusive form. The gate exists without a hold row and prevents
   an entity-wide/category-free phantom hold from racing any category purge.
2. A category-independent transaction advisory subject lock derived only
   from `RetentionSubjectKey`. Every destructive attempt, record hold
   placement/release, and change to owner category, retention anchor, or
   destruction-relevant lifecycle facts takes it before owner-row work.
3. The owner locks the record or obtains equivalent serialization and
   returns current facts, including category. It must re-read after any wait;
   category cannot change concurrently because category mutators take the
   same subject lock. Owner mutation never starts from a stale category.
4. After category is known, the authority takes the applicable
   tenant/resource/category policy-scope coordination lock, then locks or
   reads current policy and applicable hold/destructive-state rows. Policy
   create/update/deactivate takes that same policy-scope lock, so policy
   replacement and purge have a serial order. Policy-only operations do not
   acquire subject locks after the policy lock.

An operation needing only a later lock must never acquire an earlier lock
afterward. The implementation audit must verify the actual database lock
graph, including ADR-010/011 Policy locks if a protected command uses both.
No category is used to select the subject or entity gate. Entity-wide holds
are explicit `ALL`/null-category holds and apply regardless of a record's
category; applicable category-specific holds are checked additionally.
An entity-wide hold operation uses the exclusive gate before changing its
hold rows. A record hold checks the locked owner record so it cannot claim
protection of an already purged subject. Hold-first commit makes purge wait
then deny; purge-first commit makes a later hold reject or record an explicit
post-purge nonprotective outcome. Release takes the same gates and only a
committed release removes protection. Two purgers of one subject serialize
on the subject lock; the second re-reads owner state and returns an explicit
already removed/anonymized, not-found, or documented idempotent result rather
than executing destruction twice. Rollback releases locks and preserves the
pre-transaction authority state. Tenant is present in every lock key,
predicate, RLS check, and evidence record; another tenant's hold cannot
affect eligibility. Deadlock, timeout, retry, and cross-tenant tests are
required. No lock spans asynchronous external cleanup.

### V1 transition and migration

`foundation.governance.retention-policy.v2` publishes the effective-policy
read/write semantics; `foundation.governance.purge-authority.v2` publishes
the transaction-scoped destructive authority. A distinct versioned
`foundation.governance.destructive-lifecycle.v2` contract makes the owner
mutation path explicit: Governance coordinates authority and locks, while
the record-owning module performs delete/anonymize/archive against its own
data in that same transaction through the ADR-018 neutral owner-operation boundary. Governance
never directly deletes another module's rows. The existing
`retention-policy.v1`/`CheckPurgeEligibilityQuery` may remain only as a
deprecated **informational** check. Its response cannot authorize deletion,
anonymization, archival, or a worker job; destructive consumers must move to
v2. The existing `foundation.governance.export-delete-hooks.v1` is split by
effect: non-destructive export may remain during its ordinary compatibility
window, but `DataGovernanceHooks.anonymize_subject` and any delete hook
cannot execute directly as destructive authority after v2 activation. A
v1-shaped compatibility adapter may exist only if it enters the full v2
Governance-owned coordinator, including the ADR-018 owner provider, in one
framework unit of work; where that cannot be guaranteed, the destructive v1 operation is
disabled and consumers migrate to `destructive-lifecycle.v2`. Neither the
old hook result nor an old `CheckPurgeEligibility` Boolean can bypass v2.
If an existing v1 route is used as destructive authority and cannot be
safely constrained, Security and Release Maintainers must approve an urgent
security/legal exception to its support window, naming affected consumers,
mitigation, notice, and expiry. Otherwise v1 remains supported through at
least the next Stable platform minor after v2 availability; removal also
requires tested migration, owner/SDK/Architecture approval, and release
notes per [RELEASES.md](../governance/RELEASES.md). This proposal grants no
exception and sets no release number.

A new forward Governance revision (next available `gov_` slot) adds policy
effective intervals, category identity, exclusion/uniqueness enforcement,
an explicit hold `ALL`/category representation, and any coordination indexes
or RLS changes. Existing category-free holds migrate to `ALL` without losing
scope. It must preserve all existing policy, hold, and consent rows and
meanings, run the overlap/category preflight, and use
expand/contract conversion with an explicit owner-approved mapping. It does
not rewrite `gov_0001` or `gov_0002`. Subject to acceptance of companion
ADR-016, Data Governance may use Audit-owned `AuditAppenderV2` in the
coordinator's current unit of work because Governance already depends on
Audit. The owner provider does not import Audit. For a different permitted
entry path without an Audit dependency, its versioned outbox event is
transaction-bound evidence and Audit materializes later; that path must not
claim an Audit row was committed with the owner action. Audit records
the decision but grants no purge authority, and Audit never depends on
Governance.

## Consequences and impact

Deletion waits for a serially valid hold decision and an unambiguous current
policy. Governance owns policy/hold data and the public coordination port;
the record owner owns facts and its operation provider/mutation. The generic kernel
still owns unit-of-work and transaction machinery. Later document, HR,
healthcare, localization, privacy, and marketplace modules can participate
without direct Governance-table access or reverse frozen-layer dependencies.
Some legacy data may require reviewed cleanup before migration. Tenant
isolation and exact retention evidence become testable; asynchronous cleanup
requires completion monitoring and truthful audit status.

## Approval and implementation gates

The listed roles are the union of architecture, tenant/security, public
contract, migration/data lifecycle, affected owner, and release rows in
[ADR-GOVERNANCE.md](../governance/ADR-GOVERNANCE.md) and
[MAINTAINERS.md](../governance/MAINTAINERS.md). This PROPOSED decision
authorizes no Phase 4 remediation. Formal acceptance requires exact-revision
role evidence, exact-head CI, independent read-only technical audit with zero
Critical/High findings, and governance acceptance. Implementation must test
overlap preflight, half-open boundaries, owner-fact forgery, both hold/purge
commit orders, missing-row race, rollback, cross-tenant holds, worker retry,
v1 informational-only behavior, and downstream compatibility.
