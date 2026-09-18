# BusinessOS Release and Version Governance

Status: Active governance policy

## Scope

This policy governs future BusinessOS platform, SDK, public-contract, module, and release decisions. It complements the upgrade mechanics in [UPGRADES.md](../architecture/UPGRADES.md). A version number communicates compatibility; it never replaces impact analysis, review, migration planning, or certification evidence.

## Versioned surfaces

BusinessOS versions four related surfaces independently:

1. **Platform/runtime** — the protected kernel, framework runtime, distribution, and coordinated first-party release.
2. **SDK** — published module-development APIs, types, manifests, conformance rules, and tooling used by modules outside the protected kernel.
3. **Public contracts** — REST APIs, events, commands/queries exposed across ownership boundaries, provider interfaces, frontend extension contracts, and published application/module contracts.
4. **Compatibility-sensitive schemas and protocols** — database migration graphs, durable event payloads, stored metadata definitions, module manifests, CLI automation, and wire protocols.

Module package versions remain module-owned. Each module declares compatible platform, SDK, dependency, capability, and public-contract ranges in its manifest or published compatibility metadata.

## Platform and SDK version rules

After `1.0.0`, platform and SDK releases use `MAJOR.MINOR.PATCH`:

- **PATCH** contains compatible defect, security, documentation, packaging, or performance corrections. It does not require consumers to change a published integration.
- **MINOR** adds compatible capability. Existing supported integrations continue to work, and new behavior is opt-in or compatible by default.
- **MAJOR** may remove or incompatibly change a published compatibility surface after the required deprecation, ADR, migration, and release approvals.

The platform and SDK versions do not have to advance together. A runtime-only compatible fix does not force an SDK increment. An SDK change receives its own compatibility classification and version even when shipped in a coordinated platform release.

### Pre-1.0 policy

Before `1.0.0`, platform and SDK versions use `0.MINOR.PATCH`:

- **PATCH** is limited to compatible fixes and compatible documentation, security, packaging, or operational corrections.
- **MINOR** adds compatible capability or carries an explicitly approved compatibility evolution that cannot be represented as a patch.
- A published or frozen contract is not allowed to break silently because its version is below 1.0. An incompatible pre-1.0 change requires impact analysis, an ADR when architecture or a public contract is affected, a migration or coexistence plan where applicable, downstream regression review, release approval, and clear release notes.

When an incompatible public contract can be versioned independently, BusinessOS introduces a new contract major and supports coexistence rather than using a platform `0.MINOR` increment as permission to replace the old contract in place.

## Public contract evolution

The bounded-context owner and SDK/Contract Maintainer jointly classify every public-contract change:

- **Additive compatible change** — adds optional fields, operations, event types, capabilities, or behavior that old consumers can safely ignore. It may retain the current contract major and must include compatibility tests.
- **Deprecation** — retains the old behavior while documenting the replacement, first deprecated release, migration guidance, support window, and earliest removal release.
- **Incompatible change** — removes, renames, narrows, changes required semantics, or requires an existing consumer to change. It requires a new contract major or explicit version-negotiated protocol, an ADR, compatibility and security impact review, and a migration/coexistence plan.

The owner of the published contract owns its version bump, compatibility tests, deprecation record, and consumer migration guidance. Consuming modules must declare supported ranges and must not claim compatibility they have not tested.

Unless a longer promise is published, a deprecated contract remains supported through at least the next stable platform minor release after its replacement becomes available. Removal is permitted only when:

- the earliest removal release has arrived;
- supported consumers have a documented migration path;
- required coexistence and regression evidence exists;
- the owning domain, SDK/Contract Maintainer, and Architecture Maintainer approve; and
- release notes identify the removal and affected compatibility ranges.

An urgent security or legal exception may shorten a window only with Security Maintainer and Release Maintainer approval, a written rationale, and the safest available mitigation or migration path.

Protocols that support negotiation must reject unsupported versions explicitly. Older versions remain available only for their published support window; negotiation does not imply indefinite support.

