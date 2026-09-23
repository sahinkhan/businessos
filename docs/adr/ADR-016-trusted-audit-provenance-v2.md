# ADR-016: Trusted Audit Provenance and Write Contract V2

Status: PROPOSED

Decision date: Pending formal acceptance

Approving roles required: Architecture Maintainer; Security Maintainer; Audit Owning Domain Maintainer; Identity Maintainer; SDK/Contract Maintainer; Policy Maintainer for support-access evidence; Release Maintainer; Migration Safety Reviewer if the provenance schema changes

Approval pull request or commit: Pending

Supersedes: None

Superseded by: None

## Context

`foundation.audit.write-facade.v1` exposes `RecordAuditLogCommand` with
caller-supplied `actor_id`, `actor_type`, `tenant_id`, and `correlation_id`.
Holding `foundation.audit.write` can therefore attribute an event to someone
else. That violates the [security baseline](../architecture/SECURITY.md),
which requires auditable privileged activity. Audit is append-only, so false
provenance can persist in an integrity-valid chain unless the write boundary
binds actor identity before computing the checksum.

## Proposed decision

Audit publishes `foundation.audit.write-facade.v2` with a distinct
`RecordAuditLogV2` command/result contract. The ordinary actual actor is the
verified `(principal_type, principal_id)` in `RequestContext` through the
frozen Identity binding. Trusted context also supplies tenant, correlation
and trace identifiers, and the server-side event instant. If any required
binding is missing or inconsistent, the write fails closed. Caller fields
cannot override these values, including by repeating the same UUID with a
different principal type. The caller supplies only event/action, bounded
resource locator, authorized business evidence, and outcome; Audit validates
the declared evidence shape and avoids sensitive payloads/secrets.

Service account, device, job, and system events use typed identities already
verified by the framework/Identity boundary. A caller cannot assert `system`
or another service actor as a string. A framework-controlled bootstrap or
internal migration event with no human actor must use an explicit trusted
system-actor capability, scoped purpose, and recorded origin; it is never
the default fallback for a failed identity binding.

Support or administrative on-behalf-of activity records **both** the actual
verified actor and the target `(principal_type, principal_id)` as a separate
on-behalf-of subject. It records the authorization/grant reference, reason,
scope, and time where the accepted support-access contract supplies them.
The target never replaces the actual actor. Audit validates any claimed
support context against a trusted Policy/Identity grant or framework evidence;
unverified free text may be stored only as non-authoritative business detail.
The v2 contract permits trusted Policy decisions proposed in
ADR-014 and purge decisions
proposed in ADR-017 to
record evidence without making Audit an authorization oracle. Audit depends
on public contracts, not private Policy, Governance, or Party tables.

Audit appends its row in the caller's active framework-owned unit of work,
and any published audit event uses the transactional outbox in that same
transaction. No committed business action claims a durable audit record if
its required audit write failed. Existing append-only/immutability controls
remain. A versioned canonical integrity encoding includes tenant, actual
typed actor, on-behalf-of typed subject and support references when present,
trusted correlation/trace, action/resource/evidence, event instant, and the
prior-chain checksum. Verification selects the correct encoding version for
historical rows; it never recomputes legacy checksums using a new layout or
silently treats old rows as v2 provenance. New on-behalf-of data is tamper
evident. Secrets and raw sensitive values are excluded or minimized.

### V1 transition

The correction is incompatible and security-sensitive under
[RELEASES.md](../governance/RELEASES.md). V2 is introduced as a separate
contract major with a deprecation/consumer inventory. A v1 shim may remain
only if it ignores or rejects caller `actor_id`, `actor_type`, tenant,
correlation, and event time when they conflict with verified context, derives
actual provenance exactly as v2, and cannot produce spoofed audit entries.
It must not relabel an old actor assertion as verified. If a safe v1 shim is
impossible, the unsafe write operation is disabled when v2 is available;
Security and Release Maintainers must explicitly approve an urgent shortened
window, with risk, affected users, mitigation, expiry, and notice. The v1
symbol can remain for a safe shim through at least the next Stable platform
minor after v2 availability. Removal later requires downstream regression,
owner/SDK/Architecture approval, release notes, and supported-range updates.
No exception or removal is approved by this PROPOSED ADR.

Any new provenance columns or integrity-version field require a new forward
Audit-owned migration with a preflight for chain validity and no rewrite of
existing audit rows. Old rows retain their historical evidence status;
there is no retroactive claim that their actor fields were verified. The
implementation and release notes must distinguish legacy and v2 assurance.

## Consequences and impact

Audit owns the write and integrity contract; Identity owns actor
verification; Policy owns support authority. The protected kernel supplies
generic trusted context and transaction boundaries. Typed service principals
and on-behalf-of relationships remain auditable without permitting actor
spoofing. Existing v1 callers may need to stop sending actor identity.
Tenant isolation, append-only storage, and outbox consistency remain required
across self-hosted and cloud modes. Later modules consume the public v2
facade; no frozen-layer reverse dependency or private-table import is added.

## Alternatives considered

| Alternative | Reason declined |
| --- | --- |
| Keep caller-supplied actor under `audit.write` | Allows forged provenance. |
| Store only the impersonated target | Conceals the actual support/admin actor. |
| Rewrite historical chain rows as v2 | Destroys historical integrity evidence and invents verification. |
| Use an ambient `system` fallback | Turns missing authentication into privileged provenance. |

## Approval and implementation gates

The role union follows the architecture, identity/security, public contract,
affected owner, and release rows in
[ADR-GOVERNANCE.md](../governance/ADR-GOVERNANCE.md) and
[MAINTAINERS.md](../governance/MAINTAINERS.md). Migration Safety Reviewer is
required if implementation changes the schema or integrity storage. This
PROPOSED ADR authorizes no Phase 4 implementation. Acceptance requires
exact-revision role evidence, exact-head CI, independent read-only technical
audit with zero Critical/High findings, and formal governance procedure.
Implementation must test wrong-type/same-UUID actor claims, missing context,
typed service identity, on-behalf-of evidence, tenant isolation, checksum
tampering/version verification, rollback/outbox, and v1 shim safety.
