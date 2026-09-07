# BusinessOS Python Development Setup

The Phase 1 runtime requires Python 3.13 or newer. Docker Compose is the supported path when the host Python version is older or when PostgreSQL, Redis, NATS JetStream and S3-compatible storage should run together.

## Repository Boundaries

- `platform/src/businessos/` contains the protected custom ASGI framework.
- `platform/src/businessos/migration_assets/` contains packaged protected-kernel Alembic
  configuration, templates and revisions.
- `examples/proof_module/` is an external package that consumes the public module SDK.
- `tests/unit/`, `tests/integration/` and `tests/conformance/` separate fast, infrastructure and external-module checks.

Do not add business-domain concepts to the protected framework.

Trusted first-party in-process modules import BusinessOS contracts only from `businessos.sdk`.
Module-owned repositories execute SQLAlchemy statements through
`HandlingContext.unit_of_work.persistence`; that adapter is bound to the active framework
transaction and intentionally exposes no commit or rollback operation.

Durable event handlers receive `EventHandlingContext`. Its persistence adapter and the framework
inbox claim share one tenant-scoped Unit of Work, so a subscriber must not open an independent
session. Command handlers only write the outbox; they never invoke subscribers directly. Providers
required by a module manifest are supplied by the distribution composition root, started before
modules, exposed through typed SDK dependency keys and included in readiness. An absent optional
provider has no startup or readiness effect, while an absent or unhealthy required capability fails
closed before the module publishes contributions.

## Docker Development

Copy `.env.example` to `.env` only when local overrides are needed. The committed Compose defaults are development-only credentials.

Start infrastructure and apply the protected runtime migration:

```bash
docker compose up -d postgres redis nats object-storage
docker compose run --rm database-bootstrap
docker compose run --rm migrate
```

Start Uvicorn with source reload:

```bash
docker compose up --build app
```

Start the standalone durable event worker after role bootstrap and migrations:

```bash
docker compose --profile events up --build event-worker
```

The development profile provisions only its local MinIO bucket. Production object-storage buckets
remain deployment-managed. The event worker is a separate process: it receives both the
`businessos_app` URL for tenant-scoped consumer transactions and the `businessos_ops` URL for
cross-tenant outbox publication. Never add the operations URL to the `app` service. Worker event
permissions are an explicit comma-separated allowlist; an empty allowlist denies every protected
subscriber. Installation and principal UUIDs identify the trusted worker service account until the
later identity foundation supplies that deployment integration. The worker's shutdown timeout
bounds each subscription, publisher, application and database cleanup step while still attempting
all later finalizers after an earlier timeout. Mandatory cleanup retains ownership until it reaches
a terminal result. The `businessos events run` supervisor provides the hard process deadline and
terminates the isolated child if an in-process dependency cannot complete cleanup cooperatively.

Verify diagnostics:

```bash
curl --fail http://localhost:8000/livez
curl --fail http://localhost:8000/readyz
curl --fail http://localhost:8000/version
curl --fail http://localhost:8000/diagnostics/modules
```

## Local Python 3.13 Environment

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --constraint requirements/constraints-py313.txt -e '.[dev,providers]'
python -m pip install --constraint requirements/constraints-py313.txt -e examples/proof_module
```

Configuration uses `BOS_`-prefixed environment variables. `BOS_DATABASE_URL` must use SQLAlchemy's `postgresql+psycopg://` dialect. Secrets belong in environment/secret providers and must not be committed.

The development database uses separate roles:

- `businessos_admin` is the local bootstrap administrator. Its credentials are supplied only to
  the explicit `database-bootstrap` operation and test-database provisioning.
- `businessos_migrator` owns the database and schema objects and is used only by migrations.
- `businessos_app` is the `NOSUPERUSER`, `NOBYPASSRLS`, non-owner application role.
- `businessos_ops` has explicit cross-tenant eventing privileges for approved operational workers; the application never uses it.

The checked-in credentials are local-development values only. Production deployments must supply these roles and credentials through deployment secrets.

### Retained databases from before role separation

Do not delete the PostgreSQL volume. Stop application traffic, retain a verified backup, start
PostgreSQL, and invoke the administrative transition with the original administrator URL:

```bash
docker compose stop app migrate
BOS_ADMIN_DATABASE_URL=postgresql://businessos:businessos@postgres:5432/businessos \
  docker compose run --rm database-bootstrap
docker compose run --rm migrate
```

The transition takes a PostgreSQL advisory lock, creates/configures the three operational roles,
transfers only the Phase 1 database/schema/table and Alembic ownership, restores exact grants,
corrects the retained inbox key, and enables plus forces RLS on all tenant-owned Phase 1 tables.
It is idempotent and prints no credentials. It is never called by web application startup. Supply
administrator and target-role passwords through deployment secrets in non-development systems.

## Required Validation

With the Compose infrastructure running:

```bash
ruff format --check platform/src examples tests
ruff check platform/src examples tests
mypy platform/src tests examples/proof_module/src
pytest --collect-only -q tests
pytest -q tests/unit
BOS_TEST_DATABASE_ADMIN_URL=postgresql://businessos_admin:businessos-administration@localhost:5432/postgres \
BOS_TEST_DATABASE_MIGRATION_URL=postgresql://businessos_migrator:businessos-migration@localhost:5432/postgres \
BOS_TEST_DATABASE_RUNTIME_URL=postgresql://businessos_app:businessos-application@localhost:5432/postgres \
BOS_TEST_DATABASE_OPERATIONS_URL=postgresql://businessos_ops:businessos-operations@localhost:5432/postgres \
  pytest -q tests/integration -m postgres
BOS_TEST_DATABASE_ADMIN_URL=postgresql://businessos_admin:businessos-administration@localhost:5432/postgres \
BOS_TEST_DATABASE_MIGRATION_URL=postgresql://businessos_migrator:businessos-migration@localhost:5432/postgres \
BOS_TEST_DATABASE_RUNTIME_URL=postgresql://businessos_app:businessos-application@localhost:5432/postgres \
BOS_TEST_DATABASE_OPERATIONS_URL=postgresql://businessos_ops:businessos-operations@localhost:5432/postgres \
  pytest -q tests/conformance
git diff --check
```

Pyright is configured as an approved secondary checker:

```bash
pyright platform/src examples/proof_module/src
```

HTTP ingress extracts W3C trace context and creates a server span. Command, query, event-consumer
and job dispatch create child spans. Outbox publication restores `traceparent` and `tracestate`
headers and always derives the tenant NATS subject from the persisted tenant UUID.
The `businessos events run` command owns publication, durable subscription, envelope validation,
commit-before-ack and redelivery. Its configuration uses the separate
`BOS_EVENT_WORKER_...` namespace so operations credentials are not loaded by the web composition
root.

Provider integration tests additionally use:

```text
BOS_TEST_REDIS_URL=redis://localhost:6379/0
BOS_TEST_NATS_URL=nats://localhost:4222
BOS_TEST_S3_ENDPOINT=http://localhost:9000
BOS_TEST_S3_ACCESS_KEY=businessos
BOS_TEST_S3_SECRET_KEY=businessos-development
```

## Migration Rules

Production schemas change only through reviewed Alembic revisions. Never call SQLAlchemy metadata `create_all` as an upgrade mechanism.

The framework migration coordinator combines protected revisions with module-owned revision locations in validated module dependency order. The proof module demonstrates a v1-to-v2 module migration without placing its revisions in the protected platform directory.

Protected and module-owned migrations are loaded from installed package resources. Every owner
declares a unique migration namespace, and graph preflight rejects revision or branch-label
collisions (including revision-to-label collisions), cycles, missing revision packages and
undeclared cross-module dependencies before opening a database connection or applying DDL.
Multiple module heads are intentional, so coordinated upgrades target `heads`; ambiguous `head`
selection is not substituted silently.

After the inventory migration is present, every installed module records an immutable historical
graph manifest containing logical package locations, distribution identity, namespace, version,
parents, dependencies, labels and revision fingerprints. Future releases may append revisions or
valid merge revisions, but may not remove or rewrite recorded history. The coordinator serializes
migration and inventory updates with a PostgreSQL advisory transaction lock and commits them
together. Current format-2 rows are validated as a strict closed structure before normalization;
empty or duplicate revision lists, incomplete or unknown manifest fields, malformed fingerprints
and any manifest/list mismatch stop the migration before database changes. Retained format-1 rows
remain readable only for their one-way promotion to the current format.

Async framework code must call `MigrationCoordinator.upgrade_async()` or `downgrade_async()` and
must not wrap the synchronous CLI methods with `asyncio.to_thread()`. The async methods own a child
process and keep it behind an explicit commit handshake. Before commit authorization, task
cancellation terminates and joins that process, confirms its PostgreSQL backend has exited, and
only then propagates `CancelledError`. After authorization, the operation waits for and returns its
durable database outcome instead of reporting cancellation that could be followed by a commit.

From any working directory, an installed environment can inspect or execute the complete graph:

```bash
businessos migrate plan
BOS_MIGRATION_DATABASE_URL=postgresql+psycopg://... businessos migrate plan --check-database
BOS_MIGRATION_DATABASE_URL=postgresql+psycopg://... businessos migrate upgrade heads
```

Build and validate clean wheel installations with `sh scripts/validate_wheels.sh`. With the
documented separated-role test environment configured, this builds and installs the wheels in a
clean Python 3.13 environment, changes to an unrelated directory, performs a real PostgreSQL role
bootstrap plus upgrade/downgrade/replay, and verifies heads and immutable inventory. CI repeats that
database proof with the production-derived `migration-smoke` image, which contains installed wheels
and no copied repository migration tree.
