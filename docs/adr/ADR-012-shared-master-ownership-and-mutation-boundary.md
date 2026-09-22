# ADR-012: Shared Master Ownership and Mutation Boundary

Status: PROPOSED

Decision date: Not set; this proposal has not been accepted.

Approving roles required: Architecture Maintainer; Security Maintainer; SDK/Contract Maintainer; Migration Safety Reviewer; Geography Owning Domain Maintainer; Currency Owning Domain Maintainer; Release Maintainer

Approval pull request or commit: Pending proposal review.

Supersedes: None

Superseded by: None

## Context

Phase 3 requires a currency master but has no Currency owner. The canonical
[module catalog](../architecture/MODULE-CATALOG.md) lists Currency / Exchange
Rate as a distinct shared-master foundation. The four existing Phase 3 modules
own Party, Geography, Reference Data, and UoM. Reference Data and UoM are
tenant-owned; Geography's country, subdivision, and city rows are shared while
its addresses are tenant-owned.

The current `RegisterCountry`, `RegisterSubdivision`, and `RegisterCity`
commands let a tenant with `foundation.geography.manage` insert shared rows.
The application role also has direct DML privileges on those global tables.
The Phase 3 integrity candidate adds a city-change trigger that examines
tenant-owned addresses. A trigger run as a tenant-scoped application role can
see only that tenant's addresses under RLS, so it cannot establish whether a
global change is safe for every tenant. Normal tenant authority must not
become installation-wide authority or determine global referential safety from
one tenant's view.

This proposal defines shared canonical masters, their owner and maintenance
boundary, and the forward compatibility path. It does not authorize runtime
implementation before formal acceptance. It does not change tenant-owned
Reference Data or decide the remaining Phase 3 Party, validation, matching,
and pagination work.

## Decision

### Ownership and scope

`foundation.currency` is a new first-party bounded context and sole owner of
the canonical Currency schema, migrations, write invariants, and public
contracts. Its canonical rows are global installation-shared masters without
`tenant_id`. A tenant may reference a currency but cannot create a private
competing definition of a canonical code or change its numeric code or minor
unit. Any later tenant-specific enablement, display preference, reporting
currency, or rate configuration is a separate tenant-owned profile owned by
the appropriate future module. This ADR does not allocate that profile.

The Phase 3 Currency master contains a stable technical identity, stable
ISO-style alphabetic code, numeric code when available, display/name metadata,
canonical minor-unit precision, active state, and versioned seed/source
identity. Codes and technical IDs are never silently reassigned. Historical
codes can remain resolvable even when inactive. Seed updates are deterministic,
idempotent, and reviewed for changed canonical meaning; they never select an
arbitrary winner for conflicting data.

Currency publishes typed, versioned `CurrencyRecord`, `GetCurrency`,
`ListCurrencies`, and `ResolveCurrency` read contracts. Lookup by code has one
result or a controlled absence; listing is bounded and deterministically
ordered. Other modules use the public contract, not Currency's private table.
There is no normal tenant Currency mutation command. Exchange rates,
rate-provider integration, conversion across currencies, and treasury/trading
behavior are separate later capabilities. Monetary values still carry an
explicit currency code and exact numeric amount; Currency precision is a
canonical attribute, not a replacement for transaction-specific rounding
rules.

Country, subdivision, and city are global canonical Geography masters with
no tenant identity. Addresses remain Geography-owned tenant records with
`tenant_id` and tenant RLS. This distinction applies to other masters only
when their owning architecture explicitly classifies them as canonical global
data; it does not make tenant-owned Reference Data global.

### Authority and maintenance

Normal tenant users may read global Currency and Geography masters. Their
runtime database role receives `SELECT` but no `INSERT`, `UPDATE`, `DELETE`,
`TRUNCATE`, table ownership, or role-switch capability on canonical tables.
`foundation.geography.manage` governs tenant-owned address operations only.
It grants no authority over country, subdivision, city, or canonical metadata.
Normal tenant runtime has no global-master write command. No installation-wide
administrator principal, first-tenant bootstrap expansion, or permanent
runtime bypass is created by this decision.

Canonical datasets are packaged, versioned release artifacts applied by
explicit Currency/Geography migrations or a future separately approved trusted
deployment/localization maintenance workflow. The existing separately
credentialed `businessos_migrator` role is the initial write authority.
Operator execution is an authenticated deployment action with migration
inventory, release provenance, change review, and operational audit evidence.
Fresh installations apply the packaged baseline; upgrades apply forward seed
versions. Localization packages may propose additive or corrective canonical
content only through this governed path. Installing localization for one
tenant cannot grant its runtime unrestricted global SQL or mutate other
tenants' masters. A general online global-master updater requires a separate
ADR and trust design.

