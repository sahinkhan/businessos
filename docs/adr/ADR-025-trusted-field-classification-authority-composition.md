# ADR-025: Trusted Field Classification Authority Composition

Status: PROPOSED

Decision date: PENDING; no architecture acceptance has occurred.

Proposal preparation date: 2026-10-10.

Approving roles required: Architecture Maintainer; Platform/Kernel Maintainer;
Security Maintainer; Policy Maintainer; Data Governance Owning Domain Maintainer;
Metadata/Studio Owning Domain Maintainer; Party Owning Domain Maintainer;
SDK/Contract Maintainer; Migration Safety Reviewer; Audit Owning Domain Maintainer;
Release Maintainer.

Approval pull request or commit: PENDING.

Owner architecture attestation: PENDING. No owner approval is represented by this
proposal or by its authoring commit.

Supersedes: None. This proposes an opt-in extension to ADR-014, ADR-015,
ADR-018, ADR-022, ADR-023 and ADR-024; their existing contracts and decisions
remain unchanged.

Superseded by: None.

Implementation authority: NONE. Acceptance of this ADR would establish a
decision, not authorize implementation, certify a runtime, or authorize Phase
5E-B. Separate implementation authorization and the gates below are required.

Protected preparation baseline: `78779cf515fee6ca15cde383bc375b220607863a`;
tree `8aa2c2cf39ce3bd350c85a3a473d48f933ee1bf5`.
Phase 5D remains CERTIFIED / CLOSED / FROZEN. Phase 5A–5D and the Phase 4.5
frontend foundation are not reopened by this proposal.

## Context and problem

The Phase 5E-A compatibility specification identified an unresolved authority
boundary: which classification applies to a canonical field of an admitted
resource owner for the trusted tenant? Its local specification input is commit
`46b400d36c24cd51b1cf723a6fe51ba3d49f7ee7`; that input is planning evidence,
not an accepted architecture decision or implementation authority.

[ADR-014](ADR-014-trusted-policy-decision-context-v2.md) requires trusted,
owner-origin resource facts and commit-bound authority within the framework's
active transaction. Its existing field evaluator obtains classification
references from the resource owner's `field_classifications` projection.
The projection does not define a join with Governance field tags.

[ADR-015](ADR-015-data-classification-ownership-and-tenancy.md) makes Data
Governance the classification owner and the implementation of the Policy-owned
classification provider. Party does not consume Governance. Policy does not
import Governance implementation or query its private tables.

[ADR-018](ADR-018-canonical-resource-ownership-and-owner-operation-boundary.md)
supplies neutral owner registration/admission. It does not presently issue a
canonical field witness binding field meaning, dynamic definition provenance,
approved artifact and durable activation generation.

The current `platform_gov.sensitive_field_tags` identity is tenant plus
`entity_type` and `field_name`. Those strings and a qualified classification
reference do not prove which admitted owner's field is being classified.
Metadata definitions, published UI declarations, transport inputs and browser
state cannot supply that missing authority.

The decision needed is bounded to the composition of owner field identity and
Governance tag authority. It does not replace classification storage generally,
Policy rules, Party redaction, Metadata ownership, or UI publication provenance.

## Decision

Select **Option B: Policy composes two independently authenticated providers**.

1. The resource owner supplies a canonical field witness through a neutral,
   versioned extension of the ADR-018 owner boundary.
2. Data Governance supplies current tenant-bound tag facts through a new
   **Policy-owned** `PolicyFieldTagFactsProvider` port. It supplies a tag binding,
   not an owner field witness and not an authorization decision.
3. Policy authenticates both sources, joins their exact identities, obtains
   effective classification facts through the existing classification authority,
   and makes the field decision using the applicable Policy rules.
4. Framework-private execution retains the same active UOW and admissions for
   those fixed adapters. The framework does not interpret classifications or
   decide business authorization.

The proposed capability is independently versioned as
`field-classification-composition.v1`. Names here identify proposed contracts;
none is claimed to exist in the baseline. Existing `field-policy.v2` behavior,
its owner-supplied classification map, and its public contracts remain unchanged.
The new path cannot overwrite that map, masquerade Governance facts as
owner-origin facts, or silently intercept existing V2 calls.

A participating operation must be explicitly enrolled in the new capability.
If its composition is unavailable or denied, it cannot fall back to legacy V2,
an unclassified field, a UI declaration, or a cached decision. Non-enrolled
operations continue their existing frozen contracts.

### Ownership and dependency direction

| Concern | Authoritative owner | Boundary |
| --- | --- | --- |
| Canonical resource and fixed field meaning | Registered resource owner | Neutral ADR-018 field witness |
| Party custom-field values/resource identity | Party | Party-owned values and resource witness |
| Custom-field/custom-entity definition and immutable revision | Metadata/Studio | Authenticated definition witness and schema pins |
| Canonical tenant field-tag binding and history | Data Governance | Policy-owned tag-facts port |
| Classification definition and effective tenant overlay | Data Governance | Existing Policy-owned classification port |
| Composition and field authorization decision | Policy | New Policy-owned composition capability |
| Invocation, provider admission, private execution and UOW | Platform/Kernel | Generic lifecycle/transaction contracts |
| Audit append | Audit | Existing supported AuditAppender contract |
| Published UI source/dependency completeness | Metadata under ADR-024 | Separate UI compatibility proof |

