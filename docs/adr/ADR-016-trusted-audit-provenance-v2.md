# ADR-016: Trusted Audit Provenance and Write Contract V2

Status: SUPERSEDED

Decision date: 2026-09-24

Supersession date: 2026-09-25 (formal ADR-019 acceptance candidate; effective on merge to `main`)

Approving roles required: Architecture Maintainer; Security Maintainer; Audit Owning Domain Maintainer; Identity Maintainer; SDK/Contract Maintainer; Policy Maintainer; Release Maintainer; Migration Safety Reviewer

Approval pull request: [#26](https://github.com/sahinkhan/businessos/pull/26) — MERGED as `a1f1bd16ad72369dbfa88b2565c9b143590404b3`

Approved semantic proposal SHA: `176cd4c49d6c787d4d841cd44bfcbd6269a29f9f`

Final acceptance candidate SHA: `28e18939822350dde0b71f30bf0008477be1eb35`

Proposal owner attestation: [@sahinkhan's exact-proposal attestation](https://github.com/sahinkhan/businessos/pull/26#issuecomment-5808042233) — Solo Maintainer Owner Attestation; independent human review NOT PERFORMED

Review model: SOLO MAINTAINER OWNER ATTESTATION by `@sahinkhan`

Independent human review: NOT PERFORMED

Proposal independent technical/read-only review: PERFORMED — PASS; Critical 0; High 0; Medium 0; Low 0

Proposal exact-head CI: [35953594084](https://github.com/sahinkhan/businessos/actions/runs/35953594084) — PASS

Final owner acceptance attestation: COMPLETE — [@sahinkhan's exact-candidate attestation](https://github.com/sahinkhan/businessos/pull/26#issuecomment-5811086802)

Independent technical/read-only acceptance review: PERFORMED — PASS; Critical 0; High 0; Medium 0; Low 0

Acceptance exact-head CI: [35976420287](https://github.com/sahinkhan/businessos/actions/runs/35976420287) — PASS (`python-quality`, `windows-typing`, `web-quality`)

Accepted main merge SHA: `a1f1bd16ad72369dbfa88b2565c9b143590404b3`

Authoritative reconciliation baseline: [main `0b88bdfcc9be257096f62b07467eb61b72c6a185`](https://github.com/sahinkhan/businessos/commit/0b88bdfcc9be257096f62b07467eb61b72c6a185)

Accepted prerequisites and compatibility: ADR-014 — ACCEPTED / AUTHORITATIVE / EVIDENCE CLEAN; ADR-015 — ACCEPTED / AUTHORITATIVE / EVIDENCE CLEAN; ADR-018 — ACCEPTED / AUTHORITATIVE / EVIDENCE CLEAN. ADR-017 remains PROPOSED and is not a current acceptance prerequisite.

Implementation/certification gates carried forward: Audit write-facade v2, `AuditAppenderV2`, Policy security-outbox materialization, trusted worker/service-principal binding adapter, immutable origin/causation envelope, on-behalf-of provenance v2, checksum/integrity v2, and safe v1 shim are NOT IMPLEMENTED; a new forward Audit migration is NOT CREATED. ADR-014 Policy V2, ADR-015 classification runtime, and the ADR-018 Platform/SDK extension are NOT IMPLEMENTED. The Audit appender must use trusted provider registration and generation admission, and implementation must stop for a separate governed architecture decision if satisfying trusted binding or provider lifecycle requires a frozen runtime change. Phases 0–3 remain FINAL PASS / FROZEN with no general reopening.

Formal authority: ACCEPTED / AUTHORITATIVE ON MAIN until the exact ADR-019 acceptance candidate receives final owner attestation and is merged; then SUPERSEDED by ADR-019. ADR-019 incorporates every ADR-016 Audit V2 decision except the worker-binding model it replaces. ADR-016 Audit V2 runtime remains BLOCKED until ADR-019 workload identity runtime is implemented and certified.

Supersedes: None

Superseded by: [ADR-019 — Trusted Workload Identity and Tenant-Bound Worker Execution](ADR-019-trusted-workload-identity-and-worker-execution.md) upon formal acceptance on `main`

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
`RecordAuditLogV2` boundary and two explicit ingestion paths. An ordinary
authenticated request derives actual `(principal_type, principal_id)`, tenant,
and authentication/session binding from verified `RequestContext` and the
frozen Identity contract. Caller actor/type/tenant fields cannot override
that identity; same-UUID/different-type claims fail. Audit supplies a trusted
server event instant. The caller supplies only authorized action/resource,
bounded business evidence, and outcome. Missing or inconsistent actor/tenant
binding denies the write.

### Path A: current-transaction appender

Audit owns and registers the public typed `AuditAppenderV2` provider port for
modules that may depend on Audit, including Data Governance and later business
modules. It accepts the caller's verified request/execution context, active
restricted `HandlerTransaction`, and validated evidence, and appends an Audit
row using **that transaction**. It does not invoke ordinary command dispatch,
open a second unit of work, or commit. The owning handler retains the
transaction and permission boundary; the appender verifies tenant/context,
the calling module's declared Audit capability, and backend
`foundation.audit.write` authority before append. Caller code cannot select
an alternate appender provider: the framework resolves Audit ownership from
trusted registration. If the owner rolls back, the Audit row
and any outbox event roll back. The existing dispatcher creates a separate
unit of work for each ordinary command, so `RecordAuditLogV2` cannot be
implemented as a nested dispatched command for this path. The provider is
resolved through the framework's existing dependency/provider mechanism;
the design requires no frozen Phase 1 runtime change.

### Path B: lower module outbox evidence

Policy is a dependency of Audit and **must not call or depend on Audit**.
For Policy-originated evidence, Policy emits a versioned security event into
its own transactional outbox using the existing framework event contract.
Audit, as an allowed downstream consumer of Policy, materializes an Audit row
after commit with idempotency keyed to the immutable source event ID. The
outbox event is transaction-bound evidence; the final Audit projection is
asynchronous and cannot be described as a row committed in Policy's unit of
work. Delivery failure leaves durable retryable outbox evidence and an
observable materialization lag, not a fictional completed Audit row. The
event payload carries authenticated origin provenance and a versioned schema,
not caller-asserted actor fields. No Audit -> Governance, Policy -> Audit, or
private cross-module import is introduced. Subject to acceptance of companion
ADR-014, this path records Policy decisions; subject to ADR-017, Path A can
record Governance purge actions.

### Interactive, worker, and support actors

The actual actor of a worker action is the **verified worker/service
principal executing that attempt**, not the original triggering person.
Current worker and job contexts do not themselves prove Identity binding:
before v2 audit ingestion, an Audit/Identity-owned adapter at the consumer
handler boundary verifies the executing service account against the
registered Identity principal and trusted deployment credential, then binds
it to that request/tenant through the existing Identity binding contract.
The frozen worker's configured ID and event headers alone are insufficient;
the adapter is a Phase 4 integration around the generic worker, not a change
to worker context construction. If binding is absent, ingestion fails closed
and the job/event remains retryable; no ambient `system` fallback is allowed.
System maintenance likewise runs as a registered service-account principal
with installation-scoped purpose from trusted runtime configuration/Identity
registry, not a free-form `system` principal type or actor string (the frozen
binding admits `user`, `service_account`, and `device`).

An immutable internally produced event/job envelope may separately carry
`originating_actor`, causation event ID, job/message ID, tenant, and origin
authentication provenance. The producer binds origin from verified context
at enqueue/publish time; an external or mutable header is not origin proof.
Workers propagate only a verified internal envelope, and Audit validates its
source/integrity and tenant before recording it. A retry records the current
verified worker as actual actor and preserves the immutable origin/causation
identity; it never invents a new human actor. One logical business event
materializes once under event-ID idempotency; distinct attempts, if audited,
have separate attempt IDs and outcomes without duplicating that logical
event. The required envelope and binding are Phase 4 integration contracts,
not a claim that frozen workers already supply them. If they cannot be
integrated without modifying frozen runtime, implementation stops for a
separate architecture decision.

Support or administrative on-behalf-of activity records **both** the actual
verified actor and target `(principal_type, principal_id)` separately. It
records trusted grant reference, reason, scope, and time where the accepted
Policy/Identity support contract supplies them. The target never replaces
actual actor; free-text claims cannot establish a support grant. Audit may
validate through public Policy evidence, consistent with its existing Policy
dependency, and never reads Policy private tables.

Correlation ID and trace context are diagnostic/causal metadata, not
authenticated principal identity or authorization authority. Inbound
client-provided IDs may be validated/sanitized, namespaced or replaced, and
recorded with a source marker. Their presence in trusted `RequestContext`
does not make the original string an authenticated claim. They may be
integrity-covered without being promoted to actor provenance.

Existing append-only/immutability controls remain. A versioned deterministic
canonical checksum encoding covers tenant/scope, actual typed actor,
on-behalf-of subject and support reference, verified origin actor and
causation where present, job/message/attempt identity, action/resource,
outcome/evidence, event instant, correlation/trace values **and source**, and
the prior-chain checksum. Verification selects the correct encoding version
for historical rows and never rewrites or falsely upgrades legacy actor
assurance. Secrets and raw sensitive values are excluded or minimized.

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
