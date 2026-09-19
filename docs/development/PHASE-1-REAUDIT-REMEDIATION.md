# Phase 1 Independent Re-audit Remediation

## Scope and provenance

- Repository: `sahinkhan/businessos`
- Branch: `fix/phase1-reaudit-remediation`
- Authoritative starting `main`: `1decf4b030ce0663632d298b70dc5c290970ca88`
- First-remediation audit head: `306dfafba7e5abdccbf13889258b32875bfa4704`
- Second-remediation implementation commit: `c76445ceec9531f4c6bad18eb4841974f2e756e3`
- Third-remediation implementation commit: `c0ac4924fc8a75189355f468e3afa62c4584d6ea`
- Fourth-remediation audit head: `f87806c92da974f86a664cc2708bf41cc3b67788`
- Fourth-remediation implementation commit: `b20a442e6bb68f1a776255effc14bdc92e7c6d2f`
- Implementation exact-head CI: `35375774996` - PASS
- Third-remediation final-head CI: `35425280164` - PASS
- Fourth-remediation final-head CI: pending after the evidence commit
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

## Independent re-audit result and third remediation

The next independent review confirmed the prior seven remediations and found two additional P2
request-resource ownership defects at exact head
`d5122b4e541e0902b817ee88fcd671e07638117a`. Both were reproduced before the third production
change.

### Task-affine resources could exit in a different task

The second remediation preserved a copied `Context`, but it still entered a request resource in an
initializer task and exited it in a separate cleanup task. Task-affine async context managers, such
as a real AnyIO task group, reject that lifecycle with `RuntimeError` because their cancel scope
must exit in the task that entered it.

Each request resource now has one long-lived owner task. The owner enters its `AsyncExitStack`,
invokes and publishes the provider result, waits for a close signal, and exits the stack. Entry and
exit therefore execute in the same task and the same copied context. The scope stores a separate
result future so concurrent waiters can share initialization without acquiring ownership of the
resource lifecycle.

### In-flight owner cleanup failures could be discarded

When scope close cancelled an initializer that later acquired a resource, the initializer's done
callback consumed its terminal exception. A cleanup error such as `critical-close-failure` could
therefore be lost while scope close reported success.

The scope now retains every owner task through terminal teardown. Unpublished owners are cancelled
and drained explicitly; published owners are signalled and awaited in reverse acquisition order.
Every non-cancellation cleanup failure is collected once and returned in the scope's
`BaseExceptionGroup`. The result-future callback consumes initialization outcomes only and cannot
discard owner cleanup failures.

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
- real AnyIO task-group entry and exit in the same owner task;
- preservation of an in-flight owner's late `critical-close-failure`;
- reverse-order aggregation of multiple cleanup failures exactly once;
- task-affine cleanup across five repeated caller cancellations.

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

## Third-remediation local validation

The following checks ran against implementation commit
`c0ac4924fc8a75189355f468e3afa62c4584d6ea` before the evidence-only commit:

| Gate | Result |
| --- | --- |
| Focused DI regressions | PASS - 43 |
| Ruff formatting | PASS - 164 files |
| Ruff lint | PASS |
| Linux Python 3.13 mypy | PASS - 163 source files |
| Pyright | PASS - 0 errors, 0 warnings |
| Unit tests | PASS - 198 |
| Test collection | PASS - 263 collected |
| External module conformance | PASS - 13 |
| PostgreSQL/provider integration | 51 PASS; one inherited timing race passed on immediate isolated rerun |
| Development image build | PASS |
| Production image build | PASS |
| Migration-smoke image build and installed-wheel plan | PASS |
| Real shipped ASGI startup/readiness | PASS in integration coverage |
| Patch whitespace | PASS |

The broad Python run reports **261 passed and 2 failed**. Its two failures are the same
order-dependent logging-capture tests listed above and reproduced on the branch baseline. The sole
fresh-image integration-suite failure was the inherited event-delivery receipt timing race
`test_event_worker_delivers_outbox_with_nats_redelivery_and_restart_idempotency`; it passed on the
immediate isolated rerun. New branch-caused suite failures: **0**. Exact-head CI remains the
authoritative Linux, Windows, wheel, production-replay, and web gate for the final PR head.

## Independent re-audit result and fourth remediation

The independent review of exact head
`f87806c92da974f86a664cc2708bf41cc3b67788` confirmed the task-affine owner model and
identified two new P2 defects plus one inherited acceptance gap. All three were reproduced on the
audited source before this remediation.

### Published cleanup cancellation was discarded