Permitted dependencies remain downward and explicit:

```text
Party -> neutral Platform/SDK owner-field contract
Metadata -> neutral Platform/SDK owner-field contract
Data Governance -> Policy-owned tag/classification contracts
Policy -> neutral owner-field contract + Policy-owned provider interfaces
approved composition root -> fixed admitted owner, Policy and Governance adapters
```

Existing legitimate Metadata dependencies remain as admitted. No new
Party-to-Policy or Party-to-Governance import, dependency, call or SQL access is
introduced. Policy cannot import Governance types, instantiate its implementation,
or inspect its tables. The composition root binds an operator-approved provider
registration; Policy checks the admitted interface and source, not an arbitrary
module name supplied by the caller. No circular module dependency is permitted.

## Canonical field identity and witness

Use immutable, typed neutral contracts, separate from API payloads. A proposed
`CanonicalFieldLocator` contains:

| Member | Meaning |
| --- | --- |
| `tenant_id` | Trusted active tenant; never copied from browser scope |
| `resource_namespace` | Canonical ADR-018 namespace |
| `resource_contract_version` | Exact supported resource contract version |
| `resource_owner_module_id` | Registered owner of that namespace/version |
| `field_id` | Immutable UUID issued by the admitted fixed-field/definition owner and certified by the resource owner; not a label or column name |
| `field_contract_id`, `field_contract_version` | Published field identity/meaning contract |
| `dynamic_definition_id`, `dynamic_type_id` | Required only for the applicable dynamic field family |

Its canonical logical key is the exact structured tuple of those identity
members. Absent dynamic members have one canonical representation. Names,
translation keys, SQL identifiers, display paths and legacy entity/field strings
are descriptive only. A digest may index canonical bytes but cannot replace
tuple equality or authenticate their origin. Canonical encoding, identifier
bounds and version syntax must be published and conformance-tested before use.

An `OwnerFieldWitness` additionally binds:

- the exact resource locator/record when the operation is record-bound;
- field existence, supported operation and current owner lifecycle;
- immutable dynamic definition/revision ID, digest and schema pin, if applicable;
- the definition owner separately from the value/resource owner;
- the field meaning fingerprint covered by that contract/revision;
- issuer registration, approved artifact identity, process contribution generation
  and locked durable activation/fence identity for every participating owner;
- the active request, trusted tenant, invocation, transaction and admission scope.

The neutral registry issues or authenticates the witness from the admitted
owner adapter and protected activation state. An ordinary dataclass, signature
string, digest or provider-reported generation number is not an issued witness.
Process contribution generation and durable database generation are distinct;
neither can be substituted for the other. Existing owner registration alone
does not already provide all this field-level provenance.

The owner authenticates field existence and meaning under its own contract and
same-UOW locks. Transport may request a field key as intent; it cannot certify
that key. Tenant modules cannot register another owner's namespace or reuse its
field UUID. Field IDs are never reused for a different meaning after retirement.
A family/version is selected by the admitted operation, not downgraded by a
caller choosing an older contract.

For the first version, one operation is limited to one approved resource family
and at most 128 distinct fields. Duplicate conflicting locators, unsupported
versions, mixed tenants, excess cardinality and unknown owner registrations deny.
Multi-owner business transactions require separately reviewed enrollment; the
bound does not authorize a generic cross-module dispatcher.

## Governance binding and classification facts

### Current authority and immutable history

A canonical field has one stable Governance binding head per tenant and
canonical logical key. The head selects a monotonically versioned, immutable
assignment history. It persists after removal; removal appends a tombstone
version. Binding IDs, field IDs and generations cannot be recycled.

Each assignment contains an exact qualified classification reference, a binding
ID/version, lifecycle/effective start and explicit coverage of the owner field
contract and meaning fingerprint. Dynamic coverage includes the admitted
definition/revision IDs and digests. An assignment may cover a bounded explicit
set of retained revisions; it cannot cover every future revision implicitly.

Schema pins select field meaning, **not a historical tag epoch**. Live resolution
always reads the current head at the active authorization instant. An older
record/schema pin cannot recover a weaker past tag. A changed field meaning not
covered by the current binding denies until Governance explicitly approves new
coverage or reassignment. Artifact replacement does not silently recreate tags:
the logical identity may remain stable only after current owner admission and
meaning/coverage validation succeed.

Assignment versions are immutable, immediately effective transitions. The writer
records a strictly increasing trusted database effective instant while holding
the head lock; it cannot backdate a transition. Each transition optionally
declares an expiry. Its effective end is **derived** as the earlier of that
expiry and the next transition's effective start, when either exists. No old
row's stored interval is closed or rewritten. The live result reports the
derived interval, not an immutable stored `valid_until` that must later change.

