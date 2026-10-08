# Phase 5D — Published UI Schema and Resolver

Status: **IMPLEMENTATION CANDIDATE — NOT CERTIFIED**.

Authorized base: `61341e71c777aea390bee99bfd207bd6e5a6bb87`.
Phase 4.5/5A/5B/5C remain certified and frozen. Phase 5 is incomplete;
Phase 5E–5H remain unauthorized and uncertified.

## Ownership and public surfaces

Metadata owns typed UI v1 values, deterministic composition, presentation-overlay
publication, immutable revisions and resolution. The additive public contract is
`foundation.metadata.published-ui.v1`. The new canonical overlay resource is
`foundation.metadata.ui_overlay` version 1, owned by Metadata; its audit evidence
does not masquerade as a frozen v1 field definition. `ResolvePublishedUI` accepts only a stable
view UUID and locale; it does not accept tenant, principal, company, site, role,
permission, arbitrary method or component authority. Overlay commands select a
scope *kind*, and the backend derives its UUID from the issued request context.

The neutral SDK `METADATA_CATALOG` / `MetadataCatalog` v1 provides immutable JSON
snapshots of admitted module declarations, with issued owner/generation, manifest
version and direct dependency provenance. It exposes no mutable registry, database
callback or credentials. Snapshot leases include direct dependencies and reject
draining/replaced generations or mutation of captured declarations. Existing
`ModuleRegistration.metadata` remains compatible. Installation/module admission
continues to authenticate the producing artifact under ADR-018.

The protected lifecycle binds that existing approved artifact identity and the
durable generation returned by `MetadataActivationFence` to the exact admitted
catalog generation before registration. Retained snapshots include this provenance
for both producing modules and direct dependencies. Before composition is used for
drafts, publication, reactivation or resolution, each retained artifact and durable
generation must equal its locked `module_fence` identity. A stale replica fails
closed without relabeling old declarations as the replacement artifact. Process
admission numbers remain a separate namespace; identical approved artifacts may
restart with different process numbers while retaining the same durable identity.
An artifact that returns after replacement still has a new durable generation.

An active admitted artifact publishes `ui.base.v1`, `ui.capabilities.v1`,
`ui.extension.v1` and `ui.localization.v1` declarations. Module declarations are
installed immutable publication inputs, not tenant drafts. Party supplies a bounded
owner base and capability projection for public `PartyRecord` presentation bindings
and English/Arabic/Spanish localization. It does not import Metadata or change
Party data handlers. No sensitive profile, instance data, or custom-field value is
embedded in this schema. Additional owners can publish compatible declarations
through the same public SDK without private frontend imports.

## Stable identity and deterministic composition

Views, module revisions, nodes (sections/slots/fields/actions), owner field/action
capabilities, contributions, overlays and overlay revisions have stable UUIDs.
Exactly one base and one matching canonical-owner capability declaration are
required. The owner declaration must match ADR-018's current namespace, public
version and admitted generation. Extensions cannot manufacture owner capabilities
or change existing field types, permissions, classification or bindings.

Resolution order is explicit:

1. Canonical admitted module base.
2. Compatible extensions, sorted by priority, owner ID and contribution UUID.
3. Localization, sorted by locale, owner ID and contribution UUID.
4. Published tenant overlay.
5. Eligible current company overlay.
6. Eligible current site overlay.
7. Eligible authenticated human user's presentation preference.

Sibling output ordering is `(presentation.order, stable node UUID)`. UUID ordering
is explicit and never depends on registration, dictionary, SQL row or task order.
Duplicate stable nodes/bindings/contributions reject composition; differing
translations for the same locale/key reject localization. Parent references are
validated, cycles/missing parents are refused and nesting is bounded.

All contributions pin the base revision and a compatible module version range.
External extensions/localizations require the real manifest dependency on that
owner. The module lifecycle validates dependency versions; the catalog re-admits
their current generations. Database module artifact/generation fences and contract
generations are included in overlay compatibility. Active UI revisions now pin
module/base, capability and direct dependency artifacts in the existing Metadata
activation fence. Incompatible activation is rejected before authority changes;
same-artifact reactivation remains supported. Retired overlays release their active
bindings without rewriting history. A privileged operator bypass/corruption is
still refused at resolution and publication rather than silently repaired.