Updates or retirements that could invalidate existing references must preflight
the complete installation, including every tenant RLS partition, under the
trusted migration role. They must serialize with dependent writes by suitable
locks or quiesced maintenance, and use database FKs or explicit full-visibility
checks where a relational FK cannot express the dependency. In-place key
rewrites and destructive removals are not the default; stable rows may instead
be marked inactive while references remain. A failed preflight preserves all
rows and returns actionable operator guidance without exposing another
tenant's record identifiers to ordinary callers. No normal tenant transaction
may scan only its visible addresses to approve a global mutation.

Global canonical tables do not use tenant-scoped RLS because they contain no
tenant-owned rows; their read/write boundary is database privilege and the
module contract. Tenant-owned addresses retain `tenant_id`, `ENABLE ROW LEVEL
SECURITY`, `FORCE ROW LEVEL SECURITY`, and tenant-scoped application DML
policies. The migration role must have verified full visibility of dependent
rows before any global-master maintenance. A tenant-scoped role must never be
used as the safety scanner. This ADR does not approve a `SECURITY DEFINER`
function. If a future ADR proposes one, it must specify its owner, fixed
`search_path`, narrow `EXECUTE` grants, RLS/BYPASSRLS behavior, parameter and
SQL injection safety, and error-disclosure rules before implementation.

### Existing Geography commands and compatibility

`RegisterCountry`, `RegisterSubdivision`, and `RegisterCity` are provisional
pre-freeze Phase 3 tenant-runtime surfaces. The current repository inventory
finds their declarations/exports and Phase 3 unit tests, but no other
in-repository application consumer. This is not a claim about unobserved
external users. Before Phase 3 certification, the three commands are
unregistered from normal tenant dispatch and their tenant-runtime semantics
retired. The owning module publishes explicit migration guidance and a release
note; tests and seed fixtures move to the trusted migration/seed path. The
types may remain as deprecated import shims for one documented compatibility
window if package consumers require them, but an import shim never restores
tenant write authority. No command is repurposed as a hidden privileged
operation. If a supported external consumer is discovered before removal,
the owning and SDK/Contract maintainers must document a versioned
deprecation/coexistence plan under `RELEASES.md`; certification cannot retain
unsafe tenant-callable behavior to preserve compatibility.

The three command restrictions are an incompatible security correction to a
public pre-1.0 surface, even though Phase 3 is not frozen. This ADR is the
required architecture and compatibility approval, not a claim of zero impact.
`foundation.geography.manage` narrowing is likewise a security-driven
permission-semantic change. Tenant-owned address creation remains available
under that permission. Global read contracts remain available.

### Country and Currency relationship

`Country.currency_code`, when non-null, references the canonical Currency
code. It denotes the Country record's default currency reference, not a
complete legal-tender, pricing, reporting, or exchange-rate rule. Geography
depends on Currency's published identity/read contract; Currency does not
depend on Geography. Because both are first-party canonical masters in the
same installation lifecycle, this ADR approves a narrow cross-module FK from
the Geography-owned country code column to Currency's stable unique code,
subject to the migration and lifecycle checks required by ADR-006. Geography
continues to own its column and never writes Currency's table. The FK is a
database integrity boundary, not permission for private cross-module DML.

Unknown or malformed existing country currency codes must fail deterministic
preflight with remediation guidance before installing the FK. No migration
silently substitutes a code, deletes a country, or invents a currency. A
temporary null retains its current meaning; whether a country must have a
default is a separate localization decision. Later dependent modules use
Currency's public contract and their own business rules.

### Forward migration and dependency model

Historical `geography_0001`, `reference_0001`, `uom_0001`, and `party_0001`
are immutable. The unreleased local Phase 3 integrity revisions remain
separate from this proposal. After acceptance, `foundation.currency` adds its
own `currency_0001` initial revision, anchored to the existing core migration
line and requiring no Geography dependency. Geography adds a later forward
revision after its current head; it also declares a migration dependency on
`currency_0001` and a module-manifest/package dependency on
`foundation.currency`. In the current candidate that means a revision after
`geography_0002`, not an edit to `geography_0001` or the existing integrity
revision merely to fit a linear chain. The exact ID and core anchor must be
verified against the graph when implementation starts.

The canonical migration coordinator supports cross-branch `depends_on` and
deterministic multiple heads. The new graph must remain acyclic: core precedes
Currency, Geography's currency-integrity revision follows both its prior
Geography head and Currency, and Reference Data / UoM / Party keep their
downstream direction. Package metadata, manifest dependencies, migration
inventory, installed-wheel graph, upgrade, downgrade or restore, and replay
are tested on the final graph. Any stricter constraint starts with dirty-data
preflight and preserves source rows on failure. If downgrade would destroy
business data, it must reject with recovery guidance rather than delete it.

