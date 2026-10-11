# Phase 5E — Form / Detail / List Rendering Prerequisites

Status: **ADR-025 Implementation Gate 1 — public contracts implemented candidate**.
The candidate is not independently audited or certified. Phase 5E-A completion is
not claimed. Phase 5E-B remains **UNAUTHORIZED**. No backend transport or React
Form/Detail/List renderer is implemented or authorized by this gate.

Protected implementation base: `d90f02efa369c9619c8c74e38f92edb58bf278ad`.
Phase 5D remains **CERTIFIED / CLOSED / FROZEN** at implementation anchor
`9236d430464191da59bef3c9df75c83f22a9ade5`. Phase 5A–5D and the Phase 4.5
foundation remain frozen; Phase 5 overall remains incomplete.

## Authority and planning reconciliation

[ADR-025](../adr/ADR-025-trusted-field-classification-authority-composition.md)
is **ACCEPTED / AUTHORITATIVE ON MAIN**. Its accepted semantic proposal is
`1070c675656ba89d8dae01d998b47b27e03201bd`. It selects Policy composition of
independently authenticated owner-field and Governance tag/control facts, with
neutral owner admission and separately reviewed private execution.

The earlier specification input at
`46b400d36c24cd51b1cf723a6fe51ba3d49f7ee7` is planning evidence only. It is not
merged implementation, accepted architecture or authority for later gates. This
canonical specification reconciles its prerequisite decisions with ADR-025;
it does not import the planning document's proposed transport, UI v2, owner
commands, cursor state, migrations or React component changes.

| Earlier planning assumption | Accepted prerequisite |
| --- | --- |
| Legacy `entity_type` / `field_name` conventions identify authoritative tags | Exact typed canonical field identity; names and legacy strings never authenticate a field |
| Existing `sensitive_field_tags` rows can supply the new binding authority | Separate canonical binding heads and immutable assignment history require a future forward Governance migration; no legacy lookup fallback |
| A reduced effective-PUBLIC flag or digest is sufficient | Independently attributed tag masking plus all applicable effective classification controls; PUBLIC still requires an explicit valid binding |
| Exact new V2 evaluator bindings can provide the composed path | Explicitly enrolled `field-classification-composition.v1`, separate from unchanged `field-policy.v2` |
| Qualified string field keys can substitute for canonical identity | Exact structured locator equality, meaning and dynamic revision coverage |
| A new prerequisite ADR must be prepared | ADR-025 is accepted; only its explicitly authorized Gate 1 contracts are implemented here |

Any PUBLIC-only rendering enrollment in the earlier plan remains a future scope
proposal. It does not narrow these contracts or discard stricter masking,
restrictions, required controls or audience facts. A missing tag, a null
classification or `sensitive=False` cannot imply public access.

## Gate 1 contract ownership and supported surfaces

The additive neutral contracts are defined in
[`businessos.field_identity`](../../platform/src/businessos/field_identity.py)
and exported through the supported
[`businessos.sdk`](../../platform/src/businessos/sdk/__init__.py) surface.
The Policy-owned contracts are defined in
[`businessos_policy.field_classification_contracts`](../../foundations/policy/src/businessos_policy/field_classification_contracts.py)
and exported through the Policy package's supported public surface.

| Public contract | Owner | Gate 1 responsibility |
| --- | --- | --- |
| `CanonicalFieldLocator` | Neutral Platform/SDK | Exact tenant, canonical resource owner and immutable field identity |
| `OwnerFieldWitness` | Neutral Platform/SDK | Inert representation of owner field, record/operation, meaning and definition provenance facts |
| `FieldProviderDescriptor` / `FieldAuthorityProvenance` | Neutral Platform/SDK | Bounded registration, artifact and distinct generation descriptors for future admission checks |
| `PolicyFieldTagFacts` / `PolicyFieldTagFactsProvider` | Policy | Versioned tag-facts result and provider protocol; Governance may implement it in a later gate |
| `PolicyEffectiveClassificationControlsFacts` / provider protocol | Policy | Versioned complete effective-control result and protocol, without changing the existing reduced V2 projection |
| `FieldClassificationEnrollment` | Policy | Explicit capability, supported action/family and contract-version enrollment description |
| Bounded failure/reason codes | Contract-owning surface | Typed unavailable, mismatch, unsupported and stale outcomes; no permissive default |

