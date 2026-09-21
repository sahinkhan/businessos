# Phase 0 architecture and governance acceptance record

Status: **Solo-maintainer governance remediation candidate; new exact-head CI, bounded independent re-audit, and owner attestation pending.** This document does not self-certify Phase 0. The earlier audited implementation SHA `9dbd5229bcc7f3f51dd27e95a3193fa90d5a4e51` and CI run `35573079236` are historical evidence, not certification of a later governance commit.

## Scope and authority

Phase 0 establishes the technology baseline, protected-kernel responsibility boundary, repository ownership, architecture decision process, development rules, compatibility and release governance. [BOS-ARCH-003](../architecture/ARCHITECTURE.md) and accepted [ADR-008](../adr/ADR-008-python-asgi-technology-baseline.md) govern Python 3.13+, the custom ASGI runtime, Uvicorn, PostgreSQL/SQLAlchemy/psycopg, explicit Alembic migrations, and the approved test/type toolchain. ADR-008 supersedes historical ADR-001; the old Go/Gin/pgx decision remains historical evidence, not active architecture.

The [canonical kernel responsibility map](../architecture/KERNEL-RESPONSIBILITIES.md) is authoritative. Shorter architecture, catalog, engineering, build, and roadmap lists describe different abstraction levels and refer to it; they must not assign feature flags or any other kernel runtime primitive to a conflicting owner. Domain policy, identity, tenant, organization, and industry logic remain module-owned.

[ADR-GOVERNANCE.md](ADR-GOVERNANCE.md) defines decision status and role approvals; [RELEASES.md](RELEASES.md) governs platform, SDK, public-contract and schema/protocol versions, exact-main release eligibility, and immutable tags; [MAINTAINERS.md](MAINTAINERS.md) and `.github/CODEOWNERS` identify accountable review and routing. [DEVELOPMENT.md](../architecture/DEVELOPMENT.md) links the ADR process. Public SDK and module contracts must respect [upgrade compatibility](../architecture/UPGRADES.md) and module-owned data boundaries. The protected kernel cannot acquire business-domain concepts or change the accepted baseline without a reviewed superseding ADR.

## Reproducible architecture gate

Run `python scripts/check_phase0_architecture.py` from any directory; it locates the repository by its script path. The CI `python-quality` job has a named **Phase 0 architecture governance gate** on Python 3.13. Focused `tests/unit/test_phase0_architecture_gate.py` checks positive, negative, historical, source-coverage, canonical-map and exit/output behavior. Existing quality, integration, conformance, migration, container and frontend jobs remain required.

The checker explicitly requires the five derived source-of-truth documents, accepted ADR-008, current governance policies, README, project/container/Compose configuration and CI workflow. It recursively discovers active architecture, governance, Codex instruction, and **all roadmap** Markdown files; it also discovers every ADR, workflows and scoped `AGENTS.md` files. Missing required sources and ADRs without one recognized status fail closed. Accepted ADR decisions are scanned as authoritative; superseded, rejected and withdrawn ADRs are classified as historical, while draft/proposed ADRs may discuss alternatives but may not claim current authority. `docs/development/` audit evidence, migrations and test fixtures remain outside the active inventory. New active-source directories or file types require review of the checker inventory. The rules classify primary Go/Gin or superseded framework declarations, unsupported Python primary/build baselines, legacy runtime paths, and canonical feature-flag ownership. This is a declared inventory/rule gate, not a claim to detect every possible paraphrase.

## Supply-chain and deferrals

The [security architecture](../architecture/SECURITY.md) and release policy require release-specific signature, checksums, SBOM, provenance, and dependency/vulnerability scan evidence for production eligibility. Complete signing/provenance automation is not claimed by this Phase 0 work; it belongs to later release/operations maturity and must be verified before an applicable production release. Phase 0 architecture consistency does not waive an actual release blocker.

Phase 1 runtime corrections, Phase 2 remediation (currently HOLD/FROZEN), Phase 3+ implementation, browser UI, branch-protection setting verification, and production artifact signing infrastructure are outside this remediation. Historical release tags and accepted ADR records are not rewritten.

## Final focused acceptance criteria and evidence procedure

An independent read-only auditor must inspect one exact final commit and verify: canonical ownership including feature flags; derived documentation consistency; accepted Python/ASGI baseline; deterministic scan with historical exemptions and active-file coverage; focused tests and CI step; ADR/release/maintainer coherence; no forbidden production, migration, contract or downstream changes. The auditor records findings and exact commands/results. Any unresolved Phase 0 architecture or gate contradiction blocks final PASS.

The candidate commit SHA is reported externally after commit creation, avoiding a self-referential file edit. Record the SHA, changed-file inventory, local validator and test outputs, exact-head CI links/results, accountable review evidence, and independent audit verdict in the PR or independent audit record. Green CI or GitHub mergeability alone is not Phase 0 acceptance. Architectural changes after acceptance require the applicable ADR and role review, not an undocumented edit to this record.

## Formal acceptance under temporary solo-maintainer staffing

Normal Phase 0 acceptance uses independent accountable human review under [MAINTAINERS.md](MAINTAINERS.md). When exactly one verified eligible human maintainer holds all applicable roles and no second eligible reviewer is available, the temporary **Solo Maintainer Exception** may instead be used for this pre-`1.0.0` baseline. It requires new exact-head CI PASS, a bounded independent technical/read-only audit PASS on the new final candidate, zero unresolved Critical and High findings, and an explicit exact-SHA attestation personally submitted by the owner. Authorship and merge action alone are not approval evidence.

The Phase 0 PR evidence must record the final candidate SHA, PR number, exact-head CI run and result, independent technical audit verdict, Critical/High counts, owner GitHub identity, and each accountable role exercised: Documentation/Governance Maintainer, Architecture Maintainer, Platform/Kernel Maintainer, and Release Maintainer. The attestation must identify the review model without claiming human independence:

```text
Review model: SOLO MAINTAINER OWNER ATTESTATION
Independent human review: NOT PERFORMED
Independent technical audit: PERFORMED
```

After valid attestation and merge, record the distinct merge/`main` SHA and post-merge evidence. An evidence-only record never replaces or relabels the audited implementation SHA. Until the owner personally attests and all gates pass, Phase 0 remains technically passed but formally pending; it is not FINAL PASS / FROZEN. Once another eligible human maintainer is formally assigned and available, this exception is unavailable. Independent human review of the accumulated protected-platform governance baseline remains required before a production-grade `1.0.0`, Stable enterprise, or LTS release unless a later accepted governance decision explicitly changes that requirement.
