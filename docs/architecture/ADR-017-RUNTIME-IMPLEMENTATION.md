# ADR-017 retention and destructive lifecycle runtime candidate

Status: implementation and local certification candidate under the accepted
[ADR-017](../adr/ADR-017-retention-hold-and-purge-coordination.md). Hosted
exact-head CI, exact-commit audit, and owner attestation remain pending. This
record does not change the accepted decision or authorize a merge.

Base main: `0b516efaaa7de117f7b71ff2856d43fa40575fc1`.
Branch: `phase4/adr017-retention-purge-rebuild`.

## Ownership and transaction boundary

Data Governance owns the version 2 retention-policy, legal-hold,
purge-authority, and destructive-lifecycle contracts. The canonical proof
resource owner supplies locked retention category, UTC anchor, lifecycle, and
supported actions through the admitted ADR-018 facts and operation providers.
Governance resolves the owner from the protected registry, verifies the
current provider generation and normalized facts, requires exactly one
effective policy whose expiry action equals the requested action, checks
elapsed 24-hour days and applicable holds, then applies the owner's operation.
Caller-provided age, category, object key, or a previously computed eligibility
result cannot authorize the operation. V1 eligibility remains informational;
the V1 destructive anonymization hook denies execution.

**Transaction A** is one framework-owned PostgreSQL unit of work: the
Governance destructive command locks and reads the owner record, policy, and
holds; invokes the ADR-018 admitted owner operation; records the Governance
decision with `external_cleanup_status=pending`; appends AuditAppenderV2
evidence; and writes the versioned cleanup request to the transactional
outbox. Commit makes all of those database effects visible together. A
failure or cancellation rolls them back together. The cleanup event is not
published as an external effect until after this commit.

The mandatory lock order is entity gate, category-independent subject lock,
owner row and fresh facts, policy-scope lock, then policy/hold/decision rows.
The legacy hold entity gate is acquired with the subject path. A single
monotonic **5-second** deadline covers advisory-lock acquisition, using
PostgreSQL transaction advisory try-locks. Expiry returns the retryable
`retention_lock_timeout` outcome; rollback releases earlier transaction
locks. Policy replacement, category/anchor/lifecycle mutations, hold changes,
and destructive execution participate in this ordering. Transaction A
releases its entity, subject, and policy locks at commit; none spans the
later asynchronous cleanup. The proof worker uses a distinct transaction
advisory lock during S3 reconciliation of the legacy shared object, so
concurrent deliveries cannot restore purged plaintext.

## Additive external-erasure capability

ADR-017's accepted pending/completed cleanup semantics require real external
erasure. The existing `OBJECT_STORAGE` put/get contract and consumers remain
source-compatible. An additive `ObjectStorageDeleteProvider` with a separate
`OBJECT_STORAGE_DELETE` dependency key supplies only tenant-bound,
idempotent `delete(tenant_id, key)`. The existing S3 adapter implements it
with `delete_object`; the tenant-bound wrapper applies the same trusted
request-tenant check used by put/get. The SDK exposes the typed capability,
without exposing a raw S3 client, credentials, or arbitrary bucket access.

The proof owner derives `phase1-proof/records/<record-id>.txt` from its trusted
record identity. It never accepts a caller-selected cleanup key. The older
`phase1-proof/value.txt` compatibility projection remains tenant-wide. Its
worker writers serialize on a shared-key lock and read the latest surviving
current record before writing, so an out-of-order stored event cannot restore
an older value. On successful anonymization or purge cleanup, the owner
idempotently deletes the record-specific object, then rewrites the shared key
from the latest surviving current record or deletes it when none remains.
Purged plaintext is not left at the shared key. Archive preserves the
external object; it still reaches truthful cleanup completion.

## Durable cleanup after commit

The proof owner's durable EventWorker subscriber handles only its own
committed `governance.destructive.cleanup_requested.v2` event. Before any
external effect it verifies the canonical owner/resource/action, tenant,
exact subscriber and source event, active ADR-019 workload binding, protected
decision identity and status, and the resulting owner lifecycle. A fabricated
service-account request or unrelated committed event is not cleanup
authority. The worker receives only its exact cleanup-report permission;
its durable subscriber permission is kept separate.

External deletion or reconciliation failure propagates to durable NATS
delivery retry. The original committed decision remains pending and
retryable. A duplicate delivery is idempotent. Only after external cleanup
succeeds does the worker dispatch the exact
`RecordDestructiveCleanupResultV2` command. ADR-022 routes that command to
the protected Governance pool; the ordinary worker has no direct UPDATE on
the decision table. **Transaction B** is a new protected Governance unit of
work that marks completion and appends its audit evidence. It is not part of
Transaction A's same-UOW proof.

## Schema and database authority

Forward revision `gov_0005` adds version 2 policy, hold, and destructive
decision relations with tenant RLS and protected grants. Its bounded,
read-only dirty-data preflight refuses legacy policies without an
owner-approved category/interval mapping and noncanonical record-hold IDs;
it never guesses or rewrites their meaning. Forward revision `proof_0004`
adds proof-owner category, anchor, and lifecycle fields, backfills anchors
from creation time, and enrolls `proof_records` in protected owner authority.
Both revisions refuse downgrade because it would discard governed evidence
or restore unsafe grants. Historical migrations are unchanged.

The ADR-022 protected admission inventory now includes the participating
proof-owner relation. It validates the exact RLS policy, column-level grants,
ordinary app/worker restrictions, and indirect SQL write paths before
admitting protected commands. The app retains only the reviewed insert and
projection update columns. Governance has the reviewed lifecycle/value
columns. Ordinary app/worker direct lifecycle changes, role inheritance,
views, rules, triggers, and privileged functions cannot become an indirect
owner-table write bypass.

## Local certification and remaining gate

Focused PostgreSQL proofs cover both hold/purge commit orders, concurrent
purges, policy replacement, owner category/anchor/lifecycle races, lock
timeout/release/cancellation and cross-tenant independence, stale provider
generation, nested dispatch, fake authority, same-UOW commit/rollback,
external cleanup retry/idempotency, out-of-order projection, and ordinary
indirect-write rejection. The second independent read-only security preflight
reported Critical 0, High 0, Medium 0, Low 0.

On this uncommitted candidate, full integration passed **194 tests**; full
pytest passed **729 tests**. Ruff format/lint, mypy on source paths, Pyright
on source paths, and the Phase 0 architecture gate passed. Installed-wheel
migration smoke, development/production/migration-smoke image builds, and
installed-image migration plan, role transition, upgrade, reversible
Geography replay, final heads, and safe Governance downgrade refusal passed.
Phase 0–3 remain FINAL PASS / FROZEN; this work does not reopen them.

Local success is not final release authority. The candidate still requires
an exact-head hosted CI pass, independent read-only audit of the exact
committed candidate, and a personally posted exact-SHA Solo Maintainer Owner
Attestation under [MAINTAINERS.md](../governance/MAINTAINERS.md). Historical
draft PR #45 remains unmerged and unchanged. This candidate stops before
merge.
