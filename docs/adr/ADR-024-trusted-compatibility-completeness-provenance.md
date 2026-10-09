# ADR-024: Trusted Compatibility Completeness Provenance

Status: ACCEPTED / AUTHORITATIVE ON MAIN

Decision date: 2026-10-05.

Approving roles required: Architecture Maintainer; Platform/Kernel Maintainer;
Metadata/Studio Owning Domain Maintainer; Security Maintainer; Policy Maintainer;
Migration Safety Reviewer; SDK/Contract Maintainer; Audit Owning Domain Maintainer;
Release Maintainer.

Accepted exact proposal commit: `3092a976cbae291a700f26765c0b95638e4809c2`.

Audited proposal SHA-256:
`a1f928fcb009407ebaf57c99634d8716705acf420da971f77c7e56030da8b6fd`.

Independent architecture audit: ADR-024 INDEPENDENT ARCHITECTURE AUDIT — PASS;
Critical 0 / High 0 / Medium 0 / Low 0 / Documentation-only 0.

Owner architecture acceptance: [PR #67, comment 5991893651](https://github.com/sahinkhan/businessos/pull/67#issuecomment-5991893651),
personally posted by @sahinkhan for the exact proposal commit above.
Review model: SOLO MAINTAINER OWNER ATTESTATION.
Independent human review: NOT PERFORMED. Independent technical architecture audit: PERFORMED.
The acceptance comment records Architecture, Security, Metadata/Studio, SDK/Contract,
Migration Safety and Release responsibilities. This record does not add roles to that comment.

Supersedes: None. This is a bounded extension to ADR-022/ADR-023, not a
replacement of their accepted decisions or a general reopening of frozen phases.

Superseded by: None.

Implementation authority: N1 remediation under the accepted architecture below,
explicitly authorized by the owner. The original proposal context and semantic decision
are preserved below as audited. Architecture acceptance does not certify its implementation.
Phase 5D implementation is CERTIFIED / CLOSED / FROZEN at guarded merge
`9236d430464191da59bef3c9df75c83f22a9ade5`, preserving audited candidate
`43cdb3717eaa44d26528ae63624c2397e540428a` and tree
`f2d9588e0f698d3fe8eb6a2b81bba31c7461d804`. Protected-main CI
[37752894384](https://github.com/sahinkhan/businessos/actions/runs/37752894384)
completed SUCCESS; all three required jobs passed. The final independent
implementation re-audit passed with Critical 0 / High 0 / Medium 0 / Low 0 /
Documentation-only 0. Personal implementation acceptance is recorded in
[comment 6055956182](https://github.com/sahinkhan/businessos/pull/67#issuecomment-6055956182)
and [supplement 6056193477](https://github.com/sahinkhan/businessos/pull/67#issuecomment-6056193477).
The [Phase 5D certification provenance](../architecture/PHASE-5D-PUBLISHED-UI-SCHEMA-RESOLVER.md#phase-5d-certification-provenance)
is the canonical implementation record. This documentation-only reconciliation
follows its own protected governance workflow and has a distinct commit/tree.
Phase 5E–5H remain unauthorized, uncertified and unstarted.

The accepted semantic decision is unchanged by this reconciliation. The body
beginning at Context is preserved byte-for-byte relative to guarded implementation
merge `9236d430464191da59bef3c9df75c83f22a9ade5`, including its historical
failed-candidate context and prospective implementation
acceptance gate. References there to a draft PR or uncertified Phase 5D describe
the proposal-stage state, not the completed implementation recorded above.

## Context

PR #67 is based on protected main 61341e71c777aea390bee99bfd207bd6e5a6bb87.
Its committed candidate is 01f5454b94a2746fdb448e5e4a26b8e9002a6adf, tree
5b604c60b325d82fc1af7eab8f0ab4cd2d9afe1a. CI 37215110092 succeeded, but the
second-remediation independent re-audit FAILED: Critical 0, High 0, Medium 2,
Low 0, Documentation-only 0. N1 concerns incomplete sealed bindings; N2 concerns
stale readiness after disable. N2 has separate, uncommitted local remediation;
it does not depend on this ADR and must be preserved without being certified here.

Earlier failed audits of d1e17bab90b6dfbd3dbf429b674e91e6b40876df and
a9f69ad334f944fa42b4e04ff4f1218131d98c82 remain historical evidence. Green CI
does not override any failed audit. H1/H2/H3/R2/M2/M3 were independently resolved;
their Policy, disclosure, lifecycle, availability, containment and customization
invariants are constraints on this proposal, not areas to redesign.

The [Phase 5D candidate architecture](../architecture/PHASE-5D-PUBLISHED-UI-SCHEMA-RESOLVER.md)
uses the framework-issued Metadata catalog to capture admitted declarations,
their owners and dependencies. Metadata composes the view and persists module ID,
artifact identity and database generation bindings. The existing compatibility
digest covers the composition's modules, declaration digests and schema/UI
contract generations. Process-local admission generations are checked through
completion but are not durable artifact pins across process restarts.

## Problem

Migration metadata_0005_ui_binding_seals makes supplied bindings immutable and
requires a seal before activation/commit. It does not authenticate completeness.
The independent witness published a valid six-binding revision, constructed
another revision with compatible content/provenance, supplied one valid binding,
sealed it and activated it. Resolution succeeded while an omitted Party dependency
had no activation pin, admitting incompatible activation.

An immutable supplied set is not an authenticated complete required set.
Nonempty checks, row counts, individually valid rows, and a same-role writable
expected count or digest cannot distinguish that witness from a complete set.
The role could replace both actual rows and the purported expected value.

Required invariant: a revision becomes sealed and authoritative only when its
persisted bindings exactly equal the complete required set emitted by trusted
admitted composition for that exact context. The businessos_metadata SQL principal
cannot manufacture that assertion, even with direct use of all its granted SQL.

## Existing constraints

- [ADR-018](ADR-018-canonical-resource-ownership-and-owner-operation-boundary.md)
  and [ADR-020](ADR-020-trusted-handler-invocation-authority.md) remain the sources
  of approved artifact, exact handler, invocation and lifecycle authority.
- [ADR-022](ADR-022-module-scoped-database-execution-authority.md) supplies the
  protected-pool pattern, not an existing credential capable of solving N1.
  Its current Metadata enrollment uses the same SQL role for ordinary Metadata
  persistence and internal installation work; merely renaming that callback adds
  no PostgreSQL trust boundary.
- [ADR-023](ADR-023-metadata-persistence-customization-and-dynamic-ui-resolution.md)
  keeps composition/schema ownership in Metadata. PostgreSQL remains authoritative;
  tenant RLS and the existing module/contract compatibility fence remain mandatory.
- UI state, completeness evidence, actual bindings, seal, active pointer, counters,
  AuditAppenderV2 and transactional outbox must commit or roll back in one UOW.
  There is no autonomous proof transaction or distributed commit protocol.
- Preserve KEY SHARE readers, NO KEY UPDATE counter writers, bounded activation
  waits, deterministic lock order, retained admissions and final Policy fences.
- Frozen public contracts, historical migrations and browser authority remain
  unchanged. There is no vendor service or new general-purpose trust service.

## Threat model

| Actor | Boundary and guarantee |
| --- | --- |
| Browser, tenant caller, ordinary app/worker | Cannot select a protected role, issue a completeness assertion or supply identity/expected-set authority. Existing authorization and RLS still apply. |
| Buggy or compromised Metadata execution using businessos_metadata SQL | May fabricate SQL inputs within that role's grants, including proposed revisions and actual bindings. Cannot write authenticated expectations, become their issuer, or bypass verifier constraints. Same-tenant SQL is explicitly in scope. |
| Trusted publication executor/catalog | Small protected computing base. Selects the real admitted sources and controls the private publication persistence boundary. Its APIs must not become a signing/projection oracle for caller-supplied sets. |
| Privileged database administrator/migrator | Trusted installation tier; can alter grants, constraints, stored evidence or the database. This design does not claim resistance to a malicious fully privileged DBA. |
| Compromised kernel, issuer credential, OS or unrestricted process memory | Outside the SQL-principal isolation guarantee. Contain operationally, revoke credentials and investigate affected evidence. Python object privacy is not an in-process hostile-code sandbox. |

Marketplace executables retain their existing isolation requirement. Calling
arbitrary Python inside the trusted kernel is not equivalent to possessing the
bounded Metadata SQL role. The distinction must remain explicit in certification.
Completeness evidence authenticates dependency provenance, not business permission;
it cannot replace Identity, owner, scope, Policy or completion checks.

## Decision drivers

1. Independently authenticate the expected set, then enforce exact equality in SQL.
2. Reuse the existing admitted catalog, not another dependency authority.
3. Retain single-UOW atomicity and R2 reader availability.
4. Avoid unnecessary cryptographic algorithms, extensions or durable signing keys.
5. Support local, HA, shared-schema, database-per-tenant and air-gapped installations.
6. Make direct SQL, upgrade, replay, failure and restore behavior testable.

## Considered alternatives

| Alternative | Assessment |
| --- | --- |
| A. Framework-issued cryptographic receipt | Can authenticate existing catalog output if private issuance is protected and PostgreSQL verifies it. A MAC shares forging power with its verifier; signatures separate signing from verification but need a supported verifier, key provisioning, retained key history and rotation/restore rules. More machinery than needed when issuer and durable state already share trusted PostgreSQL administration. Not selected. |
| B. Privilege-separated authenticated database projection | SELECTED. A kernel-private publication executor writes immutable expectations through a distinct protected SQL identity. PostgreSQL grants establish origin; constraints establish exact equality. Reuses ADR-022's bounded private-pool discipline, with a new expressly reviewed profile and no signing keys. |
| C. SECURITY DEFINER completion routine alone | Insufficient: a procedure cannot infer missing modules from caller-supplied rows. A narrow owner-owned verifier can enforce B's independently authenticated projection, but is an enforcement detail, not the source of completeness. |
| D. Transaction-bound in-memory capability alone | Useful to route the protected executor but SQL cannot authenticate an opaque Python object. GUCs, query comments and caller-set operation IDs are forgeable. Making it SQL-verifiable requires A or B; it is not an alternative database proof. |
| E. Move all compatibility/UI persistence ownership into the kernel | Would unnecessarily move Metadata semantics/schema ownership upward and couple the kernel to UI composition. Reject the ownership move; B changes authenticated execution authority while Metadata retains owning persistence code. |

### Cryptography and PostgreSQL feasibility

[PostgreSQL 17 pgcrypto](https://www.postgresql.org/docs/17/pgcrypto.html) documents
digest/HMAC and PGP encryption operations. It does not provide a general detached
signature-verification contract for this proposed receipt; PGP encryption must
not be described as signing. A signature design would require separately approved
database/library support and packaging. No handwritten cryptography or assumed
extension support is acceptable.

HMAC would require the backend issuer and database verifier to protect the same
secret from Metadata SQL. A database verifier holding that secret can also forge.
An asymmetric alternative would keep only public verification material in SQL but
still needs an authenticated key registry, algorithm/version policy and offline
restore support. Runtime-only signature verification with Metadata-writable proof
rows leaves the direct-SQL bypass open. B avoids these added dependencies while
retaining the same explicit trust in the kernel and privileged database operator.

## Proposed decision

Recommend exactly B: a **kernel-private, privilege-separated publication executor
that persists Metadata-owned completeness provenance in the same publication UOW**.

Only this executor may assert the expected complete set, and only from the existing
framework-admitted catalog/composition snapshot. Metadata remains the semantic
owner of composition, binding tables and verification SQL. The kernel authenticates
invocation, holds the private execution profile and controls transaction completion.
It does not create or interpret an alternative module dependency registry.

This requires a new bounded SQL profile distinct from businessos_metadata. Reusing
the Governance, migrator or ops credential is prohibited. The new profile is not
given to arbitrary Metadata handlers: simply selecting a more privileged pool and
passing its unrestricted UOW to the current handler would fail this decision.

The private executor must own the whole publication transaction. Existing supported
UI commands provide validated authoring intent, not SQL, an expected set, projection
rows or a privileged callback. The executor selects fixed approved owner persistence
operations and trusted catalog inputs through exact invocation/admission provenance.
No credential, connection, raw privileged persistence handle, role selector or generic
projection-write API is exported to handlers, SDK, DI, tenant settings or manifests.

This is a bounded internal persistence boundary change requiring explicit acceptance;
it is not claimed to exist already. Implementation must preserve public command and
query contracts and the owner/UOW architecture. If that cannot be achieved, amend
the proposal before implementing; do not fall back to a second transaction or SQL
interception masquerading as privilege isolation.

## Trust boundaries and ownership

| Component/principal | Allowed authority |
| --- | --- |
| Existing admitted catalog and owner composition | Determines required sources/dependencies for the view under current approved lifecycle admissions. |
| Kernel-private executor | Recomputes/captures that complete set; selects the protected pool; invokes the fixed Metadata-owned writer; retains final guards and controls commit/rollback. |
| New private publication SQL profile | Narrow DML needed for expected provenance and owning publication, plus explicitly reviewed Audit/outbox and authorization reads. No schema ownership, superuser, BYPASSRLS, role switching or general owner-table access. |
| businessos_metadata | Cannot insert/update/delete authenticated expectation rows or assume the private profile. May retain only reviewed ordinary Metadata privileges; every accessible seal/pointer path must enforce the independent projection. |
| Metadata-owned verifier | Exact relational set/context comparison and immutable seal enforcement; cannot issue expectations from caller data. |
| Migrator/operator | Provision reviewed roles, ownership, policies and version transitions; manage recovery. Not an online publication fallback. |

The implementation grant audit must include column grants, inherited membership,
views, routines, triggers, role assumption, defaults and indirect write paths.
Keep authenticated evidence in Metadata-owned tables, with FORCE RLS for tenant rows
and tenant-local policies for the distinct runtime profiles. Profile identity is
established by the actual authenticated SQL session, never a module GUC.

Current module_fence UPDATE privileges are also relevant: a completeness receipt
alone cannot stop direct counter or identity tampering. Acceptance of the implementation
requires forward privilege/constraint hardening so businessos_metadata cannot rewrite
activation-relevant identities or bypass UI counter transitions. Counter adjustments
must come from owner-controlled validated binding/pointer transitions; artifact changes
must come from admitted installation lifecycle. Do not grant an arbitrary counter-setter.
Preserve existing Phase 5A definition transitions through their bounded owning path and
prove their frozen observable behavior unchanged. This is a required grant review, not
permission to redesign Phase 5A or reinterpret its revisions as UI proofs.

## Canonical completeness model

The authoritative set is the unique union of every source owner and dependency in
the existing retained Phase 5D admitted snapshot: base/owner, admitted extension and
localization sources, capability declarations and their required dependency generations.
Do not take a caller's filtered list, infer missing modules from counts, or pin every
installed module indiscriminately. Preserve the existing bounded dependency model;
if a future contract expands its dependency closure it needs a versioned change.

Canonical model v1:

- Each member has module_id, artifact_identity and positive database generation.
- Module IDs must already satisfy the canonical manifest ID grammar. Reject aliases,
  whitespace variants or noncanonical casing rather than silently repairing them.
- Artifact identities are exact opaque UTF-8 identities from approved installation
  provenance. Do not trim, case-fold or Unicode-normalize them, or equate artifact
  identity with a digest unless its existing versioned contract defines that meaning.
- Generations are positive PostgreSQL BIGINT integers, with explicit overflow/type
  rejection. No floats or process-local admission numbers in the durable identity.
- Repeated declarations may share a module dependency. The trusted capture takes the
  union only after asserting identical identity/generation for repeated module IDs.
  Duplicate rows in a submitted/stored binding set are rejected, not silently deduplicated.
- Sort members by module ID's UTF-8 bytes; use explicit bytewise ordering, not database
  default collation, SQL row order or map iteration. There are at most 128 members.
- Expected rows are a typed relational representation keyed by tenant, revision and
  module ID. Exact equality compares both directions for missing/extra/different rows,
  with NOT NULL identities and uniqueness. Counts are a budget check only.
- A versioned diagnostic digest, if stored, uses a domain-separated length-prefixed
  encoding of those sorted UTF-8 fields and unsigned integer generations. It is a
  checksum over an authenticated projection, not its authenticator. Golden vectors
  must specify the encoding before implementation; no new public wire format is defined here.

### Context fields and their purpose

| Authenticated fact | Prevented confusion/substitution |
| --- | --- |
| Model/issuance version and purpose = Published UI completeness | Reinterpreting another projection type or unknown format as a UI seal. |
| Installation lineage identifier | Treating a copied database/projection as evidence for a different installation without reviewed restore/import. It is not a caller-set installation label. |
| Tenant UUID | Cross-tenant reuse, including within one shared database. |
| View UUID, overlay UUID, revision UUID | Moving complete evidence to another view, scope container or historical revision. Composite same-tenant references are mandatory. |
| Scope kind/ID and overlay's immutable view identity | Reusing a revision across tenant/company/site/user overlays; values derive from existing trusted scope, not browser assertions. |
| Draft generation and prior active generation at issuance | Stale or competing publication intent; consumed by the existing optimistic checks, not permanent reactivation permission. |
| Document digest and compatibility digest | Swapping content or its composition baseline while keeping an authentic binding set. |
| Complete canonical module identities/generations | Omitting dependencies or replacing them with individually valid unrelated rows. |
| Declaration digests and schema/UI contract generations | Substituting capability/dependency declarations or a different contract interpretation behind the same module names. |
| Issuer profile/version and current admitted operation provenance | Traceable approved execution path; SQL privileges establish origin, not a caller-written issuer string. |

Transient admission generations are captured and held by the executor through
completion; they may be recorded diagnostically but never used as restart-stable
module identity. Persisted module generation and artifact pins retain their existing
semantics. The proof authenticates every fact in the existing compatibility fingerprint
without making that caller-writable fingerprint the sole trust anchor.

Installation lineage is a migrator-provisioned immutable database identity, inaccessible
for Metadata mutation, retained during an approved same-installation restore. It is not
the default configuration UUID, a per-process random value or an extra module authority.
Provisioning must establish it before issuing projections; a different installation
cannot acquire old provenance merely by setting a matching runtime configuration value.

## Issuance

1. Capture the exact supported UI command/invocation, Identity-issued context and
   approved handler generation through existing kernel admission. An ordinary handler
   cannot request the private profile merely by naming a module or command.
2. The private executor opens the one tenant UOW using the authenticated publication
   profile. Credentials/profile configuration are installed by trusted composition.
3. Retain the real catalog source/dependency admissions. Derive and validate the
   composition through the approved Metadata-owned implementation selected by the
   framework, never a callback or snapshot object supplied by the untrusted caller.
4. Acquire the existing contract and sorted module compatibility fences, then the
   tenant/view and overlay locks. Verify the database identities against the captured
   approved provenance. Do not grant the caller authority to manufacture these identities.
5. Recheck document, scope, draft/prior-active generations and quotas. Allocate the
   revision identity inside this operation. Persist the immutable expected header/set,
   revision and complete actual rows through fixed Metadata-owned operations.
6. Verify exact equality, establish the completeness seal and transition the pointer
   and activation counters. Write AuditAppenderV2/outbox in this same transaction.
7. Retain existing final Policy authority and lifecycle guards through outer completion;
   commit everything together, or roll everything back on error/cancellation.

A proof is not issued in advance by an autonomous privileged pool transaction.
There is no orphan durable authorization, privileged second UOW, SET ROLE hop,
post-commit proof repair or two-phase commit. A private ephemeral operation token
may connect internal steps but is not accepted by SQL as independent authentication.

The issuer must not accept expected rows/digests as authoritative inputs. Even an
otherwise valid direct Metadata SQL transaction cannot call an issuer routine to
bless its chosen subset. Exactly which internal executor methods are admitted must
be enumerated and reviewed before implementation, without a general callback API.

## Verification and seal semantics

PostgreSQL verifies persisted state, not a Python boolean that validation occurred.
An active pointer requires an immutable completeness seal referring to the exact
authenticated expected header/set and matching tenant/view/overlay/revision context.
Before sealing, compare actual and expected tuples in both directions, verify current
module/contract identities under the existing fences and validate header/content links.
Missing, extra, substituted, duplicate, stale or mismatched members reject the transaction.

Deferred constraints also reject a committed revision lacking complete authenticated
evidence. No mutation of expected rows, actual sealed rows or seal identity is allowed
after issuance, including after retirement. Pointer changes cannot merely test whether
an arbitrary seal row exists. Uniqueness/composite foreign keys and immutable verifier
links prevent attaching a proof to a different revision. Direct Metadata INSERT/UPDATE
must encounter these same database checks; no alternate writable view/routine may bypass them.

The role itself cannot forge the independent projection. Credentials, role membership,
ownership and grants must enforce that fact even when SQL text is adversarial. In-process
API wrappers are additional controls, never the only proof of SQL-principal separation.

Use ordinary PostgreSQL constraints and invoker functions where possible. If an
owner-controlled trigger needs elevated privileges for a precise counter/proof check,
its NOLOGIN owner has only those privileges, cannot bypass tenant protection, accepts
no caller SQL or expected-set assertion, and is not a general mutation API. Fixed
qualified objects, a safe search_path, explicit EXECUTE revocation/grants and RLS
tests are mandatory. PostgreSQL's [function security guidance](https://www.postgresql.org/docs/17/sql-createfunction.html#SQL-CREATEFUNCTION-SECURITY)
requires care with writable search paths and default PUBLIC execution privileges.

## Replay and context binding

There is no portable bearer receipt. Authenticated expected rows are durable,
immutable relational evidence for exactly one revision, not an API credential.
Primary/foreign keys and full context comparison reject another tenant, view, overlay,
revision, document or set. Replaying the same publication request uses existing
idempotency/optimistic generation behavior; it cannot create a second authoritative
revision under an old projection. Rollback removes both evidence and new state.

Reactivation may reuse evidence only for that same historical revision, after fresh
scope, permissions, current composition and module/contract-generation checks. An
authentic old projection never grants permission to activate a newer incompatible
artifact. Expiry would incorrectly invalidate durable history after ordinary time
passes, so this design adds no receipt TTL or nonce. Current-authority and exact-revision
checks supply the bounded-use semantics; transaction deadlines still bound operations.

## Key and trust-material lifecycle

No HMAC secret, asymmetric key, signature algorithm or portable verification-key ring
is selected. The trust material is the private SQL credential, reviewed role/grants,
database schema/version and protected executor enrollment.

- Provision a distinct least-privilege login through the reviewed operator path,
  before forward grants. Never embed its password in migrations, source or manifests.
- Load it through existing approved secret/configuration mechanisms only in trusted
  composition. Verify expected database/session user, membership, grants, RLS, schema
  version and supported issuer version. No fallback to Metadata, migrator or ops.
- Rotation follows protected-pool replacement: validate a new credential/pool, stop
  new admissions on the old pool, drain or cancel bounded in-flight work, then dispose
  old connections. Existing immutable projections remain valid; a password is not a
  signing key whose disappearance invalidates historical data.
- API replicas use the same reviewed SQL principal/profile policy and database schema;
  they may use separately managed credentials only if their effective authority is
  equivalently validated. Ordinary workers never receive this credential by default.
- Compose/self-hosted secret files and Kubernetes Secret/external secret references
  are deployment choices, not different authorization designs. Use bounded pools and
  account for every replica in the installation connection budget.
- After issuer compromise, stop issuance, revoke/rotate credentials, preserve evidence
  and quarantine affected projections pending operator investigation. Rotation alone
  does not retroactively make potentially forged historical rows trustworthy.
- Log profile/version and bounded outcome codes, never passwords or connection URLs.

For rejected A, accepting cryptographic receipts later would require a new decision
covering offline generation/storage, all replicas, old verification keys, compromise,
algorithm/version retirement and restoration. This proposal does not leave a latent
unreviewed signing fallback behind the database projection.

## Tenancy

Expected header/member/seal rows are tenant-owned and FORCE-RLS protected. Tenant ID
is part of every relational identity and verifier join, alongside immutable overlay
scope. Missing or mismatched tenant context denies. A copied receipt identifier or
same-looking view UUID cannot cross tenants. The private profile is installation-
scoped, with transaction-local tenant context, not one credential/pool per tenant.

Dedicated installations and database-per-tenant deployments retain the same proof
rules. Tenant restore/import must include its expectations, revisions, bindings and
seals consistently and validate destination installation/module identity. Renaming
tenant IDs or importing into another lineage requires reviewed re-publication from
fresh admitted composition, not rewriting authentic evidence in place.

## Security and confused-deputy analysis

The sole assertion authority is the protected executor acting on the existing catalog.
SQL origin separation authenticates its projection; exact equality authenticates the
actual persisted set relative to that projection. Metadata cannot author both sides.
An expected count/hash in a Metadata-writable column, GUC module identity, reusable
opaque token, or SECURITY DEFINER wrapper around caller expectations is explicitly rejected.

The executor must derive tenant/context from issued invocation, select the approved
view/owner sources itself and reject caller-selected issuer, expected list, SQL or
privileged delegate. Requested UI content remains untrusted and independently validated.
The proof cannot authorize drafts to be disclosed, grant permissions or skip final
Policy checks. Historical valid evidence is never a substitute for current authority.

Privileged DBA tampering and full kernel/issuer compromise remain trusted-tier incidents.
This does not claim cryptographic tamper evidence for an offline database file. Bounded
backup integrity and operator custody remain required. Counter/identity grant hardening
and indirect-path review are part of closing N1/M1, not optional defenses hidden outside
the audit. SQL grant denial alone also does not demonstrate complete legitimate issuance;
both adversarial SQL and supported publication must be tested.

## HA, self-hosted and air-gapped operation

Replicas agree through the same PostgreSQL constraints, durable projection version and
approved installation lineage. No instance-local secret or admission number determines
historical proof validity. Database failover/restart preserves committed evidence;
in-flight transactions retry with fresh admission after rollback/connection loss.
Rolling deployment must gate writers on mutually supported projection/schema versions.

No vendor control plane, external timestamp service, key server or online verification
service is required. Customer operators can provision, rotate, back up, restore and
audit the SQL profile locally. No extra PostgreSQL crypto extension is required by B.

## Migration and recovery

Likely future shape: a forward Metadata-owned revision after
metadata_0005_ui_binding_seals, adding immutable expected context/member storage,
proof-to-revision constraints, exact-set verifier and stricter seal/pointer/grant rules.
Actual revision and SQL object names are implementation choices, not created here.
Preserve 0003/0004/0005 and all certified historical bytes. Role provisioning is a
separate reviewed operator prerequisite; a Docker initialization script alone is
insufficient for existing volumes.

Fresh install and certified Phase 5C upgrade establish the new boundary before UI
publication is available. A retained draft without revision history can migrate without
inventing proof. A previous Phase 5D revision whose complete expected set cannot be
authenticated causes atomic preflight refusal, regardless of whether it is currently
active or its supplied rows have a 0005 seal. Do not backfill from current supplied rows,
counts or unkeyed digests, and do not silently erase that history.

Operator recovery preserves a backup/evidence export, quarantines unsupported history,
and uses a separately reviewed forward repair/re-publication procedure that derives
new evidence from current trusted composition. New publication has a new revision identity
and current Policy approval; it does not rewrite the historical record as authenticated.
Downgrade refuses retained proof/UI history or any grant transition that would restore
a writable forgery path. Replay verifies schema/role prerequisites without altering
existing proofs. Old runtimes fail closed against the tightened boundary.

| Failure | Required behavior |
| --- | --- |
| Missing/mismatched proof or unsupported proof version | Deny seal/activation and authoritative use of that revision; bounded diagnostic, no fallback. |
| Issuer credential/pool unavailable | Deny new authoritative mutations; preserve committed data. Existing validated reads may continue if their independent read path and all guards are healthy. |
| Verifier schema/grants/constraints missing or unsafe | Fail capability readiness and deny affected authoritative reads/writes/activation until repaired. |
| Backup restored without role/credential configuration | Restore/provision reviewed identities/grants before mutations; never use a more privileged fallback. No old signing key is needed. |
| Tenant restore missing expectation/member/seal data | Treat affected revision as unverifiable; refuse activation/use, restore missing coherent data or reviewed re-publication. |
| Suspected issuer compromise | Quarantine affected evidence and stop its use pending investigation; credential rotation is not retrospective validation. |

Full-instance restore includes role/grant definitions, installation lineage, schema
versions and all proof-related data in a consistent recovery boundary. Restoring to
the same approved lineage can preserve identity after validation; a divergent clone
must establish a new lineage and re-admit/re-publish rather than presenting old proofs
as fresh installation authority. No absent verifier material is silently regenerated.

## Compatibility and later-roadmap impact

| Area | Impact |
| --- | --- |
| Phase 4.5 | No UI, session, OIDC, cache or browser-authority changes. |
| Phase 5A/5B/5C | Public contracts and certified historical migrations unchanged. Shared grant/counter plumbing needs focused regression proof and no observable semantic change; any necessary public break needs separate approval/versioning. |
| Phase 5D | Supported command/query values remain compatible. Internal publication routing and forward database proof become stricter. Failed candidates with unverifiable history have the explicit refusal path above. |
| Module lifecycle/activation | Same authoritative admission/fence; no second catalog. All active complete UI dependencies must block incompatible activation, including direct-role tampering attempts. |
| SDK | No generic profile selector, privileged persistence, proof issuer or signing API. Any internal-to-public exposure proposal requires separate SDK review. |
| Phase 5E renderer | May consume the same backend-resolved contract; cannot issue/validate proofs or create authority in the browser. Not authorized here. |
| Phase 5F extended views/actions and Phase 5G Studio | Future provenance models may reuse this separation only through separately admitted, versioned owning operations; no generic executable metadata introduced. |
| Marketplace/third-party extensions | Contribute only through existing approved artifact/catalog admission. They do not receive issuer credentials or private callbacks. |
| Future Go services | Cannot mint proofs or join the private SQL profile by naming this contract. A remote issuer would require a separate authenticated service-boundary ADR. |
| Kubernetes/operator deployments | Add explicit private-profile provisioning, rotation, budgets and restore checks; no required control plane or sidecar. |

## Performance and availability

Expected publication work is bounded O(n) insertion/comparison for at most 128 unique
bindings, with deterministic ordering O(n log n). These are design bounds, not measured
latency claims. Use bulk bounded operations rather than N+1 network lookups. No signature
verification, extra database round trip to another authority, or second UOW is required.

Resolve checks the immutable completeness association/version while retaining current
composition, Identity/scope and Policy checks. It need not re-issue a projection or
contact the private issuer on every read. Reactivation verifies the retained proof and
current module/contract identities again. Migration/recovery validates the entire affected
inventory before enabling writes. There is no shared security-schema cache.

Preserve R2: counter updates use reader-compatible locks; resolvers retain KEY SHARE.
New proof rows/joins are revision/tenant-local and must not add installation-wide writer
locks across evidence/Policy waits. Activation keeps its approximately five-second bounded
database wait and clean retry. Admissions, sorted module fences, view/overlay locks and
final Policy authority retain the certified ordering. Pool waits and cancellation are
bounded; proof failure rolls back instead of polling or attempting repair in a request.

## Operational readiness and observability

Readiness follows the current active Published UI contract, consistent with local N2,
and validates the private profile, verifier version and grants when that capability is
enabled. Expose mutation-path unavailability even when existing verified reads remain
safe; deployment routing must not mislabel the whole active capability as fully ready.
Disabling it removes that capability prerequisite; request-time checks remain independent.

Use bounded codes such as completeness_missing, completeness_set_mismatch,
completeness_context_mismatch, completeness_version_unsupported, completeness_profile_unavailable
and completeness_verifier_unsafe. Record operation/issuer version and correlation identity
through existing authorized telemetry. Do not log credentials, raw documents, full proof
payloads, cross-tenant identifiers or untrusted SQL. Distinguish issuance failure,
verification refusal, timeout and operator quarantine; emit no success before commit.

## Consequences and rejected shortcuts

B adds a narrow private profile, owner-owned verifier storage and protected publication
orchestration. It trades some internal refactoring and pool/grant operations for avoiding
cryptographic extension/key lifecycle and a new online service. Schema/semantic ownership
stays in Metadata; a new SQL execution identity does not become a new compatibility authority.

It cannot be implemented safely by exposing the privileged UOW to the existing ordinary
Metadata handler, weakening RLS, accepting its expected digest, or calling a procedure that
blindly copies its rows. A projection committed separately from publication violates this
chosen design. A platform capability without SQL privilege enforcement also fails it.
These shortcuts remain rejected even if they pass the original one-binding witness.

## Implementation prerequisites

1. Independent architecture/security/owner review of this exact PROPOSED ADR, required
   role acceptance and accepted-main governance evidence. No N1 implementation before that.
2. Explicit mapping of the private executor and every allowed command/owner operation;
   prove ordinary handlers cannot acquire its connection, invoke arbitrary delegates,
   or insert expectations through another grant path.
3. Review the complete private-profile privilege matrix, RLS, counter/identity hardening,
   connection budgets and rotation/restore procedure. New privileges must not silently
   change frozen public contracts or create a privileged back door for Metadata callers.
4. Specify relational context/version invariants and canonical test vectors; preserve
   the existing admitted dependency source, not an independently maintained registry.
5. Design and review the forward migration/refusal path, package/image/provisioning
   implications and exact one-UOW integration before implementation certification.

## Audit requirements

The implementation must reproduce the six-required/one-supplied protected-role witness
and reject it at the database boundary. Add missing-one/base/dependency, same-count
substitution, duplicate, stale-generation, wrong-artifact and exact-complete positive
cases. Attempt expectation/seal spoofing, context/revision/view/tenant substitution,
role assumption, indirect grants and counter/identity tampering. The full supported
publication path must succeed, not merely reject every write.

Inject failure before/during binding creation, before/during completeness verification,
after proof/seal, around pointer/counter staging, audit/outbox and final commit. No partial
proof or authoritative state may survive rollback. Test concurrent publication/reactivation,
retirement, multi-tenant counters, cancellation, pool exhaustion/rotation, restart/failover,
unsupported version, current-generation mismatch, backup/tenant restore and downgrade refusal.

Re-run H1/H2/H3/M1/M2/M3/R1/R2/R3 and N2, including Tenant B resolution during Tenant A's
audit/outbox/Policy/pre-commit pauses and activation timeout/retry. Full repository gates,
fresh exact-head hosted CI and independent implementation audit remain mandatory. This
proposal provides no test result or implementation certificate for the selected design.

### Acceptance questions and proposed answers

| Question | Proposed answer |
| --- | --- |
| 1. Who asserts the complete set? | Kernel-private executor using the existing retained admitted catalog and approved Metadata composition. |
| 2. Why can Metadata SQL not forge it? | Distinct authenticated SQL profile owns expectation insertion; no membership, credentials, generic callback or indirect write path is exposed. |
| 3. Which facts are authenticated? | Version/purpose, lineage, tenant/view/overlay/revision/scope, document/compatibility digests, full module set, declarations and schema/UI generation context described above. |
| 4. How is exact equality defined? | Unique typed tuples; deterministic canonical ordering; bidirectional missing/extra/mismatch comparison, never count alone. |
| 5. How is replay prevented? | Immutable exact-revision context, uniqueness and current-state checks; no reusable bearer receipt. |
| 6. How is tenant substitution prevented? | Tenant-bound composite identities, FORCE RLS and trusted transaction context. |
| 7. How is revision/view substitution prevented? | Full context/header links and immutable verifier association. |
| 8. How does HA verification work? | Shared PostgreSQL evidence/constraints and compatible profile/schema versions, not process-local secrets. |
| 9. How does rotation work? | Bounded protected-pool credential replacement; durable proof validity is independent of the old password. |
| 10. What follows restore? | Validate coherent proofs, lineage, roles and schema; quarantine incomplete/divergent history and re-publish only through reviewed recovery. |
| 11. What if verifier material is unavailable? | Deny affected activation/use; missing issuer credential separately blocks new mutations without fabricating proof. |
| 12. Can old proof authorize a new incompatible generation? | No; current artifact/contract checks and activation bindings remain mandatory. |
| 13. Can a privileged DBA forge evidence? | Yes; a fully privileged DBA is a trusted installation tier, outside this SQL-principal guarantee. |
| 14. Is vendor connectivity required? | No. |
| 15. Are R2/H1/H3 preserved? | Required by unchanged lock/admission/Policy-through-completion semantics and permanent witnesses; implementation must prove it. |
| 16. How does migration avoid invented provenance? | Refuse unverifiable candidate history; add forward proof/grant structures; only new trusted publication can establish new evidence. |

## Approval questions

The architecture/owner decision is whether to accept B's distinct private publication
profile and executor, including the required grant/counter review and one-UOW boundary,
instead of introducing cryptographic receipts. Security/Migration/Release reviewers must
approve the associated provisioning and restore/refusal policy. No unresolved algorithm
choice is delegated to implementation because B selects no cryptographic receipt.

ADR-024 architecture is owner-accepted for narrowly bounded N1 implementation.
Phase 5D remains NOT CERTIFIED. PR #67 remains draft and unmerged.
