# Phase 4 destructive downgrade safety

Status: closeout candidate; exact-head CI, independent exact-commit audit, and
owner attestation pending. Base main: `9a4f1c19fc4ce0c31462acdfad3c5660a077afeb`.

## Threat and boundary

Historical Audit `audit_0004` through `audit_0001` could remove the append-only
trigger and V1/V2 evidence even when Audit V3's conditional guard found no V3
rows. Historical Policy `policy_0004` through `policy_0001` could remove
support-access, record-policy, scope, and segregation-of-duties authority when
typed-column guards found no qualifying rows. A certified installation must
not treat those empty-data checks as permission to cross its security floor.

All historical revisions remain byte-identical. Two owner-local revisions
append to the graph: `audit_0005` after `audit_0004` and `policy_0005` after
`policy_0004`. Their upgrades intentionally perform no DDL. The installed
revision marker is the durable forward-only release boundary. Each downgrade
raises an exact refusal before any historical downgrade executes. Neither
barrier offers a force or data-dependent exception.

## Reviewed current-head classification

| Head / next edge | Class | Reason |
| --- | --- | --- |
| `audit_0005 → audit_0004` | Forward-only | Historical path can remove immutable Audit evidence and its trigger. |
| `policy_0005 → policy_0004` | Forward-only | Historical path can remove Policy authority and certified SoD state. |
| `gov_0005 → gov_0004` | Forward-only | Existing guard protects retention, holds, and destructive decisions. `gov_0004` and `gov_0003` also refuse weaker authority. |
| `proof_0004 → proof_0003` | Forward-only | Existing guard protects owner lifecycle and grants. |
| `identity_0005 → identity_0004` | Conditional | Existing workload-presence guard refuses populated registry; `identity_0004` also guards its own removal. |
| `organization_0003 → organization_0002` | Conditional | Existing provenance/revocation guard refuses meaningful grant rows; `organization_0002` protects typed principals. |
| core `0006 → 0005` | Safe reversible for the security floor | Removes Governance outbox append grant and fails protected commands closed; it does not grant ordinary mutation or delete evidence. An operator must restore this edge before resuming Governance commands. |
| `geography_0003 → geography_0002` | Safe reversible | Certified Geography rollback retains read-only global-master grants. |

The older Audit V3 and typed Policy individual conditional downgrades remain
unchanged history. They are not reachable through the supported current-head
barriers. Identity and Organization conditional paths remain separately
available where their own preconditions hold.

## Atomicity and supported operations

`MigrationCoordinator` validates the installed graph and inventory, holds its
migration lock, and runs the entire Alembic command in one PostgreSQL
transaction. A targeted Audit or Policy downgrade meets its owner barrier
first. A `downgrade base` that meets any certified forward-only guard rolls
back changes attempted in other branches too. Tests snapshot revision heads,
format-2 inventory/fingerprints, evidence and authority rows, Currency data,
RLS, grants, policies, and triggers before and after refusal. Geography's
reversible edge remains usable.

The supported `businessos migrate` CLI exposes `plan`, `upgrade`, and
`downgrade`; it exposes no `stamp`, revision-state edit, force flag, or
module-specific migration executor. Direct raw Alembic or SQL performed by a
database administrator is outside the supported BusinessOS migration
contract. A DBA with sufficient privilege can destroy their database; these
barriers do not claim to prevent that.

Recovery across an irreversible boundary uses reviewed forward repair or a
tested backup/restore checkpoint, per [UPGRADES.md](UPGRADES.md) and
[RELEASES.md](../governance/RELEASES.md). Database downgrade is not a general
recovery promise.

## Evidence

The focused PostgreSQL proof covers targeted Audit and Policy refusals,
repeated attempts, `base` atomicity, preserved V1/V2/V3 Audit evidence,
append-only denial, representative Policy authority rows, fresh upgrade, and
a pre-barrier upgrade with data retained through the new heads. Existing Phase
3 and Phase 4 tests cover Geography, Governance, proof-owner, Identity,
Organization, Audit and Policy runtime behavior. Installed-wheel and image
smoke require a known barrier refusal and compare graph, inventory, Currency,
and security metadata before re-upgrade.

Local candidate evidence: the frozen focused matrix passed 35 tests;
integration passed 206; full pytest passed 753. Ruff format/lint, mypy on 339
source files, Pyright with zero errors and warnings, Phase 0 governance gate,
and `git diff --check` passed. The isolated installed-wheel smoke passed with
matching source and installed graphs. Development, production, and
migration-smoke images built; the installed-image replay passed against a
disposable database. The independent read-only preflight and its type-only
delta audits reported Critical 0, High 0, Medium 0, Low 0. Hosted exact-head
CI, exact-commit audit, and personally posted owner attestation are still
required before a guarded merge.
