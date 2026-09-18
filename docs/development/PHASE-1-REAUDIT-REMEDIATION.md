# Phase 1 Independent Re-audit Remediation

## Scope and provenance

- Repository: `sahinkhan/businessos`
- Branch: `fix/phase1-reaudit-remediation`
- Authoritative starting `main`: `1decf4b030ce0663632d298b70dc5c290970ca88`
- First-remediation audit head: `306dfafba7e5abdccbf13889258b32875bfa4704`
- Second-remediation implementation commit: `c76445ceec9531f4c6bad18eb4841974f2e756e3`
- Implementation exact-head CI: `35375774996` - PASS
- Status: **READY FOR INDEPENDENT PHASE 1 RE-AUDIT**
- Scope exclusions: PR #9 and `fix/phase4.5-certification`, Phase 4.5 production code,
  Phase 5, historical tags, public SDK exports, and all migrations.

The evidence commit follows the implementation commit. Final PR-head identity and its CI run are
therefore external review evidence rather than a self-referential value embedded in this file.

## Original findings and first remediation

### Shipped ASGI startup could not satisfy required infrastructure capabilities

The discovered Phase 1 proof module requires `object-storage`, but the shipped ASGI composition
supplied no provider and failed during startup. The application now composes the existing
S3-compatible provider from validated settings. Development may provision its configured bucket;
production remains fail closed. A real lifespan test verifies startup, readiness, and shutdown
against PostgreSQL and object storage.

### Upgrade planning validated only selected targets

The coordinator now snapshots the complete installed manifest set, substitutes every proposed
target, performs compatibility and downgrade checks, then validates and topologically orders the
complete proposed graph. Permanent tests cover unchanged dependents, missing dependencies, cycles,
ordering, multi-target upgrades, invalid targets, downgrades, and compatibility constraints.

### Dependency injection permitted lifetime capture and duplicate request construction

Singleton construction now rejects request-scoped dependencies through direct and arbitrary
transient chains. Request dependencies use per-key single-flight resolution with shared results,
retryable failures, cancellation-safe waiters, scope-local caches, and close-time cancellation.

### Migration subprocess typing was platform-specific

The migration runner now depends on a private structural connection protocol rather than a
platform-specific multiprocessing class. CI includes native Windows Python 3.13 repository-wide
mypy.

## Independent re-audit result and second remediation

The independent re-audit confirmed the first remediation, then found three P2 request-lifecycle
regressions. All three were reproduced before the second production change.

### Transient-crossing concurrent cycles could deadlock

The request wait graph recorded only the immediate waiter and lost complete ancestry when a
request initializer crossed transient dependencies. Concurrent `REQUEST A -> TRANSIENT T ->
REQUEST B -> REQUEST A` resolution timed out instead of failing.

The wait graph now records the complete active dependency chain propagated through each initializer
task's copied context. Its reference-counted edges include request, transient, and relevant nested
provider nodes. Before waiting on an existing flight, every ancestry edge is inserted and checked;
an edge that closes a cycle raises deterministic `ConfigurationError` with the dependency path.
Independent concurrent dependencies and valid diamonds do not create false cycles.

### Request resources could exit in an incompatible Context

Request providers entered async context managers inside owned initializer tasks but stored all exit
callbacks in a shared stack closed by the request caller. A context manager that reset a
`ContextVar` token during exit therefore failed because entry and exit ran in different contexts.

Every request-lifetime acquisition now has one resource owner containing its own copied `Context`
and `AsyncExitStack`. That owner controls provider invocation, context-manager entry, publication,
and exactly-once exit. Teardown creates the exit task with the same context object used for entry.
Owners are retained in acquisition order and closed in reverse order. Cleanup errors are collected
without skipping remaining owners.

### Repeated cancellation could abandon teardown

Request teardown previously ran in the caller task, so cancellation could interrupt cleanup and a
second cancellation could leave acquired resources live.