`RequestDependencyScope._cleanup` treated every `CancelledError` from a published owner as normal
shutdown control flow. A resource that explicitly raised `CancelledError` from `__aexit__` could
therefore disappear from the final cleanup result. Resource owners now retain their exact
`AsyncExitStack` failure before task termination. Scope teardown reports that failure alongside
ordinary cleanup errors and deduplicates multiple observations of the same exception object.

### A failed published owner could leave a closed cached value

An AnyIO child failure can interrupt a long-lived resource owner and finalize the resource while
the request scope remains open. The old cache still returned that closed value. An unexpected
published-owner exit now invalidates its request cache and flight before resource finalization is
awaited. Later resolution fails closed instead of republishing or returning the finalized object,
while teardown retains the original owner failure.

### Cancelled initializer unwinding errors could remain only on abandoned futures

When request shutdown cancelled an unfinished provider and its `finally` block raised, the error
was stored only on the resolution future. With no remaining waiter, a callback consumed that future
and scope close succeeded. Owners now mark shutdown before cancellation and retain any resulting
initializer/unwinding error as a scope-owned terminal outcome. Teardown drains every owner and
aggregates those outcomes before clearing tracking state.

Permanent regressions cover:

- explicit `CancelledError` plus `RuntimeError` cleanup aggregation;
- AnyIO child failure, cache invalidation, fail-closed re-resolution, and final error retention;
- three abandoned cancelled initializers with three independently preserved unwinding failures.

## Fourth-remediation local validation

The following checks ran against implementation commit
`b20a442e6bb68f1a776255effc14bdc92e7c6d2f` before the evidence-only commit:

| Gate | Result |
| --- | --- |
| Three independent auditor defect probes | PASS |
| Focused lifecycle tests | PASS - 20 |
| Ruff formatting | PASS - 164 files |
| Ruff lint | PASS |
| Linux Python 3.13 mypy | PASS - 163 source files |
| Pyright | PASS - 0 errors, 0 warnings |
| Unit tests | PASS - 201 |
| Test collection | PASS - 266 collected |
| Database-backed conformance | PASS - 13 |
| PostgreSQL/provider integration | 49 PASS / 3 migration timing failures; failed group passed 4/4 in isolation |
| Broad Python suite | 262 PASS / 4 FAIL |
| Development image build | PASS |
| Production image build | PASS |
| Migration-smoke image build and installed-wheel plan | PASS |
| Patch whitespace | PASS |

The broad failures comprise the two independently reproduced baseline logging-capture failures and
two migration cancellation timing/process-baseline failures. All four parametrized migration
cancellation cases passed together on immediate isolated rerun before the broad run. No failure
touches the DI change, and new branch-caused committed-suite failures remain **0**. Exact-head CI
is the authoritative Linux, Windows, integration, wheel, replay, and web gate for the final PR
head.

## Second independent re-audit and fifth remediation

The independent review of exact head
`b72020c730cbcfb7b22bdba9ed849825f4a008ce` confirmed that the three fourth-remediation
reproductions pass. It found one remaining P2 path in which an AnyIO child reported started and
then failed: the owner finalized its resource before the first waiting `resolve()` resumed, but
that waiter returned the already completed result future without rechecking the owner's terminal
state. The same behavior was reproduced on the earlier `f87806c` revision, so this was an
incomplete remediation rather than a newly introduced regression.

`RequestDependencyScope.resolve()` now validates the scope and failed-owner state both before and
after awaiting container resolution. A waiter may receive a value only while its request scope is
still open and the corresponding published owner remains valid. If the owner terminates and
finalizes the resource before delivery, the waiting resolution fails closed with
`ConfigurationError`; later resolution remains rejected and scope teardown still reports the
original owner failure.

The permanent regression uses the natural AnyIO `TaskGroup.start()` path and verifies:

- the child reports started and then raises;
- the resource finalizer runs before the first waiter resumes;
- the first and later resolutions both fail closed;
- the finalized resource is never delivered; and
- teardown retains the original child failure.

## Fifth-remediation local validation

| Gate | Result |
| --- | --- |
| Independent natural AnyIO reproduction | PASS - first and later resolves rejected |
| Focused lifecycle tests | PASS - 21 |
| Ruff formatting | PASS - 164 files |
| Ruff lint | PASS |
| Python 3.13 mypy | PASS - 163 source files |
| Pyright | PASS - 0 errors, 0 warnings |
| Unit tests | PASS - 202 |
| Test collection | PASS - 267 collected |

