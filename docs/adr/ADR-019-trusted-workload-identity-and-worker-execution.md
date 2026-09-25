# ADR-019: Trusted Workload Identity and Tenant-Bound Worker Execution

Status: ACCEPTED

Decision date: 2026-09-25

Acceptance stage: COMPLETE

Approving roles required: Architecture Maintainer; Platform/Kernel Maintainer; Identity Maintainer; Security Maintainer; SDK/Contract Maintainer; Audit Owning Domain Maintainer; Release Maintainer; Migration Safety Reviewer

Approval pull request or commit: [PR #38](https://github.com/sahinkhan/businessos/pull/38) — MERGED

Approved semantic proposal SHA: `33ed51422d6845373c4877bb3e94220e6f3e0cfa`

Proposal owner attestation: [@sahinkhan's exact-proposal attestation](https://github.com/sahinkhan/businessos/pull/38#issuecomment-5826426747) — personally posted for `33ed51422d6845373c4877bb3e94220e6f3e0cfa`

Review model: SOLO MAINTAINER OWNER ATTESTATION by `@sahinkhan`

Independent human review: NOT PERFORMED

Proposal independent technical/read-only architecture review: PERFORMED — PASS; Critical 0; High 0; Medium 0; Low 0

Proposal exact-head CI: [BusinessOS run 36091055099](https://github.com/sahinkhan/businessos/actions/runs/36091055099) — PASS (`python-quality`, `windows-typing`, `web-quality`)

Formal acceptance candidate SHA: `3871616573ef1da260ea054c1fea22d2d191ffb3`

Formal acceptance exact-head CI: [BusinessOS run 36092922086](https://github.com/sahinkhan/businessos/actions/runs/36092922086) — PASS (`python-quality`, `windows-typing`, `web-quality`)

Formal acceptance independent technical/read-only review: PERFORMED — PASS; Critical 0; High 0; Medium 0; Low 0

Formal acceptance owner attestation: COMPLETE — [@sahinkhan's exact-candidate attestation](https://github.com/sahinkhan/businessos/pull/38#issuecomment-5826640389)

Accepted main merge SHA: `6c3d8635fa01d62a3d37fe4296fd4bdbc3ade864`

Architecture state: ACCEPTED; ADR-018 Resource Ownership, ADR-014 Policy V2, and ADR-015 Classification V2 runtimes are IMPLEMENTED / CERTIFIED / MERGED. ADR-019 installation workload identity, tenant execution binding, and EventWorker additive binding are NOT IMPLEMENTED; Identity workload forward migration is NOT CREATED. Audit V2 runtime is NOT IMPLEMENTED and remains blocked on ADR-019 runtime implementation and certification; ADR-017 is NOT IMPLEMENTED; V1 retirement is NOT PERFORMED. Architecture acceptance alone does not certify Audit V2 runtime. Required order: ADR-019 runtime certification, then Audit V2 implementation and certification under ADR-019 authority.

Frozen-phase state: Phases 0–3 remain FINAL PASS / FROZEN. This decision authorizes only the narrow additive Platform/Kernel and Identity integration required for Phase 4; it does not generally reopen Phase 1 or Phase 2.

Formal authority: ACCEPTED / AUTHORITATIVE ON MAIN

Supersedes: [ADR-016 — Trusted Audit Provenance and Write Contract V2](ADR-016-trusted-audit-provenance-v2.md); all ADR-016 decisions except its worker-binding model are incorporated and preserved in this successor.

Superseded by: None

## Context and boundary

[ADR-016](ADR-016-trusted-audit-provenance-v2.md) requires an Audit event
consumer to record the verified service principal executing the attempt as
its actual actor. Its implementation stopped because the current generic
`EventWorker` subscribes to `businessos.events.tenant.>` and uses one
configured `installation_id`, `principal_id`, and permission list to construct
tenant `RequestContext` values. That configured UUID is an assertion, not
proof of credential possession. The current Identity `SERVICE_ACCOUNTS` rows
are tenant-owned; one row cannot authenticate a worker for every tenant it
serves. `MembershipAuthority` proves a typed tenant membership at an instant,
not possession of the account credential. Matching broker headers and event
payload cannot authenticate the worker or the originating actor. The current
worker's configured permission evaluator also does not turn its ID into an
authenticated principal.

This decision covers durable event workers, framework jobs when they execute
without an interactive principal, and future installation maintenance workers.
It establishes only the non-interactive identity prerequisite for ADR-016.
It does not redesign ordinary tenant service accounts, users, OIDC/SAML,
Policy V2, resource ownership, event meaning, workload orchestration, or a
Cloud Control Plane. BusinessOS has not made a production or Stable customer
release; a possible V2-only baseline and V1 retirement require a separate
decision. No V1 contract is retired here.

## Decision

Choose an **installation-scoped workload identity**, verified deployment
credential, and separately authorized **tenant execution binding**. Identity
owns the public verification and binding contracts. A workload has stable
`(installation_id, workload_id)` identity, typed `service_account` for audit
actor classification, declared purpose and process class, active/revoked
state, and credential reference, generation, rotation and revocation
metadata. Its identity namespace is installation-scoped and disjoint from
tenant `SERVICE_ACCOUNTS`, even if UUID values collide. It is not a tenant
membership. The exact persisted form and forward Identity migration are
implementation decisions after acceptance; implementation must not put a
global workload into a tenant-owned service-account table or infer a tenant
from its ID. An installation maintenance workload may have a distinct narrow
purpose, but no ambient `system` actor or superuser grant.

### Identity-owned verification

A versioned Identity-owned public `WorkloadCredentialVerifier` (name subject to
SDK review) receives a protected deployment credential proof and the claimed
installation/workload, purpose, and runtime process class. It establishes
credential possession through a configured provider, then checks the
registered workload's installation, active state, allowed purpose and process
class, credential reference and current generation/epoch. It returns an
immutable `VerifiedWorkloadIdentity` with those claims, proof method/reference
and a bounded validity interval, never the raw secret. A supplied UUID,
process name, broker header, database role, or previously created
`RequestContext` alone cannot produce this result. Verification failure
cannot fall back to an ordinary user, tenant service account, device, or
`system` identity.

The credential adapter is provider-neutral: a reviewed secret manager,
read-only container/file secret, deployment-approved environment injection,
or later workload OIDC/mTLS/Kubernetes identity can furnish proof. The first
implementation may choose the smallest secure provider available to
BusinessOS. The adapter must bind proof to the registered credential
reference/generation and process; a matching public reference string alone
does not prove possession. Raw credentials and tokens must not enter
`RequestContext`, `DomainEvent`, outbox/broker payload or headers, Audit rows,
logs, traces, or exception text. The verifier exposes only bounded non-secret
assurance metadata. Credential material stays in the isolated worker and
approved secret provider, not in ordinary module configuration.

### Tenant execution and authorization

For each delivery, the worker first authenticates its installation workload.
The framework then establishes an Identity-owned, immutable
`TenantExecutionBinding` for the **specific** trusted tenant, event/message,
handler attempt, purpose `event-delivery`, and active handler transaction.
The tenant comes from the validated durable delivery boundary. Before
tenant binding or subscriber invocation, the worker checks the **whole**
delivered event against its committed outbox record or equivalently
authenticated producer evidence: event ID, tenant, type, schema version,
occurred-at/causation and origin envelope, and the complete payload. A
versioned canonical digest or exact canonical payload comparison must reject
duplicate JSON keys, ambiguous encodings, and altered fields; matching an
event ID alone is insufficient. Installation comes from the trusted source
store/deployment ownership or an authenticated source field, never a broker
header. The implementation must provision source verification without
granting a subscriber arbitrary outbox mutation or cross-tenant reads. A
job similarly checks its full trusted scheduled job record and purpose.
Header/payload agreement alone is insufficient to authenticate either
source. A tenant mismatch, unknown or changed source,
wrong installation, wrong purpose, or reuse in another request, task, tenant,
subscriber, or transaction fails closed. The binding expires at the end of
that attempt. It cannot be copied into a new transaction as an authority
token.

The binding is a **distinct** Identity execution contract, not a fabricated
tenant `PrincipalIdentity` or `AuthenticatedPrincipalBinding` and not a
tenant `MembershipRecord`. Existing `TenantContext.principal_id` in the
worker's request is a compatibility/routing value only and must never be used
as proof of workload authentication or tenant membership. The minimal
additive framework integration passes the verified binding alongside the
existing request and restricted `HandlerTransaction`, or exposes it through
a versioned request-scoped Identity dependency tied to those exact objects.
Existing `RequestContext` and `TenantContext` meanings for interactive
principals remain unchanged. If an additive field is necessary, it is
explicitly versioned; a silent reinterpretation of `principal_id` is
forbidden. The generic worker may need a narrow additive credential/binding
hook and delivery admission boundary. This ADR proposes that exception for
Phase 4 only; implementation must review its lifecycle and conformance tests
before changing frozen platform code.

Authentication grants no tenant data permission. The dispatcher and Identity
binding must require the registered durable subscriber, its declared
permission/capability, the workload's authorized purpose and process class,
the trusted event tenant, and the exact handler transaction. The configured
permission list may narrow authority but cannot authenticate a workload or
grant permissions absent from the registered subscriber and deployment grant.
No installation-wide tenant superuser permission is implied. A handler
requiring ordinary tenant membership must still use a real tenant principal;
the execution binding cannot satisfy that requirement by masquerading as
one. Deny unsupported authorization paths until a specific typed workload
policy contract is reviewed.

The same installation workload also runs pre-delivery operational work:
subscriber-obligation synchronization and publication of committed outbox
rows across tenants. Those operations do **not** receive tenant execution
bindings or business permissions. Startup authenticates the workload before
subscription, obligation writes, or publisher launch. Each operational
batch revalidates the active workload and a separately approved purpose
(`subscriber-sync` or `event-publisher`) through the Identity verifier;
the existing narrow operations database role remains necessary but is not
identity proof. The worker may publish only previously committed outbox
rows and synchronize only registered subscriber declarations. Invalid or
unavailable identity halts new operational batches, stops subscription,
and alerts operators; it does not fabricate per-tenant actor provenance.
The implementation must serialize revocation with an admitted operational
batch through the same Identity authority boundary, or demonstrate an
equivalent bounded lease with an explicit maximum revocation delay. It may
not claim the per-subscriber transaction lock alone protects publisher or
startup work.

### Freshness, rotation, and failure

Credential proof is checked for each delivery attempt; startup-only proof is
insufficient. Before **each** subscriber admission, Identity checks the
proof's validity interval and obtains fresh proof if it expired; expiration
cannot be hidden by a later subscriber in the same delivery. Identity also
rechecks the workload's active state, current
credential epoch, purpose, process class, and installation in each subscriber
transaction and holds a shared authority lock through that transaction's
commit or rollback. Disable, revocation, rotation, and purpose changes take
the conflicting update lock: an already admitted transaction completes before
the change commits, while a later admission sees the new state. Thus the
revocation bound is **the end of an already admitted transaction**; no new
transaction is admitted after the revocation commits. A credential rotation
invalidates old-generation proof for subsequent attempts. Cached proof may
only be used within the current attempt and never across delivery attempts.
The implementation must bound handler duration and alert on stuck admissions;
it must not silently extend an authenticated lease forever.

Unavailable verifier, secret provider, Identity store, or authorization store
is a transient processing failure: do not acknowledge successful handling;
leave the event/job retryable. Invalid, revoked, expired, wrong-installation,
or wrong-purpose credentials quarantine/stop that worker and alert operators;
the event remains unacknowledged for recovery by a valid worker. Repeated
invalid credentials are not reclassified as a poison **event** and cannot
produce trusted Audit provenance. A malformed event may follow the separate
permanent-delivery policy only after workload authentication; that policy
must never turn authentication failure into successful processing. Existing
durable inbox claims and side effects remain in the same subscriber unit of
work, so a failure rolls back the claim and retry can proceed. A delivery with
some already committed subscribers relies on their inbox receipts to avoid
duplicate effects after retry.

### Audit and origin provenance

ADR-016 records `actual_actor` as the verified installation workload,
including type, scope, installation/workload ID, purpose, credential proof
reference/generation, and tenant execution binding reference as appropriate.
It does not claim an ordinary tenant membership. `originating_actor`, when
present, is the separately verified producer principal from ADR-016's
internally produced immutable origin/causation envelope. Source event ID,
causation ID, message ID, and attempt ID remain distinct. A broker-controlled
header, free-form event field, or target/on-behalf-of actor cannot overwrite
the actual workload. Audit must fail closed and leave materialization
retryable when the workload binding is absent. No raw credential is stored.

This **replaces** ADR-016's instruction to bind the worker through the
existing tenant `AuthenticatedPrincipalBinding`, because that unversioned
projection cannot distinguish an installation workload from a same-UUID
tenant service account. It also replaces ADR-016's expectation that this
adapter needs no generic worker-context change: the narrow additive hook
above requires explicit Platform/Kernel approval and certification. Until
ADR-019 is formally accepted, ADR-016 remains authoritative and its runtime
implementation remains stopped. At acceptance, ADR-019 becomes ADR-016's
successor under [ADR governance](../governance/ADR-GOVERNANCE.md); the same
reviewed acceptance change must mark ADR-016 `SUPERSEDED` with a reciprocal
link. ADR-019 expressly incorporates and preserves all other ADR-016
decisions, including the V2 write-facade, trusted interactive actor, Path A
same-unit-of-work appender, `Policy -> Audit: NONE`, postcommit Policy outbox
materialization and idempotency, immutable origin and support provenance,
versioned checksum, append-only/tenant controls, and safe V1 transition.
The replacement of worker binding does not change those requirements.
ADR-019 is a prerequisite for implementing Path B worker ingestion, not
itself an Audit implementation or claim that Audit V2 is certified.

## Options considered

| Option | Assessment |
| --- | --- |
| A. Trust configured `principal_id` | Rejected: an identifier and permission list do not prove credential possession or tenant membership. |
| B. One tenant service account and worker process per tenant | Possible deployment isolation, but requires tenant-by-tenant credential and process lifecycle, scales poorly for shared-schema fleets, and still needs credential verification and rotation. It may be a deployment choice, not the common identity contract. |
| C. Broker/header worker identity | Rejected: headers describe a delivery and can be changed outside Identity; they cannot authenticate the executing process. |
| D. Installation workload identity plus verified credential and tenant execution binding | Chosen: matches one multi-tenant worker process, preserves tenant isolation without false membership, and supports self-hosted and cloud credential providers. It requires a narrow additive worker/Identity/SDK boundary. |
| E. Cloud-only mTLS or OIDC workload identity | Strong option for a capable deployment, but as the sole model excludes self-hosted installations and couples the architecture to a control plane. These can implement D's verifier adapter later. |

## Impact and cross-ADR review

| Decision | Compatibility check |
| --- | --- |
| [ADR-005](ADR-005-transactional-outbox.md) | Committed outbox evidence remains durable; subscriber effects and inbox claim share a transaction. Authentication failure cannot acknowledge a delivery. |
| [ADR-008](ADR-008-python-asgi-technology-baseline.md) | The Python/ASGI modular runtime remains; only an explicit additive worker/Identity binding is proposed. |
| [ADR-010](ADR-010-delegation-action-authority-boundary.md), [ADR-011](ADR-011-transitive-delegation-authority.md) | A workload execution binding is not a user delegation or typed tenant membership and grants no delegated authority. |
| [ADR-014](ADR-014-trusted-policy-decision-context-v2.md) | Interactive typed principal and Policy commit authority remain unchanged; workload permissions require separate typed authorization, not a forged `AuthenticatedPrincipalBinding`. |
| [ADR-015](ADR-015-data-classification-ownership-and-tenancy.md) | Tenant comes from the trusted delivery/job boundary; classification ownership and cross-tenant isolation remain intact. |
| [ADR-016](ADR-016-trusted-audit-provenance-v2.md) | Supplies the previously missing actual-worker proof; origin stays separate; Path A and Policy postcommit Path B semantics remain. |
| [ADR-017](ADR-017-retention-hold-and-purge-coordination.md) | A destructive job can record workload, tenant, purpose, origin, and causation, then re-run Governance's transaction-bound authority. The binding itself grants no purge privilege. |
| [ADR-018](ADR-018-canonical-resource-ownership-and-owner-operation-boundary.md) | Canonical owner/provider generation and exact transaction admission remain mandatory; workload binding does not mint an owner or coordinator token. |

Identity owns workload registration, credential verification, and tenant
execution binding. The protected platform owns generic delivery context,
admission, transaction and dependency lifecycle; Audit consumes the public
Identity contract. Audit does not read Identity private tables. Policy does
not depend on Audit. No Data Governance dependency is added to Audit. This
maintains the downward layer direction.

Tenancy/security impact: installation identity is shared by design, but
each operation receives only one tenant binding and a checked subscriber
permission. Every tenant-owned database access still uses tenant RLS and
trusted tenant context. A stolen credential has the bounded purposes and
configured process class of that workload; operators must revoke/rotate it
and investigate affected tenant attempts. Credential and binding IDs are
non-secret references, not authorization by themselves.

Migration/data impact: an implementation will likely require a new forward
Identity-owned workload registration and credential-epoch schema, with
installation ownership distinct from tenant service accounts. Migration
Safety Reviewer participates in this ADR and reviews the later migration.
No existing tenant service-account row is
relabelled, copied, or auto-mapped to installation scope; any transition is
explicit, reviewed, and auditable. This ADR changes no schema or runtime.

Compatibility/release impact: new versioned Identity/SDK contracts and an
additive worker hook are required. Existing `RequestContext`, tenant
`PrincipalIdentity`, and V1 contracts are not silently reinterpreted or
removed. The current configured-ID worker route cannot certify ADR-016 Audit
V2 ingestion until the new binding and authorization gate are implemented.
Self-hosted operators need a deployment credential provider and installation
workload registration; cloud deployments may use the same contract with
managed workload identity. No production release migration is claimed.

## Approval and implementation gates

The role union follows [ADR governance](../governance/ADR-GOVERNANCE.md)
and [maintainer ownership](../governance/MAINTAINERS.md). Architecture,
Platform/Kernel, Identity, Security, SDK/Contract, Audit owning domain, and
Release, and Migration Safety Reviewer roles must approve the exact candidate.
The installation workload registry and credential epoch require Identity
schema ownership review even though the exact forward migration is deferred.
This proposal
authorizes no implementation, migration, ADR-016 restart, ADR-017 work, or
V1 retirement. Phases 0–3 remain FINAL PASS / FROZEN with only the narrowly
reviewed additive Phase 4 boundary proposed here; no general reopening.

Acceptance requires exact-revision owner evidence, passing exact-head CI,
independent read-only audit with no unresolved trust ambiguity or findings,
the reciprocal ADR-016 supersession metadata in the same reviewed acceptance
change, and merge to main through the governance procedure. This proposal
remains `PROPOSED` pending those steps. Implementation must
prove: wrong installation/purpose/process/credential generation denial;
same-UUID tenant/workload separation; credential rotation and revocation
serialized with in-flight transactions; multi-tenant isolation; missing
verifier/secret-store retry; no success acknowledgement or Audit assertion
on auth failure; no raw-secret persistence; source event/job verification;
subscriber permission separation; origin/actual actor distinction; and
ADR-014/016/017/018 plus frozen-phase regression. An implementation that
cannot satisfy those gates needs another explicit architecture review.
