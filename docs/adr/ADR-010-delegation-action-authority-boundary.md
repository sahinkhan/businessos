# ADR-010: Delegation Action Authority Boundary

Status: ACCEPTED

Decision date: 2026-09-22
Approving roles: Architecture Maintainer; Security Maintainer; Policy Maintainer; Organization Maintainer; SDK/Contract Maintainer
Approval pull request or commit: PR #16 (acceptance candidate; formal acceptance requires the accepted revision on `main`)
Approved semantic proposal SHA: `374b74a37ddef2bc1ac24660962baf86f69c23ae`
Review model: SOLO MAINTAINER OWNER ATTESTATION by `@sahinkhan` ([proposal attestation](https://github.com/sahinkhan/businessos/pull/16#issuecomment-5770971636))
Independent human review: NOT PERFORMED
Independent technical audit: bounded ADR review PASS; Critical 0; High 0
Exact proposal CI: [BusinessOS run 35648670033](https://github.com/sahinkhan/businessos/actions/runs/35648670033) — PASS (`python-quality`, `windows-typing`, `web-quality`)
Supersedes: None
Superseded by: None

## Context

Organization verifies the grantor's membership, organizational scope, lineage,
effective period, and permission to manage delegations. A covering Organization
assignment does not prove that the grantor holds each business action in a
delegation's `allowed_actions`. The existing command can therefore grant an
action that Policy would deny at the requested target scope.

Policy already depends on Organization. Organization cannot import Policy,
query Policy-owned tables, or call a Policy query through a hidden dispatcher
key without reversing the module dependency and weakening the transaction
boundary. The frozen Phase 1 SDK already offers typed dependency registration,
request resolution, and restricted transactional persistence; no kernel change
is needed.

## Proposed decision

Organization owns and publishes an additive, typed
`DelegationActionAuthority` port and dependency identifier. Policy implements
and registers that port using the existing module dependency mechanism. The
dependency direction remains Policy -> Organization -> lower foundations and
protected platform. Organization never imports Policy or its private models.

The port evaluates a trusted tenant ID, grantor/principal ID, Organization
target scope type and ID, one requested action, the evaluation instant, and
the proposed delegation's effective interval. It receives only the existing
restricted public `TransactionalPersistence` capability of the active
framework-owned command transaction. It returns an explicit allow/deny
decision; malformed or unsupported scopes deny. It exposes no Policy schema,
private API, raw SQLAlchemy session, Unit of Work completion control,
commit/rollback, or kernel-private type. The caller, not untrusted input,
supplies the tenant and grantor from trusted context. Policy translates the
Organization target into its own evaluation context and applies its owned
authorization rules under tenant isolation.

Policy's current evaluator also takes a `resource`: it uses that value for
`resource.*` permissions and resource-specific record policies. The adapter
must obtain the action-to-resource association from a trusted, Policy-owned
registration or mapping, not from a caller-supplied resource or a guessed
string prefix. The existing permission `category` is not automatically an
authoritative resource mapping. An unregistered, ambiguous, unsupported, or
inconsistent action/resource association denies. The resolved resource must
be the same for direct permissions, wildcards, and record-policy evaluation.
If this association is persisted or mutable, its changes join the same
authority serialization protocol. The implementation must prove that the
chosen mapping preserves existing Policy semantics; this proposal does not
authorize a silent schema or public-contract change to manufacture one.

A delegation is valid only when both conditions hold:

```text
delegated scope   ⊆ grantor effective organizational scope
delegated actions ⊆ grantor effective action authority at the actual target
```

Organization checks every requested action independently, at the relevant
evaluation time and throughout the requested effective interval. A grantor
whose authority does not cover that interval cannot create a longer-lived
delegation. If any action is denied, the entire command fails in its existing
transaction and inserts no partial delegation. `foundation.organization.manage`
permits management of delegations; it never grants arbitrary business actions.
The effective authority behind an existing delegation must be rechecked when
that delegation is consumed or otherwise invalidated after later revocation;
creation-time validation alone cannot make revoked authority permanent.

If no compliant provider is active, dependency resolution fails, or the
provider's generation is disabled, draining, removed, or stale, Organization
fails closed with a controlled configuration/authorization error. It must not
cache a callable provider beyond the framework's request/lifecycle boundary
or fall back to scope-only approval. Existing Phase 1 DI and lifecycle
semantics remain unchanged.

## Transaction and serialization protocol

The Policy decision and Organization delegation insert run in the **same
framework-owned command transaction**. The port receives the handler's
restricted persistence capability; it does not start or finish a second
transaction. The authority decision remains protected until that transaction
commits or rolls back.

Policy owns one deterministic PostgreSQL transaction-scoped authority advisory
lock per tenant. Derive its signed 64-bit key from the first eight bytes of
SHA-256 over the fixed UTF-8 domain separator
`businessos.policy.authority.v1\0` followed by the tenant UUID's 16 canonical
bytes, interpreted in big-endian two's-complement order. All participants use
the same function and verified trusted tenant UUID. Hash collisions could
only add contention, not permit an unsafe decision. Acquire the exclusive
lock with `pg_advisory_xact_lock` through the active restricted persistence
capability. PostgreSQL releases it on transaction completion, including
rollback and cancellation; there is no manual unlock or durable lock state.
Lock acquisition failure aborts the command. A transaction must acquire this
authority lock before reading authority for a delegation and before writing
Policy state that can change that decision. Within a transaction, acquire the
authority lock before Policy row locks and, for a cross-module delegation
command, before Organization's membership/grant row locks. If future work
needs more than one tenant authority lock, take them in ascending UUID-byte
order; cross-tenant authority writes remain prohibited by tenant isolation.

Under PostgreSQL `READ COMMITTED`, the Policy adapter reads authorization
state **after** acquiring the lock in the active transaction. A revocation
that already committed is visible to that read; a concurrent mutation cannot
commit a conflicting authority change until the delegation transaction ends.
This protocol must be used by every supported Policy mutation that can alter
the effective action decision. Current relevant write paths are role creation,
permission-to-role assignment, subject-role assignment, record-policy creation,
Policy delegation creation, and Policy delegation revocation. Current Policy
authorization reads roles, subject-role assignments, role permissions,
delegations, and resource-matching record policies; any mutable authoritative
action-to-resource mapping is also decision state. There is presently no
public role-assignment revocation, role-permission removal, or role update
command; any later such path must join this protocol before release. The
permission catalog upsert does not currently participate in action evaluation.
Field policy, approval limit, SoD, and support-access writes do not currently
feed this action decision and are outside this lock requirement unless their
semantics later change. Out-of-band Policy writes and migrations that alter
these records require the same serialization or a quiesced maintenance window.

If delegation obtains the lock first, verifies authority, inserts and commits,
then revocation proceeds, that is a valid serial order. If revocation obtains
the lock first and commits, delegation subsequently sees the revoked authority
and denies. It is forbidden for delegation to evaluate old authority while a
conflicting revocation commits and then insert using that stale decision.

Row locks alone do not cover authority added or removed through new rows or
role hierarchy changes (phantoms). A version/epoch scheme would require a
new durable coordination record and consistent updates in every Policy
mutation; it adds schema and retry complexity to this bounded correction.
Transaction-scoped advisory locking needs no schema and covers the current
multi-table authorization model. A coarse global lock would serialize all
tenants and is unnecessary. Tenant-scoped locking initially serializes only
authority-sensitive operations for the affected tenant; ordinary business
operations are not globally serialized. It has a measurable contention cost.
A narrower compatible protocol may replace it after profiling and review,
with equivalent concurrency tests.

## Affected boundaries and compatibility

This is an **additive public inter-foundation capability** and a
security-sensitive trust-boundary correction. Organization owns its contract;
Policy owns its adapter, evaluation rules, and Policy-table access. The
affected owners are Organization, Policy, Security, SDK/Contract compatibility,
and Architecture. The existing Organization command and SDK contracts are not
removed or version-broken. Delegation commands that relied on scope-only
approval will now fail closed unless the provider proves action authority;
that intentional authorization tightening requires deployment and conformance
review. Policy-disabled installations may continue to use unrelated
Organization capabilities, but cannot create action-bearing delegations
without an active compliant authority provider.

The decision itself requires no database schema or migration. It changes no
Phase 0 or frozen Phase 1 semantics. It introduces no Phase 3 behavior. The
narrow Policy adapter and coordinated mutation locking are Phase 2
certification integration work that must also be included in later Phase 4
certification. Policy-owned persistence remains private to Policy; all reads
and writes obey tenant RLS and the trusted tenant boundary.

## Security and operational consequences

Provider absence, bad scope translation, cross-tenant input, failed lock
acquisition, and denied actions fail closed. No permanent privileged bypass is
introduced. Organization's existing scope, membership, effective-period,
lineage, and concurrent scope-revocation checks remain required. Policy's
decision is authoritative for each requested action at the target scope; a
company A grant cannot authorize company B. The delegation command and denied
decision need correlation-aware audit evidence without logging secrets or
sensitive Policy records. Successful creation and subsequent revocation remain
auditable through existing domain/event boundaries. Provider deactivation
invalidates future resolution; stale handles cannot supply authority.

## Alternatives considered

- **Organization imports Policy:** rejected because it reverses the existing
  dependency and creates a module cycle.
- **Organization reads Policy tables:** rejected because it violates
  module-owned data boundaries and duplicates Policy rules.
- **Internally dispatch `AuthorizeActionQuery`:** rejected because a separate
  query transaction does not keep the decision valid through insertion and
  would create an upward contract dependency.
- **Treat `foundation.organization.manage` as action authority:** rejected
  because it permits privilege escalation.
- **Put Organization-specific authorization in the frozen kernel:** rejected
  because this foundation concern does not belong in the generic runtime.
- **Evaluate outside the command transaction:** rejected because revocation
  can commit between evaluation and insert.
- **Lock only selected Policy rows:** rejected because inserts and changes to
  other contributing rows can change the answer without touching those rows.
- **Use a durable authorization epoch:** deferred because it requires new
  coordination state and comprehensive mutation updates; no schema is needed
  for the chosen protocol.

## Implementation and acceptance gates

This acceptance candidate authorizes no runtime change before the accepted
revision is recorded on `main` under `docs/governance/ADR-GOVERNANCE.md`.
CI and technical review alone do not accept an ADR.

Implementation must prove with real PostgreSQL and supported public APIs:
target-scope allow/deny, each action independently checked, multi-action
atomic rejection, missing/stale provider fail-closed behavior, cross-tenant
denial, concurrent Policy revocation versus delegation, and preservation of
concurrent Organization scope revocation behavior. Test provider disable,
drain, removal and stale generation as supported by Phase 1 lifecycle APIs.
Test action/resource mapping with both wildcard permissions and restrictive
record policies, including ambiguous or missing mappings that deny.
Verify the mutation-lock inventory, lock ordering and actual transaction
identity. Confirm no frozen Phase 1 modification. Run normal validation and a
full independent Phase 2 audit before certification.

Required accountable roles for acceptance: Architecture Maintainer, Security
Maintainer, Policy Maintainer, Organization Maintainer, and SDK/Contract
Maintainer. The normal path is independent accountable human review. If the
temporary Solo Maintainer Exception is eligible, `@sahinkhan` must personally
record the exact ADR revision/SHA, CI, independent technical audit, zero
Critical/High findings, every role exercised, and the absence of independent
human review. An agent cannot supply that attestation.
