# Phase 5A Metadata definition foundation

Status: CERTIFIED / CLOSED / FROZEN. Phase 5A is authoritative on protected `main` at `3f96d668eb24f0d505b45b13428fff1c05f1d7af`; post-merge CI `36854266178` completed SUCCESS. Phase 5B is CERTIFIED / CLOSED / FROZEN as recorded in its [certification provenance](PHASE-5B-PARTY-CUSTOM-FIELDS.md#phase-5b-certification-provenance); Phase 5C is AUTHORIZED TO BEGIN subject to the [reconciliation certification gate](../roadmap/PHASE-5-METADATA-STUDIO-DYNAMIC-UI.md#phase-5c-authorization-boundary); Phase 5 overall remains INCOMPLETE. This document describes the certified bounded runtime introduced under [ADR-023](../adr/ADR-023-metadata-persistence-customization-and-dynamic-ui-resolution.md).

## Certification provenance

- Final implementation candidate: `03234293aa21d6fa56254937b4b5ee74c7d2eb0a`.
- Candidate exact-head CI: `36844589190` — SUCCESS (`web-quality`, `python-quality`, `windows-typing`).
- Independent remediation re-audit: PASS — Critical 0 / High 0 / Medium 0 / Low 0; all previous 2 High and 3 Medium findings resolved.
- Owner exact-SHA acceptance: PR #61 comment `5930138099`.
- Supplemental Solo Maintainer governance attestation: PR #61 comment `5931450033`.
- Guarded merge: `3f96d668eb24f0d505b45b13428fff1c05f1d7af`; merge tree equals candidate tree `75898ec02d765362299e60d10b0b76308b8225e8`.
- Post-merge CI: `36854266178` — SUCCESS (`web-quality`, `python-quality`, `windows-typing`).

## Ownership and storage

`foundation.metadata` owns `platform_metadata` and migration `metadata_0001`. Each tenant definition has a relational identity, canonical resource owner, lifecycle, draft generation, and active revision pointer. A bounded, validated JSONB document holds the draft snapshot. Published snapshots are complete immutable revision rows with stable IDs, sequence, SHA-256 digest, actor, timestamp, and causal provenance. A composite tenant/definition/revision foreign key constrains the active pointer. Tenant tables have enabled and forced RLS. Ordinary application, worker, and operations roles receive no Metadata schema/table grants. The existing worker-to-app inheritance is preserved; removing application grants closes that inherited path as well. Real PostgreSQL tests verify effective privileges and direct SQL denial.

The private ADR-022 execution selector enrolls only exact, first-party admitted Metadata command/query registrations. `businessos_metadata` is a dedicated non-owning, non-inheriting, non-bypass role with no role memberships. `BOS_METADATA_DATABASE_URL` supplies its separate bounded pool to trusted composition, never module DI. Worker composition uses the separately named `BOS_EVENT_WORKER_METADATA_DATABASE_URL`; this does not give the `businessos_worker` database role access or authorize Metadata commands through the worker policy. Audit owns forward grant revision `audit_0006`, and core outbox owns `0007_metadata_outbox`; Metadata's initial revision depends on both. Historical migrations on protected main remain unchanged.

Every protected admission validates the role, effective grant inventory, forced tenant RLS, and indirect access paths. Ordinary module handlers cannot select this pool. The public SDK and ordinary UOW factory expose no installation UOW. Trusted composition verifies Metadata's operator-approved artifact before supplying its private lifecycle transaction callback. Missing configuration or invalid database authority fails closed.

The kernel `MetadataRegistry` remains an in-memory immutable contribution registry. It does not store tenant definitions. Ordinary business record values, custom entity instances, owner adapters, Studio rendering, and UI resolution are outside this batch.

## Contracts and authority

Version `1.0` contracts in `businessos_metadata.contracts` define definition and revision records, bounded field and validation grammar, preflight expectations, publication outcomes, canonical references, bounded bulk reference requests, and available/retired/unavailable target states. Definitions must use an admitted ADR-018 canonical resource owner. Runtime reads expose the active published revision only. Draft reads and lifecycle commands carry distinct backend Policy permissions. Cross-tenant or missing trusted context fails closed.

Literal validation is strict and non-coercing. Integer literals are signed 64-bit values; booleans are booleans. Decimal and money require explicit precision/scale and bounded exact decimal strings. Money literals carry an amount and uppercase three-letter currency code; the grammar does not certify a currency registry lookup. Dates use ISO calendar dates, instants require timezone-qualified ISO timestamps, UUIDs use canonical representation, and email/HTTP(S) URL/phone literals use bounded syntax. Enum values must be declared choices. Reference literals remain unsupported without authoritative resolution. Comparison operands use the field's literal grammar; ordering is limited to integer, decimal, date, and instant fields. Stored snapshots are revalidated at publication and historical reactivation.

The ADR-015 authoritative classification resolver remains a separate implementation prerequisite. A draft may retain a qualified classification reference; publication and reactivation of that draft are refused until the authoritative resolver is available. Metadata does not grant business authorization or resolve reference targets itself. Source owners must reject new non-referenceable targets, and target retirement does not modify another owner's stored references.

## Publication and activation fence

Preflight captures draft and active generations, exact module artifact identities and generations, and schema/UI contract generations. Publish and reactivation lock the shared PostgreSQL contract and module fence rows, then the definition row, recheck every expectation, and update revision plus active pointer in one unit of work. The module lifecycle uses the same module fence during admission and contribution publication. A changed artifact is refused while an active Metadata revision binds its prior generation. This is a conservative Phase 5A rule; a future compatible upgrade protocol requires separate certification.

The active-binding counter changes in the same PostgreSQL transaction as the active pointer. Failed publication preserves the previous pointer. Immutable revision and module-binding triggers reject history modification. Lifecycle success emits safe facts through AuditAppenderV2 and the existing transactional outbox in the same unit of work. Typed publication failures record their status in AuditAppenderV2 without emitting an outbox event. Definition payloads are not copied into evidence.

Activation identity is a SHA-256 digest of complete, unambiguous admitted artifact evidence, including the full install identity; prefix truncation is not used. Contributions remain staged until the activation-fence transaction has committed. Commit failure and cancellation leave them unavailable and clean up the staged registration. Schema/UI generations are seeded foundation values only. Their future evolution protocol is deferred and is not certified by this implementation. Historically, Phase 5A closeout authorized Phase 5B entry; the now certified Party owner-adapter and ordinary-record custom-value scope remains separate from this frozen Phase 5A foundation.

## Verification boundary

The candidate's PostgreSQL tests exercise fresh migration and replay, RLS and grants, draft/published separation, stale preflight outcomes, competing publishers, module activation races, reactivation, immutable history, classification denial, and audit/outbox equality. Installed-wheel and image validation are required before the candidate is frozen. These checks formed the candidate evidence. Final certification completed after independent re-audit, exact-SHA owner acceptance plus supplemental Solo Maintainer governance evidence, guarded merge, and successful post-merge CI. Phase 5A and Phase 5B remain CERTIFIED / CLOSED / FROZEN. The bounded Phase 5C authorization and its reconciliation certification gate are recorded in the Phase 5 roadmap; Phase 5D–5H remain unauthorized and uncertified.