The scope now has explicit `NEW`, `OPEN`, `CLOSING`, and `CLOSED` states. Closing starts one owned
cleanup task, cancels and drains active initializers, closes every resource owner, clears scope
state, and rejects late publication. The caller shields that operation and continues waiting across
repeated `CancelledError`; once cleanup reaches a terminal state, cancellation is re-raised.

## Permanent regression tests

`tests/unit/test_dependency_injection_lifecycle.py` permanently covers:

- concurrent request cycles crossing one and multiple transient dependencies;
- deterministic `ConfigurationError` paths containing transient nodes;
- independent concurrent dependencies and a valid diamond graph;
- 20 concurrent request resolves with one provider call and one instance;
- ContextVar-sensitive entry and exit in one compatible lifecycle context;
- nested resources and partial provider failure cleanup;
- one, two, and five teardown cancellations;
- reverse teardown of multiple resources under cancellation;
- cleanup continuation when one resource exit fails;
- close during initialization and rejection of late publication.

The existing DI suite continues to cover singleton cycles, singleton lifetime rejection through
transient chains, request isolation, waiter cancellation, retry, and container cleanup.

## Validation evidence

The implementation exact-head CI run `35375774996` completed successfully on
`c76445ceec9531f4c6bad18eb4841974f2e756e3`.

| Gate | Result |
| --- | --- |
| Focused DI regressions | PASS - 39 |
| Ruff formatting | PASS - 164 files |
| Ruff lint | PASS |
| Linux mypy | PASS - 163 source files |
| Windows Python 3.13 mypy | PASS - exact-head CI |
| Pyright | PASS - 0 errors, 0 warnings |
| Unit tests | PASS - 194 |
| Test collection | PASS - 259 collected |
| PostgreSQL/provider integration | PASS - 52 |
| External module conformance | PASS - 13 |
| Installed-wheel migration smoke | PASS |
| Development image build | PASS |
| Production image build | PASS |
| Migration-smoke image build | PASS |
| Production-derived migration upgrade/replay | PASS |
| Web typecheck, lint, and format | PASS |
| Web unit tests | PASS - 16 |
| Web accessibility tests | PASS - 3 |
| Web production build and bundle budget | PASS |
| Real shipped ASGI startup/readiness | PASS in integration suite |
| Committed patch whitespace | PASS |

The combined Python 3.13 suite truthfully reports **257 passed and 2 failed**. The two failures are
the previously documented order-dependent logging-capture tests:

- `test_server_errors_and_logging_do_not_expose_exception_secrets`
- `test_event_worker_child_redacts_unexpected_exception_details`

Both reproduce on the baseline SHA and pass in their prescribed isolated unit job. New failures
caused by this branch: **0**. The combined suite is not represented as fully passing.

## Downstream regression classification

- Phase 2: **TARGETED REGRESSION COMPLETE** through unit, integration, and public-boundary tests;
  no contract change.
- Phase 3: **TARGETED REGRESSION COMPLETE** through unit and public-boundary tests; no contract
  change.
- Phase 4: **TARGETED REGRESSION COMPLETE** through unit, integration, authorization, audit, and
  public-boundary tests; no contract change.
- Phase 4.5: **TARGETED REGRESSION REQUIRED when PR #9 resumes**. Its unmerged authentication and
  web-session code is absent from this branch's authoritative base. PR #9 and its worktree remain
  untouched.

## Compatibility and data impact

- Public SDK exports changed: **NO**.
- Public contract versions changed: **NO**.
- Database schema changed: **NO**.
- Alembic revisions changed: **NO**.
- Runtime migrations changed: **NO**.
- Historical tags changed: **NO**.
- Phase 5 started: **NO**.

This remediation corrects Phase 1 runtime behavior without rewriting certified history or claiming
Phase 1 certification. Independent review remains the acceptance gate, and PR #11 remains open and
unmerged.
