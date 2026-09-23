# ADR-014: Trusted Policy Decision Context and Authorization V2

Status: PROPOSED

Decision date: Pending formal acceptance

Approving roles required: Architecture Maintainer; Security Maintainer; Identity Maintainer; Policy Maintainer; SDK/Contract Maintainer; Release Maintainer; affected Owning Domain Maintainer for each adopted facts provider; Organization Maintainer where organization scope facts are contracted

Approval pull request or commit: Pending

Supersedes: None

Superseded by: None

Extends: [ADR-010](ADR-010-delegation-action-authority-boundary.md) and [ADR-011](ADR-011-transitive-delegation-authority.md); neither is superseded

## Context

The Phase 4 Policy module registers `foundation.policy.authorization.v1`,
`foundation.policy.field-policy.v1`, and
`foundation.policy.approval-authority.v1`. Its public queries currently accept
`subject_id`, a decision `timestamp`, and caller-provided resource, record, and
field attributes. A matching UUID does not prove the principal type or the
authenticated actor. A caller-selected instant can activate expired or future
authority; fabricated facts can change ABAC, field, or approval outcomes.
The accepted [security baseline](../architecture/SECURITY.md) requires
backend-authoritative authorization, and the frozen Identity boundary already
provides a verified request-bound typed principal binding. Policy must use it.

## Proposed decision

### Live decision inputs

Policy v2 derives `tenant_id`, `(principal_type, principal_id)`, authenticated
membership/session context, and any verified support/delegation identity from
`RequestContext` and the frozen Identity principal binding. It rejects missing,
inconsistent, or unverified bindings. Caller input may describe an action and
resource locator but cannot choose another principal or tenant. UUID equality
without principal-type equality never establishes authority. Background jobs
and service/device principals must carry framework-verified typed context;
there is no ambient system principal.

The framework/Policy boundary supplies one trusted current UTC instant for a
live decision. The caller cannot set `timestamp`, `evaluation_at`, `as_of`, or
equivalent values. This instant is used consistently for membership, role,
support grant, delegation, scope, and approval validity, with half-open
effective intervals. Historical policy simulation, if needed, is a separate
privileged versioned read contract; its result is never an authorization token
for a live operation.

Policy owns evaluation and its role/permission data. Each resource-owning
module supplies authoritative typed facts through a versioned public
`AuthorizationResourceFactsProvider` contract registered at the framework
boundary. Given trusted tenant, resource type, record locator, and active unit
of work, it resolves company, legal entity, site, business unit, owner, record
state, classification, and other approved ABAC facts. Facts are fetched in
the same transaction/snapshot as the protected operation where a changing
fact could affect authorization; the owning command must re-evaluate or
serialize a mutable decision before commit. Unknown resource types, absent
records, stale facts, provider failures, or ambiguous scope deny. Transport
attributes are advisory only and cannot override owner facts. The provider
contract is owned/published by the lower Policy/SDK boundary and implemented
by owning modules; Policy never imports Party or other private repositories.

### Public contracts

Policy publishes `foundation.policy.authorization.v2`,
`foundation.policy.field-policy.v2`, and
`foundation.policy.approval-authority.v2` with distinct v2 query/result types.
Each records the trusted typed principal, trusted tenant, decision instant,
resolved scope/fact provenance, decision, and reason code in a bounded evidence
shape without exposing sensitive values. Permission declarations retain their
separate keys; a v2 marker alone grants no permission. The Policy owner and
SDK/Contract Maintainer define the exact wire schema and compatibility range
before implementation. Framework authorization entry points must consume v2
for certification; they cannot silently route to v1.

For field access, an explicit allow is required for classified or sensitive
fields. Missing, unknown, or ambiguous classification, field tag, record fact,
or rule fails closed. An unclassified field is not assumed public merely
because no rule was found. The Data Governance classification resolution
contract proposed by ADR-015
is a public typed input; Policy cannot query its private tables. Phase 3 Party
sensitive-field redaction and `foundation.party.sensitive.read` remain
authoritative. A Policy decision cannot broaden that Party contract, and Party
does not gain a private dependency on Policy.