The head selects the latest committed transition. Database uniqueness,
head/version constraints and guarded writer validation enforce one ordered
timeline; derived intervals cannot overlap. Expiry gaps and tombstones deny.
The initial capability does not support future-dated assignment, scheduled
cancellation or retroactive correction. Such requests deny; scheduling would
require a separately reviewed contract/timeline extension. Existing scheduled
classification/overlay versions retain their separate frozen semantics.
Historical resolution is a permissioned audit read contract using derived
intervals and cannot supply live field authorization.

Bindings also retain explicit tag-specific masking requirements. These compose
by strengthening classification controls and the owner's redaction floor; they
cannot be inferred absent from a low-sensitivity classification. Missing or
unsupported binding-control facts deny. This is separate from the classification
definition's mandatory masking and never permits weakening Party redaction.

### Policy-owned tag port

The proposed port takes the already authenticated canonical locator and the
active framework transaction/admission scope. Governance resolves only its own
binding side. Policy retains and checks the independent owner witness itself.
Governance does not return a newly certified owner projection or a combined
authorization receipt.

Immutable `PolicyFieldTagFacts` contain at least:

- trusted tenant and exact canonical logical key;
- binding ID, monotonically increasing version/generation and coverage fingerprint;
- exact qualified classification reference;
- explicit tag-specific masking requirement, independently attributed to the binding;
- effective start/end, lifecycle and current resolution instant;
- applicable dynamic revision coverage;
- Governance owner/provider registration and approved artifact identity;
- authenticated contribution generation and durable activation/fence identity;
- issued request/transaction/admission provenance, held through completion.

Internal issuance/authentication is checked separately from value equality.
Serialization for diagnostics or audit does not preserve an invocation capability.
Provider exceptions, missing facts, ambiguity, stale generation, mismatched tenant,
invalid interval or coverage mismatch deny; they never mean PUBLIC.

For an enrolled field requiring this capability, even a public/low-sensitivity
classification requires an explicit governed binding to a valid qualified
reference. No tag, null tag or lookup failure cannot opt that field out of Policy.
Only the admitted contract determines whether composition is required.

Governance remains the source of definition and effective overlay facts. Its
existing Policy V2 projection exposes identity, validity and a `sensitive` flag,
not the complete effective masking, restrictions, audience or required controls.
The new capability therefore requires an additive **Policy-owned, versioned
effective-control facts contract**, implemented by the admitted Governance
adapter using the same existing definition/overlay resolution semantics. Its
immutable result includes the qualified reference, definition/overlay versions,
effective interval and every control relevant to the enrolled operation, with
authenticated provider provenance. Existing V2 interfaces remain unchanged.

Tenant additions cannot weaken canonical controls. `sensitive=False` alone
cannot mean unrestricted PUBLIC handling. An unsupported control denies or
prevents operation enrollment; it cannot be discarded by a projection. No
classification definition, overlay or rule is copied into Party or Metadata
as a new source of authority.

## Policy composition and decision

Policy performs the following bounded operation:

1. Verify trusted context, exact enrolled action/family and active transaction.
2. Retain and authenticate the owner field witness under neutral admission.
3. Retain the registered tag provider and authenticate the current tag facts.
4. Require exact tenant, owner, field identity, contract and coverage matches.
5. Resolve the tag's qualified reference through admitted classification authority.
6. Compose tag-specific masking with effective classification controls and the
   owner's redaction floor; validate applicable Policy authority under retained locks.
7. Apply existing applicable field rules and return the decision/projection.

Policy decides; neither owner identity nor a tag grants access. Owner
read/manage/update prerequisites still apply. `field.read` and `field.write`
remain distinct actions requiring their actual applicable permissions; an owner
record-read grant is not translated into a field permission. Existing V2 rule
and classification semantics are preserved, not widened for rendering convenience.

The new capability has explicitly distinct read and commit-bound operation
contracts. A presentation/read projection is never a mutation receipt. In
particular, the existing V2 field evaluator's read-decision result cannot be
relabelled as proof that a later write was authorized.

Successful commit-bound evidence is framework-issued, request/operation/UOW-bound
and non-transferable. It cannot be supplied by the browser, reused in another
transaction, used after a transition or replayed after completion. Error,
unavailable, pending and unknown states deny or redact according to the supported
owner read contract; none enables a write or releases a classified value.

## Single-UOW execution and least privilege

### Selected execution mechanism

Introduce an **opt-in, per-family private execution profile and fixed executor**
as a future bounded extension of
[ADR-022](ADR-022-module-scoped-database-execution-authority.md) and the private
executor pattern in
[ADR-024](ADR-024-trusted-compatibility-completeness-provenance.md).
This is required work, not an existing implemented field-composition facility.

The framework selects a profile from exact approved handler/action, owner family,
kind, artifact and current generation **before opening its one UOW**. Caller input
cannot select a connection, role, SQL plan, provider or arbitrary callback. The
caller-facing `HandlerTransaction` is an opaque view of that active UOW;
unrestricted SQL/session/flush/commit/rollback access is unavailable.

The real transaction remains in kernel-private state. Fixed, separately admitted
owner, Governance and Policy adapters execute their own reviewed operations on
that same transaction. Owner adapters project/lock their own facts and apply the
approved owner operation; Governance adapters access only their binding and
classification tables; Policy adapters access their own authority. Existing
Audit append and transactional outbox bridges participate in the same UOW when
required by the operation. Domain logic stays with its owner.

