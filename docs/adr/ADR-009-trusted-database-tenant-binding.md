# ADR-009: Trusted database tenant binding and module persistence authority

Status: Accepted — user approval in hardening task on 2026-09-07

## Current accepted rules

ADR-003 requires database-enforced tenant isolation in shared-schema deployments.
ADR-008 permits module-owned SQLAlchemy repositories and reviewed explicit SQL in
framework-owned transactions. ADR-005 requires state/outbox and inbox/subscriber
atomicity. ADR-004 reserves in-process execution for trusted modules; arbitrary
customer code belongs in isolated processes. These rules remain authoritative.

The published `TransactionalPersistence.execute(Executable, parameters)` contract
currently forwards SQL without restriction using a shared application role. RLS
policies trust `current_setting('app.tenant_id', true)`. The framework establishes
that setting through the same role and connection used by module statements.

## Observed limitation

On main `22d9a7b800a57a7b4beef3768cd85e6b3c2b4fc2`, a real PostgreSQL 17 test:

1. Commits a tenant B outbox row through the framework.
2. Opens a tenant A transaction and verifies B's row is invisible.
3. Uses only public persistence methods to execute
   `SELECT set_config('app.tenant_id', :tenant_id, true)` with B's UUID.
4. Reads B's previously hidden row in that same transaction.

The regression is
`tests/integration/test_release_hardening_tenant_binding.py`. It is deliberately
failing, not skipped or marked expected-failure: this branch is not releasable.
The harness obtains persistence from the framework UoW; the attack itself uses
only the SDK persistence protocol. It tests kernel-owned eventing data, not an
installed proof-module endpoint, and does not claim that separate proof.

A non-owner, non-superuser, NOBYPASSRLS role and FORCE ROW LEVEL SECURITY do not
protect a policy's caller-replaceable identity input. A SECURITY DEFINER setter
that accepts arbitrary tenant UUIDs from that role would have the same problem.
SQL keyword filters, resetting the setting before each statement, Python private
attributes and annotations are not database security boundaries. Arbitrary SQL
also makes hiding Python commit/rollback methods insufficient for blocker B.

PostgreSQL documents [custom two-part settings](https://www.postgresql.org/docs/17/runtime-config-custom.html)
and [SET/set_config equivalence](https://www.postgresql.org/docs/17/sql-set.html).

## Accepted decision

Replace unrestricted module SQL authority with a versioned, request-bound
persistence capability, and establish tenant identity independently of
module-controlled SQL. Retain PostgreSQL, SQLAlchemy, psycopg, Alembic, modular
monolith deployment and framework-owned transactions.

Approved implementation direction:

- Authenticate each runtime database connection as a tenant-scoped login role.
  RLS resolves immutable `session_user` through an administrator-owned tenant-role
  mapping. Runtime roles cannot modify that mapping, create roles, bypass RLS,
  assume other tenant/operations roles or replace session authorization.
- The trusted framework routes connection pools using authenticated TenantContext.
  It alone holds connection-selection authority. Pool reuse never crosses login
  identity; credential lifecycle, bounded pool cardinality and tenant retirement
  require explicit operational design before implementation.
- Replace the public generic Executable/result surface with a constrained,
  versioned repository capability: no raw SQL, arbitrary function execution,
  session/connection/result-context handles or transaction-control operations.
  Define the supported statement/expression grammar and approved database
  functions explicitly; do not implement a textual denylist. Framework-owned
  adapters retain reviewed SQL where necessary. Module mappings and migrations
  remain owned by their bounded contexts.
- Commands expose repository operations and validated event enqueueing only.
  Subscribers expose repository operations only. The framework exclusively
  claims inbox receipts and completes the transaction.
- Keep internal dependency identities, runtime registries, activation controls
  and unbound infrastructure providers outside the SDK object graph. Cache and
  object-storage capabilities bind to the same trusted request identity.

An alternative is a separately authenticated tenant-binding authority with
transaction-bound, database-verified assertions and replay protection. It needs
its own threat model, key lifecycle and transaction-binding proof; unsigned GUC
values or a UUID-taking privileged function are insufficient. This ADR does not
approve an improvised signing mechanism or PostgreSQL extension.

## Impacts

- **Tenancy:** All three deployment modes remain supported. Shared-schema
  certification depends on immutable database identity and adversarial tests.
- **Security:** Separates tenant selection from module SQL authority. In-process
  Python remains high trust, not a sandbox against arbitrary interpreter access.
  Hostile executable modules still require ADR-004 isolation. Module table grants
  and approved functions must also preserve bounded-context ownership.
- **Compatibility:** Removing generic SQL/UoW/registry access is a breaking SDK
  change. Approve a new SDK version and compatibility preflight; upgrade the proof
  package and reject incompatible modules before activation. Do not retain a
  legacy escape hatch alongside the secured surface.
- **Migration:** Add explicit migrations for the protected identity mapping and
  RLS policy changes across kernel and module-owned tables. Provision roles via
  explicit administration, never application startup. Preserve existing databases,
  data and volumes. Do not rewrite historical revisions or the Phase 1 tag.
  A downgrade restoring vulnerable policies cannot be a certified live rollback;
  define maintenance/restore behavior before implementation.
- **Later roadmap:** Tenant onboarding, worker routing, credential rotation and
  retirement must use the approved binding contract. No Phase 2 implementation or
  migration is authorized by this proposal. Large-tenant pool/resource costs need
  measurement before choosing final operational limits.
- **Performance:** Per-tenant authenticated pools introduce connection cardinality
  and provisioning costs. Benchmark bounded pooling; do not silently substitute
  SET ROLE on an all-tenant credential, which would reintroduce authority.

## Acceptance before resuming release certification

Approve the database identity design and SDK versioning plan first. Then implement
A–F together within Batch A and run every originally requested release gate:
Ruff format/lint, strict mypy/Pyright, the complete Phase 1 unit/integration/
conformance suite, real adversarial PostgreSQL tests, installed-wheel proof,
actual production Uvicorn composition, secret canaries across traceback/repr/
serialization/logging, migration upgrade/downgrade/replay and git diff --check.

Adversarial cases must include SET/SET LOCAL/set_config, RESET, role/session
changes, transaction-control SQL, function/expression escapes, context replay,
missing context, pooled-connection reuse, cross-tenant writes, inbox/outbox
atomicity and SDK object-graph authority. No passing baseline suite substitutes
for the currently failing tenant-binding gate.

Implementation and certification are tracked on the hardening branch. Acceptance
of this ADR does not certify Batch A or Phase 1. All release gates remain required.
