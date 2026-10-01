# ADR-023: Metadata Persistence, Customization, and Dynamic UI Resolution

Status: ACCEPTED

Decision date: 2026-09-30

Acceptance stage: ACCEPTED / AUTHORITATIVE ON MAIN

Approving roles required: Architecture Maintainer; Platform/Kernel Maintainer; Metadata/Studio Owning Domain Maintainer; SDK/Contract Maintainer; Migration Safety Reviewer; Security Maintainer; Policy Maintainer; Data Governance Owning Domain Maintainer; Frontend Foundation Maintainer; Release Maintainer; each participating Resource Owning Domain Maintainer for its adapter

Approval pull request or commit: [PR #56](https://github.com/sahinkhan/businessos/pull/56) — merged at `287945713f938395c508abae3ac9115213a6602f`.

Reviewed semantic proposal SHA: `f769d7ce8a13e5f13ab9d96d427c30526d8659be`.

Semantic proposal owner attestation: COMPLETE / proposal-only — [@sahinkhan's exact-proposal attestation](https://github.com/sahinkhan/businessos/pull/56#issuecomment-5903647428) for `f769d7ce8a13e5f13ab9d96d427c30526d8659be`.

Semantic proposal exact-head CI: [BusinessOS run 36634728686](https://github.com/sahinkhan/businessos/actions/runs/36634728686) — PASS (`python-quality`, `windows-typing`, `web-quality`).

Semantic proposal independent technical/read-only architecture audit: PERFORMED — PASS; Critical 0; High 0; Medium 0; Low 0.

Review model: SOLO MAINTAINER OWNER ATTESTATION by `@sahinkhan`.

Independent human review: NOT PERFORMED.

Formal acceptance candidate SHA: `bfa680d33495f7e5d17d99cd33e14ea792cb0cb7`.

Formal acceptance exact-head CI: [BusinessOS run 36670542007](https://github.com/sahinkhan/businessos/actions/runs/36670542007) — PASS (`web-quality`, `python-quality`, `windows-typing`).

Formal acceptance independent technical/read-only audit: `ADR-023 FINAL ACCEPTANCE EVIDENCE RE-AUDIT — PASS`; Critical 0; High 0; Medium 0; Low 0.

Formal acceptance owner attestation: [@sahinkhan's final exact-SHA acceptance attestation](https://github.com/sahinkhan/businessos/pull/56#issuecomment-5905117250) for `bfa680d33495f7e5d17d99cd33e14ea792cb0cb7`.

Accepted main merge SHA: `287945713f938395c508abae3ac9115213a6602f`.

Post-merge CI / certification: [BusinessOS run 36676757074](https://github.com/sahinkhan/businessos/actions/runs/36676757074) — PASS on `287945713f938395c508abae3ac9115213a6602f` (`web-quality`, `python-quality`, `windows-typing`).

Architecture state: ACCEPTED / AUTHORITATIVE / MERGED.

Runtime state: Phase 5A CERTIFIED / CLOSED / FROZEN on protected `main` at `3f96d668eb24f0d505b45b13428fff1c05f1d7af`; Phase 5B AUTHORIZED TO BEGIN; Phase 5 overall remains INCOMPLETE. Phase 4.5 remains COMPLETE / CERTIFIED / FROZEN.

Phase 5A implementation provenance: [PR #61](https://github.com/sahinkhan/businessos/pull/61), final candidate `03234293aa21d6fa56254937b4b5ee74c7d2eb0a`, candidate CI `36844589190` SUCCESS, independent remediation re-audit PASS at Critical 0 / High 0 / Medium 0 / Low 0, owner acceptance comment `5930138099`, supplemental Solo Maintainer governance attestation comment `5931450033`, guarded merge `3f96d668eb24f0d505b45b13428fff1c05f1d7af`, and post-merge CI `36854266178` SUCCESS. This certification authorizes only the bounded Phase 5B entry gate; Phase 5C–5H retain their separate prerequisites and certification gates.

Formal authority: COMPLETE — the exact accepted candidate was merged to protected `main` and post-merge certification passed.

Supersedes: None

Superseded by: None

Implementation authority: PHASE 5A IMPLEMENTED / CERTIFIED / CLOSED / FROZEN under ADR-023 and the Phase 5 roadmap. The Phase 5A implementation, exact-head CI, independent audit/remediation, owner acceptance, guarded merge, and post-merge certification gates are complete. Phase 5B is authorized to begin as the next bounded batch, subject to its own implementation and certification gates. The earlier prospective Phase 5A entry gate is historical and satisfied. Accepted Phase 4 and frozen Phase 4.5 contracts remain unchanged.

## Context

Phase 5 must allow customer customization without protected-core forks or uncontrolled schema changes. The existing kernel `MetadataRegistry` registers immutable module declarations by owner and activation generation; it is not persistent Studio storage. PostgreSQL is authoritative. [ADR-006](ADR-006-module-owned-data.md) assigns each table one owner, [DATABASE.md](../architecture/DATABASE.md) permits controlled metadata JSONB but prohibits a global EAV model and runtime ORM schema synchronization, and [ADR-007](ADR-007-upgrade-strategy.md) requires versioned, preflighted compatibility. The certified [Phase 4.5 UI foundation](../roadmap/PHASE-4.5-UI-FOUNDATION.md) supplies the shell and reusable renderer primitives. Phase 5 consumes them.

## Considered alternatives

| Model | Advantage | Rejection or limit |
| --- | --- | --- |
| A. Physical column/table for every customer field | Native relational constraints and selected query performance | Uncontrolled customer `ALTER TABLE` on owner tables violates module migration ownership, creates upgrade and lock hazards, and cannot be an ordinary Studio publish action. A reviewed owner migration remains available for promoted stable domain fields. |
| B. Global EAV | Flexible field enumeration | Prohibited by database architecture; weak typed constraints, costly joins, difficult tenant isolation and predictable indexing, and no bounded owner of ordinary record values. |
| C. JSONB-only generic records | Simple schema surface | Loses relational envelope, owner invariants, tenant/scope constraints and bounded query guarantees; becomes a global schemaless domain escape hatch. |
| D. Governed hybrid | Stable relational envelope and owner boundaries with validated flexible attributes | Requires explicit contracts, quotas, revision pinning and query admission. Chosen. |

## Proposed decision

### Ownership and storage

The protected kernel retains generic declaration registration, contribution lifecycle and compatibility primitives. The Platform Foundation Metadata/Studio bounded context owns persistent definitions, draft and immutable published revisions, customer overlays, customization packages, UI definitions, diagnostics and its own migrations. It cannot directly mutate another module's private business tables. Its installation/module base definitions are admitted through trusted module lifecycle and versioned public contracts; a manifest assertion alone is not owner authority. Module lifecycle and owner provenance continue to follow [ADR-018](ADR-018-canonical-resource-ownership-and-owner-operation-boundary.md).

For an ordinary first-party record, the resource owner owns **all custom-field values** and supplies an opt-in, versioned `CustomizableResource` adapter. Metadata owns field definitions and validation schema; the owner validates, writes, reads, queries, exports, retains and deletes values through the same owner operation boundary as the record. A possible owner-controlled representation is a tenant-aware record extension keyed by canonical resource and immutable record UUID, with a controlled JSONB value document, published schema revision ID, optimistic concurrency token and justified owner-managed indexes. This ADR deliberately does not mandate a table name or an unreviewed schema edit. First-party records that do not publish the adapter are not Studio-customizable. Metadata cannot write owner tables, synthesize owner identity, or bypass owner commands. An owner may decline a proposed field capability or query tier.

For **governed custom entities**, Metadata/Studio owns both definition and instance storage. Instances use relational columns for immutable UUID, tenant, entity definition, allowed company/site scope, lifecycle, definition revision, actor/time provenance and concurrency version, plus a schema-validated bounded JSONB value document. Metadata owns its explicit forward migrations. This is not an unrestricted generic record table: every instance is validated against a retained immutable published schema revision, tenant RLS, type and reference validation, and quota enforcement. Security-relevant scope and identity are relational authoritative columns, never merely document keys. Stable promoted business domains move to their own owner through a separately reviewed migration and compatibility contract; Studio does not relabel a generic entity into a domain owner.

No Studio request executes DDL, arbitrary SQL, Python, JavaScript, deserialization hooks, or schema auto-sync. Approved physical indexes, projections or stable promoted columns require a reviewed owner-controlled migration and operational preflight. Metadata publishing is a data transaction, never a hidden database migration.

### Type, validation and query contract

Phase 5's allowlisted field types are bounded text, long text, integer, finite decimal with explicit precision/scale, boolean, date, timezone-aware instant, controlled enum, canonical UUID/reference, money as exact amount plus currency code/context, and syntactic email/phone/URL values. Type identifiers and wire encodings are versioned; unknown types fail validation. Required/nullability, literal deterministic default, length/range, decimal precision/scale, enum choice identities, reference targets and allowed scope are explicit. A default may not read ambient time, tenant, user or another record unless a separately reviewed owner-supplied operation provides it. A required field added to populated records needs a validated backfill or conditional activation path before publish; old rows never become silently invalid. Conditional required and bounded cross-field comparisons use a typed, total, side-effect-free expression grammar with a finite cost budget. Phase 6 owns workflow and orchestration.

Query tiers are: display-only (default); equality/range filterable where type permits; sortable where a stable ordering exists; bounded searchable through an approved index/search contract; unique only when the owning module can prove a tenant/scope-aware atomic constraint; and reportable only through an approved projection/Phase 8 contract. Each higher tier is an explicit owner capability and quota, not an automatic property of JSONB. Phase 5 provides bounded indexed/approved filtering and sorting plus server-side pagination; an unsupported or over-budget query fails explicitly, never scans unbounded tenant data or falls back to browser filtering. Full-text and arbitrary analytics projections belong to Phase 8 unless a separately governed owner capability is certified. Uniqueness cannot be promised by application prechecks alone.

Custom references use the canonical [ADR-018](ADR-018-canonical-resource-ownership-and-owner-operation-boundary.md) resource namespace, stable record UUID, tenant and contract version. The target owner supplies authorized existence and lifecycle resolution, including a bounded bulk contract for list/view workloads. Phase 5 supports optional and required many-to-one references, with one-to-one only where an owner-enforced uniqueness capability exists. Many-to-many is deferred pending an explicit owning relationship contract. No arbitrary foreign key into another module's private table or cross-tenant reference is permitted.

For a **same-owner** source and target, that owner may certify restrict, nullify or controlled cascade under its own transaction and invariants. For **cross-owner** references, Phase 5 promises no generic synchronous restrict, nullify or cascade on target retirement or deletion: the source owner owns its reference value, the target owner owns target lifecycle, and neither Metadata nor the target owner directly mutates another owner's source row. Target archive/retirement leaves existing references historically resolvable, retired, unavailable or diagnostically broken as specified by the versioned reference contract; new writes to no-longer-referenceable targets fail closed. Physical purge remains governed by [ADR-017](ADR-017-retention-hold-and-purge-coordination.md) retention, legal hold, destructive lifecycle and admitted owner operations, not a second Studio destructive coordinator. Any future strict cross-owner deletion protection requires a separately versioned and certified coordination contract covering participant/reference discovery, owner admission, serialization, failure semantics, idempotency, retention/hold interaction, deterministic ownership and transaction boundaries. Until then Phase 5 does not claim cross-owner deletion integrity guarantees.

### Revisions, overlays, upgrades and resolution

Drafts are mutable authoring state and are never read by production runtime. Publish validates schema, field types, references, classification, owner capabilities, Policy permission names, UI compatibility, quotas and upgrade compatibility; it writes an immutable revision with content digest and atomically switches the active pointer in one PostgreSQL transaction. Runtime reads only a complete published revision. Failed publication leaves the prior revision active. Rollback activates a previously validated compatible revision; it never rewrites history or silently erases values. A revision whose current dependencies no longer pass preflight cannot be reactivated until resolved. Published revisions, previous active pointers and conflict diagnostics remain audit evidence.

**Metadata publish/rollback and module activation/upgrade participate in one compatible serialization/concurrency invariant.** A publisher's preflight records the exact editable draft generation/version, current active metadata revision, module/base artifact generation/version, schema/UI contract generation and relevant dependency/capability generations. Immediately before activation/commit, a shared authoritative fence must atomically confirm those same identities and activate only the compatible pair. If any input changed, publication rejects with a stale/conflict diagnostic, leaves the previous active revision intact and requires fresh preflight/rebase/retry. Two publishers starting from the same draft generation cannot silently overwrite one another or produce last-writer-wins publication. Rollback/reactivation uses the same fence and rechecks current module/base, owner capabilities, classification prerequisite, contract/UI compatibility and active dependencies; historical validity alone does not suffice.

Module install/upgrade/activation likewise records the exact active metadata revision/generation set it preflighted and must atomically confirm it through the same serialization boundary before making a new base/schema/capability generation active. If metadata changed, activation rejects/retries and cannot leave an incompatible module/metadata pair. A module lifecycle path unable to participate in that fence denies activation; an earlier compatibility check cannot authorize it. A preflight check followed by an unguarded pointer update is insufficient on either side. Phase 5A must certify a PostgreSQL-compatible compare-and-swap, version/row lock, advisory coordination or another reviewed mechanism that enforces this semantic invariant across the authoritative state and module lifecycle; this ADR does not mandate a particular lock implementation.

Stable immutable IDs identify entity, field, view, section, slot, action and menu; display labels and positions are not identity. Module base definitions and reviewed extension contributions expose stable slots and schema versions. Tenant/customer customizations are sparse, allowlisted overlays keyed to those IDs: add/hide/reorder a permitted field, change an allowed label, add a section, extend a menu or add bounded validation. They cannot patch arbitrary component trees, overwrite protected fields or duplicate/copy a vendor view as a private fork. Company and operating-site overlays require explicit base/owner capability and cannot weaken tenant or Policy restrictions. User saved presentation preferences may reorder/hide eligible display elements but are never published business metadata or authority.

Resolution is deterministic in this order: approved module base; admitted extension contributions in dependency order with stable ID tie-breaking (duplicate conflicting IDs reject); localization label lookup; published tenant overlay; published company overlay; published site overlay; eligible user presentation preference. Later layers may modify only properties their parent exposes; they cannot override ownership, classification, required security control, permission identity, data type or protected lifecycle behavior. Localization changes text, not stable IDs or security semantics. The resolver emits a typed schema with base/overlay/revision provenance, compatibility version and diagnostics. Identical inputs, including module artifact/version, published revision IDs, trusted tenant/company/site, locale and policy/security context, produce the same schema or the same explicit error. Unknown/pending/error scope or Policy state fails closed.

Upgrade preflight compares active overlays with proposed module definitions. A deleted/renamed field, removed slot, changed type, changed required capability or changed UI schema version yields explicit stable-ID conflict diagnostics. Rename of a label with unchanged ID is compatible; identity rename requires an explicit alias/migration contract. Incompatible active overlays block module activation; operators may rebase a draft against the new base, publish a compatible revision and retain the old immutable evidence. No silent overlay drop, narrowing of classification, or automatic coercion of stored values. The existing [upgrade process](../architecture/UPGRADES.md) governs migrations, compatibility windows and release activation.

### Policy, tenancy and governance

Metadata describes presentation and validation; it grants no business authority. Metadata definitions themselves are potentially sensitive tenant resources: labels, enum choices, validation messages, references, menus/actions and business descriptions may disclose internal terminology or configuration. Backend Policy therefore guards definition read as well as Studio create/update/publish/rollback/retire, with tenant/scope isolation and [ADR-015](ADR-015-data-classification-ownership-and-tenancy.md) classification where applicable. Audit records the actor, scope, revision and outcome without indiscriminately copying sensitive definition payloads; export, retention and deletion treat definitions as protected tenant data. A resolved schema sent to a browser contains only definitions and field/action details the authenticated user is permitted to receive.

The backend also performs authoritative Policy checks on every resource read/write/query, action and field; menu hiding or frontend `requiredPermission` is presentation only. An `allow=true` metadata rule is invalid. The [ADR-014](ADR-014-trusted-policy-decision-context-v2.md) trusted decision context and owner facts are supplied by authoritative providers, not by browser or Studio fields. Field classification stores stable qualified ADR-015 IDs and resolves controls through Data Governance's public resolver; Policy consumes its own classification projection. Unknown/ambiguous/unavailable classification denies sensitive use. Custom field definitions cannot lower owner or canonical classification controls.

Reserved identity, `tenant_id`, owner/resource IDs, company/site authority fields, immutable technical IDs, audit/security fields, posted ledger facts and protected domain lifecycle fields cannot be overridden. Each resource owner publishes per-property customization levels: customizable, display-only, immutable, protected or hidden-from-Studio. A display customization never makes a field writable or readable without Policy and owner admission.

Vendor/module definitions are installation-scoped and immutable to tenant runtime. Tenant-owned metadata, revisions, overlays and custom instances carry `tenant_id`, constrained scope IDs and enabled/forced RLS in certified shared-schema deployments. Company/site inheritance is an explicit trusted Organization scope path: tenant → company → site; there is no fallback to a different sibling scope. Browser cache keys bind authenticated session/security context, trusted tenant/company/site, locale, module/base version, published revision IDs and Policy version/epoch. Session or scope transition cancels in-flight requests and invalidates metadata/query/policy caches per [Phase 4.5 browser adapter](../architecture/PHASE-4.5-BROWSER-ADAPTER.md). Redis/cache state is never metadata or authorization authority.

Metadata/Studio records auditable create, draft update, publish, rollback, archive, conflict, rebase, field create/retire and entity create/retire events with actor, tenant/scope, stable IDs, revision/digest and causal context. Audit uses the accepted Audit contract; a successful publish and its evidence must have a reviewed same-UOW/outbox path where required, with no claim of implementation here. Configurable operator-governed quotas limit entities per tenant, fields per entity, document bytes, rule depth/operations, nested view depth, menu depth, view size, query cost and filterable/sortable capabilities. The limits are capacity/security controls, not hardcoded commercial plan numbers.

Retirement archives definitions and prevents new assignments, while preserving historical values and revision meaning. Field removal never silently deletes stored values. Owner adapters and Metadata coordinate tenant export/delete and retention through published contracts, with [ADR-017](ADR-017-retention-hold-and-purge-coordination.md) holds and destructive authorization controlling physical erasure. Custom-entity instances, definitions, revisions and audit evidence have separately declared retention classes and legal-hold behavior; destruction is not a Studio UI side effect.

Menus and actions reference only admitted registered route/action identities, supported declarative navigation and published command contracts. External navigation requires a separate allowlisted URL/navigation contract. Metadata cannot invoke arbitrary backend methods or inject scripts. The resolved UI schema maps only to versioned Phase 4.5 Button, Form, DataTable, layout, modal/drawer, navigation, i18n and accessibility contracts; no parallel component framework or arbitrary React component injection.

## Public contracts and impact

Implementation will require separately versioned `metadata-definition`, `metadata-revision`, `customizable-resource`, `custom-field-values`, `custom-entity`, `metadata-resolver`, `resolved-ui-schema`, `validation-grammar`, `extension-slot`, `reference-resolution` and `studio-publish/preflight` contracts. Phase 5A must define expected draft/active/base/schema/dependency generations, stale-publish and stale-rollback diagnostics, and the module-activation compatibility fence. Reference resolution must cover bounded bulk reads, target lifecycle and unavailable/retired representation; diagnostics distinguish unavailable target, retired target and unsupported cross-owner deletion behavior. Exact package identifiers and wire schemas are Phase 5A acceptance work; this ADR locks their responsibilities, not unreviewed signatures. Existing `MetadataRegistry` and module manifest remain generic and are not repurposed as persistent storage. Changes to SDK, module contribution formats and UI schema versions require compatibility preflight. Metadata owns its tables/migrations; each resource owner owns any value-store migration. No historical migration changes.

## Consequences and gates

The hybrid model provides governed customization with bounded performance and owner isolation, at the cost of explicit owner adoption and query capability review. First-party modules are not automatically customizable. A Phase 5 implementation cannot claim completion until tenant/RLS isolation, Policy and classification fail-closed behavior, owner write containment, publish atomicity, deterministic resolution, upgrade conflicts, retention/export and Phase 4.5 renderer compatibility are certified. See the [Phase 5 specification](../roadmap/PHASE-5-METADATA-STUDIO-DYNAMIC-UI.md) for bounded batches. This proposal authorizes no runtime work before formal acceptance under [ADR governance](../governance/ADR-GOVERNANCE.md).