External roots enter only slots explicitly exposed by the canonical owner's
`extension_slots` capabilities. Every contributed descendant must remain in its
own subtree and use a primitive allowed by that slot. Protected roots, arbitrary
sections/fields, another contribution's private nodes and foreign/missing slots
are denied. A slot-shaped node alone is not an admission grant.

## Allowlist and authorization

Presentation mutations allow only `label_key`, `help_key`, `order`, `visible`,
`density` and `columns`. User preferences allow only `order`, `visible` and `density`.
There is no generic property setter. IDs, resource/owner/bindings, tenant/scope,
permissions, Policy, classification, lifecycle, security, audit, capabilities,
required/editable business facts and technical identities are not patchable.
The effective customization grant is the intersection of that platform allowlist,
owner `customization` opt-in for the exact target/scope/properties, and backend
Policy/current scope. An omitted owner grant denies customization. Party permits
only view-level order/density/label customization (with the narrower user allowlist);
its public display-name field is not customizable. These capability declarations
participate in the compatibility digest and artifact activation bindings.

Every query/command requires its own backend Policy permission. Resolution also
requires the base and every disclosed owner capability's permissions, rechecks
them as one fenced set at operation completion, and validates the current Identity-issued principal binding
and exact framework invocation/request/UOW. Hidden controls remain presentation
only; executing a business operation still requires its own independent backend
handler and Policy enforcement. There is no action executor or method-name dispatch.

No certified UI classification-disclosure projection is available. Classified
capabilities therefore return `classification_unavailable`, including unknown
classification identities; they do not fall back to ordinary read permission.
This conservative boundary preserves ADR-015 and Party's sensitive-field rules.
Policy errors/unknown/denied state produce no permissive schema or cached fallback.

Only existing Phase 4.5 primitives are allowed: FormSection, Card, Grid, TextInput,
TextArea, NumberInput, MoneyInput, DateInput, DateTimeInput, Select, Checkbox and
Button. Node kind and field type must match the primitive. Contracts forbid extra
properties, executable expressions, URLs, scripts, CSS and component imports.
Localization is bounded inert text, with keys retained where translation is absent.
It never modifies authority properties. No React renderer was added.

## Persistence decision and lifecycle

Frozen Metadata v1 definitions accept field/reference grammars, not UI composition
or scoped presentation patches. Reinterpreting them would break Phase 5A/5B/5C
contracts. The forward Metadata-owned `metadata_0003_ui_overlays` migration therefore
adds only `platform_metadata.ui_overlays` and `ui_overlay_revisions`.

Each overlay has immutable tenant/view/scope identity, a separate editable draft
generation, active revision pointer/generation and lifecycle. Draft creation/edit
does not publish. Resolution reads only `published` active revision pointers, never
draft JSON. Publication pins the current compatibility digest. Reactivation checks
that retained revision's digest and compatibility before changing the pointer;
history is never rewritten. Retirement removes eligibility and retains history.
Every mutation writes AuditAppenderV2 evidence and an outbox event in the same
protected PostgreSQL UOW; publication/reactivation/retirement use the ADR-024 private
publication profile. Failed evidence rolls back data and pointer changes.
Mutation results are `UIOverlayMutationResult`, containing identity/generation and
publication status only. They never contain editable draft JSON, including rollback,
publication and retirement. `ReadUIOverlay` alone returns `UIOverlayRecord` and
requires the distinct draft-disclosure permission. Audit/outbox values contain no draft.

`metadata_0004_ui_bindings` is a forward remediation migration; committed 0003 and
every earlier migration retain their original bytes. Its immutable, FORCE-RLS
`ui_revision_module_bindings` rows feed the existing `module_fence.active_bindings`
counter in the same transaction as pointer changes. It refuses an upgrade over
unbound active revisions from the failed, uncertified 0003 candidate: the operator
must retire those overlays first; missing historical pins are never invented.
It refuses downgrade when UI history remains. Certified Phase 5C upgrade is additive.

