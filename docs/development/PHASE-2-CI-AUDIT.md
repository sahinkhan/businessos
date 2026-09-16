# Phase 2 post-merge migration smoke audit

Audited checkpoint: `c93df4abf2687e6b15cab10126690324018809ca`.

## Finding

The migration graph is correct. `docs/architecture/DATABASE.md` explicitly requires
deterministic multiple heads. ADR-006 preserves module-owned migrations; ADR-007
requires preflighted, compatible upgrades. The Phase 1 coordinator computes heads
from revision ancestry, verifies them against Alembic, validates declared module
dependencies and persists immutable module revision inventory transactionally.

The complete graph has eleven revisions:

```text
0001_phase1_kernel
├── proof_0001 → proof_0002 → proof_0003
└── 0002_module_migration_inventory
    → 0003_migration_graph_inventory
    → 0004_strict_migration_inventory
    → 0005_durable_event_subscribers
    → tenant_0001 → identity_0001 → organization_0001
```

Therefore `organization_0001` and `proof_0003` are the correct terminal heads.
The proof branch starts at the first core revision, independently of the later
core inventory revisions and foundation chain.

The smoke verifier still expected `0005_durable_event_subscribers` and
`proof_0003`, and exactly one inventory row for the proof module. Phase 2 replaced
the former terminal core head with its foundation descendants and added three
module inventory rows. Both verifier assumptions were stale.

## Remediation

- Derive expected heads and complete module inventory from the migration coordinator.
- Require discovery of core, proof, Tenant, Identity and Organization sources.
- Compare the executed artifact's CLI plan with the expected sources and heads.
- Compare database heads exactly, rejecting missing and unexpected tips.
- Compare every module's inventory format, namespace, locations, distribution,
  revision IDs, ancestry, dependencies, labels and content fingerprints.
- Capture the build graph before wheel creation and compare it with the graph
  discovered inside the isolated wheel environment. Missing, extra or rewritten
  packaged revisions cannot silently redefine the expected graph.
- Check database preflight and inventory after both fresh upgrade and replay.

Additional discovered modules and independent heads require no revision-name edits
in the verifier. The required owner list describes the minimum artifact composition;
the build snapshot pins the complete composition and revision contents for each run.

No kernel, domain, schema, accepted migration, migration inventory implementation,
public CLI contract or Phase 3 behavior changed. No artificial merge revision or
manual Alembic version mutation was introduced.

## Regression coverage

Eighteen unit cases cover the exact Phase 1 and Phase 2 ancestry, required discovery,
valid multiple heads, missing/rogue heads and sources, missing/extra/rewritten wheel
revisions, missing/rogue/duplicate inventory owners, incomplete revision inventory,
invalid manifest data and an additional independent module head. One PostgreSQL
integration test exercises fresh upgrade, full inventory verification, downgrade and
replay with all five migration sources together. Existing retained-deployment,
isolation, authorization and module-conformance tests remain in the certification run.

## Verification environment

Verification uses the repository's Python 3.13 development image and pinned Compose
PostgreSQL, Redis, NATS and S3-compatible services. On Windows, service URLs use the
isolated `businessos-ci-audit_default` network and service hostnames. The image smoke
uses that network with `--container-host postgres`, equivalent to CI's Linux host
network topology. Target image commands execute without source mounts and from
outside the repository. The wheel gate creates a fresh virtual environment and
checks package import locations outside the source tree.

The supplied directory is a source snapshot without `.git`. A temporary clone's
index at the audited checkpoint, with this directory as its explicit work tree,
provides the diff/status checks. The initial snapshot matched the checkpoint.
No repository metadata was synthesized in the workspace and no commit was made.

## Verification results

| Command | Result |
| --- | --- |
| `ruff format --check platform/src foundations examples tests` | PASS |
| `ruff check platform/src foundations examples tests` | PASS |
| `mypy platform/src foundations tests examples/proof_module/src` | PASS |
| `pyright platform/src foundations examples/proof_module/src` | PASS; zero errors/warnings |
| `pytest -q tests/unit` | PASS; 133 tests |
| `pytest --collect-only -q tests` | PASS; 190 tests collected |
| `pytest -q tests/integration` | PASS; 48 tests on the Linux image filesystem |
| `pytest -q tests/conformance` | PASS; 9 tests |
| `sh scripts/validate_wheels.sh` | PASS; clean installed-wheel upgrade/downgrade/replay |
| `docker build --target development --tag businessos-ci-development .` | PASS |
| `docker build --target production --tag businessos-ci-production .` | PASS |
| `docker build --target migration-smoke --tag businessos-ci-migration-smoke .` | PASS |
| `python scripts/migration_database_smoke.py --image businessos-ci-migration-smoke --docker-network businessos-ci-audit_default --container-host postgres` | PASS; production-derived upgrade/downgrade/replay |
| `git diff --check` with the explicit baseline Git directory/work tree | PASS |

Ruff formatting/lint and mypy also explicitly included the changed smoke script,
which is outside the standard CI formatting/lint path list.

The first integration invocation used a Windows bind mount during concurrent image
builds and returned 43 passes and five failures: three 10-second cancellation-test
timeouts and two subsequent process-state mismatches. The unchanged full suite then
passed all 48 tests in 106.84 seconds on the Linux image filesystem. No test timeout,
assertion, migration or runtime behavior was relaxed.

## Changed files

- `scripts/migration_database_smoke.py`: generic graph, discovery and inventory checks.
- `scripts/validate_wheels.sh`: compare the installed graph with the build snapshot.
- `tests/unit/test_artifact_migration_smoke.py`: eighteen regression cases.
- `tests/integration/test_artifact_migration_smoke.py`: complete graph upgrade/replay.
- `docs/development/PHASE-2-CI-AUDIT.md`: audit rationale and certification evidence.

All available local certification gates pass. Phase 2 is eligible for final
certification after this remediation is applied and the GitHub CI run passes on
that revision. The remote branch was not modified and remote CI was not rerun.
