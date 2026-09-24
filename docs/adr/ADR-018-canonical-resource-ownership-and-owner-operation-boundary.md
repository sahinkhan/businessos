# ADR-018: Canonical Resource Ownership and Governed Owner Operation Boundary

Status: PROPOSED

Decision date: Pending formal acceptance

Approving roles required: Platform/Kernel Maintainer; SDK/Contract Maintainer; Architecture Maintainer; Security Maintainer; Release Maintainer; Policy Maintainer; Data Governance Owning Domain Maintainer; each affected Resource Owning Domain Maintainer; Audit Owning Domain Maintainer where transaction-bound audit evidence is contracted

Approval pull request or commit: Pending

Supersedes: None

Superseded by: None

## Context and frozen-platform assessment

Policy depends on Party; Audit depends on Policy; Data Governance depends on
Policy and Audit. Party cannot call Governance for purge authority without
creating a Party -> Governance -> Policy -> Party cycle. Policy also needs a
non-spoofable owner for the resource facts in proposed ADR-014.
Proposed ADR-017
needs Governance to coordinate destruction while the owner mutates its data.
Neither companion proposal is accepted authority yet.

The frozen Phase 1 `ModuleRegistry.add` rejects duplicate module IDs and
`LifecycleManager` creates `ModuleRegistration` from the manifest module ID.
But `ModuleRegistry.add` accepts that ID from the loaded manifest; discovery
loads installed entry points without verifying entitlement to a reserved
first-party ID. Manifest `publisher` and `signature_reference` fields are
assertions, not verified provenance. `ModuleRegistration.provider` stamps
that lifecycle-assigned owner and its activation
generation onto `ProviderRegistry` entries. `OwnedRegistry` rejects duplicate
capability keys, resolves active generations, and offers `admit_entry`;
`ContributionGate` stops new admission during drain and waits for in-flight
calls before removal or retirement. These are useful authentication and
lifecycle primitives. `MessageDispatcher.command` opens one framework unit of
work, passes `HandlingContext` with a restricted `HandlerTransaction`, and
commits after the handler returns. A provider can use that transaction view;
nested command dispatch would open a different unit of work. Since commit is
after handler return, a handler-local provider admission cannot by itself
remain pinned through commit.

They are **insufficient by themselves**. The current manifest has no resource
namespace declaration; the SDK's generic `provider(capability, object)` accepts
any string and does not check namespace ownership. Its registry prevents
duplicate *keys*, not two different keys or versions claiming the same
resource namespace. A package could claim `foundation.party` when genuine
Party is absent. The SDK exposes no owner-scoped resource registration or
canonical resolver to modules. A Phase 4 resolver using the first provider,
unverified naming conventions, or direct private registry access would leave
spoofing, ambiguity, or stale-handle gaps. A transaction-spanning provider
lease also needs a framework-owned close point after commit/rollback. This proposal therefore requires
the minimal neutral platform/SDK extension below before ADR-014/017 can use
this boundary. This document makes no frozen Phase 1 code change.

## Proposed decision

### Canonical namespace and registry

Introduce immutable `ResourceOwnership(resource_namespace,
owner_module_id, contract_version)` in a neutral platform public contract,
conceptually `platform.resource-ownership.v1`. The namespace has a reserved
module-ID root plus a nonempty resource suffix: `foundation.party.party`,
`business.sales.order`, `business.inventory.stock-item`. The exact grammar,
normalization and version encoding are published and tested by SDK/Contract
review. The root is the **exact registered module ID**, not a display name,
transport field, prefix guess, or caller assertion. Module IDs with embedded
underscores remain exact. Namespace comparison uses one canonical encoding;
case, Unicode normalization and separators cannot create lookalike claims.
Existing legacy resource names may use an explicit reviewed alias declaration
from old name to one canonical namespace, version and owner; aliases cannot
transfer ownership and collisions fail closed. No implicit aliases exist.

