# Batch A architecture-stop evidence

Date: 2026-09-07
Base: `22d9a7b800a57a7b4beef3768cd85e6b3c2b4fc2`
Branch: `fix/phase1-release-hardening`
Disposition: STOPPED pending ADR-009 approval; not a release candidate.

## Repository safety

`git ls-remote origin refs/heads/main refs/tags/v0.1.0-phase1` confirmed main
at the required base and tag object `bbe7340cd4538d8a0536b145550c86cbb27ce586`.
A clean separate worktree was created with
`git worktree add -b fix/phase1-release-hardening /private/tmp/businessos-phase1-hardening main`.
The pre-existing Phase 2 checkout and branch were not switched, edited, merged or
rebased. Its observed head remains `7fd49dd1598d4072bac7ea5810157385d76b0eb2`.
No existing database or volume was used or altered.

## Changes

- Proposed ADR-009: security boundary, alternatives, SDK compatibility,
  migrations, operational costs and later-roadmap impact.
- A deliberately failing PostgreSQL security gate proving the public persistence
  tenant-setting escape. No xfail or skip was added for the vulnerability.
- This evidence record. No production runtime, contract or migration was changed.

## Executed checks

Tools ran in `bos-review-118:development`, with this worktree mounted at `/app`
and `PYTHONPATH=/app/platform/src:/app/examples/proof_module/src`, so the runtime
under test is the verified Phase 1 source, not the image's source snapshot.

- `ruff format --check platform/src examples tests`: passed, 88 files.
- `ruff check platform/src examples tests`: passed.
- `mypy platform/src tests examples/proof_module/src`: passed, 88 source files;
  repository configuration has `strict = true`.
- `pyright platform/src examples/proof_module/src tests/integration/test_release_hardening_tenant_binding.py`: passed, zero errors/warnings, strict repository configuration.
  The first network-isolated attempt could not install Node; a second isolated
  tool-container run with download access completed successfully.
- `pytest -q tests/integration/test_release_hardening_tenant_binding.py`:
  **FAILED**, one cross-tenant read after successful `set_config` replacement.
- That test executed all five Phase 1 kernel upgrades and downgrades successfully
  in its new disposable test database. This is not full migration replay proof.
- `git diff --check`: passed before staging; staged check required before commit.

PostgreSQL ran in newly created `bos-batch-a-adversarial-pg`, using
`postgres:17-alpine`, `--network none`, tmpfs database storage and no host ports or
existing volumes. The test runner shared only that container's network namespace.
Test roles were created inside that instance only. All four BOS_TEST_DATABASE
URLs targeted its loopback database and used test-only trust authentication.
The fixture created and removed only its uniquely named test database.

## Validation intentionally outstanding at the architecture stop

The complete Phase 1 unit/integration/conformance suite, installed-wheel proof,
production Uvicorn startup, secret canary scans and full migration replay have
not been run for Batch A. A–F are not remediated or certified. Existing baseline
behavior must not be treated as proof of any requested hardening guarantee.

Do not merge this branch. Freeze the pushed commit for an independent read-only
Batch A audit focused on the reproduction, ADR reasoning and safety evidence.
Resuming implementation requires acceptance of the database trust design and SDK
versioning plan under ADR-009. No Batch B, Batch C or Phase 2 work is included.
