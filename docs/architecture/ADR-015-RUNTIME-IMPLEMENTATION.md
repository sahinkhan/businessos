# ADR-015 Classification V2 runtime implementation candidate

Base main: `659898404a5ba963079ed604cd04e025ee52cbf9`.
Branch: `phase4/adr015-classification-v2-runtime`.
Status: implementation candidate; this record does not certify the runtime or
alter the accepted [ADR-015](../adr/ADR-015-data-classification-ownership-and-tenancy.md).

## Ownership, contracts, and trust

Data Governance owns the canonical resource
`foundation.data_governance.data-classification`, contract version `2`.
The certified Policy V2 spelling
`foundation.governance.data-classification` is an explicit ADR-018 alias to
that resource, approved by the protected `ApprovedModuleArtifact` installation
grant. The manifest cannot approve its own alias. Production bootstrap reads
the operator-controlled `BOS_APPROVED_MODULE_INVENTORY` JSON before loading
modules, binds the grant to the exact loaded module, and rejects missing or
invalid grants. The test inventory under `tests/fixtures` is for CI only; a
deployment must provision its own reviewed inventory file and mount it
read-only. There is no implicit production approval.

The public Governance V2 contract exposes qualified `core:<CODE>` and
`tenant:<UUID>:<CODE>` references, immutable definition ID/version, effective
interval, canonical controls, tenant additions, effective controls, and
provenance. The tenant comes from trusted `RequestContext`. Historical/as-of
resolution uses a separately permissioned read query and is not registered as
live Policy authority. No Party dependency or storage change is introduced.

Governance implements Policy's `POLICY_CLASSIFICATION_FACTS_V2` port and
ADR-018 resource facts provider. Both derive the same locked effective
classification. The Policy dependency direction remains Governance to Policy;
Policy never reads Governance tables. The Policy port uses the caller's
`HandlerTransaction` and takes classification locks before Policy's tenant
authority lock. The canonical identity uses a shared transaction advisory lock
because ordinary application credentials have read-only canonical access.
Tenant definition/version and overlay rows use shared row locks. Governed
canonical writers must acquire the corresponding exclusive
`classification-core:<CODE>` advisory lock before mutating a definition or
version. Neither port opens another unit of work.

## Storage and migration

Forward revision `gov_0003` adds canonical definition/version tables, tenant
definition/version tables, tenant overlay versions, an operator-owned reviewed
legacy mapping table, and additive V2 reference columns on retention policies
and sensitive field tags. PostgreSQL constraints enforce qualified identity,
stable IDs, ordered semantic versions, and nonoverlapping half-open effective
intervals. Unsupported override fields are rejected at the command boundary.
A tenant-facing overlay deactivation command is not exposed: a previously
registered overlay with no effective version fails closed under ADR-015,
because returning to canonical-only controls would silently weaken an existing
classification. Historical V1 rows and code columns remain. This batch does not
implement ADR-017 retention/hold/purge semantics.

`businessos_app` has SELECT only on legacy/global and new canonical
classification tables; `gov_0003` revokes the broad `gov_0002` DML grant
without rewriting that migration. Tenant definition, version, and overlay
tables have ENABLE and FORCE RLS. The reviewed mapping table has FORCE RLS for
tenant-scoped evidence, while canonical mappings are shared read-only.
Migrator access is explicit; ordinary application credentials cannot write
mapping evidence. Downgrade refuses before changing schema because returning
to `gov_0002` would restore unsafe global write privileges and lose qualified
history. Operator recovery is to correct or forward-migrate the current
revision; do not downgrade this boundary.

No illustrative ADR classification names are seeded as canonical. Canonical
content remains deployment governed. A canonical seed must be reviewed as an
explicit migration or operator operation and honor the advisory lock and
version history; a legacy row never gains canonical provenance by code/name.

The `businessos-classification-legacy preflight` command produces a bounded,
read-only inventory of legacy rows, references, collisions, and orphans. It
reports unresolved provenance and inconsistent or unconverted qualified
references as blockers; it does not infer an owner. The `apply`
command requires an exact, operator-reviewed JSON mapping for every legacy
row, with target ID/version, reviewer, evidence reference, and explicit tenant
provenance where applicable. It verifies target meaning and tenant references,
then inserts mapping evidence and backfills both reference tables atomically.
Any unresolved, changed, ambiguous, or orphaned reference blocks conversion.

The unsafe V1 `RegisterDataClassificationCommand` now returns a controlled
`classification_v1_write_retired` error (HTTP 410). It cannot mutate the
installation-global table. This shortens the V1 write support window and
requires an explicit Security and Release compatibility exception at owner
review. V1 unqualified retention/tag writes resolve only through an approved
tenant-visible mapping; no guessed or first-match classification is accepted.

### Security and Release compatibility exception candidate

Approval status: **pending owner review; not attested**. The retired V1
command previously accepted a tenant context while writing a global table,
so keeping that write path would let an ordinary tenant change other tenants'
classification meaning. The affected clients are callers of
`RegisterDataClassificationCommand`; they receive the explicit 410 error and
must migrate to `CreateTenantClassificationV2Command` with a trusted tenant
context. Existing V1 rows remain read-only and require reviewed mapping before
qualified conversion. Existing V1 retention and field-tag callers may use an
unqualified code only after that mapping is approved and unambiguous. Security
Maintainer and Release Maintainer should approve the shortened support window
on the exact candidate head with the tenant isolation, privilege, migration,
and compatibility test evidence. Re-enabling global tenant DML is not a safe
rollback; recovery uses a forward repair or an operator-reviewed mapping.

## Remaining gates

ADR-016 Audit V2 and ADR-017 destructive retention/hold/purge coordination
remain unimplemented. Phase 0–3 remain frozen. This candidate requires the
full test and image matrix, exact-head CI, independent read-only audit, and
personally posted owner attestation before a later guarded merge. This task
stops before merge and does not post the attestation.