An additive manifest declaration lists the module's owned namespaces and
supported public versions. **Before any resource claim**, a trusted
installation/module admission authority binds the loaded artifact's verified
package identity and digest/signature (or equivalently protected
operator-approved install record) to its permitted `module_id` and publisher.
This evidence is independent of the module's own manifest and entry point.
Reserved first-party IDs such as `foundation.party` require first-party
approved provenance; partner/customer IDs require an installation-approved
publisher/ID grant. Missing, conflicting, revoked, or unverifiable evidence
rejects the resource claim before activation. Replacement or upgrade must
present fresh approved artifact evidence for the **same allocated ID**;
retirement does not release that ID to another publisher. Existing modules
without resource claims retain current admission behavior but cannot gain
resource-owner authority. The trusted lifecycle loader then validates each
declaration's root against this verified `module_id`, rejects duplicate or
overlapping effective ownership/alias claims deterministically before
publication, and records the trusted owner and generation. Its owner-scoped
SDK registration binds the typed facts and/or operation provider only to an
already declared namespace/version of that same module. A module cannot pass
another `owner_module_id` or publish under another module's root. A conflicting
version range, duplicate registration, missing required provider, or ambiguous
alias fails activation/lookup. No tenant API or dynamic tenant configuration
can register platform resource ownership. Every resource namespace/version
has exactly one canonical owner; a provider capability is never evidence of
ownership on its own.

The registry is generic platform machinery, not a Policy or Governance table.
Its resolver returns a typed immutable owner binding plus an admitted provider
for the requested capability. It validates registration owner, declared
namespace/version, current generation and active state at admission; it holds
generation admission for the entire transaction-bound provider operation,
including commit or rollback of the caller's transaction, using an additive
framework-managed UOW admission lease released in the dispatcher's `finally`
path. A raw object or cached handle outside
this admission has no authority. Drain rejects new admission and waits for
in-flight work; disable removes contributions; retire bars reactivation;
replacement gets a new generation. A stale provider cannot act for a current
owner even if its old object survives in memory. Existing lifecycle rules are
not weakened.

Resource ownership means bounded-context authority over an entity contract.
It is distinct from tenant ownership, row ownership, authorization ownership,
and database ownership. `foundation.party` owns the Party resource namespace;
individual Party rows remain tenant-owned with Party's existing RLS and grants.
Every fact and operation is bound to framework-verified `RequestContext`,
trusted tenant and canonical resource/record identity. The resolver rejects
missing or multiple owners, unavailable/stale providers, mismatched
namespace/owner/version/record/tenant, and unsupported operations. It never
falls back to a different provider or first match.

### Neutral facts and governed owner operation

The smallest public surfaces are a versioned owner-facts capability and a
versioned owner-operation capability, conceptually
`platform.resource-owner-facts.v1` and
`platform.resource-owner-operation.v1`. They are narrow typed protocols, not
an arbitrary service locator. The owner registers them via the owner-scoped
SDK path. A facts provider reads its own data using trusted context and, when
needed, the caller's restricted active `HandlerTransaction`. It returns an
immutable typed projection with tenant, canonical namespace, record ID, owner
identity, version, lifecycle and explicitly published fact fields. It cannot
commit, invent a tenant, expose private tables, or turn transport input into
authority. Policy's ADR-014 decision-facing facts port consumes this neutral
owner projection through a Policy-owned adapter. Party can implement the
neutral platform protocol without importing Policy. Policy's already accepted
public Party dependency remains valid where appropriate; future owners need
no Policy source edit. The adapter verifies projection and binding before
Policy evaluates it.

For governed destruction, the external/application request enters a Data
Governance-owned coordinator. Governance resolves and admits the canonical
owner-operation provider. Under one framework-owned unit of work and the
ADR-017 lock order, the owner provider locks its own record and returns
authoritative facts; Governance resolves and locks its policy/holds and checks
the requested action; Policy authorization is invoked where required; the
owner provider validates its business invariants and performs **only** its
owner-owned archive/anonymize/purge mutation; Governance appends Audit evidence
through ADR-016 where permitted; the outer dispatcher commits. The provider
never starts or commits another unit of work, calls nested command dispatch,
or sends an independent destructive command. The owner does not import or call
Governance for this operation. Governance and Policy never issue SQL against
owner-private tables or manufacture owner facts. The same admitted generation
and transaction span fact read, final check, mutation and commit/rollback.
Any asynchronous external cleanup uses a transactional outbox after the
authoritative state change; it is not part of the database atomicity claim.

The owner retains record lookup, locking, current-lifecycle validation,
supported-action declaration, domain invariants and mutation implementation.
Governance retains retention/legal-hold eligibility. Both the effective policy
action and the owner-supported action must match the requested operation;
denial or rollback follows any mismatch. A job stores a locator and requested
action, not a reusable authority result, and re-enters the coordinator.

### Dependency and tenant consequences

