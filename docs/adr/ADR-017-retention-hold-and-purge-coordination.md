# ADR-017: Retention, Legal Hold, and Transaction-Bound Purge

Status: PROPOSED

Decision date: Pending formal acceptance

Approving roles required: Architecture Maintainer; Security Maintainer; Data Governance Owning Domain Maintainer; SDK/Contract Maintainer; Migration Safety Reviewer; Release Maintainer; each affected Data Owning Domain Maintainer for its purge-facts/operation contract

Approval pull request or commit: Pending

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

The record-owning module implements a versioned public
`RetentionSubjectFactsProvider`/`PurgeSubjectFacts` port. Within its active
unit of work it supplies trusted tenant, stable record locator, creation or
applicable effective date, retention category/classification reference,
current state, and whether delete/anonymize/archive is supported. Data
Governance does not privately query another module's tables. Caller-supplied
`record_age_days` is never authority. Age and eligibility are computed from
owner facts and the trusted current instant using the policy's stated
calendar/instant semantics; the implementation must define date-boundary
tests for timezone and leap-day cases. Unknown owner facts or policy deny.

The destructive owner command invokes
`foundation.governance.purge-authority.v2` in the **same framework unit of
work/transaction** as the delete, anonymization, or archive. The authority
port resolves the current policy and facts, verifies retention elapsed and
no applicable legal hold, and returns a transaction-scoped decision object
valid only in that unit of work. The owner performs the approved action
before that transaction commits. No Boolean or decision token is reusable
in another transaction. Long external object-store or search cleanup uses a
transactional outbox after committed authoritative state; failures remain
retryable and must not falsely claim full erasure.

### Legal-hold serialization

Policy creation/change, entity-wide hold placement/release, record hold
placement/release, and purge all acquire a deterministic tenant/resource/
category **scope** transaction advisory lock. Record-specific operations
then acquire a tenant/resource/category/record lock. They lock relevant
policy/hold rows and finally the owner record in that order. Both advisory
keys exist even when no policy or hold row exists, so a phantom policy or
hold insert cannot race a purge. The scope lock deliberately serializes
destructive decisions with policy changes and entity-wide holds; throughput
must be measured, and a finer protocol needs another reviewed decision.
Hold placement checks the owner record under the same transaction so it
cannot claim to protect a record already purged. If hold commits first,
purge waits and denies. If purge
commits first, hold waits and must reject or explicitly record a post-purge
nonprotective outcome; it cannot claim a hold protected a deleted record.
Rollback releases all locks. A tenant is part of every lock key, predicate,
RLS check, and evidence record; another tenant's hold never controls the
decision. Deadlock, timeout, and retried transaction behavior must be
tested. No lock is held across asynchronous external cleanup.

### V1 transition and migration

`foundation.governance.retention-policy.v2` publishes the effective-policy
read/write semantics; `foundation.governance.purge-authority.v2` publishes
the transaction-scoped destructive authority. The existing
`retention-policy.v1`/`CheckPurgeEligibilityQuery` may remain only as a
deprecated **informational** check. Its response cannot authorize deletion,
anonymization, archival, or a worker job; destructive consumers must move to
v2. If an existing v1 route is used as destructive authority and cannot be
safely constrained, Security and Release Maintainers must approve an urgent
security/legal exception to its support window, naming affected consumers,
mitigation, notice, and expiry. Otherwise v1 remains supported through at
least the next Stable platform minor after v2 availability; removal also
requires tested migration, owner/SDK/Architecture approval, and release
notes per [RELEASES.md](../governance/RELEASES.md). This proposal grants no
exception and sets no release number.

A new forward Governance revision (next available `gov_` slot) adds policy
effective intervals, category identity, exclusion/uniqueness enforcement,
and any coordination indexes or RLS changes. It must preserve all existing
policy/hold rows and meanings, run the overlap/category preflight, and use
expand/contract conversion with an explicit owner-approved mapping. It does
not rewrite `gov_0001` or `gov_0002`. Policy/hold changes and destructive
actions emit trusted audit evidence through the v2 facade proposed by
ADR-016 in the same transaction;
Audit records the decision but does not grant purge authority.

## Consequences and impact

Deletion waits for a serially valid hold decision and an unambiguous current
policy. Governance owns policy/hold data and the public coordination port;
the record owner owns facts and its destructive command. The generic kernel
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
