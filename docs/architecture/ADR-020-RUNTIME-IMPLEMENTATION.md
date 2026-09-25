# ADR-020 trusted handler invocation runtime implementation

Status: implementation candidate under [ADR-020](../adr/ADR-020-trusted-handler-invocation-authority.md); certification and merge pending.

Base main: `8db3ab1a1b196f6968e573e857ddc2aab529460c`.
Branch: `phase4/adr020-handler-invocation-runtime`.
Accepted decision-body SHA-256: `7f9c3dda5debb47e1e2a7f2138bcd89adda6e2f5f97798c5c8ffebdfa11266f8`.

## Scope and public contracts

This compatible additive Platform/SDK change adds `HandlingContext.invocation`, the
`HandlerInvocationBinding` protocol, `HandlerInvocationKind`, immutable
`HandlerInvocationDependency`, and `validate_handler_invocation`. The binding is
available only to admitted command and query handlers registered through a
manifest-backed `ModuleRegistration`. A legacy direct `HandlerRegistry`
registration continues to dispatch with `invocation=None`.

`DependencyKey.required_owner` is an optional generic owner restriction.
Ordinary keys retain their existing registration and resolution behavior. A
restricted key requires an exact owner match in both `ModuleRegistration` and
`Container`. The module registration also requires a generation-bound
entitlement issued from the protected operator-supplied `ApprovedModuleArtifact`
inventory. The grant must match the exact loaded module and admitted manifest
and carry first-party approval. A key's resolution alone grants no caller
invocation or module authority.

## Issuance, identity, and lifetime

`ModuleRegistration` captures direct dependency IDs and version constraints
from its exact admitted manifest when its generation is created. It passes an
opaque provenance handle at command/query registration; the handler registry
retains an immutable tuple only when the handle matches the exact owner and
generation. The dispatcher never reconstructs dependencies from current
registry state. Missing provenance produces no binding, with no owner-name
fallback. Transitive dependencies are not added.

Inside `ContributionGate.admit`, after authorization and unit-of-work entry,
the dispatcher creates one restricted `HandlerTransaction`, binds it to the
resource transaction scope, and passes that same object to `HandlingContext`
and the invocation issuer. Protected issuance retains the exact owner,
`ContributionGeneration` object, `RequestContext` object, restricted
transaction object, current `asyncio.Task`, invocation kind, and immutable
direct dependency tuple in a private registry. The public binding exposes only
read-only facts and has no writable authority fields. The Platform validator
requires the exact issued concrete type, private registry membership, active
lease, same task, same request object, same transaction object, and requested
kind. A structural fake or caller-created instance cannot pass. The lease is
invalidated in a `finally` path immediately after handler return, exception,
or cancellation, before outer transaction commit or rollback. Protected active
facts that reference the request, transaction, and task are removed then;
only safe immutable display facts remain on a retained stale binding.
An invocation-local context marker also requires the binding to be the top
active handler in the task. Nested dispatch temporarily masks an outer
binding for its entire resolution, authorization, transaction, handler, and
commit window, including when the inner handler is a legacy registration; the outer
binding becomes usable again only after the inner handler returns.

Drain stops new generation admissions but does not invalidate a handler that
was admitted earlier; its invocation lease remains live until its handler
exits. Removal or replacement cannot reactivate a stored binding. Query
bindings validate only as queries and supply no command write authority.

## Boundaries and compatibility

The binding proves module invocation provenance. It does not replace
`RequestContext`, Identity's principal binding, ADR-019
`TenantExecutionBinding`, ADR-018 resource ownership or provider admission,
Policy authority, or a tenant permission. No event or job invocation binding
is added. No Audit appender, Audit V2 path, ADR-017 runtime, or V1 retirement
is implemented. Audit V2 remains blocked until this candidate is independently
audited, owner-attested, and merged, then its own implementation is certified.

This batch changes protected dispatcher, DI, module registration, artifact
entitlement, runtime composition, and public SDK files, plus focused tests and
this record. It does not change the database schema, migration graph, API
payloads, event contracts, or persistent state. The direct dependency tuple
is linear in the module's declared direct dependencies at registration; no
mutable module-registry lookup occurs during handler invocation or validation.

## Certification evidence

Focused tests cover valid command/query binding, forged-object rejection,
exact request/transaction identity, child-task and post-handler denial,
cancellation, drain, generation replacement, direct/transitive dependency
separation, manifest-snapshot immutability, legacy registration, and reserved
key owner/artifact checks. The exact implementation candidate SHA, local gate
results, exact-head CI, and independent read-only audit are recorded in the
implementation PR after the final push. No owner attestation is posted by this
candidate.
