# ADR-019 workload identity runtime implementation

## Scope and authority

Base main: `832a554e45189de9908f4cf84119e247429b7257`.
Implementation branch: `phase4/adr019-workload-identity-runtime`.
Candidate identity is the exact head of the implementation PR; it is recorded in
the certification report after the final push. This change implements the
trusted worker prerequisite accepted by [ADR-019](../adr/ADR-019-trusted-workload-identity-and-worker-execution.md).
It does not implement Audit V2, ADR-017, or V1 retirement.

## Identity authority

`identity_0004` adds `platform_identity.installation_workloads`, keyed by
`(installation_id, workload_id)`. The registry is installation scoped and
separate from tenant owned `service_accounts`. Its row carries active/revoked
state, process class, allowed purposes, a credential reference, credential
generation, a SHA-256 verifier for a high entropy deployment secret, and
creation/change timestamps. No raw credential is stored. `businessos_ops` can
provision and change the row; `businessos_app` has no direct table or admission
function access. A dedicated `businessos_worker` login inherits only the
ordinary application tenant/RLS privileges and receives the narrow
`admit_workload` function grant, which
checks current authority and holds a shared row lock in the caller's transaction.
It does not inherit operations or migrator privileges. The administrator role
transition provisions this login before migrations. `identity_0005` revokes
the candidate `identity_0004` application grant and grants worker admission;
the unmerged `identity_0004` revision was left unchanged because repository
governance does not explicitly permit rewriting candidate migrations. Downgrade
of this privilege boundary refuses while workloads exist. On an empty registry
it revokes worker admission without restoring the unsafe app grant, allowing
the earlier revision to drop the empty registry. Registry downgrade also
refuses to discard a nonempty workload registry.

Identity exports immutable `VerifiedWorkloadIdentity`, non-admissible
`WorkloadIdentityFacts`, and `TenantExecutionBinding` contracts, the `WorkloadCredentialVerifier` and
`WorkloadExecutionAuthority` ports, and a versioned dependency key. Its
database adapter verifies secret possession, reference, installation, process
class, purpose, active state, and current generation. Proof lifetime is 60
seconds. It rechecks authority in each subscriber transaction or operational
batch. A transaction bound binding names the tenant, committed source event,
subscriber, attempt, purpose, and exact handler transaction. It is invalidated
on scope exit and rejects use from another task or transaction. It is not a
tenant membership or interactive principal.
The handler-visible binding contains only the facts snapshot, never the
verified proof. Identity also compares the bound tenant with the active
transaction's `app.tenant_id` before returning a binding.

`businessos_identity.workload_operator` is the restricted provisioning CLI.
It requires the operations database role and supports registration, rotation,
disable, and process class/purpose changes. The operator supplies a secret file;
only its digest reaches the workload row. Deployment must provide a read only
secret file to the worker and set `BOS_EVENT_WORKER_WORKLOAD_ID`,
`BOS_EVENT_WORKER_WORKLOAD_CREDENTIAL_REFERENCE`, and
`BOS_EVENT_WORKER_WORKLOAD_CREDENTIAL_FILE`. The CLI and worker require a
32–4096 byte high entropy secret. Rotation increments the credential generation.

## Platform admission

The protected platform exposes a generic admission protocol and lifecycle
hook. It imports no Identity implementation or table. The standalone worker
resolves the Identity authority through the versioned dependency key. Its
outbox publisher requires an explicit admission callback; the worker supplies
the workload-authority operation for every batch, so the database role alone
cannot publish through the certified worker path. Its
configured principal UUID remains routing metadata in `TenantContext`, marked
`worker-routing-only`; it cannot authenticate the worker or create membership.
The worker authenticates before subscription startup, subscriber synchronization, each
publisher batch, and each delivery attempt. It verifies the committed outbox
source before decoding or invoking a subscriber. Each subscriber gets a fresh
transaction lock and an Identity binding before the declared permission check,
inbox claim, and handler invocation. Deployment configured permissions only
narrow the registered subscriber permission; proof does not grant arbitrary
business access. A missing permission fails admission. A separate subscriber
authorizer checks only registered durable subscribers against the deployment
permission list; the worker's general command/query authorizer denies all.
Handlers therefore cannot use the deployment list for business commands or
queries. An admitted subscriber or operational batch has a 45 second
execution bound so its authority lock cannot remain held indefinitely.

The source verifier reads committed `eventing.outbox_messages` through the
protected operations path. It compares event ID, tenant, type, schema version,
timestamp, correlation, causation, and the complete canonical JSON payload.
Strict UTF-8 JSON parsing rejects duplicate keys, nonfinite numbers, and
invalid Unicode before comparison. Broker headers and subjects are transport
metadata, never source authority. No module receives a cross tenant outbox
read capability.
The worker's runtime and operations URLs must identify the same database
endpoint, port, database, and connection options; only their roles and secrets
may differ. A deployment owns one installation per transactional database.
The operator-controlled installation ID in worker settings identifies that
database's installation; the verified Identity workload row is keyed by the
same ID. The committed outbox in that database is the trusted source-store
ownership evidence. A multi-installation database deployment needs a separate
design and is outside this certification.

Proof is obtained for every delivery attempt and renewed before a subscriber
when its remaining validity is too short for the bounded operation. Identity's
shared row lock serializes each admitted transaction or batch against operator
revocation, rotation, and authority changes. An operation admitted before an
operator change may finish; after that change commits, old generation proof is
denied. Invalid authority quarantines worker processing, closes its durable
subscription, and leaves the event
recoverable by a valid worker. Store and provider outages remain retryable;
authentication failures are not treated as poison payloads. Exceptions and
logs use nonsecret error types.

## Verification and remaining gate

Focused unit tests cover proof and binding behavior, secret exclusion, strict
source comparison, and independent field tampering. PostgreSQL integration
tests cover the Identity migration, role separation, and revocation locking.
The exact validation commands and results belong to the PR certification
report and CI run. Audit V2 remains gated on certification and merge of this
runtime batch under ADR-019 authority.