No registered ordinary handler or caller-supplied callback executes with the
private persistence handle. The owner bridge is bound by trusted startup to the
exact audited owner implementation and action, not to an extension's arbitrary
callable. Enrolled adapters must retain admission and cannot return, store or
export that handle. Ordinary owner/Policy sessions gain no Governance grants.

Every participating adapter receives the active transaction through its fixed
framework bridge; it cannot open a substitute authority UOW. The opaque public
view and private adapter view are views of **one caller operation transaction**,
not two transactions. The framework alone completes and commits or rolls back it.

A new kernel-private role per approved family/profile has an enumerated grant
inventory. It is not the existing general Governance role, an ordinary app/worker
login or a universal privileged role. There is no role membership, `SET ROLE`,
ordinary-callable `SECURITY DEFINER` escape hatch, broad schema grant or future
default grant. Runtime startup validates the exact role/grant/RLS inventory and
fails closed on drift, like the existing protected profiles.

### Role and grant matrix

These are semantic role classes; no SQL role name, secret or migration revision
is allocated by this proposal.

| Principal | Canonical bindings | Classification | Other access |
| --- | --- | --- | --- |
| Ordinary app/worker, Party/Metadata owner sessions and existing private Governance/Metadata profiles | None | Only existing supported frozen contracts | Existing inventory unchanged; no new canonical-binding grants |
| Ordinary Policy session | None | Provider interface only | Policy-owned authority; no Governance DML or ownership |
| Private field read/owner-operation profile | Exact tenant-scoped SELECT; id-column lock privilege only | Exact existing resolver SELECT/lock inventory | Enumerated owner/Policy locks; only approved owner writes and Audit/outbox append where required |
| Private Governance binding-writer profile | Tenant-scoped head INSERT/update and history INSERT; locks | Existing assignable/current resolution | Exact admitted owner witness locks and existing required Audit/outbox operations |
| Migration execution principal | Explicit forward DDL/constraints/grants | Only migration requirements | Operator-controlled; never an application provider |

PostgreSQL row-share locks require UPDATE privilege in addition to SELECT. A
read profile therefore receives only the enumerated ID-column UPDATE privilege,
with tenant-scoped UPDATE `USING` and `WITH CHECK (false)` policies, following
the existing lock-only pattern. It cannot actually modify an ID or payload.
All tenant-owned binding/head/history rows require ENABLE/FORCE RLS with trusted
`app.tenant_id` set by the framework. No private runtime role owns the tables or
has BYPASSRLS. Global canonical definitions retain their existing ownership and
access semantics; tenant overlay access remains tenant-scoped.

History has no runtime UPDATE, DELETE or TRUNCATE grants. Binding-writer UPDATE
is limited to head transition columns; immutable identity columns cannot change.
Database constraints enforce the head/version relationship, tenant/key equality,
monotonic versions and immutability. Foreign keys and uniqueness must retain
tenant identity, not merely a UUID that could refer across tenants.

Audit owns review/grants for its append participation. Platform owns outbox
review/grants. No generic Audit callback, cross-owner private SQL from Policy,
or unaudited extension privilege is authorized by the bridge.

## Lock ordering and consistency

Commit-bound composition, owner mutation and binding changes use one reviewed
lock protocol. All locks and provider admissions remain held through completion,
commit or rollback. Use finite lock/statement/transaction timeouts; timeout denies
and rolls back rather than permitting an unlocked retry/fallback.

The mandatory phase order is:

| Phase | Held authority and ordering |
| --- | --- |
| 1 | Retain handler, owner, definition-owner, Governance and Policy admission; lock/validate their durable lifecycle fences using existing lifecycle ordering |
| 2 | Owner resource/field and dynamic definition/revision locks, using the approved family's owner protocol; sort batch owner keys canonically |
| 3 | Canonical Governance binding heads, sorted by canonical logical key; readers use FOR SHARE and binding writers FOR UPDATE |
| 4 | Classification definition/version/overlay locks using existing Governance canonical-before-tenant resolution; collect and order the complete dependency set before entering this phase |
| 5 | Policy authority locks through its existing ordered authority protocol, including applicable identity/scope/membership/delegation/rule authority |
| 6 | Revalidate effective intervals/coverage and complete the approved owner operation, Audit append and outbox; final authority check, then one commit |

For phase 4, canonical-base dependencies are collected before tenant definitions.
Acquire sorted canonical definition keys and their existing definition/version/
overlay lock sequences before sorted tenant definition keys and their versions.
Retain existing classification admission/advisory fences, including absence-of-
overlay protection. Do not acquire a new canonical base after taking a tenant
definition lock. Batch resolution must precompute the finite dependency closure,
then revalidate under locks; it cannot serially call a resolver in an order that
creates a cross-reference reversal. The implementation gate must demonstrate the
existing resolver's reentrant calls do not take a new lower-phase lock.

After Policy authority locking begins, no adapter may discover an additional
owner, binding or classification identity. Reentry is permitted only for already
held locks. Policy evaluates the authenticated joined facts with its applicable
rule semantics; it cannot loop the frozen field evaluator with fabricated owner
maps or discover further provider locks after taking Policy authority.