The historical `metadata_0005_ui_binding_seals` preserves committed 0003/0004 and adds immutable
binding seals. Publication creates a revision, inserts its complete bounded binding
set, validates identities, inserts the seal, then activates the pointer and adjusts
counters in one transaction. A deferred constraint requires every new revision to
be sealed before commit. Active pointers require a seal immediately. Binding INSERT
and seal INSERT serialize on the owning overlay row; after sealing, INSERT is
rejected and existing UPDATE/DELETE protections remain. A seal cannot be updated,
deleted or reopened, including after retirement. Rollback removes all new state.

The current `metadata_0006_ui_provenance` upgrade from certified Phase 5C and retained
0004 drafts is additive and replayable. Upgrade refuses any retained revision history,
including 0005-sealed history, from the uncertified candidate
before changing schema: neither old counters nor current module identities prove
the original binding set was complete. No historical bindings or seals are invented.
Such an uncertified database requires a separately reviewed recovery plan; retirement
alone does not establish completeness. The 0006 downgrade refuses even on an empty
installation: restoring the old activation grants requires reviewed operator recovery.

All six UI tenant tables enable FORCE RLS. `businessos_metadata` retains narrowly scoped
draft/runtime access but cannot insert expected provenance. Only the private publication
profile may issue expected headers/members and perform the complete trusted publication.
Ordinary app, worker, operations and PUBLIC receive no UI grants. Migrator owns DDL.
Composite same-tenant
foreign keys bind revisions and active pointers. Triggers preserve identity/history,
generations, bounded sequences and quotas. Downgrade refuses before any destructive
statement. Historical migrations are unchanged.

## Concurrency, provenance and cache decision

There is **no shared or cross-request resolved-schema cache**. Current public
contracts do not expose a security-complete session/Policy epoch suitable for such
a cache. Request correlation IDs, browser IDs or invented epochs are not substitutes.
Every resolution recomposes current admitted sources, current scope and active
published overlays, and evaluates live Policy. This prevents stale cache population
and reuse across login/logout, tenant/company/site/locale and permission changes.

Lock order: shared contract fence → sorted module fences → tenant creation
quota fence if creating → tenant/view advisory fence → overlay row. Resolution
uses the shared view fence; publication/reactivation/retirement/creation use its
exclusive form. Module rows use `FOR KEY SHARE` for reads/drafts and
`FOR NO KEY UPDATE` for active pointer changes. These modes coexist: counter writes
do not block unrelated tenant resolvers during awaited evidence, outbox, Policy or
outer commit work. Active-pointer writers still serialize globally for shared module
counters, without a lock upgrade. Artifact activation explicitly uses `FOR UPDATE`,
which conflicts with both modes and preserves generation stability through completion.
The forward migration also makes `(module_id, artifact_identity, generation)` a
unique database key. PostgreSQL therefore uses the conflicting key-update lock even
for direct SQL identity changes; safety does not depend on callers remembering an
explicit `FOR UPDATE`. Counter-only writes leave that key unchanged.
Retirement also locks the retained revision's module identities, so a disabled
extension's bindings can be released without admitting disabled code. Current
provenance is bounded to 128 modules; the sorted union with retained pins is
bounded to 256 locks. Retained pins must still match the existing database fence.
Module activation's existing exclusive artifact fence waits for
readers. Overlay edits preserve active snapshots. Locks are transaction-scoped with
a five-second lock bound; cancellation rolls back and releases locks/admission.
There is no installation-global UI lock; unrelated tenants/views resolve concurrently.

Admissions precede database compatibility locks. After sorted module fences, the
tenant/view and overlay locks precede revision/binding/seal creation. Final Policy
authority follows evidence staging and is retained through the outer transaction.
Activation takes its exclusive module fence before lifecycle drain; an inversion
with previously admitted work is bounded by the five-second database lock timeout
and the existing lifecycle drain deadline. Cancellation releases database locks and
admissions. Policy providers must bound authority waits and isolate unrelated subjects;
readiness cannot certify a provider's synchronization implementation. No generic
dispatcher changes are required by this second remediation.