### Compatibility classification

| Change | Classification and required evidence |
| --- | --- |
| New `foundation.currency` module and typed read contracts | Additive pre-1.0 capability; package/manifest, contract, discovery, and consumer tests required. |
| `RegisterCountry`, `RegisterSubdivision`, `RegisterCity` tenant-runtime retirement | Incompatible security correction to provisional public commands; consumer inventory, release note, ADR approval, and any required versioned coexistence plan. |
| `foundation.geography.manage` narrowed to tenant addresses | Security-sensitive semantic tightening; authorization and compatibility tests required. |
| Country-to-Currency FK | Compatibility-sensitive schema tightening; dirty-data preflight, same-lifecycle review, upgrade/replay, and recovery evidence required. |
| Currency code/precision seed revisions | Canonical-data and protocol impact; stable identity, versioned source, deterministic replay, and operator change record required. |

The proposal changes no frozen Phase 0, 1, or 2 contract and requires no
Party-to-Policy dependency. Implementations must prove that claim rather than
using it as permission to alter frozen modules.

## Consequences and downstream impact

Organization and Party can retain currency codes/preferences and resolve them
through Currency's public read contract without owning or mutating canonical
definitions. Catalog, Pricing, Tax, Billing, Payments, Accounting, and later
verticals consume that identity and add their own price, tax, settlement,
posting, and exchange-rate rules. No later module duplicates a canonical
currency table. Localization supplies governed data updates and country
behavior through its own release boundary. Hospitality, e-commerce, and
other verticals remain consumers rather than Currency owners. Currency has
no dependency on those modules, preserving the downward direction and
avoiding a cycle.

Tenant users cannot influence another tenant through canonical-master writes
or infer another tenant's dependent row from a global mutation error, because
they have no such mutation path. Canonical changes are operationally
versioned and auditable. Availability of shared masters during an upgrade
depends on the migration's lock/quiescence plan; operators must rehearse
upgrades, backups, rollback or forward repair, and seed provenance. No
customer installation needs a manual source edit to receive canonical data.

## Alternatives considered

| Alternative | Decision and reason |
| --- | --- |
| Currency in Geography | Rejected: currency identity and precision are not geographic properties; later finance consumers would depend on Geography for unrelated semantics. |
| Currency in tenant Reference Data | Rejected: tenant-scoped extensible sets allow conflicting canonical definitions and provide no dedicated typed Currency lifecycle. |
| Currency in Party | Rejected: Party is tenant-owned and a consumer of currency preferences. |
| Currency in UoM or another existing owner | Rejected: UoM's tenant measurement categories and conversion ratios do not own global monetary identity or future exchange-rate contracts. |
| New `foundation.currency` | Chosen: one typed global owner aligned with the module catalog and future rate evolution. |
| Tenant-callable global Geography mutation | Rejected: tenant authority cannot authorize installation-wide changes or see all dependent tenants through RLS. |
| Global super-admin in normal tenant runtime | Rejected: it creates a privileged bypass and an unreviewed trust boundary. |
| Versioned migration/seed/localization-controlled masters | Chosen: uses a separate existing deployment credential and reviewable source versions. |
| Duplicated Currency masters per business module | Rejected: conflicting identities and precision would break cross-module money contracts. |
| Default `SECURITY DEFINER` trigger for dependent scans | Rejected: avoid privileged application SQL and its ownership, search-path, execution, and disclosure risks. |

## Affected surfaces and approval gates

Affected owners are Currency (new) and Geography. The affected public surfaces
are Currency's new read contracts, the three Geography registration commands,
`foundation.geography.manage`, global Geography reads, and the country
currency reference. Migration graph, deployment seed artifacts, and
localization publishing are affected. The protected kernel, SDK, tenant
identity model, Policy, and tenant-owned Reference Data are not changed by
this proposal.

The required approval union from `ADR-GOVERNANCE.md` and `MAINTAINERS.md` is:
Architecture Maintainer; Security Maintainer; SDK/Contract Maintainer;
Migration Safety Reviewer; Geography Owning Domain Maintainer; Currency
Owning Domain Maintainer; Release Maintainer. The Release Maintainer is
required because the decision governs retirement of a public pre-1.0
command and its release compatibility path. `@sahinkhan` currently holds
these roles; authorship is not approval. Proposal review, exact-head CI,
independent technical audit, and owner attestation are separate evidence.

Implementation remains blocked pending formal acceptance through the
governance process. Acceptance does not itself certify Phase 3: the five
audit blockers, focused PostgreSQL security proofs, full validation, and a
new independent read-only Phase 3 audit remain required.
