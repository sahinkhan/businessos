# ADR-011: Transitive Organization Delegation Authority

Status: PROPOSED

Decision date: Not yet applicable

Approving roles required: Architecture Maintainer; Security Maintainer; Policy Maintainer; Organization Maintainer; SDK/Contract Maintainer; Migration Safety Reviewer

Approval pull request or commit: Pending proposal pull request and accountable review

Extends: [ADR-010 — Delegation Action Authority Boundary](ADR-010-delegation-action-authority-boundary.md)

Supersedes: None

Superseded by: None

## Context

The accepted [Organization architecture](../architecture/IDENTITY-ORGANIZATION.md)
requires an authority chain rooted in an effective assignment. Each downstream
delegation is bounded by the chain's scope, actions, and effective period.
ADR-010 adds a Policy-owned action decision to that Organization boundary, but
does not specify how an intermediate recipient uses an Organization delegation
as an action source. In Phase 2 candidate `fdb8544e0e8a1a665e1519716ecc4d5f9d8bb44c`,
A may delegate to B and B may persist a delegation to C using A's Policy
authority. C cannot consume it because consumption instead asks whether B has
direct Policy authority. A committed grant must not have different creation
and consumption semantics.

This proposal defines the missing transitive semantics. It does not accept
itself, alter ADR-010, or authorize runtime changes before formal acceptance.

## Decision

### One explicit authority path

An Organization delegation has exactly one immutable authority source:

- **Direct source:** the grantor has an effective, tenant-owned Organization
  assignment covering the target and a Policy action decision independent of
  any Organization delegation. This is a root delegation.
- **Delegated source:** the trusted current context selects one specific parent
  Organization delegation whose recipient is the grantor. This is a child
  delegation. Its authority is derived only through that parent and its
  ancestors; the implementation must not search for a different usable parent
  after creation.

The selected source is explicit. A grantor who also has independent direct
authority may create a root delegation from a non-delegated trusted context.
When a parent is selected, the command uses that parent or denies; it does not
silently fall back to direct authority. A child records the immutable parent
delegation ID. Each link is in the same trusted tenant, names the preceding
recipient as its grantor, and is immutable after insertion. The chain ends at
one root grantor. The root must have an active membership, a currently
effective Organization assignment covering the actual target, and a positive
Policy decision for each action. Every intermediate grantor and final recipient
must have an active membership. Unsupported or malformed principal, target,
source, or chain state denies.

Policy's root decision is evaluated through the Organization-owned typed port
and the same transaction-bound persistence capability defined by ADR-010.
The root Policy decision may reflect Policy-owned role assignments or
Policy-owned delegations under Policy's existing rules; it is independent of
the Organization chain. An intermediate recipient gains **effective delegated
action authority**, not a new direct Policy role or permission. Organization
validates the chain structure and calls the Policy port for the root action
decision. It never reads Policy tables or duplicates Policy rules. Policy does
not own Organization hierarchy or private delegation rows. The dependency
direction remains Policy -> Organization; frozen kernel and SDK semantics do
not change.

### Canonical effective-delegation algorithm

Creation, active-scope consumption, and any later backend authorization that
relies on an Organization delegation use the same chain-validation procedure.
Given a trusted tenant, principal, selected delegation or direct source,
target, action set, evaluation instant, and (for creation) proposed interval:

1. Resolve the exact source and follow immutable parent IDs to one root. Deny
   missing, unverified, revoked, cross-tenant, mismatched, repeated, or
   over-depth links. The final link must name the consuming principal as its
   recipient; a child creator must be its selected parent's recipient.
2. Validate current membership for every principal in the path and the root's
   effective direct Organization assignment. Validate the canonical
   Organization target lineage; each parent scope must contain the child
   scope and the actual requested target. A child cannot authorize an
   explicitly selected ancestor that its parent did not cover.
3. Require the requested actions to be present in **every** link's
   `allowed_actions`. For a new child, require its entire action set to be a
   subset of every ancestor's set. Resolve the action-to-resource association
   only through Policy's trusted mapping under ADR-010. Ask Policy for a
   positive root decision for each exact action at the actual target. One
   denial rejects the entire operation without a partial row or event.
4. Apply the time rules below and revalidate all mutable evidence after
   acquiring the required locks. Return an auditable path of delegation IDs,
   the root principal and matching Organization assignment, and Policy
   decision identifiers without exposing sensitive Policy records.

This is an existential **effective authority** check at the root: if several
direct assignments cover the target, use the matching assignment with the
lowest canonical UUID bytes for deterministic evidence. Losing one assignment
does not invalidate the chain if another current assignment still supplies
the same direct Organization authority. Losing effective root scope or Policy
action authority does invalidate it. The immutable parent path itself never
rebases onto another delegation.