New contract envelopes use version **`1.0`**. The composition capability identity
is exactly **`field-classification-composition.v1`**. These versions are separate
from resource contracts, module versions, database revisions, Policy V2 and UI
formats. In particular, resource version `1` remains exact and distinct from
`1.0`; there is no normalization, downgrade or automatic version negotiation.

These are interfaces and immutable values, not installed provider implementations
or a second resource-owner registry. The existing ADR-018 ownership boundary
remains authoritative. A descriptor does not register, admit or authenticate its
provider by itself.

## Canonical field identity

The locator preserves the exact structured tuple of:

- trusted tenant UUID;
- canonical resource namespace and exact resource contract version;
- resource owner module identity;
- immutable field UUID;
- field contract identity and exact field contract version;
- applicable dynamic definition UUID and dynamic type UUID.

Fixed fields have no dynamic identity members. Definition-backed fields retain
their definition identity; a dynamic type identity requires the corresponding
definition identity. The admitted field family determines the applicable dynamic
combination. Invalid or ambiguous combinations fail validation.

Tenant/owner/resource mismatches, malformed identifiers or versions and conflicting
identities are rejected. The same display name or UUID-shaped selector cannot
collapse distinct canonical resource/definition/type identities. Field labels,
translation keys, SQL columns and legacy `entity_type` / `field_name` strings are
not identity sources. A fingerprint may identify canonical bytes; it cannot
replace tuple equality or certify origin.

Validation proves representation consistency only. A caller constructing a
well-formed locator cannot manufacture the trusted tenant or resource owner. Live
context equality and admission remain mandatory future runtime checks.

## Owner witness and admission boundary

The neutral witness representation carries the locator, field existence and
lifecycle, supported operation, applicable resource/record binding and field
meaning fingerprint. Dynamic fields retain immutable definition/revision/schema
pins and the definition owner separately from the resource/value owner where
those owners differ.

Provider provenance describes the registration, approved artifact and process
contribution generation separately from durable activation/fence identity. A
future issuer must authenticate every participating owner and bind the witness
to the active request, trusted tenant, invocation, transaction and admission.

**Gate 1 values are inert and unissued.** Constructing, copying or deserializing
`OwnerFieldWitness`, a provenance descriptor, a signature-like string or a digest
does not produce trusted authority. This gate adds no privileged issuer, admission
resolver, database lock, activation lookup or invocation token. Future kernel
issuance and same-UOW authentication remain Gate 2 and later work.

Public serialization exposes no database handles, connection information,
invocation capabilities or privileged generation objects. Serializable generation
descriptors remain evidence values; they are not admission capabilities.

## Policy tag and effective-control contracts

Tag facts represent the exact tenant and canonical field identity, stable binding
identity, binding version/generation, qualified classification reference,
tag-specific masking, effective interval and current/lifecycle state. Dynamic
coverage and owner/provider provenance remain explicit. The current binding's
coverage must match the field's admitted contract, meaning and retained revision;
a historical schema pin cannot select a historical tag epoch.

Effective-control facts independently represent the qualified classification
reference, definition version, effective overlay version/provenance, effective
interval, sensitivity, mandatory masking, required controls, restrictions and
allowed audience. Unsupported or missing controls cannot be projected away or
interpreted as unrestricted access.

These protocols and results are **Policy-owned**. Governance may later implement
them using its own canonical binding and classification authority. Policy does
not import Governance implementation or inspect Governance tables. No contract
combines the independently attributed owner witness and tag source into a
Governance-issued authorization receipt.

No provider is installed and no Policy evaluator consumes these results in this
gate. Existing `PolicyClassificationFactsProvider`, `field-policy.v2` behavior and
owner-origin `field_classifications` retain their exact existing meanings.

## Enrollment, failures and compatibility

Enrollment explicitly identifies the new capability and its supported versions,
resource family and operations. Unknown versions or unsupported enrollment fail
safely. The contract provides no automatic enrollment and no fallback path to
legacy V2, an unclassified field, a UI declaration or a cached decision.

Bounded failures cover owner/field unavailable, retired field, field/tenant/owner
identity mismatch, definition/revision mismatch, tag unavailable, coverage
mismatch, classification unavailable, provider mismatch, unsupported contract
version or capability/enrollment, and stale authority/provenance. Failure values
never imply PUBLIC or a permission grant. This gate implements their typed
representation, not a runtime authorization or recovery engine.

