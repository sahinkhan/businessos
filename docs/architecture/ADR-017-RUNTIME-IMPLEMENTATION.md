# ADR-017 Runtime Implementation Record

Status: implementation candidate; exact-head CI, independent audit, and owner certification pending.

Base main: `485e80ab183fae69c7ce2b0c531d893111f3c414`.

Branch: `phase4/adr017-retention-purge-runtime`.

Authority: [ADR-017](../adr/ADR-017-retention-hold-and-purge-coordination.md) is accepted. Its decision body remains byte-identical in this batch. Its semantic-body SHA-256, from `## Context` through end of file, is `79736ea7499357aeae97682c63eee929a939446d6fa2853b4a91beef2fd9e0bf` before and after header reconciliation.

Certified prerequisites on the base: ADR-014 Policy V2, ADR-015 Classification V2, ADR-018 owner-operation boundary, ADR-019 workload identity, ADR-020 handler invocation, and Audit V2 are implemented, certified, and merged. Audit V2's merge/main SHA is the base SHA above. ADR-016 is superseded by ADR-019 for worker identity.

## Ownership and contracts

Data Governance owns `foundation.governance.retention-policy.v2`, `foundation.governance.purge-authority.v2`, and `foundation.governance.destructive-lifecycle.v2`, registered as distinct versioned public contract keys. `SetRetentionPolicyV2` creates explicit intervals. `ReplaceRetentionPolicyV2` atomically closes an existing interval and opens a future interval in the same policy scope. Replacement refuses a shorter retention duration or a different expiry action. `PlaceRetentionHoldV2` and `ReleaseRetentionHoldV2` own legal-hold changes. `ExecuteDestructiveLifecycleV2` is the Governance-owned coordinator. `RecordDestructiveCleanupResultV2` accepts a result only from a trusted service-account principal with the separate cleanup-report permission.

`RetentionSubjectKey` contains tenant, canonical owner module and namespace, owner contract version, entity type, and stable UUID. It contains no category. The admitted ADR-018 facts provider must explicitly declare its supported entity types; policy writes, holds, and destruction reject an undeclared type. This prevents an entity-wide hold from claiming coverage of a caller-invented type when no owner row is available to check. The operation provider supplies a locked `ResourceOwnerFacts` projection with matching identity, current lifecycle, category, aware UTC anchor, and supported actions. Governance validates all these facts and independently requires the provider's registered exact action. Governance does not read or mutate owner-private tables. The conformance proof owner is an external test module through the public SDK; this batch does not enroll Party or another production owner.

The coordinator uses the dispatcher's restricted `HandlerTransaction` for owner validation and apply, Governance SQL, Audit V2 append, and transactional outbox. It takes the entity and subject locks before provider admission; the owner locks and re-reads its row; Governance then takes the policy lock, selects one effective policy, checks holds and elapsed time, appends Audit V2 evidence, applies the owner action, records pending cleanup, and emits a cleanup request. The Audit row, owner mutation, decision, and outbox event share one commit or rollback. No Boolean result from the V1 informational query is accepted as authority.

## Database and migration

The only new Governance revision is `gov_0004_retention_purge_v2.py`. It adds `retention_policies_v2`, `legal_holds_v2`, and `destructive_decisions_v2` under forced tenant RLS, plus an explicit constrained `ALL`/`RECORD` scope for new and existing holds. A PostgreSQL GiST exclusion constraint prevents active `[valid_from, valid_until)` policy overlap for tenant, owner, namespace, entity type, and category. Null `valid_until` is unbounded. A category is owner-provided, never mapped from a classification code. An exactly matching expiry action and at least one full `24 * retention_period_days` elapsed-hour interval after the trusted UTC anchor are required.

