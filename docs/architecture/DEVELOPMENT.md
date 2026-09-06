# BusinessOS Development Workflow

## Purpose

This workflow applies to human developers and Codex-assisted implementation.

## Work Unit

Do not ask an agent to "build BusinessOS" as one task.

Use bounded work units with:

- one architecture owner/context
- explicit acceptance criteria
- known dependencies
- tests
- migration/contract impact

## Standard Task Flow

1. Read root and nearest scoped `AGENTS.md`.
2. Read relevant architecture documents and ADRs.
3. Inspect current code and tests.
4. Identify bounded-context owner.
5. Identify public-contract, tenancy, security and migration impact.
6. Present a short plan for substantial work.
7. Implement the smallest coherent change.
8. Run required validation.
9. Summarize files, commands, migrations, contracts and risks.

## Git Strategy

Use short-lived branches:

```text
feat/<bounded-feature>
fix/<bounded-bug>
chore/<engineering-task>
docs/<documentation-task>
```

Do not use long-lived customer forks of protected core.

Prefer pull requests into `main` with CI and review.

## Commit Style

Use clear conventional-style prefixes where practical:

```text
feat: add tenant context resolver
fix: prevent cross-tenant cache key collision
docs: define payment provider contract
refactor: isolate organization repository
chore: update CI toolchain
```

## Architecture Decision Records

Create/propose an ADR when a change affects:

- protected kernel boundaries
- technology baseline
- tenancy/isolation model
- database ownership strategy
- public compatibility policy
- extension execution model
- security trust boundaries
- major infrastructure dependency

Implementation convenience alone is not sufficient reason to bypass an accepted ADR.

## Validation Expectations

As the repository becomes executable, CI should include:

- Ruff formatting and lint verification
- Pyright strict type checking
- architecture/import-boundary checks
- unit tests with pytest
- integration tests
- PostgreSQL migration tests
- tenant-isolation tests
- architecture/dependency-boundary tests
- API/event contract checks
- frontend typecheck/lint/tests
- secret scanning
- dependency/vulnerability scanning
- build/package validation

Never report a check as passing unless it was actually executed successfully.

## First Platform Proof

Before broad vertical development, build an external demo module that can:

- install/register
- own/create its schema through migrations
- register permissions
- expose a supported API
- contribute supported UI
- read trusted TenantContext
- publish an event
- consume an event idempotently
- use an approved provider such as object storage
- upgrade v1 -> v2
- disable
- uninstall/retire according to lifecycle rules

It must do this without modifying protected kernel source.

This is the architecture proof that BusinessOS is an extensible platform rather than a monolithic application with documentation claiming modularity.