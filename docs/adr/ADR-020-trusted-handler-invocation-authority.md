# ADR-020: Trusted Handler Invocation and Module Authority

Status: PROPOSED

Decision date: Pending formal acceptance

Approving roles required: Architecture Maintainer; Platform/Kernel Maintainer; SDK/Contract Maintainer; Security Maintainer; Audit Owning Domain Maintainer; Release Maintainer

Approval pull request or commit: Pending

Review model: Pending; proposal authorship is not approval evidence

Independent human review: NOT PERFORMED

Independent technical audit: Pending

Formal authority: NONE — this proposal does not authorize implementation

Supersedes: None

Superseded by: None

Related decisions: [ADR-005](ADR-005-transactional-outbox.md), [ADR-008](ADR-008-python-asgi-technology-baseline.md), [ADR-014](ADR-014-trusted-policy-decision-context-v2.md), [ADR-015](ADR-015-data-classification-ownership-and-tenancy.md), [ADR-016](ADR-016-trusted-audit-provenance-v2.md), [ADR-017](ADR-017-retention-hold-and-purge-coordination.md), [ADR-018](ADR-018-canonical-resource-ownership-and-owner-operation-boundary.md), and [ADR-019](ADR-019-trusted-workload-identity-and-worker-execution.md)

## Context and current gap

At main `d551a5c0baf559b237a61e764d1194697ceaf12e`, Audit V2 Path A remains blocked. The dispatcher has trusted handler registration facts: owner module ID, exact `ContributionGeneration`, permission, and coordinator token where applicable. `ModuleRegistration` has the registration-time owner, exact generation, and admitted `ModuleManifest`. `ModuleRegistry` validates direct dependency declarations, version compatibility, enabled dependencies, and lifecycle state. `ContributionGate` controls generation admission and drain. These facts reside in protected runtime components.

The public `HandlingContext` exposes `RequestContext`, `RequestDependencyScope`, and restricted `HandlerTransaction`. It supplies no trusted binding that jointly proves the active handler owner, exact generation, exact request and transaction objects, bounded invocation lifetime, and direct dependencies from the admitted manifest. `RequestContext` identifies the request, principal, and tenant; it does not identify the executing module. Resolving a `DependencyKey` or finding a provider does not prove which module's handler called it. Inspecting the current module registry without an invocation binding would not prove the active transaction or generation. Consequently, Audit cannot certify that a Path A appender call came from an admitted handler of a module that directly depends on `foundation.audit`.

The next pre-1.0 V1 runtime-elimination decision is reserved for ADR-021; this proposal does not create or decide it.

## Proposed decision

Introduce a generic, additive Platform/SDK `HandlerInvocationBinding` for trusted first-party in-process handlers. Its purpose is to prove: **this call is executing inside this exact admitted module handler, under this exact activation generation, request, and restricted transaction**. Audit will consume the public contract; the protected framework owns issuance and lifetime. The binding is not an actor identity, authorization decision, tenant execution credential, or transferable token.

### Issuance and immutable facts

Only the protected dispatcher may issue a valid binding after capturing the registered handler and entering its existing `ContributionGate.admit(generation)` lease. It takes the owner and generation from that captured registration, and an immutable snapshot of direct dependency module IDs and version constraints from the trusted manifest admitted for **that same generation**. The snapshot is retained with the registration or resolved through a framework-owned, exact-generation lookup; it must not be reconstructed from caller-supplied values or a later replacement manifest. Existing manifest dependency/version and enabled-state checks remain authoritative. The binding exposes only read-only owner module ID, safe immutable generation identity, invocation kind, and direct dependency facts. It exposes no mutable registry, manifest object, coordinator token, or mutation handle.

The implementation uses a framework-private issuer and a revocable, invocation-local lease (or an equivalent opaque construction) so a module cannot make an authoritative binding by filling in a module ID, generation number, dependency list, or permission string. An implementation must verify the issuer and live lease when the binding is used. This is a contract for trusted first-party in-process code; Python object opacity is not a sandbox against hostile code with protected-runtime access. Customer and marketplace executable code remains in isolated processes under the existing module architecture.

The initial application-service opt-in is a **direct** manifest dependency on `foundation.audit`. A transitive dependency, Audit package availability, known dependency key, matching permission string, or arbitrary provider name is insufficient. `ModuleManifest.capabilities` currently names infrastructure requirements; it is not repurposed as application authority. A later decision may add finer-grained application declarations if needed.

### Exact invocation and transaction