The additive neutral SDK completion boundary lets handlers retain admissions and
register final guards; it gives them no commit/rollback authority. The dispatcher
enters guards after handler evidence/outbox work, while its issued invocation is
valid, and retains them across the outer commit/rollback and result cleanup.
Cleanup revokes every issued completion registration and clears guard closures
on success, failure and cancellation; completed handler contexts are not retained.
Catalog source/dependency leases are retained through that boundary and validated
before completion. A drain already observed at validation rejects the operation;
a later drain waits for already admitted work to complete or roll back.

Phase 5D requires an operator-configured, backend-owned `FencedPolicyEvaluator`
behind the existing `Authorizer`. Its `permission_fence` must evaluate the complete
UI/owner permission set from one current authoritative snapshot and fence all
applicable revocation writers through operation completion. It must also validate
current Identity/membership/scope/validity using their existing authority contracts.
A legacy sequential-only evaluator is denied with `authority_fence_required`;
there is no permissive fallback, invented epoch or browser authority. The original
`Authorizer.require` and frozen Policy V2 contracts remain unchanged. The provider
owns authority synchronization; Metadata does not duplicate Policy rules or read
Policy/Identity private tables. Unrelated subjects/tenants must not use a global
process mutex. No shared schema cache was introduced.

Production composition registers `published-ui-authority-fence` in the existing
readiness checks. Each evaluation uses the current active contract registry for
`foundation.metadata.published-ui.v1`, not startup manifests. Draining generations
already reject new admissions and are absent from active contract lookup; this
readiness prerequisite therefore ceases during drain and after disable/retirement.
Existing admitted work still retains its independent completion and Policy fences.
Reactivation publishes a new generation and restores the readiness prerequisite.
Registry lookup and evaluator capability inspection do not await, so the check
observes one event-loop snapshot without caching lifecycle state or taking a global lock.
A sequential-only evaluator returns not-ready (HTTP 503); a runtime-checkable
`FencedPolicyEvaluator` satisfies this capability check. Deployments without that
contract and development/test composition retain their existing behavior. This is
interface validation, not proof of provider locking semantics: provider certification
remains an operator obligation. Request-time `authority_fence_required` still denies
an evaluator that lacks the capability; readiness creates no fallback.

Final checks reject replaced request/Identity bindings, expired credentials,
revoked Policy and mutated declarations. Browser scope/session transitions
retain Phase 4.5's cancellation and security-context cache isolation. Results remain
bound to that issued request; they cannot authenticate a later browser context or
authorize a business operation. The Phase 5E renderer must preserve those existing
response-adoption guards when separately authorized.

Provenance records base revision, locale, declaration digests, module artifacts and
database/admission generations, schema/UI generations and applicable overlay
revision IDs/generations/digests. Process-local admission numbers are not persisted
compatibility pins, so identical artifact restarts do not invalidate publication.
No nonexistent Policy epoch is asserted. Tenant/company/site/principal/session
security context remains private on the server. Diagnostics contain one enum code,
never untrusted payloads, business values, classification facts or cross-tenant IDs.

Budgets: 128 declarations per view, 64 KiB per declaration/overlay document,
256 nodes, depth four, 128 fields, 32 actions, 512 translations, 128 patches,
four eligible overlay scopes, 128 dependency modules, 1024 overlays per tenant,
64 retained revisions per overlay and 128 KiB resolved output. Quota refusal never
deletes history. All database reads and conflict output are bounded.

## Verification and non-goals

Focused unit and real PostgreSQL tests exercise deterministic ordering, strict
grammars, owner/capability and classification refusal, localization, draft exclusion,
scope/RLS/grants, immutable rollback, stale publication, live Policy and Identity
transitions, module drain/upgrade, synchronized publication races, cancellation,
transactional evidence rollback, quotas and certified-base migration/replay/refusal.
Full frozen-contract, static, frontend, artifact/wheel and image gates are required
before freezing a candidate, followed by exact-head hosted CI and independent audit.

