# Phase 5C — Governed Custom Entities

Status: **Phase 5C implementation candidate**. Independent audit, personal
exact-SHA owner acceptance, guarded merge and post-merge certification remain
required. Phase 5 overall is incomplete; Phase 5D–5H are not authorized by this
document.

Certified starting point: `c4e48ca365338f8142d06525f64aec39ac39e554`.
This bounded backend extension uses accepted ADR-023, ADR-018, ADR-017 and ADR-015.
It does not replace their decisions or reopen earlier frozen certifications.

## Ownership and type identity

`foundation.metadata` owns definitions, immutable schema revisions and instances.
The static canonical instance resource family is
`foundation.metadata.custom_entity`, owner contract version `1`. Each type is
identified by its immutable Metadata definition UUID, never its label, translation,
route or field names. Customer types do not register modules, wildcard ownership or
new resource namespaces. Party storage is not used.

The additive `DefinitionKind.CUSTOM_ENTITY` reuses the Phase 5A `DefinitionSnapshot`,
`FieldDefinition`, `FieldType`, `ValidationRule`, publication lifecycle and digest
contracts. The definition UUID already supplies the additional type identity.
A partial unique index keeps the existing `(tenant_id, resource_namespace, kind)`
uniqueness for every ordinary definition. Only `custom_entity` definitions in the
exact Metadata family are exempt. A database check enforces that family/kind
equivalence, owner and version. Existing ordinary rows are not reinterpreted.

## Public operations and persistence

Version `1.0` frozen, extra-field-forbidding contracts cover identity, records,
scope, lifecycle, pages, query capabilities and per-record exports. Supported
installed imports are `businessos_metadata` and its documented `custom_entities`
and `module` modules. Values reuse SDK `CustomFieldValue` with stable field UUIDs.

Typed commands are `CreateCustomEntity`, `UpdateCustomEntity` and
`ArchiveCustomEntity`; typed queries are `ReadCustomEntity`, `ListCustomEntities`
and `ExportCustomEntity`. They are dispatcher operations, not a generic JSON save
endpoint. Create takes a type ID, scope kind and values. Update is complete
replacement with `expected_version`; archive also requires that version. Callers
cannot supply instance IDs on create, tenant, owner, scope UUID, revision pin,
lifecycle, actors or timestamps. The server generates the technical instance UUID.

`platform_metadata.custom_entities` has a relational identity envelope:
`id`, `tenant_id`, `definition_id`, `revision_id`, `revision_digest`, `lifecycle`,
`scope_kind`, `scope_id`, `value_version`, `created_by`, `updated_by`, `created_at`,
`updated_at`, `archived_at`, plus one bounded `value_document` JSONB object.
There are no field-per-row records or customer-specific physical tables.
A four-column FK binds the immutable pin to the same tenant, definition, revision
and digest. There are no cross-owner foreign keys.

Database checks enforce positive BIGINT versions, digest shape, current/archived
lifecycle, archive timestamp consistency, scope shape, exact tenant scope and a
JSON object/physical byte ceiling. Invoker-security triggers preserve instance
identity/scope/creation provenance, initial state, exact version increments,
archived immutability and archive pin/value preservation. Definition identity is
immutable. Physical instance deletion is refused even for the migrator.
The database structural checks complement the application field grammar; SQL does
not attempt to implement the full schema language.

## Trusted scope and Policy

Scope kinds map only to existing trusted `TenantContext` UUID fields: tenant,
active company, enterprise group, legal entity, business unit, division, department,
team, region, operating site, warehouse, cost center, profit center and project.
The caller selects a kind; the backend derives its UUID. An absent or malformed
trusted field fails closed. A scoped record is readable/writable/exportable only
with the exact corresponding active scope. Lists select exact type and scope.
Browser selection is not authority.

Server permission registrations enforce `foundation.metadata.custom_entity.read`,
`create`, `update`, `archive` and `export`; lists use `read`. Every operation also
requires `foundation.metadata.definition.read`. Same-owner reference validation
requires target-read permission. Denied, unknown and error Policy states fail
closed; no frontend behavior grants backend authority.

## Lifecycle, pins and validation

Create requires a published custom type and produces a current instance at
version 1. Update requires current lifecycle, exact expected version and a currently
published type. Archive increments the version while retaining the exact pin and
values; it does not delete or erase. Retired types reject create/update, while
historical pinned read/export and safe archive remain available under Policy.

Create/update resolve immutable active revision R, validate against R and store
its exact ID/digest. Publication may advance after resolution: an in-flight writer
still commits only a document validated against R, pinned to R. A subsequent update
resolves R+1 and rejects incompatible prior values. Read/export interpret the
stored immutable pin, not the current active schema. Deterministic PostgreSQL
barriers exercise this publication race without sleeps as a correctness mechanism.

The certified literal/rule validator handles supported text, integer, boolean,
decimal, money, enum, UUID, date, instant, email, phone and URL values. Unknown or
duplicate stable IDs, required omissions, nonnullable nulls, incompatible values,
arbitrary nested structures, invalid precision and nonfinite numbers are refused.
Documents are serialized canonically with sorted keys and no NaN/Infinity; input
values are detached before asynchronous execution. No executable expression is
introduced.

Classification references fail closed at publication and instance interpretation.
The authoritative ADR-015 classification resolver is not certified for this batch;
there is no unclassified fallback or claim of classified-entity certification.

## Bounded references