Exact-head CI remains required for the final Linux, native Windows typing, integration, wheel,
image, replay, whitespace, and web gates.

## Third independent re-audit and sixth remediation

The independent review of exact head
`ef40d3614c25c1c6c346131f664c4948b923bfd0` confirmed the direct REQUEST first-resolver fix and
found the same failure path for default TRANSIENT resources. A failed transient owner could
finalize its value before the first waiter resumed, yet key-level validation did not identify that
non-cached owner. A REQUEST provider could consequently receive and cache the finalized transient
value. The defect was also present on `b72020c`, while the original branch base returned a usable
resource.

Request scopes now associate every initialization result future with its exact resource owner.
Container resolution validates that owner immediately after each shielded request or transient
initialization await and before delivering the value to either an external caller or a parent
provider. This instance-level validation rejects only the failed transient attempt: a later healthy
transient with the same key remains independently resolvable, and a REQUEST parent can retry and
cache that healthy value.

Permanent parameterized regressions cover direct TRANSIENT resolution and a REQUEST parent that
depends on the transient. They verify that:

- the first finalized transient is rejected before delivery;
- the parent cannot cache the failed child's value;
- a later healthy transient remains usable;
- a successfully retried REQUEST parent caches only the healthy instance;
- every entered resource exits exactly once; and
- teardown retains the original AnyIO child failure.

## Sixth-remediation local validation

| Gate | Result |
| --- | --- |
| Fresh independent correctness groups | PASS - 9/9 |
| Independent transient variants | PASS - direct, nested, and healthy controls |
| Focused lifecycle tests | PASS - 23 |
| Ruff formatting | PASS - 164 files |
| Ruff lint | PASS |
| Python 3.13 mypy | PASS - 163 source files |
| Pyright | PASS - 0 errors, 0 warnings |
| Unit tests | PASS - 204 |
| Test collection | PASS - 269 collected |

Exact-head CI remains required for integration, conformance, wheel, image, replay, whitespace,
native Windows typing, and web validation.

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


## Seventh remediation: dependency chains and generation delivery

Audit head `61f9651b51722ea2fd91c86434718e1afe699e50` retained two P2 failures:
a parent could publish a child that failed during further initialization, and a result could be
delivered after its module generation stopped. Both portable auditor reproductions now reject
resolution with ConfigurationError; neither delivers the invalid value.

Each request-owned initializer retains the exact owners acquired by its provider, including
transient instances and cached request dependencies. Publication, awaited delivery and cached reuse
validate that owner graph and its original registration/generation. Invalid cached parents are
evicted before reporting failure so a later healthy attempt can retry. Validation uses registration
identity and the original generation gate, so replacement registrations cannot authorize old values.
Resource cleanup remains on its owner task and original failures remain owned by scope teardown.

Four regression cases cover failure during parent initialization, failure after parent caching,
healthy parent retry, generation replacement, and draining during initialization. Native Windows
validation: 27 lifecycle tests, 208 isolated unit tests, 13 independent probe scenarios passed;
both additional audit reproductions reject invalid delivery. Mypy passed for 163 source files.
The final CI run is recorded externally against the final commit. These results do not constitute
independent certification. PR #11 remains unmerged, and PR #9 remains on hold.


## Eighth remediation: drain rejected resource finalizers

Audit head `a61a6d76494dfd262d55562deb8be579a66ba577` exposed an unpublished
owner already running resource cleanup after validation rejected its acquired value. Scope
teardown treated that owner as an active initializer and cancelled its finalizer.

Owners now explicitly record entry into finalization before awaiting stack exit. Scope teardown
still cancels active initialization, but drains owners already finalizing without interrupting
their cleanup. Fail-closed delivery, owner-task affinity, and original cleanup-error aggregation
are preserved. No public contract, schema, migration, or SDK export changes are required.

Four regression cases cover delayed cleanup after generation rejection, successful and failing
cleanup, and repeated cancellation of the caller closing the scope. Cleanup completes exactly
once on the entering task; the original cleanup exception remains observable.

Native Windows validation: 31 lifecycle tests and 212 isolated unit tests passed; 277 tests
collected. All 13 retained independent probe scenarios passed. Both auditor reproductions
(the normal LifecycleManager.disable path and natural child failure during parent initialization)
now report cleanup completion. Ruff formatting/lint, mypy (163 source files), and Pyright passed.
The combined broad suite was not rerun locally; its previously audited inherited logging failures
are outside this correction. Exact-head CI results are recorded externally against the final commit.

Independent acceptance remains required. PR #11 is not merged; PR #9 remains untouched and on hold.