## Schema and protocol compatibility

Database changes follow reviewed Alembic migrations and expand-contract evolution. A release that changes stored data or a durable protocol records forward compatibility, mixed-version behavior, rollback or restore strategy, and replay/idempotency impact. Irreversible changes require tested restore or forward-repair evidence; a database downgrade is not implied.

Published event schemas, stored metadata, module manifests, CLI automation, and frontend extension contracts follow the same additive/deprecation/incompatible classification as other public contracts.

## Release channels

- **Development** is an integration state for maintainers. It has no production support promise and may contain incomplete work behind explicit gates.
- **Preview** is an evaluation release with identified scope and known limitations. Compatibility intent is documented, but production support and long support windows are not implied.
- **Stable** has passed the applicable certification and release gates in this policy and is eligible for its documented production use.
- **LTS** is reserved for a stable release with an explicitly published support window, maintenance scope, and upgrade path. BusinessOS does not claim an LTS guarantee until that release-specific policy exists; the mature LTS program remains a Phase 40 deliverable.
- **Security-only maintenance** may be offered for a specifically documented stable or LTS line. It does not arise automatically from the channel name.

## Release eligibility

A commit is eligible to be released only when the Release Maintainer records that all applicable gates are satisfied:

- required pull-request and exact-head `main` CI is green;
- the affected phase, module, or bounded work unit has the required certification evidence;
- formatting, linting, typing, tests, security checks, packaging, and conformance gates required by repository policy pass;
- public-contract compatibility has been classified and reviewed;
- migration graph, upgrade, replay, mixed-version, restore, or forward-repair evidence exists when applicable;
- cross-tenant, authorization, identity, secret, and supply-chain blockers are resolved or the release is rejected;
- known non-blocking limitations and security advisories are recorded;
- release notes or a changelog describe changes, deprecations, migrations, compatibility ranges, and operator action;
- required accountable reviewers approved the change under [MAINTAINERS.md](MAINTAINERS.md); and
- the exact commit SHA to tag is recorded after post-merge verification.

Known release blockers cannot be waived informally. A proposed exception must name the risk, affected users, mitigation, expiry, and approving roles. Cross-tenant exposure and unresolved critical security defects remain release-blocking.

## Release approval matrix

| Release scope | Required accountable approval |
| --- | --- |
| Compatible documentation or patch release | Release Maintainer and owning area maintainer |
| Normal stable release | Release Maintainer and owning area maintainer |
| Protected kernel/runtime release | Release Maintainer, Architecture Maintainer, and Platform/Kernel Maintainer |
| Security-sensitive release | Release Maintainer and Security Maintainer, plus the owning area maintainer |
| Public SDK or contract-breaking release | Release Maintainer, Architecture Maintainer, SDK/Contract Maintainer, and every affected owning-domain maintainer |
| Migration or data-ownership-sensitive release | Release Maintainer, Migration Safety Reviewer, and affected owning-domain maintainer |
| LTS designation | Release Maintainer and Architecture Maintainer under a separately published support policy |

One person may hold multiple roles while the maintainer group is small, but the release record must list each role being exercised. Approval means a traceable pull-request review, release approval record, or signed/attributed commit evidence; authorship alone is not an undocumented approval.

## Tag and artifact integrity

Release tags identify one exact certified commit. Annotated tags are preferred and must be pushed only after the required post-merge `main` checks and audit complete. Published tags and artifacts are immutable: do not delete, retarget, overwrite, or rebuild them under the same version. A correction receives a new version and new immutable evidence.

## Historical releases

Tags and releases created before this policy took effect remain historical records. This policy governs future release decisions and later corrective releases. Historical tags must not be deleted, retargeted, rewritten, or declared invalid solely to conform retroactively.

## Enforcement boundary

This document defines repository governance requirements. CODEOWNERS records requested ownership. It does not assert that GitHub branch protection, required-review counts, signed tags, or deployment environments currently enforce every rule. The Release Maintainer must record which controls were enforced by GitHub and which were verified procedurally for each release.
