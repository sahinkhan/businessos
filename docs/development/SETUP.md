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

## Docker Development

Copy `.env.example` to `.env` only when local overrides are needed. The committed Compose defaults are development-only credentials.

Start infrastructure and apply the protected runtime migration:

```bash
docker compose up -d postgres redis nats object-storage
docker compose run --rm migrate
```

Start Uvicorn with source reload:

```bash
docker compose up --build app
```

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

- `businessos_migrator` owns the database and schema objects and is used only by migrations.
- `businessos_app` is the `NOSUPERUSER`, `NOBYPASSRLS`, non-owner application role.
- `businessos_ops` has explicit cross-tenant eventing privileges for approved operational workers; the application never uses it.

The checked-in credentials are local-development values only. Production deployments must supply these roles and credentials through deployment secrets.

## Required Validation

With the Compose infrastructure running:

```bash
ruff format --check platform/src examples tests
ruff check platform/src examples tests
mypy platform/src tests examples/proof_module/src
pytest -q tests/unit
BOS_TEST_DATABASE_ADMIN_URL=postgresql://businessos_migrator:businessos-migration@localhost:5432/postgres \
BOS_TEST_DATABASE_RUNTIME_URL=postgresql://businessos_app:businessos-application@localhost:5432/postgres \
BOS_TEST_DATABASE_OPERATIONS_URL=postgresql://businessos_ops:businessos-operations@localhost:5432/postgres \
  pytest -q tests/integration -m postgres
BOS_TEST_DATABASE_ADMIN_URL=postgresql://businessos_migrator:businessos-migration@localhost:5432/postgres \
BOS_TEST_DATABASE_RUNTIME_URL=postgresql://businessos_app:businessos-application@localhost:5432/postgres \
BOS_TEST_DATABASE_OPERATIONS_URL=postgresql://businessos_ops:businessos-operations@localhost:5432/postgres \
  pytest -q tests/conformance
git diff --check
```

Pyright is configured as an approved secondary checker:

```bash
pyright platform/src examples/proof_module/src
```

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
collisions, missing revision packages and undeclared cross-module dependencies before applying DDL.
Multiple module heads are intentional, so coordinated upgrades target `heads`; ambiguous `head`
selection is not substituted silently.

From any working directory, an installed environment can inspect or execute the complete graph:

```bash
businessos migrate plan
BOS_MIGRATION_DATABASE_URL=postgresql+psycopg://... businessos migrate plan --check-database
BOS_MIGRATION_DATABASE_URL=postgresql+psycopg://... businessos migrate upgrade heads
```

Build and validate clean wheel installations with `sh scripts/validate_wheels.sh`. The
`migration-smoke` Docker target performs the same resource-discovery proof on top of the production
image without copying repository migration directories into that image.
