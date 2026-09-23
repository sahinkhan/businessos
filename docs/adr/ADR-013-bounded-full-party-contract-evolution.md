# ADR-013: Bounded Complete FullParty Contract Evolution

Status: PROPOSED

Decision date: Pending acceptance

Approving roles required: Architecture Maintainer; SDK/Contract Maintainer; Party Owning Domain Maintainer; Security Maintainer; Release Maintainer

Approval pull request or commit: Pending proposal PR and formal acceptance evidence

Supersedes: None

Superseded by: None

## Context

Party publishes `GetFullParty` and `FullPartyRecord`. The current Phase 3
remediation candidate `1d8309faf8af64d5d9723c8b8990933c2835e425` also
publishes `GetSensitiveFullParty` under `foundation.party.sensitive.read`.
`GetFullParty` returns a complete *authorized projection*: it redacts sensitive
profile fields and identifiers and does not include contact values. The
sensitive query returns those fields only after explicit permission checks.
Both queries load address assignments and identifiers without an SQL bound;
the sensitive query also loads contacts without a bound. Tenant-created child
collections can exhaust database, application memory, serialization capacity,
and response budgets. This conflicts with the bounded interactive-query rule
in [DATABASE.md](../architecture/DATABASE.md).

These query names promise a complete aggregate. A successful response cannot
silently contain only the first page of any authorized child collection.
The query's `FullPartyRecord` currently has no pagination metadata. Adding
ordinary pagination in place would change meaning while hiding that change.
An SQL hard limit with explicit overflow preserves the meaning of successful
responses, but narrows the contract: a large request that previously succeeded
will fail. [RELEASES.md](../governance/RELEASES.md) classifies this as an
incompatible public-contract change even before 1.0.

The repository-wide source search found no Phase 4 Policy, later business
module, or example application caller of `GetFullParty`, `GetSensitiveFullParty`,
or `FullPartyRecord`. The current references are Party declarations, handlers,
and exports, Phase 3 integration tests on the remediation branch, and release
documentation. That is an internal implementation inventory, not evidence
that external users do not exist. The historical immutable `v0.3.0-phase3`
tag contains `GetFullParty` and `FullPartyRecord`; its release channel and
external adoption have not been established. `GetSensitiveFullParty` is in
the later Phase 3 remediation candidate, not that historical tag.

## Proposed decision

### Complete bounded aggregate and public versions

`FullParty` continues to mean a complete authorized Party aggregate. A
successful bounded read includes every child in each collection visible to
that query, up to its documented supported bound. It never returns a partial
aggregate or silently drops children. A Party-owned, contractually fixed
maximum of **100 children per collection** applies to contacts, address
assignments, and external identifiers. This matches the current Phase 3
public list maximum and cannot be raised by a request or tenant setting.
Changing the maximum later is a public-contract change requiring impact
review. Relationships are not part of `FullPartyRecord`; their existing
standalone query remains separately bounded.

The replacement public query names are `GetFullPartyV2` and
`GetSensitiveFullPartyV2`, returning `FullPartyRecordV2` with the same logical
field projection as the current successful response. The owning module
registers the aggregate contract as `foundation.party.full-read.v2`. The
existing `foundation.party.sensitive-read.v1` marker and
`foundation.party.sensitive.read` permission retain their current meaning;
the v2 marker does not version unrelated sensitive Party operations.
The existing `GetFullParty`, `GetSensitiveFullParty`, and `FullPartyRecord`
names are the v1 surface and are deprecated on v2 availability. The v2
query types, marker, and result type make the contract-major change explicit.

For each child collection actually included in the caller's authorized
projection, the owning Party handler executes an SQL query scoped to the
trusted tenant and Party, ordered by a stable unique key, with `LIMIT 101`.
It may fetch all rows from that bounded SQL result. If any result has 101
rows, the handler returns **no** `FullPartyRecordV2`; it raises a controlled
`BusinessOSError` with code `full_party_aggregate_too_large`, an application
error status suitable for an oversized bounded read, and guidance to use the
paginated Party child queries. The message includes no values, raw SQL,
exact child counts, sensitive collection identity, or information from
another tenant. Exactly 100 visible rows in any collection succeeds. The
ordinary query neither fetches nor counts sensitive-only contacts or
identifiers. The sensitive query checks the existing explicit permission
before loading its sensitive projection. Query and response resources are
therefore calculably bounded.

