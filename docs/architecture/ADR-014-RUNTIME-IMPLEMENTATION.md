# ADR-014 Policy V2 runtime implementation candidate

Base main: `a9a505858a7017f958b4f2090f3342e6dd986927`. This document describes
the `phase4/adr014-policy-v2-runtime` candidate. It does not alter the accepted
ADR-014 semantic decision or certify the candidate by itself. The ADR-018
Platform/SDK owner registry prerequisite is implemented and merged on the base.

## Public contracts and owner integration

Policy publishes `foundation.policy.authorization.v2`,
`foundation.policy.field-policy.v2`, and
`foundation.policy.approval-authority.v2`. The executable port is the
request-scoped `POLICY_AUTHORIZATION_V2` dependency. Its methods receive the
existing `RequestContext`, `HandlerTransaction`, canonical `ResourceLocator`,
and (for a mutation or approval) immutable `AuthorizationOperationFactsV2`.
The port opens and finishes no unit of work. Presentation and read results
contain evidence only. Mutation and approval results expose a one-use permit
bound to that request, transaction, typed actor, canonical locator, action,
and owner-normalized operation. The permit is never serialized or reused by a
worker.

The owning handler obtains its record lock and normalized operation through
its ADR-018 facts provider's optional `read_locked_facts` method. A V2 decision
requires that method; a provider implementing only `read_facts` fails closed.
The provider returns canonical `ResourceOwnerFacts` with
`facts.normalized_operation` containing exact `action`, `amount` (`Decimal`),
`currency`, `quantity` (`Decimal`), `target_state`, and published attributes.
Policy rejects unsupported fact shapes, mismatched owner identity, missing
operation, or a difference between owner-normalized and requested operation.
The Platform registry verifies that a commit-bound call comes from the
current canonical owner handler and generation. Owner business invariants and
the actual mutation remain owner responsibilities. The handler calls
`permit.apply(operation, owner_apply)` before the outer dispatcher commits;
`owner_apply` must apply that exact operation under the held owner lock and
return the normalized operation actually applied. The permit rejects a
different return before outbox evidence is written; the owner transaction
must roll back on that error.
Policy re-evaluates live authority at `apply`, and the successful decision
emits bounded versioned outbox evidence in the same transaction. Rollback
discards both the mutation and evidence. Owner handlers must not use a read
decision as commit authority.

The Policy module constructor accepts a trusted action-to-canonical
`(namespace, contract_version)` map. Unmapped, conflicting, or mismatched
actions deny. The default map is empty until a consuming owner is certified.
The ADR-010 Organization delegation action map and tenant advisory lock key
remain unchanged.

## Combined lock order

For an ordinary owner commit: ADR-018 generation admission; owner record lock
and normalized facts; ADR-010/011 Policy tenant advisory lock; Identity
membership shared row locks; Policy role/assignment/delegation/approval reads;
owner mutation; outer framework commit. The owner facts provider must lock and
re-read current facts after any wait. Policy-only authority writers acquire
the tenant advisory lock before Policy rows and never later acquire an owner
record lock. The V2 port therefore does not invert ADR-010/011's order.

ADR-017 destructive coordination remains a separate implementation. Its
entity gate and subject lock precede the owner record lock. A future combined
destructive path must place any Policy tenant lock after the owner lock and
before Identity and Policy authority rows, while preserving Governance's
policy-scope lock order. That entire path must be certified with concurrency
tests before ADR-017 implementation; this candidate does not claim it is
already certified.

## Identity, time, classification, and approval

Policy resolves Identity's request-bound `AUTHENTICATED_PRINCIPAL` and
same-transaction `MEMBERSHIP_AUTHORITY`. Principal type and UUID, tenant, and
request object must match exactly. One internal UTC instant is used for a
decision; the caller cannot supply it. Identity's additive `lock_current`
operation locks the membership row first, then captures and validates that
instant, so a row-lock wait cannot revive expired authority. Existing
`lock_many` behavior for ADR-010/011 consumers is unchanged. Effective windows
are half-open.
Role assignment lookup includes tenant, principal ID, and principal type;
legacy `NULL` type rows do not authorize. Owner facts supply organization and
ABAC values. Delegation roots require typed live membership and a bounded
typed live authority chain.

Field access requires Policy's `PolicyClassificationFactsProvider` port, a
canonical classification owner projection, live role permission, and an
explicit field allow. Missing or ambiguous classification and missing field
rules deny. There is no Policy dependency on Governance storage. The
production classification provider is not installed until ADR-015 runtime;
classified fields therefore fail closed. Owner/Party redaction continues to
apply independently.

Approval uses an exact owner-normalized `Decimal` and uppercase currency,
typed live role authority, and same-transaction limit lookup. V2 disables
bare-UUID direct subject limits; historical rows remain stored but cannot
authorize. No currency conversion is implied.

## Forward migration and V1 transition

`policy_0004` adds nullable `support_principal_type` and
`approved_by_type` columns with type checks and bounded V2 indexes. It does
not guess the type of any historical row. Existing Policy tenant RLS and
`FORCE ROW LEVEL SECURITY` remain in place. Downgrade checks for typed rows
and refuses before dropping provenance-bearing columns. A newly created
support grant requires an explicit target principal type and derives the
approver's type and identity from Identity's trusted binding. Live V2 support
authorization matches the actual typed actor, trusted tenant, current
membership and internal instant; untyped, revoked, or expired grants deny.

The V1 symbols remain importable and the three V1 contract names remain
registered. The registered V1 evaluator and the four live V1 authorization
queries return a controlled `policy_v1_retired` error. This is an early
support-window shortening for those live entry points. A safe shim cannot
recover canonical owner/record identity, typed actor, and normalized
operation from their caller-controlled request shapes. Existing consumers of
those queries must move to the V2 port (or V2 read path) before rollout.
Security and Release owner review of this explicit compatibility exception is
required before certification. Pure V1 model helpers remain for historical
tests and the separately certified ADR-010 adapter; they are not registered
as live authorization contracts.

## Remaining certification gates

The exact candidate SHA, local validation, CI run, and independent audit will
be recorded in the PR. ADR-015 classification storage/provider, ADR-016 Audit
V2, ADR-017 retention/hold/purge, and the later preventative SoD remediation
batch remain unimplemented. This candidate does not reopen Phases 0–3.
