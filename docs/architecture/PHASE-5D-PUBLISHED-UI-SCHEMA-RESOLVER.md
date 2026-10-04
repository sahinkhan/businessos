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
protected Metadata PostgreSQL UOW; failed evidence rolls back data and pointer changes.
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

All three UI tenant tables enable FORCE RLS. Only `businessos_metadata` has narrowly scoped
runtime grants (overlay SELECT/INSERT/UPDATE, revision/binding SELECT/INSERT); ordinary app,
worker, operations and PUBLIC receive none. Migrator owns DDL. Composite same-tenant
foreign keys bind revisions and active pointers. Triggers preserve identity/history,
generations, bounded sequences and quotas. Downgrade refuses retained overlays before
any destructive statement. Historical migrations are unchanged.

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
exclusive form. Module rows are shared for reads/drafts and exclusive for active
pointer changes, avoiding shared-to-exclusive lock upgrades while adjusting counters.
Retirement also locks the retained revision's module identities, so a disabled
extension's bindings can be released without admitting disabled code. Current
provenance is bounded to 128 modules; the sorted union with retained pins is
bounded to 256 locks. Retained pins must still match the existing database fence.
Module activation's existing exclusive artifact fence waits for
readers. Overlay edits preserve active snapshots. Locks are transaction-scoped with
a five-second lock bound; cancellation rolls back and releases locks/admission.
There is no installation-global UI lock; unrelated tenants/views resolve concurrently.

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