A new canonical binding writer uses the same owner -> binding -> classification
-> Policy phases, including assignability checks, instead of resolving a new
classification first and later locking its binding. Multi-field writes gather
the entire lock set first. The bound supports deterministic ordering, not a
caller-controlled lock sequence.

A classification-only or Policy-only writer may enter its existing suffix of
the protocol, but it cannot then acquire owner/canonical-binding locks. Existing
legacy tag writers operate only on the separate legacy table and cannot mutate
canonical binding heads. Their classification-first legacy upsert sequence must
not be reused for canonical binding writes.

The implementation must prove that no enrolled owner, definition, classification,
Policy or lifecycle path reverses this order. An incompatible owner family is
not enrolled until a separately reviewed adapter supplies the compatible
protocol. This is not permission to modify frozen implementations generally.

Missing heads deny without proceeding to an owner write. Assignment creates a
stable head under the unique tenant/key constraint; concurrent creates serialize
and conflict/retry within bounded writer behavior. Existing-head readers/writers
serialize on the same row. Removal retains the locked head and appends a
tombstone, avoiding disappearance/recreation races.

Time does not stop while locks are held. After waiting for locks, use fresh
database time to select effective versions and validate the final authority
instant. Recheck validity immediately before owner application and at operation
completion. A finite validity interval limits the operation deadline; if the
transaction cannot safely complete inside that budget, deny/roll back. Historical
snapshots and an expired pre-lock evaluation cannot authorize a commit-bound
operation. Timer rollover, concurrent reassignment and rollback require explicit
concurrency tests at the implementation gate.

Completion checks the captured versions/intervals without discovering a newly
effective version. If a boundary has passed, abort the entire operation; a fresh
operation must acquire and evaluate its whole ordered authority set again.

### Presentation and reads

An authorized value read requiring composition executes in its own single,
bounded framework UOW using the corresponding private read profile. It obtains
current witnesses/tag/control/Policy facts and projects only permitted values.
This is logically a read but may need database lock privileges; an SQL READ ONLY
transaction cannot be assumed to support row locks. It is never followed by a
second authority transaction to repair that limitation.

Presentation-only hints carry a fresh validity/generation boundary and are not
mutation authority. Server value retrieval reevaluates authority; a later write
does so again within its own write UOW. Any caches are isolated by trusted tenant,
principal/security context, owner/definition provenance, canonical key/schema pin,
binding generation, effective classification/overlay and Policy epoch. Invalid
or unavailable cache identity means a miss/deny, not a shared default. Browser
cached hints never replace current backend checks.

## Change, revocation and stale replicas

| Event | Required behavior |
| --- | --- |
| Tag reassignment | Append immutable assignment and advance locked head/generation; a competing operation serializes and evaluates the applicable current version |
| Tag removal | Append tombstone; new live decisions deny; no implicit PUBLIC or recovery from historical history |
| Classification deactivation | Preserve ADR-015: new assignments deny, but existing live references continue resolving current effective controls; deactivation alone is not a mass revocation |
| Missing/expired/ambiguous effective classification | Deny; existing-reference semantics do not authorize an unavailable effective definition |
| Overlay change | Use current effective tenant additions under locks; weakening canonical minimum, missing effective registered overlay or stale evidence denies |
| Owner field/version/revision changes | Require exact admitted witness and current binding coverage; uncovered meaning/version denies, with no name-based inheritance |
| Owner/provider artifact replacement | Re-admit exact approved artifact and durable generation; retained in-flight admission follows existing activation fencing; new calls on stale instances deny |
| Old application replica or process-local handle | Validate current durable fence and active invocation; cached contribution number alone is insufficient |
| Identity/scope/Policy transition | Discard presentation/decision reuse; backend reevaluates under current trusted context |

Stricter assignment/removal serializes against in-flight operations: an operation
already holding the relevant locks completes or rolls back before the writer
commits, or the writer wins and the operation reads its new state. Revocation
cannot retrospectively undo an already committed transaction. Audit must make
the effective binding/classification/Policy versions at the decision observable.

## Party and Metadata boundaries

### Party

Party supplies only its own canonical field identity, existence and meaning.
It does not import/call Governance, resolve a classification, inspect
`sensitive_field_tags`, or know canonical Governance table layout. Ordinary Party
sessions receive no new Governance grants and no canonical binding access.

Party's existing sensitive-field/redaction contract remains an independent
minimum. Composition may deny or require additional masking; it cannot release
a value Party already redacts or weaken its existing authorization. A PUBLIC tag
or failed tag lookup cannot turn a sensitive Party field into a visible value.
Fixed Party fields are identified by the admitted Party field contract, not by
Metadata-generated labels.

Party custom-field values remain Party-owned under the Phase 5B contract.
Metadata owns their definitions/revisions. Their witness retains both admissions:
Party for the resource/value field and Metadata for the exact definition/revision.
Metadata definition provenance is not relabelled Party provenance.

### Metadata/custom entities