No protected-kernel error type or Policy dependency is required. The Party
module owns the error code and translates it through the existing BusinessOS
application error boundary. The response remains an all-or-error result;
there is no partial-result variant.

### Paginated child queries

Large-aggregate callers use additive, tenant- and Party-scoped public list
queries. Each has a validated `limit` (default 50, maximum 100) and
nonnegative `offset`, SQL-level `LIMIT`/`OFFSET`, and deterministic ordering
with an immutable unique ID tie-breaker. Every page is authorized and tenant
isolated independently. No client needs Party private-table access.

| Collection | Public migration contract | Authorization and projection |
| --- | --- | --- |
| Contacts | Add `ListPartyContacts` | `foundation.party.sensitive.read`; values are classified sensitive, so no general-read contact value list is created. |
| Address assignments | Add `ListPartyAddresses` | `foundation.party.read`; tenant- and Party-scoped assignment records. |
| External identifiers | Add `ListPartyIdentifiers` and `ListSensitivePartyIdentifiers` | General read excludes `is_sensitive` values; sensitive query requires `foundation.party.sensitive.read`. |
| Relationships | Reuse `ListPartyRelationships` after the current Phase 3 branch's pagination change is reconciled | `foundation.party.read`; match either endpoint as the current query does. |

The ordinary FullParty projection still omits contacts; an authorized caller
who needs contact values uses `ListPartyContacts`. The child queries are
independently versioned additive Party operations. Tests must prove first and
next pages, stable ordering, maximum and invalid-limit rejection, SQL bounds,
permission enforcement, redaction, and tenant isolation.

### V1 transition and release exception requested

The old unlimited v1 behavior **cannot remain publicly callable at Phase 3
freeze**. A versioned v2 alone would leave the DATABASE.md violation in
place. This proposal therefore requests a narrow security and release
exception to the ordinary v1 behavior/deprecation window: when v2 and the
child-list contracts become available, the existing v1 query names remain
as deprecated compatibility shims, but their reads also use the same
complete-or-overflow SQL bound. Successful small v1 responses retain their
current shape and authorized content. Large v1 calls receive the same
controlled overflow error and migration guidance. No unlimited v1 execution
path survives certification. This is **incompatible v1 narrowing**, not an
additive change or a claim that absence of known callers proves compatibility.

The normal deprecation rule retains the v1 names through at least the next
stable platform minor release after v2 becomes available, unless a separately
approved removal exception shortens that period. This ADR requests an
exception only for **unlimited v1 read behavior**, not for the v1 symbol's
support duration. The earliest ordinary removal of the deprecated v1 names
is after that next stable minor support checkpoint, documented consumer
migration, downstream regression evidence, and owning Party,
SDK/Contract, Architecture, and Release approval. No removal is authorized by
this proposal. If a later release needs earlier removal, it requires its own
explicit Security and Release exception with an expiry and notice.

The requested immediate behavior exception is justified by tenant-controlled
resource-exhaustion exposure and a release-blocking bounded-query violation.
Affected users are callers with more than 100 authorized children in any
FullParty collection. They must switch to v2 for bounded complete reads or
combine `GetParty` with the paginated child queries for larger collections.
The mitigation is additive child access, explicit deterministic overflow,
release notice, and preservation of all smaller complete responses. The
exception expires when the last unlimited v1 handler is replaced before
Phase 3 freeze. It is **not granted by PROPOSED status**: Security Maintainer
and Release Maintainer must explicitly approve this exception at ADR
acceptance. If they do not, no implementation may claim Phase 3 certification
while an unbounded v1 endpoint remains.

### Compatibility and implementation gates

The v2 queries and child-list operations are additive. Replacing unlimited
v1 execution with complete-or-overflow behavior is an incompatible public
contract narrowing. The v1 names are deprecated, not silently reinterpreted
as pages. The independent query major and controlled v1 transition are the
version/coexistence plan required by RELEASES.md. Existing v1 users must be
notified of the fixed bound, error code, migration path, and support window.
Release notes must identify the exact rollout checkpoint and any known
consumer. The immutable historical tags and artifacts are not retargeted.

