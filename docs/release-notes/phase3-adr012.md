# Phase 3 ADR-012 compatibility and migration notice

Status: proposed for the Phase 3 certification pull request. Release approval is pending.

## Canonical masters

`foundation.currency` owns installation-shared currency identities. Version 1 of
`foundation.currency.read.v1` exposes `CurrencyRecord`, `GetCurrency`,
`ListCurrencies`, and `ResolveCurrency`. The first migration installs a
reviewed, versioned baseline of 42 ISO-style codes with deterministic UUIDs.
Later canonical additions and corrections require a new reviewed migration and
source version. The application role has read access and no canonical write
permission. This baseline is not a claim that every ISO 4217 code is present;
localization releases extend it through the trusted migration boundary.

Country, subdivision, and city remain installation-shared Geography masters.
The `businessos_migrator` credential is the supported write path for this
release. Deployment operators must review the migration and its inventory,
rehearse it on a backup, and use the normal release audit process. Canonical
keys should remain stable; retire a row by deactivation where references remain.
Trusted city updates and deletes serialize with address writes and check all
tenant addresses before commit; an unsafe change fails without altering rows.
The new Country to Currency foreign key preflights unknown codes and stops the
upgrade with a correction message. It never substitutes a currency.

## Retired tenant commands and event

`RegisterCountry`, `RegisterSubdivision`, and `RegisterCity` are no longer
registered with tenant runtime dispatch. Their Python types remain importable
as deprecated compatibility shims for this pre-1.0 release. They cannot be
used to write canonical data. `foundation.geography.manage` now authorizes
tenant-owned address operations only. Integrations should replace command
calls with canonical Geography reads and submit dataset changes through a
reviewed release or localization package.

`geography.country.registered.v1` stops publication at this release. Its
schema and historical outbox records remain readable for their supported
retention and replay window. In-repository consumer inventory found no
subscriber. External subscriptions must be checked by the Release Maintainer
before release; supported consumers should migrate to the Country read
contract and versioned canonical dataset releases. A required event stream
needs a separately reviewed trusted publisher. ADR-012 approves the security
exception to the ordinary deprecation window; the release cutoff and external
consumer evidence still require exact SHA owner attestation.

## Party read compatibility

`GetFullParty` under `foundation.party.read` now redacts date of birth, tax and
registration identifiers, all contact values, and external identifiers marked
sensitive. `GetSensitiveFullParty` exposes the full projection only with
`foundation.party.sensitive.read` under `foundation.party.sensitive-read.v1`.
This is an incompatible security correction
to the provisional Phase 3 query. The published Party package remains pre-1.0;
the owning and SDK/Contract Maintainers must record the compatibility approval
for the exact candidate. In-repository consumers of `GetFullParty` were not
found. Consumers needing sensitive fields must request the new permission and
query explicitly. `ResolvePartyByExternalId` skips sensitive identifiers;
`ResolvePartyBySensitiveExternalId` uses the sensitive permission.

`SearchParties` defaults to 50 rows, permits 1 to 100 rows, and uses a stable
name and technical-ID order with nonnegative offset. Existing callers receive
the first page and should page explicitly to traverse larger result sets.

The advisory `MatchPartyDuplicates` query never updates or merges Party rows.
Its `foundation.party.duplicate-match.v1` contract requires sensitive read
authority because matching uses classified inputs,
but returns only candidate IDs and signal names. Geography exposes the
`foundation.geography.address-validator.v1` contract and `ValidateAddress`
query; callers receive typed field errors and normalized locality values.

## Rollback and replay

The forward migrations preserve existing rows. `geography_0003` can be
downgraded to its predecessor after removing the Currency FK and restoring the
old runtime grants, but doing so reopens the tenant global mutation risk and
must not be used as a production security rollback. Restore the pre-upgrade
database backup or apply a reviewed forward repair if canonical data has
changed. Fresh upgrade and replay require the same packaged seed and migration
inventory; they do not depend on customer-authored SQL.