The public binding provides `assert_active(request, transaction, *, invocation_kind)` or equivalent. It verifies exact object identity for the active `RequestContext` and restricted `HandlerTransaction`, the private issuer and unexpired lease, and the current async task. The framework must create one transaction view for the invocation and pass that same object to `HandlingContext` and the binding. A UUID or `id()` value alone is insufficient. A different request, transaction, handler invocation, or task fails closed. The lease closes in a `finally` path when the handler returns, raises, or is cancelled; retaining or copying the binding cannot authorize later work. For this first version, detached or child tasks cannot use it, even while the parent handler is active.

The binding's lifetime is bounded by the handler call, while the dispatcher's existing generation admission and transaction remain held through commit or rollback. A handler admitted before drain may finish under its captured generation; drain stops new admissions. Replacement creates a different generation and cannot turn an old binding into new authority. An old binding expires when its handler exits and remains invalid after removal. This reuses `ContributionGate`; it creates no second lifecycle system. A failed or missing exact-generation manifest snapshot blocks issuance rather than falling back to a module name.

### Additive SDK integration

The preferred narrow SDK change is an optional trusted `HandlingContext.invocation` field populated by `MessageDispatcher` for command and query handler calls. Existing request and tenant context meanings are unchanged. The binding type and its validation operation become a published, versioned SDK contract; unversioned caller-provided data must not satisfy it. Legacy handlers that do not use the field retain their behavior, subject to existing security requirements. The first implementation may restrict issuance to dispatcher command/query paths and must certify those paths before Audit V2 resumes.

The generic contract identifies command and query invocations. Mutating `AuditAppenderV2` accepts **command** authority only and rejects `invocation_kind=query`; a query binding never becomes permission to write through a query. Event and job invocation support is an explicit additive follow-up, using the same issuer and lifetime principles if needed. ADR-019 `TenantExecutionBinding` remains the identity authority for a durable event's verified workload. A future event handler may hold both bindings: one proves the workload executing the attempt, and the other proves the admitted handler module. Neither substitutes for the other. This ADR does not alter current event/job delivery or ADR-019 binding behavior.

### Audit V2 Path A use

A future Audit-owned `AuditAppenderV2` is registered through the framework's trusted Audit-owned dependency/provider mechanism. Its public dependency key is reserved to `foundation.audit`: registration verifies the trusted install artifact's entitlement to that exact first-party module ID and rejects a different registration owner. The existing ADR-018 approved-artifact admission pattern can be reused for this narrow application-service claim; a manifest publisher string or a key prefix alone is insufficient proof. An absent Audit module cannot be replaced by another module registering the same key. This check is at protected registration/admission, not a mutable registry lookup by Audit on each append. Resolving the `DependencyKey` alone never authorizes an append. On **every** append, the appender checks the framework-issued live binding and exact request/transaction identities; command invocation kind; the exact admitted caller owner and generation; a direct `foundation.audit` dependency in that generation's trusted manifest snapshot; and tenant equality between the request, evidence, and active transaction. Interactive actual actor identity is derived separately from Identity's exact-request `AuthenticatedPrincipalBinding`. No caller-selected module ID, actor, tenant, or provider substitutes for these checks. The appender uses the caller's exact active `HandlerTransaction`, without nested dispatch or another unit of work, and fails the owning transaction when mandatory evidence cannot be appended. Audit provider ownership and generation must be admitted by the existing framework dependency lifecycle for the duration of the call and owning transaction; a stale or caller-selected replacement provider fails closed.

For Path A, the appender performs an explicit **backend `foundation.audit.write` authority check** using the live module-side binding: it requires the active command invocation, exact generation, direct admitted `foundation.audit` manifest dependency, and the Audit-owned provider admission above. This is the module's narrowly scoped authority to append mandatory evidence in its own transaction; neither a permission string nor dependency resolution alone grants it. This specifies how the backend write-authority requirement incorporated from ADR-016 into ADR-019 is met without treating the request principal as the appender's permission holder. External/manual `RecordAuditLogV2` commands remain a separate authorization path governed by ordinary principal-based `foundation.audit.write` permission. The internal appender is module-side mandatory evidence, not end-user impersonation authority. A person authorized to perform an audited business action does not need the principal-based `foundation.audit.write` permission merely for the owning module to append required evidence. Acceptance review must explicitly confirm that this module-side interpretation preserves the incorporated ADR-016 requirement; if it is judged a material replacement, ADR governance requires a separately reviewed successor decision before implementation.

## Alternatives considered

