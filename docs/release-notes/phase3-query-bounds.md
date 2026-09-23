# Phase 3 collection query bounds

Status: ADR-013 implementation candidate; Phase 3 certification and release approval remain pending.

`DATABASE.md` requires bounded interactive results. The Phase 3 public query
inventory is:

| Owner | Public collection query | Classification | Bound |
| --- | --- | --- | --- |
| Geography | `ListCountries` | Global list, not enforced as finite canonical set | 50 default, 100 maximum |
| Geography | `ListSubdivisions` | Global, unbounded per country | 50 default, 100 maximum |
| Reference Data | `ListReferenceSets` | Tenant-owned, unbounded | 50 default, 100 maximum |
| Reference Data | `ListReferenceValues` | Tenant-owned, unbounded per set | 50 default, 100 maximum |
| UoM | `ListMeasurementCategories` | Tenant-owned, unbounded | 50 default, 100 maximum |
| UoM | `ListUnitsOfMeasure` | Tenant-owned, unbounded | 50 default, 100 maximum |
| Party | `SearchParties` | Tenant-owned, unbounded | Existing 50 default, 100 maximum |
| Party | `ListPartyRelationships` | Tenant-owned, unbounded | 50 default, 100 maximum |
| Party | `MatchPartyDuplicates` | Bounded match candidates | Existing 25 default, 50 maximum |
| Party | `GetFullParty`, `GetSensitiveFullParty`, and v2 successors | Tenant-owned, formerly unbounded per party | Complete-or-overflow; 100 per included child collection, ordered SQL `LIMIT 101` |
| Party | `ListPartyContacts`, `ListPartyAddresses`, `ListPartyIdentifiers`, `ListSensitivePartyIdentifiers` | Tenant- and Party-owned child collections | 50 default, 100 maximum |
| Currency | `ListCurrencies` | Global list, seed version may grow | Existing 100 default, 200 maximum |

The other Phase 3 public queries return one record, a scalar, or a fixed-shape
validation/conversion result. Reference external-ID resolution fetches at most
two rows to detect an integrity conflict. No public city or address list query
is registered. Party matching's internal candidate queries are already limited.

The seven newly paged list queries add optional `limit` and `offset` fields.
They keep their response shape and tenant filtering. Results use a stable sort
with a unique ID tie-breaker. This is an additive input change under
`RELEASES.md`, with a security/performance bound on previously unbounded reads.
In-repository consumer search found declarations, exports, and tests only; no
later-phase application consumer calls these list queries.

ADR-013 accepts `GetFullPartyV2` and `GetSensitiveFullPartyV2`, returning
`FullPartyRecordV2` under `foundation.party.full-read.v2`. A successful v2
response contains the complete authorized aggregate. Each included child
collection has a fixed maximum of 100. Ordered SQL `LIMIT 101` detects
overflow; the whole query then returns no aggregate and raises
`full_party_aggregate_too_large` (HTTP 409) with guidance to use paginated
child reads. There is no silent truncation or partial-result variant.

The existing `GetFullParty` and `GetSensitiveFullParty` names remain available
as **deprecated v1 compatibility shims**. They have the same bounded
complete-or-overflow behavior and retain the safe candidate response shape.
General Party read omits contact values, date of birth, tax identifier,
registration number, and sensitive external identifiers. Callers needing
classified values must obtain `foundation.party.sensitive.read` and use
`GetSensitiveFullPartyV2`, `ListPartyContacts`, or
`ListSensitivePartyIdentifiers`. `ListPartyAddresses` and
`ListPartyIdentifiers` use ordinary Party read; the latter excludes sensitive
identifiers. All child lists default to 50, cap at 100, and accept a
nonnegative offset with deterministic ordering. Existing
`ListPartyRelationships` provides the corresponding relationship pages.

This is an incompatible security correction to both unlimited v1 reads and
historically exposed sensitive general-read fields. The owner explicitly
approved ADR-013's Security/Policy/Release exception. Large-aggregate
consumers should combine `GetParty` with the paginated child queries; callers
of the historically exposed fields must migrate to sensitive-read authority.
The first **proposed**, not published, deprecation checkpoint is
`v0.5.0-phase3-fullparty`, carrying Party distribution `0.4.0`. Deprecated v1
names cannot be removed before `v0.6.0`, and that is the earliest checkpoint
only if it is the next Stable platform minor. Otherwise support extends
through the actual next Stable minor and removal moves later. Release
Maintainer must verify identifiers, consumer migration, notice, and approval
before publication or removal. No release or tag is created by this candidate.
