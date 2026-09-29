# Metadata, Studio and Dynamic UI Architecture

Status: Phase 5 architecture proposal; implementation blocked pending formal acceptance of [ADR-023](../adr/ADR-023-metadata-persistence-customization-and-dynamic-ui-resolution.md).

## Boundary map

| Component | Owns | Does not own |
| --- | --- | --- |
| Protected kernel `MetadataRegistry` | Generic versioned declaration registration, owner/generation lifecycle and contribution admission | Studio persistence, customer definitions, custom values or UI layouts |
| Metadata/Studio Foundation | Persistent definitions, drafts, published revisions, overlays, custom-entity instances, resolution and diagnostics | First-party resource values, business authority, other owners' private tables |
| Resource-owning module | Ordinary record values, owner-side custom-field adapter, invariants, queries, export, retention and owner migrations | Global Studio definitions or another owner's records |
| Policy / Identity / Organization / Data Governance / Audit | Their accepted authority and evidence contracts | Authority delegated to metadata or browser presentation |
| Phase 4.5 frontend | Shell, routes/navigation contributions, design system, form/table primitives, scope and permission presentation | Metadata persistence or backend authorization |

This is a design for later implementation, not evidence that any Phase 5 service or table exists. It preserves [kernel responsibilities](KERNEL-RESPONSIBILITIES.md), [module ownership](MODULES.md), [database rules](DATABASE.md), [upgrades](UPGRADES.md), [frontend contracts](FRONTEND.md) and the [Phase 4.5 browser adapter](PHASE-4.5-BROWSER-ADAPTER.md). The current `platform/src/businessos/metadata.py` contains `MetadataDeclaration` and a generation-aware `MetadataRegistry`; Phase 5 must not silently turn that registry into a database-backed customer store.

## Write and read paths

```text
Studio draft → Metadata Foundation validation → immutable published revision
                                              ↓
owner-admitted CustomizableResource → first-party record values in owner's UOW
Metadata-owned custom-entity adapter → relational envelope + validated JSONB
                                              ↓
module base + contributions + published overlays + trusted scope/locale/Policy
                    → deterministic typed resolved UI schema
                    → Phase 4.5 components and registered route/action contracts
```

The Metadata Foundation alone writes definitions and custom-entity instances. A first-party resource owner alone writes its record's extension values and enforces owner invariants. A `CustomizableResource` contract must bind canonical [ADR-018](../adr/ADR-018-canonical-resource-ownership-and-owner-operation-boundary.md) namespace/owner/version, trusted tenant and scope, immutable record UUID, schema revision, optimistic version, explicit permitted field capabilities and an admitted owner operation. Create/update must validate against the published revision and owner rules before one owner-controlled commit. Read applies owner and Policy checks before returning field values. Filter/sort are allowed only through owner-advertised bounded query plans. Delete, export and retention stay with the owner. The contract does not expose a generic SQL table handle or privileged session to Metadata.

For Metadata-owned custom entities, stable scope and provenance fields are relational, with controlled JSONB values subject to the same schema validation. `tenant_id` and allowed company/site IDs are trusted server-side facts; JSONB values cannot override them. All tenant-owned tables require enabled and forced RLS under the certified shared-schema model, tenant-aware constraints and tested role/grant isolation. A cross-tenant or invalid-scope reference is rejected before write and again by the owner boundary.

## Definition model

Stable IDs, not labels, key entity, field, view, section, slot, action and menu definitions. Each definition records canonical owner, tenant/scope where applicable, schema version, lifecycle, classification reference if relevant, capability requirements, compatibility range and provenance. Drafts are editable. A published revision is immutable and content-addressable with an atomic active pointer. Runtime never consumes drafts. Definition version, value schema revision and UI schema version are distinct; all are present in diagnostics so historical records can be interpreted without rewriting metadata history.

The type registry is an allowlist: bounded text/long text, integer, exact decimal, boolean, date, timezone-aware instant, enumerated selection, canonical UUID/reference, exact money plus currency, and syntactic email/phone/URL. Field constraints are typed and total. Defaults are literal and deterministic. A required new field needs a validated backfill/activation path. Cross-field validation uses bounded comparisons and conditional required rules; it cannot run SQL, JavaScript or Python. Workflow/orchestration remains Phase 6.