For Phase 5C Metadata-owned custom entities, Metadata is the resource/value owner
as well as definition owner. It authenticates dynamic field UUID/type/definition,
immutable revision/digest, retained record schema pin and current lifecycle
through its admitted owner adapter. A browser schema or a published UI resolver
response does not issue that witness.

An authorized definition may already carry a qualified classification reference.
That remains definition data, not a Policy receipt. Where present, composition
requires it to match the current Governance binding's qualified reference and
covered definition meaning. Mismatch denies; Policy does not choose the less
restrictive source. Reference changes require explicit authorized definition and
binding transitions; this ADR does not authorize a general multi-owner editor.

Historical record/schema pins are preserved. They establish which immutable field
meaning is read or written, but cannot select an old tag, overlay or Policy state.
Owner/version/revision/digest mismatch, a stale definition-owner generation or
missing current binding coverage denies. No universal EAV store, Metadata-to-
Party private SQL, or new Metadata-owned authorization authority is introduced.

## ADR-024 relationship

ADR-024 remains the authority for published UI source/dependency compatibility
and completeness. Its proof does not authorize a field or attest current
Governance/Policy state. ADR-025 composition evidence does not certify a
published UI declaration. The two evidence types remain separately issued,
validated and lifecycle-bound.

If a future Phase 5E declaration requires a field-composition contract version,
the requirement must be part of an admitted declaration source and its permitted,
actual direct manifest dependencies. ADR-024 fences that selected source and
those direct dependencies at their admitted versions/artifacts/generations.
A literal contract name/version is not proof that its provider was admitted.
Unsupported/unadmitted requirements fail compatibility admission.

Do not add Party -> Policy/Governance dependencies merely to include those
modules in a UI proof. An appropriate owning source, such as Metadata where its
actual dependencies permit, declares the requirement. No recursive dependency
catalog, runtime tag rows, authorization decision or browser classification is
injected into ADR-024's model-1 seal. Runtime composition separately retains and
validates its complete owner/provider authority.

## Storage and migration impact

Review of the baseline shows:

- `sensitive_field_tags` is unique on tenant, `entity_type`, `field_name`;
- it carries legacy code and optional qualified reference/version/definition ID;
- ordinary legacy upserts can replace assignment data in place;
- it lacks authenticated owner/field identity, immutable binding history,
  meaning coverage, durable generation and the canonical-head lock protocol.

Therefore **a forward Governance-owned migration is required before the new
capability can use canonical tag authority**. No migration is implemented or
number allocated here. The required semantic shape is:

1. Separate canonical binding heads with normalized typed identity columns,
   tenant/key uniqueness, stable IDs, current generation and guarded transitions.
2. Append-only assignment transitions with exact qualified reference, explicit
   contract/meaning/revision coverage, tag-specific masking, immediate effective
   start, optional expiry and tombstone lifecycle; derive historical ends from
   ordered transitions.
3. Tenant-preserving relational constraints, immutable identity/history enforcement,
   indexes, ENABLE/FORCE RLS and enumerated profile grants.
4. Concurrency fencing for head creation, immediate changes, revocation and
   derived effective history; no future-dated tag scheduling in the first version.
5. Existing supported classification definition/reference relationships; no
   duplicate classification catalog.

The legacy table and contracts remain legacy data/provenance, not live authority
for the new capability. There is no runtime string join, guessed backfill or
fallback to it. Existing legacy writers cannot mutate canonical storage.

Conversion is an explicit permissioned Governance operation requiring an admitted
owner mapping, exact tenant, valid assignable qualified reference and meaning
coverage. It creates new canonical history and preserves traceable legacy input.
Unmapped, ambiguous, cross-tenant, inactive-for-new-assignment or mismatched rows
remain unbound and deny in the new path. Counts/conflicts are reported; no data
is silently dropped or assigned PUBLIC.

Legacy `is_masked_by_default` is independently significant: it may be true even
for a PUBLIC reference. Conversion must explicitly preserve that masking intent
in the canonical binding requirement, or quarantine the row pending accountable
review of an equivalent disposition. It cannot copy only the reference and
silently initialize masking to false. Any stronger canonical masking semantics
are explicit in that approved mapping; the old contract is not rewritten.

The fixed conversion operation alone may receive an enumerated legacy-table
read grant in its private profile. Normal field readers/owner operations and
canonical writers do not inherit that conversion access.

Use expand-and-admit rollout: create storage/grants, verify source/wheel migration
graphs and retained upgrades, reconcile authorized mappings, then explicitly
enroll supported operations. Rollout cannot enable composition while required
bindings are absent. No historical revision changes or ORM auto-synchronization.
Downgrade with canonical authority/history present must refuse destructive loss
unless a separately authorized, audited export/decommission procedure is proved;
it cannot recreate equivalent authority from legacy strings.

## Compatibility and affected public surfaces