Implementation begins only after this ADR is formally `ACCEPTED`. The
remediation branch must then reconcile the accepted decision without changing
frozen Phase 0/1/2 behavior or ADR-012 semantics. The implementation adds
Party-owned v2 types and marker, the bounded v1 compatibility shims,
paginated child queries, and conformance and PostgreSQL tests. It must prove
both v1 and v2 aggregate SQL have a limit and unique ordering, exactly-100
success, 101-row fail-closed behavior, no partial object, no sensitive
overflow leakage, permission checks, tenant RLS, and downstream consumer
compatibility. A fresh full Phase 3 audit and exact-head CI remain separate
certification gates. There is no schema change or Alembic migration implied
by this decision; implementation must reassess if a schema need is found.

## Consequences

The fixed bound limits query rows, application memory, serialization work,
response payload, and tenant-created pathological aggregates. Heavy callers
use predictable pages, supporting enterprise workload isolation and
horizontal scaling. A caller with a large aggregate receives a controlled
failure and must use a documented child-list path. Small successful FullParty
responses remain complete.

The owning Party module enforces tenant and Party predicates on every read.
The ordinary projection never discloses sensitive identifier values or
contact values. The sensitive projection and sensitive child lists retain
their explicit permission; overflow does not reveal sensitive data or exact
counts. Party does not depend on Policy. This proposal changes no Phase 0,
Phase 1, or Phase 2 runtime, no migration or data ownership, no ADR-012
semantic, and no Phase 4+ business behavior.

Affected public surfaces are the Party v1 aggregate queries and result,
their v2 successors, the new child-list queries, `ListPartyRelationships`,
the existing sensitive-read marker and permission, and release notices.
Affected accountable roles are Architecture Maintainer, SDK/Contract
Maintainer, Party Owning Domain Maintainer, Security Maintainer, and Release
Maintainer. Security and Release are required for the requested shortened
unlimited-v1 behavior window and resource-exhaustion review. No migration
safety approval is required absent a later schema or data-lifecycle change.

## Alternatives considered

| Option | Outcome |
| --- | --- |
| Keep unlimited FullParty forever | Rejected: violates DATABASE.md and keeps a tenant-controlled resource-exhaustion path. |
| A: bound v1 in place only | Rejected as the sole strategy: it narrows an independently versionable public contract without a new major. The transition does bound deprecated v1 under the explicit proposed exception. |
| B: bounded v2 with unlimited v1 coexistence | Rejected at freeze: unlimited v1 leaves the certification blocker open. |
| C: bounded v2 plus explicit v1 retirement | Chosen in staged form: unlimited v1 behavior retires when v2 is ready; the deprecated v1 name remains as a bounded complete-or-overflow shim through its governed support window. |
| D: paginate inside FullParty | Rejected: a successful response would misleadingly be a partial aggregate. |
| E: remove FullParty entirely | Rejected: loses a useful bounded aggregate read and breaks callers without a migration period. |
| Silent truncation or hidden automatic pages | Rejected: violates complete-response semantics and hides data loss or unbounded work. |
| Unlimited configurable limit | Rejected: permits the same resource-exhaustion exposure through configuration. |
| Unbounded SQL followed by Python slicing | Rejected: database and application still pay for every row. |
| Paginated child lists | Chosen for collections larger than the aggregate contract permits, with permission and tenant checks on every page. |

## Approval and follow-up gates

This is a proposal, not an implementation authorization or an accepted
exception. Formal acceptance requires the accountable-role approval union,
explicit Security and Release approval of the unlimited-v1 behavior
exception, exact-head CI, independent read-only technical review with zero
Critical/High findings, and the governance evidence required by
[ADR-GOVERNANCE.md](../governance/ADR-GOVERNANCE.md). The owner attestation,
if the Solo Maintainer Exception remains eligible, must identify every role
and state that independent human review was not performed. After acceptance,
the Phase 3 implementation, full validation, independent Phase 3 audit, and
remote certification remain separate work.
