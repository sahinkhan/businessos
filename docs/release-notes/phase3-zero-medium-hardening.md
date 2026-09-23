# Phase 3 Party-number and locality hardening

## Party number

Newly created Parties receive `PRT-` followed by 16 uppercase hexadecimal
characters instead of eight. The value is a human-facing business identifier;
the immutable Party UUID remains technical identity. Existing Party numbers
remain valid and are not renumbered. The published `party_number` field is an
opaque string with no fixed-width constraint in the public `PartyRecord` or
`PartyCreated` contracts, and the existing 50-character database column and
tenant-scoped uniqueness constraint support both formats. No migration is
required. This is a compatible widening of generated values under the current
pre-freeze contract. Consumers that assumed an undocumented eight-character
suffix must stop parsing it and treat the field as opaque.

Allocation uses the existing `(tenant_id, party_number)` database unique
constraint as the final integrity boundary. A conflict on that named constraint
causes a new candidate to be tried, at most five times. Other database
integrity failures propagate unchanged. Exhaustion returns the controlled
`party_number_allocation_exhausted` error (409). The application does not query
for availability before insertion.

## Locality resolution

`ValidateAddress` now uses the supplied country and subdivision to identify
active city candidates. Zero candidates retain the typed `invalid_city`
validation result; one candidate proceeds to postal-pattern validation;
multiple candidates return the typed `ambiguous_city` result with guidance to
provide a subdivision or more specific context. `CreateAddress` returns the
same controlled ambiguity code and does not insert an arbitrary city. Postal
patterns validate a uniquely resolved city; they do not act as city identity.
The `AddressValidationResult` shape and public query names remain unchanged.

Both fixes are covered by real PostgreSQL integration regressions in
`tests/integration/test_phase3_zero_medium_hardening.py`.
