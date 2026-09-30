# Phase 5A Metadata definition foundation

Status: implementation candidate. Independent audit, owner acceptance, merge, and post-merge certification remain pending. This document describes the bounded runtime introduced under [ADR-023](../adr/ADR-023-metadata-persistence-customization-and-dynamic-ui-resolution.md).

## Ownership and storage

`foundation.metadata` owns `platform_metadata` and migration `metadata_0001`. Each tenant definition has a relational identity, canonical resource owner, lifecycle, draft generation, and active revision pointer. A bounded, validated JSONB document holds the draft snapshot. Published snapshots are complete immutable revision rows with stable IDs, sequence, SHA-256 digest, actor, timestamp, and causal provenance. A composite tenant/definition/revision foreign key constrains the active pointer. Tenant tables have enabled and forced RLS. The normal application role has only the required grants; worker and operations roles have no Metadata table access.

The kernel `MetadataRegistry` remains an in-memory immutable contribution registry. It does not store tenant definitions. Ordinary business record values, custom entity instances, owner adapters, Studio rendering, and UI resolution are outside this batch.

## Contracts and authority

Version `1.0` contracts in `businessos_metadata.contracts` define definition and revision records, bounded field and validation grammar, preflight expectations, publication outcomes, canonical references, bounded bulk reference requests, and available/retired/unavailable target states. Definitions must use an admitted ADR-018 canonical resource owner. Runtime reads expose the active published revision only. Draft reads and lifecycle commands carry distinct backend Policy permissions. Cross-tenant or missing trusted context fails closed.

The ADR-015 authoritative classification resolver remains a separate implementation prerequisite. A draft may retain a qualified classification reference; publication and reactivation of that draft are refused until the authoritative resolver is available. Metadata does not grant business authorization or resolve reference targets itself. Source owners must reject new non-referenceable targets, and target retirement does not modify another owner's stored references.

## Publication and activation fence

Preflight captures draft and active generations, exact module artifact identities and generations, and schema/UI contract generations. Publish and reactivation lock the shared PostgreSQL contract and module fence rows, then the definition row, recheck every expectation, and update revision plus active pointer in one unit of work. The module lifecycle uses the same module fence during admission and contribution publication. A changed artifact is refused while an active Metadata revision binds its prior generation. This is a conservative Phase 5A rule; a future compatible upgrade protocol requires separate certification.

The active-binding counter changes in the same PostgreSQL transaction as the active pointer. Failed publication preserves the previous pointer. Immutable revision and module-binding triggers reject history modification. Lifecycle success emits safe facts through AuditAppenderV2 and the existing transactional outbox in the same unit of work. Typed publication failures record their status in AuditAppenderV2 without emitting an outbox event. Definition payloads are not copied into evidence.

## Verification boundary

The candidate's PostgreSQL tests exercise fresh migration and replay, RLS and grants, draft/published separation, stale preflight outcomes, competing publishers, module activation races, reactivation, immutable history, classification denial, and audit/outbox equality. Installed-wheel and image validation are required before the candidate is frozen. Passing these checks does not certify Phase 5A or authorize Phase 5B.
