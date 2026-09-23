# ADR-015: Data Classification Ownership and Tenancy

Status: PROPOSED

Decision date: Pending formal acceptance

Approving roles required: Architecture Maintainer; Security Maintainer; Data Governance Owning Domain Maintainer; SDK/Contract Maintainer; Migration Safety Reviewer; Release Maintainer; Frontend Foundation Maintainer when Phase 5 UI classification consumption is contracted

Approval pull request or commit: Pending

Supersedes: None

Superseded by: None

## Context

`platform_gov.data_classifications` is installation-global and has no
`tenant_id`, while `RegisterDataClassificationCommand` is tenant-authorized.
`gov_0002` grants `businessos_app` DML on every Governance table. A tenant
can therefore mutate a code whose meaning another tenant consumes. Accepted
[ADR-012](ADR-012-shared-master-ownership-and-mutation-boundary.md) grants
canonical-global status to Currency and Geography and requires a separate
owner decision for other catalogs; it does not grant this catalog global
tenant-write authority. Party-sensitive fields, Policy field rules, and Phase
5 metadata need stable classification meaning across self-hosted, database
per tenant, and shared-schema deployments.

## Options considered

| Model | Benefit | Cost/risk |
| --- | --- | --- |
| Global canonical only | Stable common meanings and simple cross-module vocabulary | No tenant-specific regulatory, industry, or marketplace extensions; global mutation must be tightly governed. |
| Tenant-owned only | Complete tenant autonomy with RLS | Duplicates common meanings and makes cross-tenant platform policy vocabulary/versioning harder. |
| Hybrid | Stable governed base plus isolated tenant extension/profile | Needs explicit namespace, resolution precedence, grants, and migration of current global rows. |

## Proposed decision

Choose **hybrid ownership**. Data Governance owns both stores and the public
resolution contract. A small installation-global canonical base provides
stable codes such as `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `RESTRICTED`,
`PERSONAL`, and `SENSITIVE`, but this list is illustrative: acceptance does
not recode existing rows or declare every existing code canonical. Canonical
definitions are versioned, installation-governed, and read-only to ordinary
tenant runtime. Tenant-owned extensions and profiles carry `tenant_id`, use
FORCE RLS in shared-schema mode, and may add locally named classifications or
raise controls for an existing canonical classification. They cannot shadow,
rename, lower the minimum sensitivity of, or redefine a canonical code.
Unknown codes fail closed for authorization and sensitive-data use. Legal or
regional labels and industry extensions belong in tenant profiles or
localization/vertical-owned mappings through public contracts, not in a
global mutable label that changes another tenant's meaning.

Resolution uses an explicit namespace (`canonical` or `tenant`) plus tenant
and version, not an unqualified code that can silently switch owners. The
public typed `foundation.governance.data-classification.v2` read/resolution
contract returns stable identity, owner namespace, effective tenant, version,
sensitivity floor, allowed handling obligations, and provenance. It rejects
unknown, ambiguous, cross-tenant, or inactive definitions. Policy field
decisions in ADR-014 consume
this contract and deny ambiguous classifications. Phase 5 Metadata/Studio
stores a stable classification reference on custom fields and resolves it
through this contract; neither Phase 5 nor a marketplace module reads
Governance tables. Party field tags and future HR/healthcare/localization
profiles follow the same reference rules and can impose stricter owner rules.
The resolver does not turn a classification into authorization by itself.

### Mutation authority and database roles

The canonical base is written only by reviewed, explicit Data Governance
migrations or governed seed deployment using `businessos_migrator`; there is
no tenant-facing or hidden global-super-admin mutation endpoint. Normal
`businessos_app` receives SELECT on canonical definitions and no
INSERT/UPDATE/DELETE or table ownership. `businessos_ops` may inspect and
perform separately approved operational repair but does not become an
ordinary application actor or an unreviewed definition editor.
`businessos_migrator` owns migration DDL and narrowly governed canonical DML;
its credential is never available to the app. Tenant extension/profile
commands require trusted tenant context, backend authorization, and tenant
RLS. `businessos_app` receives only the needed tenant-table DML, is a
non-owner `NOSUPERUSER NOINHERIT NOBYPASSRLS` role, and cannot assume ops or
migrator. Cross-tenant SELECT and mutation are denied at both contract and
database levels. A forward Governance migration must revoke the broad
`gov_0002` canonical-table DML grant without editing that historical revision.

### Existing data and forward migration

Before conversion, a read-only dirty-data preflight inventories every
global code, definition, sensitivity, field-tag/retention reference, and
known tenant use. It identifies noncanonical/custom meanings, collisions,
possibly tenant-authored rows, missing provenance, and meanings that differ
between consumers. Because current global rows have no tenant owner, the
migration must **not infer tenant ownership** from a UUID, last writer, or
referencing row. It must not deduplicate, overwrite, silently rename, or
reinterpret any existing meaning. A reviewed disposition maps each row to a
canonical version or an explicitly identified tenant extension with affected
tenant consent/evidence. Rows with unresolved provenance or divergent
meanings block migration and certification; they remain preserved for a
manual, audited resolution. Existing references are backfilled atomically to
the qualified identity after the mapping is approved, with referential checks
and rollback-safe expand/contract stages. A new forward `gov_0003` or next
available Governance revision adds tenant tables/constraints, FORCE RLS,
qualified references or compatibility mapping, and narrowed grants. The
implementation must verify the actual revision slot and never rewrite
`gov_0001`/`gov_0002`.

The existing registration/write contract is an incompatible security
surface. It cannot remain a route for global tenant writes. A v1 read may be
a deprecated resolver only if it preserves the old known meaning and rejects
ambiguity; v1 registration is disabled or safely redirected only to an
explicit tenant-owned namespace without changing canonical semantics. If a
safe shim cannot exist, Security and Release Maintainers must approve an
urgent exception to the normal deprecation window, naming affected callers,
notice, migration path, and expiry. V2 and safe v1 symbols coexist for at
least the next Stable platform minor after replacement availability where
safe; earliest removal additionally requires downstream regression and
owner/SDK/Architecture approval under [RELEASES.md](../governance/RELEASES.md).
No exception is granted merely by this proposal.

## Consequences and impact

Classification meaning becomes stable across tenants while tenant and
industry customization stays isolated. Data Governance owns both schemas and
contract; Policy, Party, Phase 5, HR, healthcare, localization, and
marketplace consumers use public references without private imports.
Existing unqualified codes need migration. Ambiguous historical data may
delay rollout rather than be guessed. The architecture preserves tenant
residency, export/delete handling for extensions, and future stricter
classification rules. It does not change accepted ADR-012 or frozen phases.

## Approval and implementation gates

The role union follows the architecture, tenant trust, public contract,
migration/data ownership, and release rows of
[ADR-GOVERNANCE.md](../governance/ADR-GOVERNANCE.md) and
[MAINTAINERS.md](../governance/MAINTAINERS.md). Frontend Foundation review
becomes required when its public UI binding is designed, not for this
documentation-only proposal. This PROPOSED decision authorizes no migration
or runtime remediation. Acceptance requires exact-revision role evidence,
exact-head CI, independent read-only audit with zero Critical/High findings,
and the formal governance procedure. Implementation must test role grants,
FORCE RLS, cross-tenant negatives, namespace collisions, canonical mutation
denial, retained-row mapping, custom-field resolution, and compatibility.