Public contract models are frozen, validate exact UUID/string/version bounds and
reject unknown authority-bearing properties. Their typed serialization is
deterministic and conformance-tested. Any compatible extension receives explicit
version review; unknown versions cannot silently enter an existing schema.
Deserialization preserves values only, never live authority.

Dependency direction remains:

```text
Party / Metadata -> neutral Platform/SDK field contracts
Governance -> Policy-owned tag/control contracts
Policy -> neutral Platform/SDK field contracts + Policy-owned protocols
```

There is no new Party -> Governance dependency, Policy -> Governance implementation
dependency, arbitrary provider registry or duplicate owner registry. Party
sensitive redaction remains an independent floor; a classification or composition
result cannot weaken it.

## Prerequisite and implementation matrix

| ADR-025 gate | Current status | Remaining evidence / authorization |
| --- | --- | --- |
| 1. Public identity/witness/tag/control/enrollment contracts | Implemented candidate only | Focused tests, complete repository CI, independent exact-candidate audit and subsequent governance acceptance |
| 2. Trusted owner field admission/issuance | NOT IMPLEMENTED / UNAUTHORIZED | Exact fixed/dynamic owner witnesses, current admission and forged/stale/retired negative certification |
| 3. Governance canonical resolver | NOT IMPLEMENTED / UNAUTHORIZED | Stable heads, immutable history, current coverage and no legacy fallback |
| 4. Policy composition | NOT IMPLEMENTED / UNAUTHORIZED | Independently authenticated join, current controls, actual field permissions and distinct read/commit evidence |
| 5. Private execution, grants and RLS | NOT IMPLEMENTED / UNAUTHORIZED | Fixed admitted per-family adapters, opaque caller transaction and least-privilege inventory |
| 6. Forward Governance migration / conversion | NOT IMPLEMENTED / UNAUTHORIZED | Explicit owning migration, retained upgrade/replay, source/wheel equality and destructive downgrade refusal |
| 7. Concurrency and lock ordering | NOT IMPLEMENTED / UNAUTHORIZED | Complete lifecycle -> owner -> binding -> classification -> Policy protocol and completion/time-bound checks |
| 8. Party/custom-entity operation integration | NOT IMPLEMENTED / UNAUTHORIZED | Separate enrollment, same-UOW operation proofs and frozen owner/redaction regressions |
| 9. Phase 5E projection, transport and rendering | NOT IMPLEMENTED / UNAUTHORIZED | Cleared prerequisites, ADR-024 compatibility admission and separate explicit authorization |

**Gate 1 requires no database migration.** It adds no persistent state, DB roles,
grants, RLS, private execution profile, field-tag conversion or owner mutation.
Canonical Governance authority requires future storage work under Gate 6; that
requirement does not authorize allocating a revision now.

ADR-024 remains separate authority for published UI compatibility/completeness.
A literal field-composition contract name in metadata is not proof of provider
admission or current field authorization. No UI declaration, resolver or proof
model is changed by this candidate.

## Validation and candidate evidence

Permanent tests cover locator validation and identity separation, dynamic identity
combinations, tenant/owner mismatch, model immutability, malformed/unknown versions,
unknown properties, deterministic serialization, contract ownership/dependency
direction, explicit enrollment/no fallback and existing Policy V2 compatibility.
Relevant SDK, Policy, Party/Metadata and conformance regressions remain required.

Formatting/lint, canonical mypy/Pyright, Phase 0 governance and `git diff --check`
are required before freeze. Full repository CI is also required; its packaging,
integration, migration/image and frontend gates are not waived by contract-only
scope. Expensive gates follow clean focused remediation.

Test counts/results, exact candidate SHA/tree/parent, changed-file inventory and
fresh exact-head hosted CI are **PENDING** and will be recorded in the candidate
PR/report after execution and freeze. This specification claims no passing test,
independent audit, owner attestation or release. Existing ADR-014/015/018/022/023/024,
Policy V2, Party redaction and Phase 4.5/5A–5D regressions must remain intact.

Completion of this contract candidate does not complete Phase 5E-A or authorize
any runtime Gate 2+, backend transport or React rendering. **Phase 5E-B remains
UNAUTHORIZED.**