`gov_0004` runs a deterministic read-only preflight before DDL. Legacy policies lack both a retention category and effective interval, so any such policy blocks migration with up to ten policy IDs and a bounded overflow marker until an owner-approved mapping exists. Noncanonical legacy record-hold identifiers also block. This avoids inventing a classification-to-category mapping or silently selecting a policy. The revision preserves all pre-existing policy, hold, consent, and classification rows. Category-free entity holds become explicit `ALL`; their owner-free legacy scope is checked conservatively for V2 subjects. Historical `gov_0001`, `gov_0002`, and `gov_0003` were not edited. Downgrade refuses a silent drop of V2 authority evidence.

## Lock graph

All advisory keys contain tenant identity. Exclusive transaction advisory locks are used because the current abstraction does not expose a reviewed shared-lock path:

1. Entity gate: tenant, owner, entity type. Entity-wide V2 hold changes stop all purges in that owner/entity scope.
2. Category-independent subject lock: tenant, owner, namespace, entity type, UUID. The neutral SDK helper `lock_resource_subject_facts` gives participating owners the same entity/subject order before owner row work.
3. Owner row lock and post-wait re-read through the admitted ADR-018 provider.
4. Policy-scope lock: tenant, owner, namespace, entity type, locked category.
5. Current policy, applicable V2 holds, conservative legacy holds, and destructive state.

An additional legacy-hold entity lock is taken after the subject lock and before the policy lock. V1 hold placement/release takes that lock, so old holds cannot appear or disappear between the V2 check and commit. Policy-only writes take only the policy-scope lock and never acquire an earlier subject lock afterward. Record V2 hold placement uses the entity/subject/owner path; release uses the same entity/subject gates. A post-purge record hold is rejected by the locked owner state; canonical V1 record holds also reject an existing destructive decision.

## Compatibility, Audit, and external cleanup

`CheckPurgeEligibilityQuery` remains a deprecated informational estimate. Its result includes `authoritative=false`, and its positive reason explicitly directs callers to V2. V1 export remains available. The V1 `anonymize_subject` hook fails closed because its old signature cannot enter the full trusted coordinator transaction.

The successful destructive Audit V2 row includes subject identity, exact action, policy ID, category, anchor, eligibility and decision instants, hold outcome, owner lifecycle, provider generation, and cleanup status. Audit supplies actor provenance. An owner exception after the Audit append rolls both back. Governance's outbox event `governance.destructive.cleanup_requested.v2` asks the owning consumer to perform long external deletion after the authoritative commit. The decision starts as `pending`; a trusted cleanup service reports `completed` or retryable `failed`, with another Audit row. No external cleanup is claimed complete by the coordinator. The proof owner has no external object to delete, so no production cleanup consumer is enrolled in this generic batch.

## Verification and scope

The Python 3.13 PostgreSQL proof covers fresh forward migration, dirty legacy preflight, overlap rejection, exact policy/action combinations, future and expired policies, half-open boundary predicates, tenant RLS, declared entity types, owner facts and capability checks, category-free ALL holds across categories, both hold/purge orders, release racing purge, duplicate and distinct-subject purgers, policy replacement concurrent with purge, category/anchor mutation races, advisory lock timeout and holder rollback, owner rollback, committed and rolled-back Audit evidence, committed cleanup outbox, and provider drain/replacement. Additional exact-head CI and independent read-only audit results belong to the implementation PR before owner attestation.

The independent audit identified a certification blocker under the current shared database role: `businessos_app` can directly update a same-tenant V2 hold row. RLS prevents cross-tenant access, but it cannot authenticate which in-process module issued a same-tenant SQL statement. A first-party handler with raw SQL access can therefore deactivate a hold without the Governance release command and its locks. The public V2 command path does not expose that bypass, but the literal application-role protection required by this batch is unproven. Certification remains blocked until a separately reviewed database-enforced authority boundary can distinguish the Governance owner from other handlers within one Unit of Work. This batch does not add an unreviewed role or credential model.

This batch does not implement preventative segregation of duties, broad V1 runtime elimination, a new business owner integration, or any general reopening of Phases 0–3. Phases 0–3 remain FINAL PASS / FROZEN. Later production owners must adopt the public lock/facts/operation conformance contract and their own external cleanup consumers before enabling their resource class for destructive lifecycle execution.
