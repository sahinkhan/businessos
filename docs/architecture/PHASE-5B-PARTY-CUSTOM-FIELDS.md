# Phase 5B Party custom fields

Status: **Phase 5B implementation candidate**. Independent certification and owner
acceptance remain required. Phase 5A remains certified, closed and frozen; Phase 5
remains incomplete. Phase 5C–5H are not implemented or authorized by this candidate.

## Ownership and compatibility

Party adopts exactly `foundation.party.party`, owner `foundation.party`, contract
version `1`, through ADR-018 resource ownership and its transaction-bound facts
provider. This is an additive Party-root capability. Existing Party queries,
commands, sensitive reads and profile semantics remain unchanged. Contacts,
addresses, identifiers, relationships and separate profiles are not customizable.

Deployment must supply an approved first-party Party artifact in its protected
operator inventory. The CI inventory adds an explicit **test-only** Party grant;
it is not a production installation approval. Missing, spoofed or duplicate owner
admission fails closed. No alias or alternative owner registry is introduced.

## Published schema port

The additive neutral `businessos.custom_fields` version 1 contracts avoid a
Party → Metadata → Policy → Party dependency cycle. They contain no independent
field grammar. Metadata derives the immutable schema projection and supported
type names from the certified `DefinitionSnapshot` and `FieldDefinition` grammar.

The reserved `foundation.metadata.published-custom-field-schema.v1` dependency is
registered by the approved Metadata generation. Cached readers re-admit through
that reserved entry and reject replacement. The reader checks canonical owner
transaction scope, tenant, owner, namespace/version and the backend permission
`foundation.metadata.definition.read`. Party read/export additionally require
`foundation.party.read`; replace/clear require `foundation.party.manage`.

Private trusted bootstrap composition retains the Metadata schema-read callback
in an external identity-bound internal registry. Neither the public resolver nor
the Metadata module stores that callback, its bound authority, a pool, session or
UOW in its instance graph. The public reader holds only bounded validation limits;
constructing one conveys no authority. Each lifecycle registration binds a new
reader to the exact Metadata contribution generation. Disable drops its issued
state, replacement revokes the old reader, and changing an active flag cannot
restore authority. Reserved DI admission remains held by the request scope.

The protected callback validates the Metadata database profile and uses a
tenant-bound PostgreSQL **READ ONLY** transaction from BEGIN. Failure and
cancellation release the read UOW and pool lease. Only immutable admitted schema
facts are returned to Party. Metadata cannot read or mutate the Party value table.
This uses the accepted trusted first-party in-process boundary, not a Python
sandbox against code importing protected internals or inspecting module globals.

Normal writes resolve the active published Party `field_set`; absent or retired
active definitions deny writes. Historical reads/export/clear resolve the exact
immutable revision stored with the document. Digest verification is mandatory.
Classification and reference fields fail closed even in retained revisions.

## Owner value operations

Public typed operations are `WritePartyCustomValues`, `ReadPartyCustomValues`,
`ClearPartyCustomValues`, and `ExportPartyCustomValues`, in
`businessos_party.custom_fields`. Write is a complete replacement, never a patch
or silent coercion. Stable UUID field IDs are used. Duplicate IDs, unknown IDs,
caller schema/owner facts, malformed values, missing non-nullable values and
unsupported query operations are rejected. Defaults are not implicitly applied.

Every Party adapter operation combines ADR-018 canonical owner admission with
the existing framework-issued handler invocation validation. Write/clear require
COMMAND; read/export require QUERY. The binding must be live in the issuing task,
match the exact request and restricted transaction objects, and identify the
current admitted Party owner generation. Missing, structural fake, expired,
cross-task, mismatched-kind, wrong-owner and replaced-generation bindings fail
before any persistence or success event. Raw registration with a claimed Party
owner/generation and weaker read permission conveys no invocation authority.
Policy remains dispatcher authority through the registered manage/read permissions;
the helper accepts no caller-provided permission decision.

Validation reuses certified literal validation for text, long text, integer,
boolean, exact decimal/money, enum, UUID, date, timezone-aware instant, email,
phone and URL. Declarative comparisons and conditional-required rules execute
only the bounded certified grammar. No executable expressions are accepted.
The owner supports at most 128 fields and 65,536 canonical UTF-8 value bytes.

`platform_party.custom_values` has a relational tenant/Party envelope, logical
definition/revision UUIDs, digest, monotonically increasing value version, bounded
JSONB, clear marker and actor/time provenance. Its only FK is tenant-aware to the
Party root; no FK reaches Metadata. New migration `party_0003_custom_fields`
extends the verified `party_0002` head. Historical migrations remain unchanged.
The table forces tenant RLS; application grants are SELECT/INSERT/UPDATE only.
Metadata, Governance, operations and PUBLIC receive no table privilege. Worker
inherits the existing application role model, without new independent authority.
Downgrade refuses to discard any retained row, including clear tombstones.

## Transaction and lifecycle semantics

The admitted Party generation lease lasts through outer dispatcher transaction
completion. The writer locks Party first, then its custom-value row, validates
active lifecycle and the exact expected value version (zero only before the first
row), obtains and validates published schema, and writes through the same Party
UOW. There is no nested dispatch, autonomous commit or second write transaction.

Clear retains the revision pin and increments the value version with an empty
tombstone. It is not physical erasure. Inactive Parties cannot be written or
cleared; existing unclassified values remain readable/exportable under Policy.
Missing Parties fail explicitly. Ordinary Party reads do not include custom values.

A publication racing after schema resolution may commit before the owner writer:
the owner document remains pinned to its exact resolved immutable revision R.
The next replacement resolves the newly active revision and must validate against
it; existing values are never silently reinterpreted. Owner lifecycle changes
serialize on the same Party row lock.

Successful mutations append `party.custom-values.changed.v1` to the existing
transactional outbox with IDs, version, action and correlation facts only. Custom
value payloads are excluded. Rollback, cancellation and failed commit must retain
neither values nor misleading success events.

## Bounded capabilities and remaining gates

Custom query support is direct record display only. Filtering, sorting, search,
uniqueness and range requests fail explicitly without scanning JSONB. Export is
one typed owner document, not a general tenant export implementation. Physical
purge remains governed separately by ADR-017.

No custom entities, dynamic UI, Studio, arbitrary owner enrollment, workflow,
menus/actions, analytics or later-phase runtime is introduced. This candidate
requires repository quality gates, PostgreSQL adversarial/concurrency tests,
migration/source-wheel/image verification, exact-head CI, a fresh independent
audit, personal exact-SHA owner acceptance and a separate guarded merge.