Phase 5D implementation only. Phase 5E–5H were not implemented. No dynamic renderer,
Studio UI, generic action/menu authoring, Kanban/calendar/dashboard runtime, workflow,
search/reporting engine, executable metadata, customer DDL or business authorization
was introduced. This document does not certify Phase 5D or authorize Phase 5E.

Next required gate: independent Phase 5D security/architecture/compatibility audit
of the exact candidate SHA, then personal owner acceptance, guarded merge and
protected-main post-merge CI before certification.

The audit of `d1e17bab90b6dfbd3dbf429b674e91e6b40876df` failed with
Critical 0 / High 3 / Medium 3 / Low 0. Its green CI remains historical evidence,
not acceptance. This remediation remains an IMPLEMENTATION CANDIDATE and requires
a fresh independent exact-commit remediation re-audit.

The first remediation `a9f69ad334f944fa42b4e04ff4f1218131d98c82` also failed
independent re-audit: Critical 0 / High 0 / Medium 3 / Low 0. Run `37202792639`
passed for that candidate but is historical evidence only. R1 binding sealing, R2
cross-tenant reader availability and R3 production capability readiness are the
scope of this second remediation. Both failures remain historical evidence.
Phase 5D remains an IMPLEMENTATION CANDIDATE / NOT CERTIFIED. A fresh independent
second-remediation re-audit of the exact new candidate is required.

