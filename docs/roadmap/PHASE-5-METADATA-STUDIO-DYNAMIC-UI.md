# Phase 5 — Metadata, Studio and Dynamic UI

Status: [ADR-023](../adr/ADR-023-metadata-persistence-customization-and-dynamic-ui-resolution.md) ACCEPTED / Phase 5A CERTIFIED / CLOSED / FROZEN / Phase 5B CERTIFIED / CLOSED / FROZEN / Phase 5C CERTIFIED / CLOSED / FROZEN / Phase 5D AUTHORIZED TO BEGIN subject to the reconciliation gate below / Phase 5 overall INCOMPLETE. Phase 5E–5H remain UNAUTHORIZED / UNCERTIFIED.

## Entry condition and destination

Phase 4.5 UI Foundation remains FINAL PASS / CERTIFIED / FROZEN; its accessibility maintenance is closed. ADR-023 was accepted through [PR #56](https://github.com/sahinkhan/businessos/pull/56), with accepted-main provenance reconciled through [PR #58](https://github.com/sahinkhan/businessos/pull/58). Phase 5A was implemented through [PR #61](https://github.com/sahinkhan/businessos/pull/61): final candidate `03234293aa21d6fa56254937b4b5ee74c7d2eb0a`, guarded merge `3f96d668eb24f0d505b45b13428fff1c05f1d7af`, and post-merge CI [run 36854266178](https://github.com/sahinkhan/businessos/actions/runs/36854266178) SUCCESS. Independent remediation re-audit closed at Critical 0 / High 0 / Medium 0 / Low 0. Owner acceptance is recorded in PR #61 comment `5930138099`, with supplemental Solo Maintainer governance evidence in comment `5931450033`. Phase 5A is therefore CERTIFIED / CLOSED / FROZEN. Phase 5B is now CERTIFIED / CLOSED / FROZEN at `b93c227a95adc683e0880d5ddc4bc710594683d0`. Phase 5C is now CERTIFIED / CLOSED / FROZEN at `e9baad7b7b8b7ef681099808d7ebed2db2f8337c`. Phase 5D is AUTHORIZED TO BEGIN within the boundary below; Phase 5D coding remains blocked until this reconciliation certification completes. Phase 5 overall remains INCOMPLETE.

Entry sequence completed through Phase 5C: ADR-023 acceptance and accepted-main provenance → bounded Phase 5A certification → bounded Phase 5B implementation and certification → bounded Phase 5C implementation → original exact-head CI and failed audit → runtime remediation and fresh exact-head CI → independent remediation re-audit PASS with L2 remaining → documentation correction and fresh exact-head CI → focused documentation re-audit PASS → personal owner acceptance → guarded merge → successful post-merge certification. Phase 5A, Phase 5B and Phase 5C remain CERTIFIED / CLOSED / FROZEN. Phase 5D authorization is bounded and conditional on this reconciliation certification; Phase 5E–5H are unauthorized and uncertified.

The destination is source-free customer customization of ordinary records, governed custom entities, versioned list/form/detail/kanban/calendar/dashboard definitions, menus/actions, validation, extension slots and deterministic UI resolution over the certified Phase 4.5 shell and design system. Customers can upgrade vendor/module definitions without losing customizations or taking over protected ownership. PostgreSQL remains authoritative; browser presentation never becomes authorization.

## Phase 5B certification provenance

Phase 5B is **CERTIFIED / CLOSED / FROZEN** on protected `main` at
`b93c227a95adc683e0880d5ddc4bc710594683d0`, following [PR #63](https://github.com/sahinkhan/businessos/pull/63).
The certification sequence distinguishes the original candidate and failed audit
from the accepted remediation and completed post-merge certification:

| Stage | Exact evidence |
| --- | --- |
| Original implementation candidate | `e02a427bce8df3627d340e84cc9ea362aa16eba3`, based on `64889d369dd5f3796d13f43260f87a74d37fbb5e` |
| Original exact-head CI | [36980442434](https://github.com/sahinkhan/businessos/actions/runs/36980442434) — SUCCESS |
| Original independent implementation audit | FAIL — Critical 0 / High 2 / Medium 0 / Low 0 |
| Original H1 blocker | Raw-handler Party custom-value authority bypass |
| Original H2 blocker | SDK-reachable Metadata protected execution authority exposure |
| Remediation candidate | `0db5a10e82e712f93abcde6253e79cb1f2300e96` |
| Remediation parent | `e02a427bce8df3627d340e84cc9ea362aa16eba3` |
| Remediation tree | `fed2ddfa6b2d4dd88cbcaefb1945a15725a36f64` |
| Fresh remediation exact-head CI | [37051035889](https://github.com/sahinkhan/businessos/actions/runs/37051035889) — SUCCESS |
| Fresh independent remediation re-audit | PHASE 5B REMEDIATION INDEPENDENT RE-AUDIT — PASS; Critical 0 / High 0 / Medium 0 / Low 0; H1 and H2 resolved |
| Personal Solo Maintainer owner attestation | [@sahinkhan, PR #63 comment 5966216066](https://github.com/sahinkhan/businessos/pull/63#issuecomment-5966216066), approving the exact remediation SHA and recording the independent re-audit |
| Guarded merge / certified checkpoint | `b93c227a95adc683e0880d5ddc4bc710594683d0`; direct parents `64889d369dd5f3796d13f43260f87a74d37fbb5e` and `0db5a10e82e712f93abcde6253e79cb1f2300e96`; tree equals the remediation tree |
| Post-merge certification CI | [37102510942](https://github.com/sahinkhan/businessos/actions/runs/37102510942) — SUCCESS on the guarded merge SHA |

The fresh exact-head and post-merge CI each passed `web-quality`, `python-quality`,
and `windows-typing`. The owner attestation states independent human review was
NOT PERFORMED and independent technical audit was PERFORMED. The original green
CI did not approve the failed original candidate; certification applies to the
remediation preserved by the guarded merge. No historical migration was rewritten.

## Historical Phase 5C entry boundary

The earlier Phase 5B reconciliation authorized governed custom entities only.
Its audit, owner acceptance, guarded merge and post-merge entry gates were
completed before Phase 5C implementation. That historical authorization did
not certify Phase 5C or authorize later batches. The implementation now
certified below retains that bounded scope: Metadata-owned relational
instances with pinned schemas, validated bounded JSONB, lifecycle/reference
semantics, tenant/RLS isolation, concurrency, bounded queries and safe
retention/export. It does not adopt Party ordinary-value tables.

## Phase 5C certification provenance

Phase 5C is **CERTIFIED / CLOSED / FROZEN** on protected `main` at
`e9baad7b7b8b7ef681099808d7ebed2db2f8337c`, following
[PR #65](https://github.com/sahinkhan/businessos/pull/65).
The original failed audit remains part of the certification chronology:

| Stage | Exact evidence |
| --- | --- |
| Original implementation candidate | `3ac10a34c572a6c4a1d3301310f6328f36698112` |
| Original parent/base | `c4e48ca365338f8142d06525f64aec39ac39e554` |
| Original tree | `bf15c834f9d9664cbb29def2588b6f089687c347` |
| Original exact-head CI | [37120604413](https://github.com/sahinkhan/businessos/actions/runs/37120604413) — SUCCESS |
| Original independent audit | PHASE 5C INDEPENDENT AUDIT — FAIL; Critical 0 / High 0 / Medium 2 / Low 1 |
| Original M1 | Frozen Phase 5A v1 definition compatibility broken by adding `custom_entity` to `DefinitionKind` |
| Original M2 | Tenant-wide mutation contention could exhaust the protected DB pool; transient capacity exhaustion could permanently invalidate healthy protected Metadata execution |
| Original L1 | Archived-list inclusion was not explicitly documented |
| First remediation candidate | `a8bd9b370e65347a456e65919ed612f6b93919e0` |
| Remediation parent | `3ac10a34c572a6c4a1d3301310f6328f36698112` |
| Remediation tree | `9a364d60389feccf5ecb3678f9d083257809e89f` |
| Fresh remediation exact-head CI | [37135779483](https://github.com/sahinkhan/businessos/actions/runs/37135779483) — SUCCESS; all three required jobs PASS |
| Independent remediation re-audit | PHASE 5C REMEDIATION INDEPENDENT RE-AUDIT — PASS; Critical 0 / High 0 / Medium 0 / Low 1 |
| Resolved findings | M1, M2 and L1 — RESOLVED |
| Remaining Low after first remediation | L2 — documentation punctuation encoding |
| Final accepted documentation candidate | `22d15f6f9e09be49225e7a32534ac23393387a18` |
| Final candidate parent | `a8bd9b370e65347a456e65919ed612f6b93919e0` |
| Final candidate tree | `d058581c6e53cb6da829cd04e53c65e6d92b58d3` |
| Final exact-head CI | [37143827091](https://github.com/sahinkhan/businessos/actions/runs/37143827091) — COMPLETED / SUCCESS; all three required jobs PASS |
| Focused independent documentation re-audit | PHASE 5C FINAL DOCUMENTATION RE-AUDIT — PASS; Critical 0 / High 0 / Medium 0 / Low 0; L2 — RESOLVED |
| Personal owner acceptance | [@sahinkhan, PR #65 comment 5972579781](https://github.com/sahinkhan/businessos/pull/65#issuecomment-5972579781), approving exact candidate `22d15f6f9e09be49225e7a32534ac23393387a18` |
| Guarded merge / certified checkpoint | `e9baad7b7b8b7ef681099808d7ebed2db2f8337c` |
| Direct merge parents | `c4e48ca365338f8142d06525f64aec39ac39e554` and `22d15f6f9e09be49225e7a32534ac23393387a18` |
| Merge tree | `d058581c6e53cb6da829cd04e53c65e6d92b58d3`, identical to the final accepted candidate tree |
| Protected-main post-merge CI | [37147061189](https://github.com/sahinkhan/businessos/actions/runs/37147061189) — COMPLETED / SUCCESS on the guarded merge SHA; all three required jobs PASS |

The required jobs are `web-quality`, `python-quality` and `windows-typing`.
The focused documentation audit established that the final commit changed no
runtime, security, contract, migration or test semantics, so the previous
technical PASS remained applicable. The original successful CI did not override
the original failed audit.

Review model: SOLO MAINTAINER OWNER ATTESTATION.
Independent human review: NOT PERFORMED.
Independent technical audit: PERFORMED.
The personal acceptance above is the existing approval record; this
reconciliation does not create another owner approval.

## Phase 5D authorization boundary

Phase 5D is **AUTHORIZED TO BEGIN** only for **Published UI Schema and Resolver**.
This authorizes a future separately audited implementation; Phase 5D is
**NOT IMPLEMENTED / NOT CERTIFIED**. Phase 5 overall remains **INCOMPLETE**.
Phase 5E–5H remain **UNAUTHORIZED / UNCERTIFIED**.

**Phase 5D coding remains blocked until this documentation/provenance
reconciliation PR itself completes every gate in order:**

1. Fresh exact-head CI with all required jobs successful.
2. Fresh independent technical documentation/provenance audit PASS.
3. Personal owner exact-SHA attestation after audit PASS.
4. Guarded merge preserving the audited candidate.
5. Successful protected-main post-merge CI.

No Phase 5D runtime is introduced by this reconciliation. Phase 4.5 remains
FINAL PASS / CERTIFIED / FROZEN; Phase 5A, Phase 5B and Phase 5C remain
CERTIFIED / CLOSED / FROZEN. Their authority, runtime and public contracts are
not reopened.

### Purpose and dependencies

Phase 5D may implement backend Metadata contracts and runtime that produce a
deterministic, typed, published-only UI schema or an explicit conflict.
Dependencies are certified Phase 5A definition/publication, Phase 5B ordinary
resource customization, Phase 5C governed custom entities and Phase 4.5 UI
foundation; stable Phase 4.5 route/navigation/slot/permission/component contracts;
accepted authoritative ADR-023; existing Policy/Identity/Organization authority;
ADR-018 ownership; and trusted scope contracts.

### Bounded authorized scope

- Versioned published UI-schema, resolver and extension-slot contracts.
- Stable view/section/slot/field/action identities required by resolver output.
- Published overlays, published-only reads, deterministic precedence and conflict
  diagnostics, allowlisted presentation properties and owner capability enforcement.
- A Metadata-owned forward persistence migration for views/overlays **only if**
  implementation analysis proves persistence is required; no historical migration
  changes and no runtime customer DDL.
- Localization, trusted tenant/company/site overlay eligibility, and eligible user
  presentation preferences that cannot change security or authority.
- Policy/scope fail-closed behavior and compatibility preflight for module/base,
  schema/UI contract and dependency/capability generations.
- Security-complete cache identity, invalidation inputs and session/security/scope
  transition safety.
- Typed output limited to certified Phase 4.5 primitives, with explicit unsupported
  component/schema-version diagnostics.

### Deterministic resolution order

admitted module base
→ compatible admitted extension contributions
→ localization
→ published tenant overlay
→ eligible company overlay
→ eligible site overlay
→ eligible user presentation preference

Conflicting stable IDs or incompatible edits have no arbitrary winner.
Conflicts must fail deterministically with bounded diagnostics. User preferences
are presentation only and are never published business metadata or authority.

### Security, properties and published-only inputs

Resolved UI schema is **PRESENTATION, not authorization**. It must not grant
backend permissions, override Policy, weaken owner invariants or ADR-015
classification, trust browser-provided tenant/company/site authority facts,
expose unauthorized metadata, or turn hidden controls into backend authority.
Backend Policy remains authoritative for every actual business command, query
and action. Unknown/pending/error Policy, scope, classification or compatibility
state fails closed wherever security-sensitive output is involved.

Overlays may change only explicitly allowlisted presentation properties.
Protected properties cannot be overridden: tenant/resource/owner identity,
technical IDs, company/site authority facts, security facts, audit facts,
posted/immutable business facts, owner-protected lifecycle and backend permission
requirements. Owner capability admission remains mandatory.

The runtime resolver consumes only published compatible definitions/revisions.
Draft metadata must never leak into production resolved schema.
Rollback/reactivation uses compatibility checks and never rewrites history.

### Cache identity and transition safety

The future security-complete cache identity must account for applicable base
artifact/version/generation, active published revision IDs, trusted tenant,
eligible company and site, authenticated session/security context, locale,
Policy version/epoch and relevant schema/UI contract generations, together with
dependency/capability generations where they affect the resolved result.
Cache state is never authority. Invalidation and scope/session/security
transitions must prevent stale permissive schema, including cancellation or
rejection of in-flight results tied to the previous context.

### Phase 4.5 consumption and non-goals

Output targets certified Phase 4.5 primitives only. No parallel UI framework,
arbitrary React imports, JavaScript, Python, SQL, CSS framework injection,
method names or unrestricted URLs are permitted. Phase 5D defines typed schema
and resolution; actual frontend dynamic rendering belongs to Phase 5E.

Phase 5D does **not** implement:

- Phase 5E form/detail/list rendering or an actual dynamic React renderer.
- A new frontend component framework.
- Phase 5F Kanban, calendar or dashboard definitions or menu/action authoring.
- Phase 5G Studio authoring UI.
- Phase 5H final upgrade/export certification.
- Workflow/rules or Phase 6 orchestration.
- Phase 8 search/analytics or arbitrary reports.
- Arbitrary executable metadata or unrestricted URLs/scripts.
- Global EAV, runtime customer DDL or new business authorization.
- Physical purge/destruction.

### Future Phase 5D implementation exit gate

These are **future required proofs**, not tests already passed:

- Published-only input and no draft leakage.
- Deterministic precedence, stable-ID conflicts and property allowlists.
- Tenant/company/site overlay isolation and Policy/scope fail-closed behavior.
- Localization determinism.
- Complete cache identity/invalidation and session/scope transition safety.
- Module upgrade compatibility preflight and stale revision/base generation conflicts.
- Unsupported component/schema-version diagnostics and Phase 4.5 contract compatibility.
- No arbitrary code/UI injection and no backend authority granted by presentation.

Future implementation requires its own exact-head quality gates, independent
security/compatibility audit, owner acceptance, guarded merge and post-merge
certification. Authorization here is not proof of implementation or certification.

## Goals, non-goals and ownership

Goals: explicit owner-scoped storage, published-only runtime, safe query tiers, typed metadata contracts, deterministic overlays, compatibility preflight, tenant/Policy isolation, auditable publishing and accessible localized rendering. The [focused architecture](../architecture/METADATA-STUDIO.md) defines the paths; accepted [ADR-023](../adr/ADR-023-metadata-persistence-customization-and-dynamic-ui-resolution.md) records the persistence decision.

Non-goals: changing frozen Phase 4/4.5 authority, new Policy behavior, kernel-owned Studio persistence, global EAV, customer-triggered DDL, arbitrary executable metadata, Phase 6 workflow/rules, Phase 8 general search/analytics or Phase 10+ business modules. Existing `MetadataRegistry` remains generic registration infrastructure. The Metadata/Studio Foundation owns persistent definitions/custom entities; each first-party resource owner owns its custom values and migrations. No owner is automatically enrolled.

## Required contracts and security rules

Versioned public contracts are needed for metadata definitions/revisions, `CustomizableResource` owner adoption and field values, custom entities, reference resolution, typed resolver and resolved UI schema, validation grammar, extension slots, query capability/limits and Studio publish/preflight diagnostics. Exact wire formats and names are decided in 5A without changing the accepted ownership model. Canonical [ADR-018](../adr/ADR-018-canonical-resource-ownership-and-owner-operation-boundary.md) resource namespaces and trusted owner admission are prerequisites; a module manifest or browser value cannot claim another owner. SDK compatibility and module lifecycle use existing governance. No contract exposes raw tables or a privileged SQL handle.

Every tenant-owned table has `tenant_id`, owner-controlled constraints, enabled/forced RLS and tested grants for certified shared-schema deployments. Tenant/company/site scope derives from authenticated backend Identity and Organization contracts. Policy authorizes Studio operations and every business command/query/field/action on the server. Unknown/pending/error Policy, classification, scope or revision state denies. Custom fields store qualified [ADR-015](../adr/ADR-015-data-classification-ownership-and-tenancy.md) classification IDs and cannot weaken owner/canonical controls. Field/menu visibility is only presentation. Metadata never issues an `allow=true` authorization override. No browser-created identity, scope or permission is trusted.

Metadata definitions are themselves protected tenant resources. Labels, enum values, validation messages, reference settings, menus/actions and business descriptions may expose internal information. Backend Policy guards definition read/create/update/publish/rollback/retire; scope isolation, applicable Data Governance classification, export, retention and deletion apply. Audit captures identity, revision and outcome without indiscriminately copying definition payloads. Resolved schemas sent to the browser contain only information the authenticated user may receive.

The existing ADR-015 classification implementation gate remains independent. A Phase 5 batch may define contracts while that prerequisite is outstanding, but cannot publish or certify classified custom fields until the authoritative resolver and Policy-facing classification path are separately implemented and certified. A missing resolver does not permit an unclassified or weaker fallback.

Protected properties include tenant/owner/resource IDs, technical IDs, company/site authority, audit and security facts, immutable posted records and owner-declared protected lifecycle state. The owner advertises customization levels and supported query tiers. Metadata validation is declarative and bounded; Phase 6 owns workflow. Custom references use canonical public resource identities and owner-provided lookup, not private cross-module foreign keys. No implicit cross-module cascade. Studio menu/action definitions reference only admitted registered route/action/command contracts.

Same-owner references may use owner-certified restrict, nullify or controlled cascade. Cross-owner references have no generic synchronous restrict/nullify/cascade contract. The source owner retains its reference value; the target owner reports lifecycle through a bounded single/bulk resolver; archive or retirement does not mutate another owner's row. New references to non-referenceable targets fail closed, while historical references remain diagnosable. Physical purge stays under ADR-017 and canonical owner operations. Stronger cross-owner integrity would require a separately versioned and certified coordination contract; Phase 5 does not invent one.

## Persistence and query model

Use the governed hybrid of relational envelopes plus validated bounded JSONB. Ordinary record values remain with each opted-in resource owner through its versioned adapter; Metadata owns only their definitions. Metadata-owned custom entities have relational identity, tenant/scope, lifecycle, provenance and concurrency facts plus a type-checked value document. No global EAV and no JSONB-only generic domain table. Physical indexes or promoted columns require explicit owner-controlled forward migrations; a Studio publish cannot execute DDL. All historical migrations remain unchanged.

The query ladder is display-only by default, then separately admitted filterable, sortable, searchable, unique and reportable tiers. Useful Phase 5 equality/range filtering and stable ordering require an approved owner plan, quota and server-side pagination. Unsupported or over-budget queries fail explicitly. Unique constraints must be atomic and tenant/scope aware. General text search and analytics are deferred to Phase 8 unless a separately reviewed owner capability is certified. Configurable limits govern entities per tenant, fields per entity, metadata/value bytes, rule/view/menu depth, filter/sort count, query cost and publishing workload without hardcoding pricing tiers.

## Versioning, overlays and upgrade safety

Drafts are editable; published revisions are immutable complete snapshots. Publish preflight checks schema/types, references, owner capabilities, classification, permissions, UI version, quota and upgrade compatibility, then atomically activates a new revision. Runtime reads only the active published revision. Failed publish leaves the old one active. Rollback is compatible reactivation of an older revision, never history rewriting. Retired definitions and old values remain interpretable/exportable under retention policy.

Publication and rollback are conditional on the exact preflighted draft version, active revision, module/base artifact generation, schema/UI contract generation and dependency/capability generations. A shared authoritative fence rechecks these at activation/commit; changed state rejects with a stale/conflict diagnostic and preserves the prior revision. Module install/upgrade/activation uses the same serialization invariant against its preflighted active metadata revision set. Two publishers cannot silently overwrite the same draft or active pointer, and module activation cannot race publication into an incompatible active pair. Phase 5A chooses and certifies a PostgreSQL-compatible mechanism; the architecture locks the outcome, not a particular lock primitive.

Stable IDs identify entity/field/view/section/slot/action/menu independently of labels. Resolution order is admitted module base; compatible extension contributions; localization; tenant overlay; eligible company overlay; eligible site overlay; user presentation preference. Each layer is restricted to allowlisted properties and slots; security and owner invariants cannot be lowered. Inputs include base/revision IDs, trusted scope, locale and security/Policy context. The same inputs give the same schema or explicit conflict. Scope/session transition cancels requests and invalidates data/metadata/policy caches. Upgrades preflight removed fields/slots, identity/type/capability and UI version changes. Incompatibility blocks activation, emits diagnostics and supports a draft rebase without dropping the old revision.

## Rendering and governance

Typed resolved schemas map to Phase 4.5 layout, Button, Form, DataTable, modal/drawer, navigation, scope/permission presentation, i18n/RTL and accessibility contracts. No parallel shell, private component framework, arbitrary React import or script injection. Lists must use server pagination/filtering. Menus/actions must resolve to registered routes/commands and remain subject to backend checks. Kanban/calendar/dashboard are view definitions over admitted query/data contracts, not new authority or arbitrary report engines.

Studio authoring/publishing/rollback/retirement and compatibility conflicts are auditable with actor, tenant/scope, stable IDs, revision/digest and causal context. Archive is distinct from erasure. Owner contracts support tenant export/delete, field/entity retirement, legal hold and preservation of published revision evidence under [ADR-017](../adr/ADR-017-retention-hold-and-purge-coordination.md). New destructive behavior requires a separately certified owner path. These are design obligations, not implementation claims.

## Bounded implementation sequence

Each batch is a separately reviewable candidate. A batch cannot claim completion based solely on passing unit tests; the listed gate and independent audit apply to its exact commit. No batch changes an accepted architecture decision without a new ADR.

| Batch | Scope and dependencies | Migrations and public contracts | Tests, exit gate and independent audit boundary |
| --- | --- | --- | --- |
| **5A — Contracts and definition foundation** | After ADR-023 acceptance. Versioned definitions, type/validation grammar, drafts, immutable revisions, publish/preflight and audit. No custom values or UI runtime. | New Metadata-owned forward migration for tenant-aware definitions/revisions/active pointers, RLS/grants; definition/revision/publish/diagnostic contracts. Versioned publication contracts include expected draft generation, active revision, module/base and schema/UI generations, compatibility/dependency generations, stale-publish/stale-rollback diagnostics and module-activation fence. Versioned reference contracts include bounded bulk resolution, target lifecycle and retired/unavailable representation, with no cross-owner deletion side effect. Diagnostics distinguish stale draft, active revision conflict, module/base generation change, incompatible dependency, unavailable target, retired target and unsupported cross-owner deletion behavior. Exact wire schemas remain 5A work. | Type/schema and malicious-payload rejection; two-publisher lost-update, publish-versus-module-activation and rollback-versus-upgrade race proofs; atomic publish/rollback, quota, RLS/cross-tenant, reference lifecycle/bulk isolation, audit/outbox and migration replay. Audit exact 5A contract/schema/authority boundary; exit only with published-only read, compatible serialization and clean preflight. |
| **5B — Ordinary record custom fields** | 5A and accepted ADR-018 owner contract. Add one explicitly selected first-party owner adapter, its lifecycle/query capabilities and field read/write; further owners enroll separately. | Owner-controlled forward migration for values/indexes if needed; `CustomizableResource`, custom-field value and query-capability contracts. Metadata may not migrate owner tables. | Same-UOW owner create/update/read/delete/export, Policy/classification, conflict/concurrency, tenant isolation, unsupported query rejection and rollback. Independent audit exact owner SQL/grants/admission; exit with no direct Metadata write to owner tables. |
| **5C — Governed custom entities** | 5A; owner model and quotas from 5B inform semantics, but does not adopt 5B tables. | Metadata-owned forward migration for instance relational envelope and JSONB; custom-entity, lifecycle/reference contracts. | RLS/tenant and scope isolation, schema revision pinning, type/reference validation, retention/export, concurrency and bounded queries. Audit exact generic-store escape and grants; exit with no unrestricted schemaless records. |
| **5D — Published UI schema and resolver** | Certified 5A/5B/5C and Phase 4.5; stable route/navigation/slot/permission/component contracts; ADR-023, ADR-018 and trusted authority/scope; conditional authorization gate above. | Metadata-owned forward migration for views/overlays only if required; versioned UI schema, extension-slot and resolver contracts. | Deterministic precedence/conflict/property allowlist, upgrade preflight, cache identity/invalidation, Policy/scope fail-closed and localization. Independent audit exact resolver security/compatibility boundary; exit with published-only typed output. |
| **5E — Form/detail/list rendering** | 5D and Phase 4.5 certified primitives; 5B/5C owner data contracts. | No runtime DDL; additive UI schema contract versions only, plus reviewed Metadata migration if definitions need persisted properties. | Component/a11y/keyboard/RTL/responsive/i18n, field Policy, query cancellation, pagination/filter budget, error states and browser cache isolation. Audit exact UI/data/authority boundary; exit without parallel design system. |
| **5F — Kanban/calendar/dashboard/menu/action definitions** | 5D/E and registered route/action/command contracts. | Metadata-owned forward migration only for new persisted definition kinds; additive typed view/action contracts. | Query cost/pagination, route/action admission, backend authorization, no arbitrary URL/code, localization and accessibility. Independent audit each new action/query surface; exit with no new business authority or Phase 8 analytics claim. |
| **5G — Studio authoring UI** | 5A–F publish and compatibility APIs. | No separate business schema; versioned Studio authoring/preflight APIs and UI contract. | Draft isolation, explicit publish/rollback permissions, conflict diagnostics, tenant/scope transitions, CSRF/session, accessibility and upgrade preview. Audit exact author/publish/evidence boundary; exit with no draft leakage into production runtime. |
| **5H — Upgrade, export and certification** | 5A–G. Production-like module/customer upgrade and rollback/restore rehearsal. | Forward migrations only for identified compatibility gaps, with owning-module approval; published compatibility/export contracts. | Full migration replay, installed-wheel and images where relevant, module upgrade conflict matrix, tenant export/delete/hold, heavy-user quotas/performance, full regression and Phase 4.5 frozen checks. Independent exact-head combined security/ownership/compatibility audit; exit only after all blocking findings close and owner acceptance process completes. |

For each batch, inspect the actual migration graph before naming revisions; no historical revision is rewritten. Hosted CI, exact-head independent audit and formal owner approval follow repository governance. Batch sequencing may split further when an owner adapter or UI surface warrants its own certification; it must not combine unrelated migrations to save review steps.

## Acceptance checklist for final Phase 5

- All published definitions and ordinary/custom records have one authoritative owner and no cross-module private-table mutation.
- No global EAV, runtime schema auto-sync, unreviewed customer DDL or executable metadata exists.
- Tenant and company/site isolation, enabled/forced RLS, Policy/classification fail-closed behavior and protected-field rules pass adversarial tests.
- Versioned contracts, published-only reads, deterministic resolution, atomic activation/rollback and module-upgrade conflict blocking pass.
- Query tiers and quotas prevent unbounded scans and misleading search/unique/reporting guarantees.
- Phase 4.5 shell/design system, routes, forms/tables, scope transitions, i18n/RTL, accessibility and responsive regressions pass unchanged.
- Audit, export, retention, hold and deletion behavior has owner-certified evidence.
- Forward migrations, compatibility, installed artifact and deployment validation pass where applicable; independent exact-commit audit has no blocking findings.

The historical Phase 5A, Phase 5B and Phase 5C implementation entry and
certification gates are completed as recorded above. This reconciliation records
certified Phase 5C and bounded Phase 5D authorization only; it introduces no
Phase 5D runtime. Phase 5D coding remains blocked on the reconciliation CI,
independent audit, personal owner exact-SHA attestation, guarded merge and
protected-main post-merge CI. Phase 5E–5H remain UNAUTHORIZED / UNCERTIFIED.
Later batches retain separate prerequisites and implementation certification
gates. Phase 5 overall remains INCOMPLETE.
