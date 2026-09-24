# ADR-015: Data Classification Ownership and Tenancy

Status: ACCEPTED

Decision date: 2026-09-24

Approving roles required: Architecture Maintainer; Security Maintainer; Policy Maintainer; Data Governance Owning Domain Maintainer; SDK/Contract Maintainer; Migration Safety Reviewer; Release Maintainer; Frontend Foundation Maintainer when Phase 5 UI classification consumption is contracted

Approval pull request or commit: [PR #25](https://github.com/sahinkhan/businessos/pull/25) — MERGED as `64f70b02de9d13f7be1a203f21b732363884d3aa`

Approved semantic proposal SHA: `25c9643b2a971a62e02c5e7ec15e87415f8342fc`

Final acceptance candidate SHA: `a9fb65f182439895abe6f6e234396b591a60426f`

Proposal owner attestation: [@sahinkhan's exact-proposal attestation](https://github.com/sahinkhan/businessos/pull/25#issuecomment-5808039324)

Review model: SOLO MAINTAINER OWNER ATTESTATION by `@sahinkhan`

Independent human review: NOT PERFORMED

Independent technical/read-only proposal review: PERFORMED — PASS; Critical 0; High 0; Medium 0; Low 0

Exact proposal CI: [BusinessOS run 35956530352](https://github.com/sahinkhan/businessos/actions/runs/35956530352) — PASS (`python-quality`, `windows-typing`, `web-quality`)

Final owner acceptance attestation: COMPLETE — [@sahinkhan's exact-candidate attestation](https://github.com/sahinkhan/businessos/pull/25#issuecomment-5810121506)

Independent technical/read-only acceptance review: PERFORMED — PASS; Critical 0; High 0; Medium 0; Low 0

Acceptance exact-head CI: [BusinessOS run 35970830703](https://github.com/sahinkhan/businessos/actions/runs/35970830703) — PASS (`python-quality`, `windows-typing`, `web-quality`)

Accepted main merge SHA: `64f70b02de9d13f7be1a203f21b732363884d3aa`

Cross-ADR architecture review: PASS

Accepted prerequisites: ADR-014 — ACCEPTED / AUTHORITATIVE / EVIDENCE CLEAN; ADR-018 — ACCEPTED / AUTHORITATIVE / EVIDENCE CLEAN on [main `559ae04743c4e68b09595aa94d52768b71527183`](https://github.com/sahinkhan/businessos/commit/559ae04743c4e68b09595aa94d52768b71527183). These architecture prerequisites are satisfied; their Policy V2 and Platform/SDK runtime extensions remain NOT IMPLEMENTED.

Implementation/certification gates carried forward: The canonical and tenant schemas, next forward Governance migration, FORCE RLS and grant narrowing, dirty-data preflight, safe v1/v2 compatibility transition, and Phase 5 integration remain NOT IMPLEMENTED. Implementation must preserve the hybrid global-base/tenant-extension model, monotonic security overlays, qualified no-shadow identities, historical resolution, Party's frozen boundary, and the Policy-owned classification port. No historical `gov_0001` or `gov_0002` rewrite is authorized. Phases 0–3 remain FINAL PASS / FROZEN; no general frozen-phase reopening occurred.

Implementation status: Classification runtime, canonical/tenant Governance schema, the next forward Governance migration (`gov_0003` or the next available revision after graph inspection), FORCE RLS and grant narrowing, and the v1/v2 runtime transition are NOT IMPLEMENTED. The dirty-data preflight is NOT EXECUTED. ADR-014 Policy V2 and the ADR-018 Platform/SDK extension are NOT IMPLEMENTED. Phase 5 integration is NOT STARTED. The implementation/certification gates above remain active; Phases 0–3 remain FINAL PASS / FROZEN with no general reopening.

Formal authority: ACCEPTED / AUTHORITATIVE ON MAIN

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
definitions have immutable technical IDs and codes, version/effective
metadata, active/inactive lifecycle, and governed semantic attributes. They
are installation-governed and read-only to ordinary tenant runtime.
Tenant-owned extensions and profiles carry `tenant_id`, use
FORCE RLS in shared-schema mode, and may add locally named classifications or
raise controls for an existing canonical classification. They cannot shadow,
rename, lower the minimum sensitivity of, or redefine a canonical code.
Unknown codes fail closed for authorization and sensitive-data use. Legal or
regional labels and industry extensions belong in tenant profiles or
localization/vertical-owned mappings through public contracts, not in a
global mutable label that changes another tenant's meaning.

The canonical namespace is reserved, conceptually `core:<code>`; tenant
identities use a disjoint namespace, conceptually
`tenant:<tenant-id>:<code>`. The exact encoding is a public contract detail,
but identity always includes stable immutable ID, namespace, tenant where
applicable, and definition version. Display labels never resolve identity.
A tenant may use the same display name or local code but cannot shadow,
replace, or rename a `core` identity. Duplicate qualified IDs or ambiguous
legacy unqualified codes fail closed. A custom definition can declare a
stable, explicit canonical base relationship; it is never inferred by name.

Tenant security overlays are separate records from classification identity.
They may only strengthen canonical controls: required controls compose by
logical OR, restrictions by union, allowed audience by intersection, and
mandatory masking by logical OR. A numeric sensitivity level alone does not
define a total order over privacy, secrecy, jurisdiction, and handling
obligations. For an attribute without a safe monotonic merge, an override is
forbidden; the owner must publish a new reviewed classification version or an
additional restriction contract. A qualified canonical reference is always
resolved with the trusted tenant's overlay lookup before use. An explicit
"no overlay registered" result uses canonical controls; lookup failure,
multiple active overlays, or a registered but unavailable overlay denies
rather than falling back to weaker canonical-only authority. A tenant overlay cannot edit the
canonical ID, code, base meaning, or minimum controls.

The typed immutable `foundation.governance.data-classification.v2`
read/resolution contract returns the stable qualified identity, canonical
base where applicable, current or requested historical definition version,
active state, canonical controls, tenant additional controls, effective
composed controls, effective interval, and provenance. A current resolution
uses the trusted tenant and instant; historical resolution uses a separately
authorized as-of contract and the immutable version effective then. Unknown,
ambiguous, or cross-tenant identities deny. Deactivation prevents **new**
assignment but preserves stable IDs and historical meanings for existing
records, metadata, and audit; referenced definitions are never hard-deleted.
Existing live references remain resolvable with current effective controls,
including any stricter tenant overlay. A material semantic change creates a
new version/effective revision, never rewrites historical meaning. A display
name may change without changing identity or security semantics.

Subject to acceptance of companion ADR-014, Data Governance implements the
**Policy-owned** `PolicyClassificationFactsProvider` port and registers it
as canonical classification owner through the neutral ADR-018 resource
ownership boundary, **subject to acceptance of ADR-018**. The frozen
manifest/generic provider registry alone does not establish that ownership. Policy
knows only its own port and typed effective projection; it has no dependency
on Governance. The module direction remains Data Governance -> Policy.
Data Governance's public resolver is separately available to Phase 5
Metadata/Studio, which stores stable qualified IDs on custom fields and
cannot create Policy permissions, weaken canonical controls, or bypass
Governance ownership. Neither Phase 5 nor marketplace modules read Governance
private tables. Higher modules and later HR, healthcare, and localization
profiles may use Governance public classification references where their
dependency direction permits. Party remains frozen, owns Party data, and does
not call Governance to resolve classification. Its Phase 3 sensitive-field
rules and redaction remain authoritative. Policy consumes the Governance
classification projection through the Policy-facing port without a
Policy -> Governance dependency. Classification itself does not grant
authorization or relax Party's accepted sensitive-field redaction.

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
manual, audited resolution. Existing global codes remain stable legacy
identifiers until an approved one-to-one mapping assigns immutable qualified
IDs and definition versions; neither a generated ID nor an overlay may alter
their historical meaning. Tenant overlays are created only where tenant
ownership is deterministically evidenced. Existing references are backfilled atomically to
the qualified identity and version after the mapping is approved, with referential checks
and rollback-safe expand/contract stages. A new forward `gov_0003` or next
available Governance revision adds tenant tables/constraints, FORCE RLS,
qualified references, overlay/version history or compatibility mapping, and narrowed grants. The
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
contract; Policy consumes the classification projection through its
Policy-facing port, while permitted higher modules and Phase 5 consumers use
Governance public references without private imports. Party does not become
a Governance consumer.
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