| Option | Assessment |
| --- | --- |
| Trust caller-supplied `module_id` or manifest facts | Rejected: ordinary values do not prove a registered, admitted invocation. |
| Let Audit inspect the mutable `ModuleRegistry` directly | Rejected: cross-boundary coupling still does not bind the current handler, generation, or transaction. |
| Treat dependency resolution as authorization | Rejected: knowing or resolving a key does not identify the caller module or its direct manifest dependency. |
| Use Python stack inspection or caller introspection | Rejected: fragile, forgeable, and not a public compatibility contract. |
| Dispatcher-issued generic invocation binding | Preferred: captures the already trusted registration, manifest, generation admission, and exact transaction in one bounded proof. |
| Add an Audit-specific dispatcher special case | Rejected: protected runtime must stay generic and must not depend on Audit. |

## Impact and cross-ADR review

| Decision | Compatibility |
| --- | --- |
| ADR-005 | Path A remains in the owner's unit of work; any Audit outbox effect rolls back with that transaction. No change to outbox/inbox semantics. |
| ADR-008 | The BusinessOS framework remains the owner of dispatch, SDK, dependency injection, and transaction boundaries. The extension is additive to the Python/ASGI runtime. |
| ADR-014 | Policy V2 continues to derive principal authority from Identity and owner facts. `Policy -> Audit` remains **none**; invocation authority is not a Policy decision. |
| ADR-015 | Classification ownership, tenant isolation, and Governance's direct Audit dependency remain unchanged. |
| ADR-016 and ADR-019 | ADR-019 remains the accepted successor preserving Audit V2 semantics except the replaced worker-binding model. This binding supplies the missing Path A module proof and makes ADR-016's backend `foundation.audit.write` check explicit as a module-side appender check; ordinary manual commands retain principal-based permission enforcement. It does not replace `TenantExecutionBinding` or actual actor verification. |
| ADR-017 | A later Governance coordinator can use the Audit appender in its own command transaction because Governance directly depends on Audit. This proposal does not implement purge, retention, or hold runtime. |
| ADR-018 | Canonical resource ownership, `ResourceTransactionScope`, provider generation admission, and owner-operation rules remain intact. Invocation binding proves the **calling handler module**, a different fact from canonical ownership of a resource. No change to the ADR-018 lock order is proposed. |

The Platform owns only generic issuance and validation; Audit consumes the public binding; business and Data Governance modules consume Audit's public appender only when their manifest directly depends on Audit. Platform does not import Audit implementation. Audit does not inspect another module's private code or mutable registry at call time. No Policy-to-Audit or Audit-to-Governance dependency is introduced.

Tenancy and security: the binding adds module provenance, not tenant or principal authority. The appender must still bind trusted request tenant and Identity principal independently and preserve database RLS. A forged, stale, cross-task, cross-request, or wrong-transaction invocation denies. An absent direct dependency denies. No database role or cross-tenant permission is granted.

Compatibility and release: this is a narrowly scoped, opt-in protected Platform/SDK extension to otherwise frozen Phase 1, requiring its own implementation review and conformance tests under [release governance](../governance/RELEASES.md). Existing handlers and manifests remain valid; the new binding cannot be silently substituted for existing principal, worker, resource-owner, or permission contracts. Version and coexistence details are fixed before implementation. Phases 0–3 remain FINAL PASS / FROZEN; there is no general reopening.

Schema and migration: **none**. Module invocation is runtime authority. No audit table, historical row, migration, database token, or stored credential changes are proposed.

## Implementation and acceptance gates

This proposal authorizes no runtime work while `PROPOSED`. Formal acceptance follows [ADR governance](../governance/ADR-GOVERNANCE.md) and [maintainer ownership](../governance/MAINTAINERS.md), including exact-revision accountable role evidence, passing exact-head CI, independent read-only audit, and merge of a separate acceptance change. The role union is Architecture, Platform/Kernel, SDK/Contract, Security, Audit Owning Domain, and Release Maintainer. No Migration Safety Reviewer is required because this proposal changes no schema, migration, or data ownership. Owner attestation, if used under the temporary Solo Maintainer Exception, is personally posted by the owner and is not independent human review.

The later implementation must prove issuer and manifest provenance; direct versus transitive dependency denial; exact request/transaction/task binding; command-only Audit appender use; handler return, cancellation, detached-task, drain, removal, and generation-replacement denial; admitted in-flight completion; Audit key registration denial for an unentitled artifact or wrong owner; Audit provider lifecycle and same-unit-of-work rollback; no end-user Audit permission requirement for internal mandatory evidence; no new Policy-to-Audit edge; ADR-019 worker separation; and Phase 0–3 plus ADR-014/015/018/019 regression. If the narrow additive SDK shape cannot preserve existing behavior, stop for another explicit architecture review. Audit V2 Path A remains blocked pending formal ADR-020 acceptance and certified implementation of its generic binding. Audit V2, `audit_0003`, ADR-017 runtime, and V1 retirement are outside this proposal.