The second remediation `01f5454b94a2746fdb448e5e4a26b8e9002a6adf` failed
independent re-audit: Critical 0 / High 0 / Medium 2 / Low 0. Run `37215110092`
passed for that candidate but does not override the failed audit. N1 established
that the 0005 seal proves immutability of supplied rows, not authoritative set
completeness; R1 and M1 remain incomplete. N2 identified readiness retaining startup
manifest state after disable. The dynamic readiness change above addresses N2;
ADR-024 subsequently passed independent architecture review and received owner
acceptance on exact proposal `3092a976cbae291a700f26765c0b95638e4809c2` in
[comment 5991893651](https://github.com/sahinkhan/businessos/pull/67#issuecomment-5991893651).
Its semantic architecture is unchanged. The current implementation adds the
accepted N1 boundary described below; it requires fresh implementation audit.
Phase 5D remains an IMPLEMENTATION CANDIDATE / NOT CERTIFIED.

The final implementation audit of `d95ecacf2582e35b8ae942de5cf6bc9be33167f1`
failed with Critical 0 / High 0 / Medium 3 / Low 1 / Documentation-only 0.
Its successful CI run `37323579608` remains historical validation evidence only.
F1 concerns the complete private admission deadline; F2 concerns retained approved
artifact provenance across replicas; F3 concerns cancellation-safe lease accounting;
F4 concerns private credential distribution to the ordinary event worker. This
remediation preserves ADR-024 and requires a fresh independent exact-commit audit.

## ADR-024 private publication boundary

`PublishUIOverlay`, `ReactivateUIOverlay` and `RetireUIOverlay` retain their public
contracts. The kernel authenticates their exact approved registration/generation,
selects `businessos_ui_publication` before opening the UOW, and invokes the fixed
Metadata-owned writer. It does not invoke the ordinary registered handler with a
more privileged session. No profile selector or proof-issuance API is added to SDK,
DI, manifests or tenant configuration. Handler/provider contexts deny generic SQL;
the private transaction remains in the kernel's scoped capability registry. The
AuditAppenderV2 bridge offers only the approved Audit append operation.

The executor retains the actual catalog declarations/dependencies through completion.
The approved owner writer captures their complete union against locked database
identities, with canonical module IDs, exact opaque artifact identities, positive
BIGINT generations, UTF-8 byte ordering and a 128-member bound. It neither accepts
an expected set from a command nor reconstructs expectations from actual binding rows.

Forward revision `metadata_0006_ui_provenance` adds immutable expected headers and
members and an immutable migration-provisioned installation lineage. Context binds
tenant/view/overlay/revision/scope, draft/prior-active generations, document and
compatibility digests, declarations, contract generations and issuance model/version.
Expected rows can be inserted only through the private principal. A seal requires
bidirectional relational equality with the actual bindings and exact context matching.
All revision, proof, seal, pointer, counter, Audit and outbox effects share one
PostgreSQL transaction, with final Policy authority held through commit. No signature,
second publication transaction, role switch or post-commit repair is involved.

Ordinary Metadata cannot write module artifact/generation/counter facts. Existing
`MetadataActivationFence` remains the lifecycle authority. Counter updates execute
only from the existing pointer-transition triggers under a narrowly granted NOLOGIN
owner; runtime roles have no membership or direct EXECUTE permission. FORCE RLS
constrains tenant-owned provenance and counter binding reads. Existing KEY SHARE
reads and NO KEY UPDATE counter writes preserve cross-tenant reader availability.
Activation retains the five-second lock bound. Restart at an unchanged admitted
artifact and normal resolution use ordinary Metadata reads, without the issuer pool.

Unverifiable 0005 revision history is refused before schema changes; it is never
backfilled from old bindings or seals. This security boundary is forward-only:
downgrade refuses rather than restoring forgeable activation/provenance privileges,
including on an otherwise empty UI installation. Reviewed operator recovery is required.

## Private-profile deployment and readiness

Operators provision `businessos_ui_publication` as LOGIN/NOSUPERUSER/NOBYPASSRLS,
non-owner, with no role memberships. `businessos_metadata_fence_owner` is NOLOGIN;
only the trusted migrator has its ownership-maintenance membership. The database-role
transition command provisions these identities before the forward migration and
requires the separate `BOS_UI_PUBLICATION_PASSWORD` operator secret. Migrations
contain no runtime password. Docker development bootstrap uses development-only
credentials; production, Kubernetes and self-hosted operators inject their own secret
through the existing trusted deployment environment/secret-store mechanism.

`BOS_UI_PUBLICATION_DATABASE_URL` must name the dedicated role on the same endpoint
and database. There is no Metadata/Governance/migrator fallback. The bounded pool is
included in the installation connection budget, has no overflow, checks identity,
effective grants, verifier objects and FORCE RLS, and supports the existing atomic
credential-rotation/lease-draining mechanism. Connections are physically renewed on
checkout to reset state. Connection/pool waits are bounded; queries have a 30-second
limit, idle transactions 30 seconds and transactions 60 seconds. No vendor connection
or external signing service is required in air-gapped installations.

Private admission uses one absolute deadline, configured by the publication pool
timeout, covering mutex selection, profile validation, revalidation and actual UOW
checkout. Blocking validation runs outside the authority state mutex. A temporary
lease reservation keeps the selected pool alive across rotation; a changed pool or
contribution fails revalidation without an automatic retry. Lifecycle installation
uses the same bounded path. An owned, shielded finalizer releases each lease token
exactly once despite repeated cancellation. Retired-pool disposal is claimed under
the mutex and completed outside it; no SQL validation or disposal holds that mutex.

The ordinary `events` worker receives no publication credential. Its configuration
has no publication URL field, and both worker-created application settings explicitly
exclude an inherited API publication URL from environment or `.env` configuration.
Normal delivery uses its existing runtime/operations and foundation authority
profiles. A worker requiring publication in the future needs separate architecture
and deployment review. The resolved Compose credential-exclusion check is
`python scripts/check_event_worker_deployment.py`.

Production readiness follows the currently active Published UI contract. Active UI
requires both fenced Policy and a valid private profile; disabled/draining UI does
not retain either requirement from a startup manifest. Request-time enforcement still
fails closed. Published reads consume stored authenticated proof without issuer access.
A valid same-installation restore preserves lineage and all proof associations.
Cross-installation copies need reviewed import/re-publication; setting the application
installation UUID cannot create or replace database lineage authority.