The module graph remains: Governance -> Policy and Audit; Audit -> Policy;
Policy -> Party. Party -> Governance/Policy, Policy -> Governance/Audit, and
Audit -> Governance are absent. The owner imports only the lower neutral
platform contract. Governance calls the provider through the registry, not an
owner-private repository. Policy receives trusted owner facts through that
same neutral boundary. Governance implements the Policy-facing classification
port under ADR-015; Policy does not import Governance. Policy-originated audit
evidence uses the transactional outbox for Audit consumption; Governance may
use AuditAppenderV2 in its active unit of work. This graph has no new cycle.

The resolver and provider validate tenant ID from trusted context against
projection, lock keys, RLS and persisted row. A cross-tenant locator, changed
tenant, or wrong resource identity fails closed. Authorization and retention
cannot be bypassed by direct provider access; the operation provider is an
internal admitted capability, not a public route or free-standing deletion
API. The operation resolver admits only a framework-identified Governance
coordinator (and any later explicitly reviewed coordinator), never a
caller-supplied module name. The implementation must prevent a caller from
invoking it outside the governed coordinator and test that constraint. Failed or missing admission
never authorizes a mutation.

Sales, Procurement, Inventory, HR, healthcare, education and other modules
can declare their own module-rooted namespaces and implement the neutral
protocols without editing Policy or Governance for each module. Phase 5
Metadata may reference canonical identities but cannot claim another module's
namespace, supply fake owner facts, or replace an owner provider. Ownership of
new custom entities created by Metadata/extension runtime needs a later
reviewed declaration through this boundary; this ADR does not design Phase 5.

## Frozen Phase 1 and compatibility impact

Implementing this decision requires a **compatible additive platform/SDK
extension** under [RELEASES.md](../governance/RELEASES.md): add optional
resource ownership declarations to
`platform/src/businessos/modules/manifest.py`, an owner-scoped registration
method in `platform/src/businessos/modules/sdk.py`, and a neutral resource
registry/resolver integrated with trusted lifecycle creation/removal in
`platform/src/businessos/modules/registry.py` and the platform composition
root. The opt-in resource-claim admission also requires a protected
artifact-to-module-ID grant checked in `ModuleRegistry.add` before a claiming
module is enabled; `platform/src/businessos/modules/discovery.py` or its
composition caller must carry verifiable artifact provenance rather than
trusting manifest fields. The grant is installation-controlled, reserves
first-party IDs, and survives disable/retire so another publisher cannot
inherit them. Add a narrow transaction-scoped admission lease to the restricted
handler/dispatcher path in `platform/src/businessos/messages.py`, released
after the outer commit or rollback. The existing `ProviderRegistry`,
`OwnedRegistry`, `ContributionGate`, dispatcher and UOW ownership are reused,
not redefined. Existing manifests
without resource declarations and existing provider registrations continue to
work; they simply cannot serve as canonical owner facts/operations. New
consumers opt into the published versioned contracts. Any discovery that this
cannot preserve old behavior requires a separate incompatible-contract ADR
and migration plan, not an implicit Phase 1 rewrite. Frozen Phase 1 must pass
its own conformance/compatibility gates and required role review before any
code change. This proposal authorizes no implementation, migration or release.

No database migration is required for the neutral registry itself. Owner or
Governance schema changes remain under their respective ADRs. Implementation
must test duplicate/colliding/alias claims, spoofed owner, stale and draining
generations, replacement, unsupported action, same-UOW rollback, wrong tenant,
record mismatch, lock ordering, dependency graph and Phase 5 spoof attempts.

## Alternatives considered

| Alternative | Reason declined |
| --- | --- |
| Treat any generic provider capability as the owner | Capability names are unchecked strings and the manifest has no canonical namespace declaration. |
| Infer owner from caller or display name | Caller-controlled identity and aliases can spoof ownership. |
| Let Party call Governance authority | Creates a cycle through Governance -> Policy -> Party. |
| Let Governance mutate Party tables | Breaks bounded-context ownership and Party invariants. |
| Nested command dispatch for owner mutation | Opens an independent UOW and loses atomicity. |
| Put retention or Policy decisions in the kernel | Makes neutral platform machinery depend on Phase 4 business semantics. |

## Approval gate

The role union includes protected lifecycle/provider registry, SDK/manifest
and public contract, authorization, tenant security, retention/data lifecycle,
affected owners, Audit where used, and release compatibility rows in
[MAINTAINERS.md](../governance/MAINTAINERS.md) and
[ADR-GOVERNANCE.md](../governance/ADR-GOVERNANCE.md). Acceptance requires
exact-revision accountable role evidence, exact-head CI, independent read-only
technical review with zero Critical/High findings, cross-ADR review, and the
formal governance procedure. Status remains PROPOSED until then.