Approval checks use the same trusted typed principal and current instant,
live assignment, and verified organization scope. The owning module supplies
the authoritative transaction amount and currency when approval protects an
operation. Limits and amounts use exact `Decimal`/PostgreSQL `NUMERIC`, explicit
currency, and approved precision rules; no float or cross-currency comparison
without a published conversion contract. Missing limit, invalid scope, or
expired assignment denies.

### V1 transition

This is an incompatible security correction under
[RELEASES.md](../governance/RELEASES.md), even before 1.0. V2 coexists at the
symbol/registration level during the published deprecation window. A v1
compatibility shim may remain callable only if it ignores or rejects
caller-selected subject, time, and authoritative facts, binds verified context,
and produces the same fail-closed v2 decision. It must reject legacy requests
whose claimed identity/tenant conflicts with context. If a safe shim cannot
be built, the unsafe v1 operation is disabled at the Phase 4 certification
checkpoint; Security and Release Maintainers must explicitly approve the
shortened behavior/support exception with affected consumers, mitigation,
notice, and expiry. No unsafe v1 route is retained for compatibility.
Consumers move to v2 typed context and owner-facts registration. Release notes
identify the first v2/deprecation release and tested consumer ranges. The v1
symbol's earliest ordinary removal is after at least the next Stable platform
minor following replacement availability, subject to downstream regression,
owner/SDK/Architecture approval; earlier removal needs a separate Security
and Release exception. No release number or exception is approved by this
proposal.

### Compatibility with accepted delegation decisions

ADR-010 remains the authority for Policy-owned action/resource mapping,
Organization scope provider, same-transaction deterministic advisory lock,
and revocation protocol. ADR-011 remains the authority for typed principals,
action/scope/time narrowing, live root authority, maximum depth 16, cycle
denial, half-open intervals, and revocation invalidation. V2 applies those
rules to the trusted live subject and instant; it does not reinterpret or
weaken either ADR. If implementation discovers an irreconcilable conflict,
it requires another reviewed ADR, not an implicit override.

## Consequences and impact

Policy owns the public decision contracts; Identity owns the verified binding;
Organization and record owners own their facts. The protected kernel provides
generic context, injection, and unit of work only. The contract is usable by
later business/vertical modules without upward dependency or private imports.
Tenant isolation and sensitive-field protection improve, while existing v1
consumers may need code changes. No schema or data migration is mandated by
this proposal; implementation must assess any Policy-owned migration and
perform compatibility and tenant-isolation tests. Decision evidence may be
written through Audit v2 as proposed by
ADR-016; Audit must not become a
prerequisite for Policy's authorization calculation.

## Alternatives considered

| Alternative | Reason declined |
| --- | --- |
| Keep caller-selected identity, time, and facts | Permits privilege selection and fabricated ABAC evidence. |
| Trust a matching principal UUID alone | Loses typed-principal separation required by ADR-011. |
| Let Policy read owner tables directly | Violates bounded-context ownership and frozen-layer direction. |
| Historical simulation through live authorization | Makes a simulated decision usable as current authority. |
| Keep unsafe v1 behavior indefinitely | Leaves the confirmed security blocker callable. |

## Approval and implementation gates

The listed roles are the union of architecture, security/identity/authorization,
public-contract, affected owner, and release/compatibility rows in
[ADR-GOVERNANCE.md](../governance/ADR-GOVERNANCE.md) and
[MAINTAINERS.md](../governance/MAINTAINERS.md). Each adopted owner provider
requires that owner's review. This PROPOSED record grants no security exception
and authorizes no Phase 4 remediation. Acceptance requires exact-revision role
evidence, exact-head CI, independent read-only technical audit with zero
Critical/High findings, and the governance acceptance procedure. Later
implementation must test wrong principal type, forged tenant/time/facts,
future/expired grants, scoped delegation, classified fields, approval
precision, v1 shim safety, and downstream compatibility.