For example, if A has direct `sales.approve` and `billing.refund`, A -> B
allows both, and B -> C allows only `billing.refund`, C has only that action
through this chain. B cannot create a child for an action absent from A -> B,
even if another unrelated delegation grants B that action. B may use its own
independent direct authority only through a separately selected direct source.

### Scope and time intersection

Organization's canonical hierarchy determines containment. The child's scope
must be the same as or a descendant of **every** ancestor scope and within
the root assignment. Unrelated company, tenant, or lineage values deny. A
company A authority cannot authorize company B. Policy receives the actual
requested target, not a broader ancestor or caller-supplied resource.

All validity windows are half-open `[valid_from, valid_until)`. A proposed
child window must be wholly contained within each parent window and every
required effective membership, root assignment, and Policy authority window;
the command denies rather than truncates it. Creation checks authority at its
evaluation instant and across the proposed window, as ADR-010 requires.
Consumption checks the complete path and Policy root action at the current
instant. It does not promise future authority: every later use rechecks.
Expired or not-yet-effective links deny. A Policy or scope revocation after
creation takes effect on the next use even if a stored validity window remains.

### Revocation and provenance

Revoking a parent does not silently delete descendants. They remain as audit
records but become **immediately ineffective** because every use traverses
the exact parent path. The same fail-closed result follows root Policy
revocation, membership revocation, root assignment loss, upstream expiry, or
invalid target lineage. Re-granting another parent does not resurrect a child.
An explicit Organization delegation revocation operation must record actor,
reason, correlation ID, and time and emit its event atomically. It marks the
specified grant revoked; validation propagates ineffectiveness to descendants
without requiring a potentially unbounded cascade. No caller may treat an
earlier `TenantContext` or cached authorization result as enduring delegated
authority. Backend use must revalidate; frontend visibility is never an
authorization decision.

The persisted chain requires an additive `authority_source_kind` with values
`direct` or `delegation`, a nullable immutable `parent_delegation_id` required
for child rows, and revocation state (`revoked_at`, actor, reason). The parent
reference is tenant-bound at the database level through a composite
`(tenant_id, parent_delegation_id)` foreign key to a tenant-unique delegation
key. A direct row has no parent;
a child has exactly one parent. Public Organization read projections expose
safe source/revocation state and parent ID so operators can explain why C has
an action on company A. Decision audit evidence records the traversed IDs,
root principal, selected root assignment ID, target, action, outcome,
correlation ID, and Policy decision reference. It does not log credentials,
sensitive Policy rows, or secret-bearing attributes.

Existing records have no reliable parent provenance. The migration must not
invent a parent from a coincidental match. Add nullable source metadata by
expand-contract migration; rows whose source remains unknown are
`legacy_unverified` and **cannot be consumed or re-delegated** until a bounded
operator-reviewed reconciliation proves one exact path and current root
authority. A uniquely provable row may be backfilled without changing its
scope, actions, or dates; ambiguous or unsafe rows require operator action
and must never be silently deleted or classified as direct. The migration and
public contract changes need explicit upgrade, rollback, and compatibility
review. No schema or contract change is made by this proposal itself.

### Cycles and depth

A chain may contain at most **16 delegation edges**, aligned with the existing
Phase 2 bounded traversal budget. This bounds query work and keeps evidence
reviewable. The limit is a fixed compatibility/security rule; changing it
requires review. A 17th edge denies before persistence. Validation rejects a
repeated delegation ID **or principal ID**: A -> B -> A and longer principal
cycles are invalid even if parent IDs themselves form an acyclic list.
Concurrent creators cannot evade this check because their writes serialize
under the tenant lock below. Parent references are immutable; direct SQL or
maintenance that changes authority records requires quiescence or the same
serialization and must not bypass tenant RLS.

### Transaction and lock protocol

ADR-010's exact tenant-scoped `pg_advisory_xact_lock` key, restricted
transactional persistence, and Policy mutation inventory remain authoritative.
This ADR extends that protocol to Organization chain creation, consumption,
explicit revocation, and any Organization grant mutation that changes the
effective chain. The framework owns the transaction; handlers neither open a
second transaction nor commit or release the lock early. Failed resolution or
lock acquisition aborts. No cross-tenant lock is taken for a delegated action.

The order is: (1) verify trusted tenant and acquire the ADR-010 tenant Policy
authority lock; (2) read immutable parent IDs to identify candidate rows;
(3) lock required Identity membership rows in canonical `(principal_type,
principal_id)` order, required Organization assignment rows by UUID bytes,
then Organization delegation rows by UUID bytes; (4) re-read and validate the
whole path and Policy root decision under PostgreSQL `READ COMMITTED`; (5)
insert, revoke, or emit the selection event in the same transaction. All
supported writers of the affected Organization rows must observe compatible
ordering. Identity membership writers that do not acquire the advisory lock
still serialize through their row locks and must not later try to acquire the
tenant advisory lock while holding those rows. Any future path that would do
so must be redesigned before release. Multi-tenant authority writes remain
forbidden; a future reviewed multi-tenant operation would acquire tenant
locks in ascending canonical UUID-byte order.