| Existing decision/surface | Extension boundary |
| --- | --- |
| ADR-014 Policy V2 | Owner resource facts remain owner-origin; new separately attributed tag facts/new capability; existing field-policy.v2 unchanged |
| ADR-015 classification | Governance definitions/overlays/reference lifecycle unchanged; new canonical binding resolver under Policy-owned port |
| ADR-018 owner admission | Add neutral authenticated field witness; retain owner admission and existing operation boundary |
| ADR-022 execution | New exact opt-in profile/executor follows private same-UOW precedent; no role switching or ordinary privileged persistence |
| ADR-023 customization | Preserve definition/value ownership, immutable revisions and record pins; no Metadata authorization receipt |
| ADR-024 UI provenance | Preserve model-1 source/direct-dependency proof and frozen publication/resolver behavior |
| Phase 5A–5D | No existing contract, migration, private profile, published schema or resolver behavior changed by this proposal |
| Phase 4.5 | No session, UI shell, component, navigation, permission presentation or security-transition contract changed |

No accepted clause is superseded. Specifically, ADR-014's owner-origin field
classification path remains applicable to its existing evaluator. The proposed
capability permits an additional **separately attributed** input, not a forged
owner projection. If implementation cannot preserve that coexistence or discovers
another conflict, it must stop for explicit ADR/governance review rather than
silently revise an accepted decision.

Affected future surfaces are the neutral owner-field witness contract, the
Policy-owned tag/composition interfaces, Governance canonical binding commands/
facts, and exact private execution enrollment. Their versioning, wire exposure,
errors, admission and supported SDK imports require separate contract review.
No browser/transport/React rendering contract is implemented by this ADR.

## Security invariants

The implementation gates must demonstrate all of the following:

- Trusted tenant equality across context, witness, binding, classification,
  Policy, database RLS, audit and outbox; no cross-tenant lookup or cache reuse.
- Only an admitted owner authenticates its canonical field. Governance alone
  performs authorized binding assignment; other modules cannot self-assert
  another owner's field or issue a tag.
- Transport/browser/Metadata display data cannot manufacture either authority
  source, choose an old provider, downgrade the enrolled contract or select SQL.
- Missing, null, ambiguous, stale or failed resolution denies; no implicit PUBLIC.
- Current binding coverage and classification/overlay controls are checked even
  for historical schema pins; historical audit reads do not restore live access.
- Party's existing redaction/owner permission floor cannot be weakened.
- Read hints cannot authorize writes; field permissions cannot be inferred from
  record access; issued decisions are not transferable receipts.
- One transaction and retained admissions/fences cover authority, owner operation,
  Audit/outbox and commit/rollback; no second authority transaction.
- Ordinary owner/Policy roles have no canonical Governance table access; private
  adapters are fixed and least-privileged; no arbitrary callback or SQL escape.
- Concurrent change/revocation follows the common lock order and cannot produce
  a value/commit from stale facts; timeouts roll back.
- Owner identity, Governance assignment, Policy composition and UI compatibility
  remain distinct responsibilities without a circular dependency.

## Consequences and considered alternatives

### Option comparison

| Criterion | A: owner supplies reference | B: Policy joins independent providers | C: Governance composes both | D: neutral composer |
| --- | --- | --- | --- | --- |
| Dependency direction | Existing owner reference path is valid; discovering Governance tags from Party would add forbidden dependency | Owner uses neutral SDK; Governance implements Policy port; Policy imports no Governance | Possible through neutral witness plus Policy port | Neutral interfaces possible, but new cross-module composition service |
| Ownership | Cannot establish Governance assignment by an owner assertion | Owner identity and Governance tag independently attributed; Policy owns join/decision | Tag owner also certifies combined input | Framework/service owns join despite Policy-facing authority semantics |
| Same UOW | Owner reference alone omits current binding lock | Fixed same-UOW adapters and explicit lock phases | Still needs retained owner/tag/classification locks | Still needs all adapters/fences; extra boundary supplies no transaction advantage |
| Stale replicas | Owner cache does not establish current tag/fence | Validate both current sources and durable fences | Composite source must independently validate both | Neutral receipt still needs both current sources; cannot become portable authority |
| Grants/RLS | Direct owner tag access would violate Party boundary | Private per-family profiles; no ordinary owner/Policy Governance grants | Private cross-owner executor still required | Generic service risks universal role; per-family restriction still required |
| Extensibility | Every owner would duplicate Governance discovery | New owner witnesses/providers admitted by published contract | Governance acquires more owner-integration composition responsibility | Adds a general provider/service lifecycle beyond this bounded need |
| Party freeze | Cannot solve new tags by Party -> Governance | Preserves dependency and independent redaction | Can preserve it only using neutral witnesses | Can preserve it but introduces additional authority coordinator |
| Metadata custom fields | Definition reference alone is not current assignment authority | Exact dynamic pins and separate current coverage | Must carry the same provenance and coverage rules | Same pin rules plus another composition owner |
| Phase 5E complexity | Appears simple but leaves the authority gap | Explicit new contracts/storage/execution; bounded and reviewable | Combines authentication/join in Governance while Policy owns decision port | Highest additional framework/domain composition surface |

**B is selected.** A remains valid for its existing frozen path but cannot answer
the new Governance-tag question without changing ownership. C is feasible with
careful contracts, but would put the independently attributed join inside the tag
owner. D would assign field-classification joining to a new neutral service
despite Policy owning decision semantics. Neither C nor D is selected or an
implementation fallback. The framework-private executor in B transports fixed
same-UOW operations; it is not Option D's semantic composer.