`FieldType.REFERENCE` supports only the same static Metadata instance family,
version `1`, with the existing `CanonicalResourceReference` identity (tenant,
namespace, version, record UUID). A random UUID string is insufficient. New
references require the exact tenant, trusted target scope, current instance and
published target type. Missing, archived, unavailable, cross-scope and cross-tenant
targets are refused. Reference fields target the canonical family; the certified
schema grammar does not declare a particular target-type UUID, so there is no
claim of per-field target-type restriction beyond that family.

The certified literal/rule validator uses the validated reference's technical UUID
as a bounded projection for rule evaluation; stored schemas and their digests are
unchanged. This preserves conditional-required rules for reference fields.

When a target is later archived or its type retired, the source is not mutated.
Read/export retain the canonical value and return a typed retired diagnostic.
Inaccessible targets return unavailable diagnostics without payload disclosure.
Cross-owner reference schemas are explicitly rejected for runtime instance use;
there is no Party credential, private-table read, generic cross-owner broker,
cross-owner cascade, restrict or nullify behavior.

## Queries, budgets and concurrency

Supported queries are one-by-ID and exact type/scope lists, ordered by immutable
instance UUID with an exclusive `after` UUID cursor. Pagination is server bounded.
Indexes cover `(tenant, type, scope kind, scope ID, ID)` and
`(tenant, type, lifecycle, ID)`. Query capabilities explicitly declare arbitrary
custom-field filtering/sorting, search, uniqueness and analytics unsupported.
Unsupported query operations fail rather than scan JSONB.

Operator-supplied `CustomEntityLimits` default to 100,000 retained instances per
tenant, 10,000 per type, 100 rows per page and 100 references per document.
Archived instances count toward retained-storage quotas. Existing `MetadataLimits`
default to 1,000 definitions per tenant (ordinary and custom combined), 128 fields,
32 rules and 65,536 schema/value-document bytes. Limits are bounded typed
configuration, not commercial pricing tiers. The database has an independent
1 MiB physical JSONB ceiling.

All instance mutations first acquire the transaction-scoped tenant advisory lock
`metadata-custom-entity:<tenant UUID>`, then lock an existing source row, then resolve
immutable schema and reference facts. Reference UUIDs are sorted before the bounded
lookup. Custom-type retirement acquires the same tenant lock before the existing
module-fence and definition locks. Definition creation retains the certified
definition-quota serialization. Publication keeps its existing fence locks and
does not take the instance advisory lock or silently reinterpret resolved pins.
No instance path takes a definition row lock, avoiding an inverted lock order.

Tenant serialization makes instance quotas atomic and orders reference creation
against target archive/type retirement. A new reference cannot commit after a
target ceased being referenceable before its commit. PostgreSQL race probes verify
the contested advisory lock. Version conflicts have one winner and one typed
loser, followed by an explicit retry; values, Audit and outbox commit once.

## Protected execution, RLS and evidence

Only six exact Metadata command/query classes are added to the existing private
protected execution allowlist. The protected table inventory adds only
`platform_metadata.custom_entities` with SELECT/INSERT/UPDATE. The role retains
NOSUPERUSER/NOCREATEDB/NOCREATEROLE/NOINHERIT/NOBYPASSRLS, nonownership and exact
inventory/policy validation. Ordinary app, worker, operations and PUBLIC grants
are revoked. RLS is enabled and forced with exact `app.tenant_id` USING/WITH CHECK;
missing/malformed tenant state fails closed. No ordinary database fallback exists.

The store demands the framework-issued exact live invocation binding, including
request, UOW, task, owner, generation and operation kind before persistence.
Public capability/contract objects contain no pool, engine, UOW factory, protected
authority or privileged callback. Certified H1/H2 enforcement is retained.

Successful create/update/archive append value-free `AuditEvidenceV2` and emit
`metadata.custom-entity.changed.v1` into the existing transactional outbox in the
same protected PostgreSQL UOW. Evidence carries safe identity, revision, version,
lifecycle, scope and correlation facts, not arbitrary values. Validation, Policy,
conflict, cancellation and pre-commit failure rollback probes verify no partial
value/Audit/outbox success survives. No nested transaction or autonomous publish
is introduced.

## Migration, retained data and non-goals

New Metadata-owned revision `metadata_0002_custom_entities` follows exact
`metadata_0001`; historical migrations remain byte-for-byte unchanged. It adds
the partial identity index, revision-pin constraint, instance table, constraints,
triggers, indexes, RLS and exact grants. Retained ordinary definitions survive
exact certified-base upgrade and replay unchanged. Source and installed-wheel
graphs must match; wheels must contain the new contracts/runtime/migration without
source-tree shadowing. Development, production and migration-smoke images are
required validation artifacts.

Downgrade locks definitions/instances and refuses if any retained custom instance
(current or archived) or custom type definition exists. Every refusal check occurs
before destructive DDL. With no custom data, the empty downgrade restores the
original ordinary uniqueness and schema kind constraints. A separately certified
recovery/export process is required before any future destructive capability.

Per-record export preserves stable identity, owner, lifecycle, provenance and
schema facts. Phase 5C does not implement full `retention-policy.v2`,
`purge-authority.v2`, bulk tenant export, anonymization, legal-hold orchestration,
runtime customer DDL, global EAV, cross-owner destructive semantics, dynamic UI,
Studio, executable metadata, workflow/rules, search/analytics or Phase 5D–5H.