If child creation obtains the tenant lock first, validates and commits, then
parent or root revocation proceeds, that is a valid serial order; the child
becomes ineffective afterward. If revocation obtains the lock first and
commits, child creation subsequently observes it and denies. Assignment or
membership revocation similarly waits on the protected row or commits before
the chain is re-read. A child must never commit from a parent or Policy
decision that became invalid before its commit. Tests must use explicit
barriers to prove both orders; sleeps alone are insufficient.

### Cost and caching

At most 16 delegation rows, the associated memberships and root assignment,
and one Policy root evaluation **per requested action** are required for a
decision. Bounded reads and indexes on tenant/parent and tenant/grantor are
appropriate. No positive decision, traversed path, or context projection may
be cached across commands or requests unless a separately reviewed version
and invalidation scheme proves immediate revocation safety. Denial on a
missing provider, stale generation, malformed path, unknown mapping, or
unavailable authoritative store is preferable to stale authorization.

## Affected boundaries and compatibility

- **Organization:** owns chain structure, scope containment, source selection,
  revocation state, migration, events, and additive public provenance fields.
  Existing command names and fields remain; trusted context selects the
  parent. Existing direct delegation behavior remains subject to live Policy
  authority. Legacy rows without proven source fail closed pending repair.
- **Policy:** owns the root action/resource decision and continues to implement
  the Organization-owned ADR-010 port. It does not gain Organization table
  access or fabricate direct roles for intermediate recipients.
- **SDK/kernel:** no frozen Phase 1 or Phase 0 semantic change. Existing typed
  dependency and transaction APIs are used as published.
- **Schema/data:** a new forward Organization migration is required for
  immutable source and revocation metadata, tenant-bound parent reference,
  safe legacy reconciliation, and supporting indexes. Do not rewrite a
  released revision or `organization_0002`. No Policy schema change is
  required by this decision. Downgrade must refuse data-losing removal of
  provenance or revocation history.
- **Downstream:** Phase 2 API/read consumers and later Policy/UI work must
  treat a delegated context as provisional until backend chain validation.
  Mixed-version rollout needs explicit compatibility review because old code
  cannot honor the new source and revocation semantics. Phase 3+ behavior is
  not implemented by this ADR.

## Alternatives considered

- **Disallow all transitive delegation:** rejected because the authoritative
  Organization architecture requires a bounded assignment-rooted chain.
- **Pretend an intermediate recipient has a direct Policy role:** rejected;
  an Organization delegation creates no Policy role or permission.
- **Trust the root only at child creation:** rejected because consumption and
  upstream revocation would diverge.
- **Copy allowed actions to descendants without a live parent path:** rejected
  because stale or revoked authority could remain usable.
- **Reconstruct any currently matching parent without provenance:** rejected
  because an ambiguous or revoked chain could silently rebind.
- **Unlimited recursive traversal:** rejected due security, denial-of-service,
  and auditability costs.
- **Validate only at creation:** rejected because membership, Policy, scope,
  or parent authority can later be revoked.
- **Cascade-delete descendants on revocation:** rejected because it destroys
  evidence and makes revocation cost unbounded; live validation makes them
  ineffective immediately.

## Implementation and acceptance gates

Implementation remains blocked until this ADR receives the accountable
approval required by [ADR governance](../governance/ADR-GOVERNANCE.md) and the
accepted revision is on `main`. The required role union is Architecture
Maintainer, Security Maintainer, Policy Maintainer, Organization Maintainer,
SDK/Contract Maintainer, and Migration Safety Reviewer. The proposal must
receive exact-head CI and an independent bounded read-only ADR audit with
zero Critical and High findings before a Solo Maintainer Owner Proposal
Attestation can be requested. The owner must personally post any attestation;
an agent cannot post it or mark this proposal `ACCEPTED`.

Implementation must add real PostgreSQL tests for: direct A -> B; valid A ->
B -> C; child action, scope, and validity widening; denied and later revoked
root Policy authority; revoked parent; revoked membership and root assignment;
short and long principal cycles; depth 17; cross-tenant source; multi-action
intersection and atomic rejection; consumption after upstream expiry;
creation/consumption equivalence; provenance evidence; provider absence and
lifecycle fail-closed behavior; and deterministic concurrent parent revoke
and Policy revoke against child creation in both serial orders. Validate
upgrade/backfill, ambiguous legacy rows, data-preserving failure, safe
downgrade refusal, RLS, and exact installed-wheel migration replay. Run normal
backend, frontend, image, architecture, and conformance gates, followed by a
fresh independent **full** Phase 2 certification audit. PR #13 remains
unmerged during ADR review.