Owner-protected and security-critical properties are not overlay targets: tenant/resource/technical IDs, owner and company/site authority, audit provenance, security tags, posted ledgers and owner-protected lifecycle state. Owners declare fields as customizable, display-only, immutable, protected or hidden-from-Studio. A presentation change cannot grant field read/write access or lower the qualified [ADR-015](../adr/ADR-015-data-classification-ownership-and-tenancy.md) classification. Data Governance resolves classification for Metadata through its public contract; Policy uses its Policy-facing projection. Missing or ambiguous classification fails closed.

## Query admission and relationships

Display-only is the default. Filterable, sortable, searchable, unique and reportable are separately admitted capability tiers. Phase 5 must support useful bounded equality/range filters and stable sort where the owner provides an indexed/approved plan, with server-side pagination and explicit limits. Unsupported or over-budget queries return a typed error. Uniqueness needs an atomic owner/database constraint within the declared tenant/scope, not an application precheck. Search and arbitrary reports belong to Phase 8 unless separately certified. Any added index is an explicit owner-controlled migration after tenant, lock, upgrade and capacity review; publishing metadata never executes DDL.

References carry canonical resource namespace/version, immutable UUID and tenant. The target owner checks visibility, existence and lifecycle through a public contract. Many-to-one is the Phase 5 baseline; one-to-one requires owner-backed uniqueness; many-to-many needs a future explicit relationship owner decision. Owner-declared restrict or nullify govern deletion. No arbitrary cross-module foreign key or cascading write is implied.

## Overlay and resolver contract

The ordered layers are: admitted module base → compatible admitted extension contributions → localization → published tenant overlay → allowed company overlay → allowed site overlay → eligible user presentation preference. A layer may touch only published extension slots and allowlisted properties. Conflicting stable IDs or incompatible property edits fail with deterministic diagnostics. The resolver does not silently pick an arbitrary winner. A company/site layer cannot change tenant-level security or owner invariants. A saved user preference is presentation only.

The cache identity includes base artifact and schema versions, all active published revision IDs, trusted tenant/company/site, authenticated session/security context, locale and Policy version/epoch. A session/identity/scope switch aborts in-flight queries and clears metadata, data and permission state as required by Phase 4.5. Cache failure or stale security context cannot yield a permissive schema. Metadata resolution may hide unavailable actions but backend command/query/route authorization remains mandatory.

The resolved schema is typed, versioned and limited to certified Phase 4.5 primitives: layout, form fields, DataTable columns/filters/pagination, detail, kanban/calendar/dashboard placements, menu/action references and translation keys. Extension slots accept declarative supported contributions only. They cannot contain raw React component imports, arbitrary scripts, CSS frameworks, method names or URLs. Menu/action references must resolve to registered route/action/command identities and be rechecked against backend Policy. Unknown component or schema versions fail closed with a diagnosable compatibility error.

## Publish, upgrade and retirement

Publish preflight validates type/schema, references, owner capabilities, Policy permission names, classification, quotas, UI contract version, installed module compatibility and existing values. A successful transaction writes an immutable revision and switches the active pointer atomically; it emits appropriate audit/outbox evidence through reviewed contracts. Failure preserves the old pointer. Re-activation of an earlier revision is a compatibility-checked pointer change, not a rewrite.

Module upgrades preflight deleted/renamed fields, removed slots, type/capability changes and UI schema-version changes. Incompatible active overlays block activation with stable-ID diagnostics. A customer may rebase a draft and publish a new revision; the previous revision and values remain evidence. Accepted [ADR-007](../adr/ADR-007-upgrade-strategy.md) compatibility windows and forward migrations govern any physical schema change. Historical migrations stay untouched.

Archive/retire prevents new use without deleting historical values. Tenant export/delete, legal holds, physical erasure and audit retention use owner and [ADR-017](../adr/ADR-017-retention-hold-and-purge-coordination.md) contracts. Studio actions cannot perform unreviewed destructive cleanup. Auditable events include draft/create/update, publish, rollback, retire, conflict/rebase, field and entity lifecycle, actor, scope, revision and digest. Operator-governed quotas bound entities, fields, document bytes, expression/view/menu depth, query complexity and high-tier query capabilities; exact numbers are deployment policy, not architecture constants.

## Certification boundary

The [Phase 5 roadmap](../roadmap/PHASE-5-METADATA-STUDIO-DYNAMIC-UI.md) divides implementation into separately auditable batches. No batch may claim production readiness without tenant/RLS, Policy, owner-boundary, compatibility, published-only runtime, deterministic resolver and Phase 4.5 regression evidence relevant to that batch. Formal ADR acceptance precedes runtime migrations or implementation.
