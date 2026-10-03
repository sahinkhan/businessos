# Phase 5C — Governed Custom Entities

Status: **Phase 5C CERTIFIED / CLOSED / FROZEN** on protected `main` at
`e9baad7b7b8b7ef681099808d7ebed2db2f8337c`.
Phase 4.5 remains FINAL PASS / CERTIFIED / FROZEN; Phase 5A and Phase 5B remain
CERTIFIED / CLOSED / FROZEN. Phase 5 overall remains INCOMPLETE.
Phase 5D is AUTHORIZED TO BEGIN only within the
[bounded roadmap authorization](../roadmap/PHASE-5-METADATA-STUDIO-DYNAMIC-UI.md#phase-5d-authorization-boundary).
Phase 5D coding remains blocked until this reconciliation PR passes fresh
exact-head CI, independent audit, personal owner exact-SHA attestation, guarded
merge and successful protected-main post-merge CI.
Phase 5D is not implemented or certified; Phase 5E–5H remain UNAUTHORIZED / UNCERTIFIED.

Implementation starting point: `c4e48ca365338f8142d06525f64aec39ac39e554`.
The certified bounded backend extension uses accepted ADR-023, ADR-018, ADR-017
and ADR-015. It does not replace their decisions or reopen earlier frozen
certifications. The runtime architecture description below is preserved.

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

## Ownership and type identity

`foundation.metadata` owns definitions, immutable schema revisions and instances.
The static canonical instance resource family is
`foundation.metadata.custom_entity`, owner contract version `1`. Each type is
identified by its immutable Metadata definition UUID, never its label, translation,
route or field names. Customer types do not register modules, wildcard ownership or
new resource namespaces. Party storage is not used.

The frozen Phase 5A definition v1 contract and its `DefinitionKind` remain
byte-identical to protected base: only `field_set` and `reference_set` are public
v1 kinds. Custom types use the independently versioned
`foundation.metadata.custom-entity-definition.v1` contract (`1.0`), including
`CustomEntityDefinitionSnapshot`, identity, definition/draft/revision records and
dedicated create/edit/read/retire commands and queries. Their envelope reuses the
certified `FieldDefinition`, `FieldType`, `ValidationRule`, consistency validator,
publication lifecycle and digest algorithm; there is no second field grammar.
Internal persisted kind remains `custom_entity`. Old create cannot represent that
kind; old edit/read/retire surfaces reject custom types with an explicit
`definition_contract_required` result. Shared publish/reactivate/preflight contracts
carry opaque IDs/generations and no kind/snapshot, so their existing logic remains
shared. Unsupported new-surface versions are rejected at the boundary. This is an
additive coexistence implementation under ADR-023 and RELEASES.md; no frozen
consumer is required to migrate or receive a new enum value. The definition UUID already supplies the additional type identity.
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
instance UUID with an exclusive `after` UUID cursor. Pagination is server bounded. Archived rows are included by default, participate
in pagination and return lifecycle in each record. They remain immutable and
exportable under Policy. No lifecycle filter is currently supported.
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

Create/quota admission is serialized per tenant before protected DB checkout.
The database create-only tenant advisory lock independently preserves quota safety
across processes; archived instances continue to count. Updates and archives have
no tenant-global mutation lock. Private bounded keyed admission queues overlapping
source/target UUID sets before checkout, while unrelated records/types and tenants
progress independently. A maximum of 4,096 active/waiting tickets and the configured
bounded admission timeout limit memory/waiting. Tickets are removed on success,
failure and cancellation; shutdown closes admission and wakes queued requests.
Overlapping key sets use FIFO ordering; no claim of global mathematical fairness
is made. Admission is only a scheduling hint and grants no tenant/Policy authority.

The transaction locks the complete source/target instance set in stable UUID order
before taking sorted type-specific shared advisory locks. Custom-type retirement
takes the matching exclusive type lock before the existing module/definition locks.
This coordinates instance writes/references with target archive and type retirement
without blocking unrelated types. Publication deliberately does not take those
locks: a resolved immutable revision R remains the write pin while publication
advances to R+1. Deterministic race tests cover both outcomes and explicit retries.

Protected pool checkout capacity timeout returns typed
`protected_database_capacity` (503), affecting only the bounded request. It never
revokes the healthy active profile or closes its pool. Later requests automatically
recover when capacity returns. Cancellation similarly releases queue/lease state.
Actual identity, credential, role, grant, RLS or generation validation failures still
fail closed with existing profile invalidation semantics; no checks are waived.
The common runtime correction applies to Governance and Metadata.

## Protected execution, RLS and evidence

Six instance and five custom-definition command/query classes are added to the existing private
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
