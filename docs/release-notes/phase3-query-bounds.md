# Phase 3 collection query bounds

Status: candidate correction; certification remains pending.

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
| Party | `GetFullParty`, `GetSensitiveFullParty` child collections | Tenant-owned, unbounded per party | **Compatibility decision pending** |
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

`GetFullParty` and `GetSensitiveFullParty` promise all child collections in a
single `FullPartyRecord`. A default page would return a partial record with
the same shape and silently alter the contract's meaning. The existing record
has no page metadata. Under `RELEASES.md`, a versioned or explicitly approved
coexistence/migration design is required before this surface can be bounded.
The present candidate leaves those queries unchanged and cannot claim full
Phase 3 query-bound certification.