Benefits are explicit provenance, no Party/Governance dependency, current tag
authority, least-privilege private execution and extensible owner contracts.
Costs are new canonical storage, owner witness enrollment, private profile
review, bounded multi-provider locking and migration/concurrency certification.
Unsupported owners remain unavailable in the new path rather than being adapted
by private SQL or legacy name matching.

## Accountable approval roles

The union follows [ADR governance](../governance/ADR-GOVERNANCE.md#approval-authority)
and [maintainer ownership](../governance/MAINTAINERS.md#required-review-ownership).
Every approval is PENDING:

| Role | Required responsibility |
| --- | --- |
| Architecture Maintainer | Selected composition/ownership and compatibility decision |
| Platform/Kernel Maintainer | Neutral witness admission, fixed private executor/profile and active UOW/fences |
| Security Maintainer | Tenant trust, fail-closed authority, private grants/RLS and revocation |
| Policy Maintainer | Decision-facing ports, independent join and preserved field-rule semantics |
| Data Governance Owning Domain Maintainer | Canonical assignments/history, classification lifecycle and provider |
| Metadata/Studio Owning Domain Maintainer | Authenticated dynamic identity, definition/revision pins and UI provenance separation |
| Party Owning Domain Maintainer | Fixed/custom field witness, value ownership and redaction floor |
| SDK/Contract Maintainer | Versioned owner/provider/decision contracts and compatibility admission |
| Migration Safety Reviewer | Forward canonical storage, retained upgrades, grants/RLS and downgrade refusal |
| Audit Owning Domain Maintainer | New private principal's existing append grants/RLS and fixed same-UOW bridge |
| Release Maintainer | Frozen-phase coexistence, deployment enrollment and implementation gates |

The Audit role is required because a new execution principal's append authority
must be explicitly reviewed, even though AuditAppender semantics do not change.
The outbox boundary is covered by Platform/Kernel ownership. Frontend Foundation,
Identity, Organization and Documentation/Governance policy roles are not added
for unchanged owned contracts; a later change to those contracts requires their
roles. One owner holding multiple roles cannot collapse this list. Formal
acceptance requires exact-revision accountable review or the documented Solo
Maintainer Exception. The eligible Solo Maintainer path additionally requires
independent technical audit, its other documented gates and actual personal
owner attestation. This proposal does not supply either form of acceptance.

## Implementation and follow-up gates

Architecture acceptance alone does not clear any runtime gate. Require explicit
owner implementation authorization after acceptance, with exact scope and order:

1. **Public contracts:** approve bounded identity/witness/tag/composition versions,
   origin issuance, errors, SDK surfaces and conformance. Preserve old V2 surfaces.
2. **Owner field locator:** implement neutral admission and exact fixed Party,
   Party-custom and Metadata-custom identity/pin witnesses; certify forged,
   retired, mismatched and stale owner/definition cases.
3. **Governance resolver:** implement current canonical assignment/history and
   Policy-owned tag port; prove no legacy-name fallback or implicit PUBLIC.
4. **Policy composition:** implement independently attributed join, actual field
   permissions, current effective controls and distinct read/commit contracts.
5. **Private execution/grants/RLS:** separately enroll fixed families and audited
   adapters; validate opaque caller transaction, no SQL/callback/role escape,
   tenant isolation and exact owner/Audit/outbox grant inventories.
6. **Forward migration:** approve semantic storage/constraints, source/wheel graph
   equality, fresh and certified-base retained upgrade, explicit conversion,
   replay and destructive downgrade/refusal behavior; historical files unchanged.
7. **Concurrency:** certify complete lifecycle/owner/binding/classification/Policy
   lock ordering, absent-head/overlay races, reassignment/removal, scheduled
   intervals, stale replicas, rollback and finite timeout behavior.
8. **Owner integration:** separately authorize Party and custom-entity operation
   enrollment; preserve Party redaction and frozen Phase 5A–5D regressions.
9. **Phase 5E projection:** reconcile the compatibility specification with the
   accepted contracts, admit any ADR-024 declaration dependency correctly, and
   explicitly authorize backend projection/transport and rendering separately.

Each runtime candidate requires fresh exact-head CI, focused security/conformance
and integration evidence, independent audit, owner acceptance and guarded release
under repository governance. No future candidate may reuse proposal checks as
implementation certification. React Form/Detail/List rendering, backend transport
and Phase 5E-B remain unauthorized until their prerequisites and explicit gate are
cleared. This ADR authoring task implements none of them.

## Proposal validation and evidence boundary

Applicable checks are the Phase 0 architecture/governance gate, focused governance
tests, ADR record/number/relative-link checks, strict UTF-8/mojibake integrity,
documentation-only/frozen-file diff checks and `git diff --check`. The authoring
report records actual results, commit/tree and SHA-256 of these exact ADR bytes.
Do not invent a self-referential commit/hash inside this document.

No full runtime certification is required to prepare this proposal. Hosted CI,
independent architecture audit, required-role acceptance and accepted-main
reconciliation remain separate formal acceptance gates. No source, contract,
migration, frontend or CI implementation change is included here.
