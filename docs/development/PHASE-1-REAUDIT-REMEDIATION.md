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

## Tenth remediation: fresh full-audit concurrency and cancellation findings

The fresh full audit of `61641bd4aa6a1fdd9419622241b4804aceec622f` found three P2
failures in adjacent concurrency schedules. This remediation closes all three without changing
public SDK exports, public contract versions, migrations, or database schemas.

Singleton-owned transient resources now receive a dedicated framework owner task and copied
context. The acquiring singleton retains that exact owner in its dependency graph, validates its
registration and generation before delivery, and closes and drains nested transient owners in
reverse acquisition order. Resource entry and exit therefore run in the same concrete task and
context even when a singleton provider resolves dependencies through `asyncio.gather()`.

Completed singleton attempts are retained for shutdown reporting only when they carry cleanup
evidence. A cleanly unwound provider failure is removed from the active flight and its task,
future, traceback, and provider locals can be reclaimed; initializer and finalizer failures remain
aggregated during container shutdown.

The completed-handler ASGI branch now consumes the handler's terminal outcome after draining the
disconnect watcher. If caller cancellation arrives during that drain, a completed non-cancellation
failure is logged with trusted request context and a safe error type before caller cancellation is
preserved.

Permanent regressions cover parallel ContextVar and AnyIO resource affinity, forty failed
singleton retries with weak-reference-observable payloads, and repeated cancellation during
watcher cleanup after an already-completed handler failure.

## Fresh full-audit remediation local validation

| Gate | Result |
| --- | --- |
| Fresh independent DI matrix | PASS - 75/75 |
| Fresh independent minimal DI diagnostics | PASS - parallel affinity; 0/40 retry payloads retained |
| Fresh independent HTTP matrix | PASS - 4/4 |
| Focused lifecycle and application regressions | PASS - 78 |
| Unit suite | PASS - 236 |
| Test collection | PASS - 303 collected |
| External-module conformance without configured database | PASS - 9; 5 database cases skipped |
| Ruff formatting and lint | PASS |
| Python 3.13 mypy | PASS - 163 source files |
| Pyright | PASS - 0 errors, 0 warnings |

The complete provider-backed integration suite requires the Linux CI execution environment. A
native Windows attempt reached the migration subprocess but did not produce a terminal result and
was stopped; no product assertion failure was observed. Exact-head CI remains required for the
full integration, conformance, wheel, image, migration-replay, Windows typing, and web gates.

These results establish a new candidate for independent full Phase 1 re-audit. They do not certify
Phase 1 or authorize merging PR #11. PR #9 remains untouched and on hold; Phase 5 remains
unstarted.


## Tenth remediation: retained dependency graphs and HTTP cancellation drains

The full independent audit of `133ada1d3c9eaf5cd3166f1092189cf3989e8e1c` found four
remaining P2 blockers. Parent resources did not validate retained singleton dependencies or
singleton-owned transient registrations, completed failed singleton initializers could lose their
cleanup errors, and outer ASGI cancellation could both discard handler unwind failures and interrupt
cleanup under repeated cancellation.

Every request or singleton owner now retains concrete links to the exact registrations and owner
instances acquired while its provider runs. Validation recursively checks those links before
publication, first delivery, and cached delivery. Singleton-owned transient links retain their exact
registration even though their cleanup remains correctly tied to the singleton's task-affine exit
stack. This rejects failed, finalized, removed, or replaced dependency graphs without invalidating
an unrelated healthy instance.

Completed unpublished singleton owners remain available to terminal cleanup until their unwind
evidence is collected. A provider's original initialization failure still reaches its resolver,
while a later cleanup failure is preserved for container or generation teardown aggregation.

The HTTP runtime now cancels each owned handler and disconnect watcher once, then shields and drains
their terminal outcomes. Repeated cancellation of the outer ASGI task cannot re-cancel a running
handler finalizer. Cancellation is still propagated to the caller after cleanup completes, and any
non-cancellation unwind failure is recorded with trusted correlation, trace, and tenant context;
exception text remains excluded from the diagnostic.

Permanent regressions cover request and singleton parents, first and cached singleton-child
delivery, request/singleton/transient generation removal edges, completed failed singleton unwind,
single outer cancellation, and repeated outer cancellation.

## Tenth-remediation local validation

| Gate | Result |
| --- | --- |
| Fresh independent DI probe | PASS - 28/28 |
| Fresh independent DI race probe | PASS - 5/5 |
| Independent HTTP/proof probe | PASS - 3/3 |
| Focused lifecycle and application regressions | PASS - 74 |
| Unit suite | PASS - 232 |
| Test collection | PASS - 299 collected |
| Ruff formatting and lint | PASS - 164 files |
| Python 3.13 mypy | PASS - 163 source files |
| CI-equivalent Pyright source check | PASS - 0 errors, 0 warnings |

Exact-head CI and a fresh independent full Phase 1 audit remain required. These results do not
certify Phase 1 or authorize merging PR #11. PR #9 remains untouched and on hold; Phase 5 remains
unstarted.

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


## Ninth remediation: full Phase 1 certification findings

The full independent audit of `65684ccbffff68ee667835a1c60884f1c8aff1b7` superseded the
earlier narrow acceptance result. It identified eight Phase 1 P2 findings and one missing external
proof demonstration. This bounded remediation addresses that complete set without exempting
findings that were already present on the branch base.

Singleton resources now remain in one framework-owned task and copied context from acquisition
through release. Container shutdown and module-generation removal shield and drain owned cleanup,
preserve real initializer and finalizer errors, validate the exact registration and generation
before and after awaited delivery, and reject cycles using the full dependency ancestry. Permanent
regressions exercise ContextVar and AnyIO task affinity, initializer unwind failures, repeated
shutdown cancellation, generation-drain delivery, and a singleton cycle through transient
dependencies.

Migration logging preserves existing runtime loggers. Framework HTTP failure logging temporarily
binds the trusted response context so correlation, trace, and tenant fields survive handler unwind
without including exception text. Disconnect handling distinguishes ordinary handler cancellation
from a real cleanup failure and records the latter with the same safe contextual fields.

The external proof module now registers and consumes a typed, request-scoped dependency through the
published SDK and verifies its lifecycle and removal. The Phase 1 roadmap, full-system gate, and
development architecture now consistently define its UI proof as a versioned declarative metadata
contribution. Executable shell rendering remains assigned to Phase 4.5 and the metadata-driven
renderer to Phase 5.

## Full-audit remediation local validation

| Gate | Result |
| --- | --- |
| Full auditor probe set on Windows Python 3.13.15 | PASS - 11/11 |
| Focused dependency/application regressions | PASS - 90 |
| Unit suite | PASS - 222 |
| Linux PostgreSQL proof-module conformance | PASS - 3/3, 0 skipped |
| Linux integration and conformance without optional provider services | 60 passed; the only failure and six skips require Redis, NATS, or S3 test endpoints |
| Same-process Linux migration/logging probe | PASS - 3/3 |
| Ruff formatting and lint | PASS - 164 files |
| Python 3.13 mypy | PASS - 163 source files |
| CI-equivalent Pyright source check | PASS - 0 errors, 0 warnings |
| Test collection | PASS - 289 collected |

Exact-head CI remains required for the complete provider-backed integration suite, wheel and image
validation, production migration replay, native Windows typing, and web validation. These local
results establish a candidate for a fresh independent full audit; they do not certify Phase 1 or
authorize merging PR #11.

## Full-audit remediation compatibility and data impact

- Public SDK exports changed: **NO**. The proof consumes already published dependency APIs.
- Public contract versions changed: **NO**.
- Database schema or Alembic revisions changed: **NO**.
- Historical tags changed: **NO**.
- PR #9 / Phase 4.5 changed: **NO**.
- Phase 5 started: **NO**.

## Eleventh remediation: singleton cleanup ownership and disconnect watcher outcomes

The fresh full independent audit of `7dd5ebb3add1de9b548c64b2e91ac4351eebc758`
found three P2 defects and one P3 defect in terminal lifecycle paths. A singleton parent closed
its transient children before its own finalizer ran, a failed transient attempt remained in the
parent's validity graph after the provider handled it, disconnect-watcher cleanup failures were
ignored when the request handler completed first, and nested cleanup failures could repeat the
same exception leaf in the terminal aggregate.

Singleton owners now track cleanup ownership separately from accepted dependency validity. Every
started transient remains owned and drained, including failed attempts, while only successfully
validated dependencies enter the graph used for publication and cached-delivery checks. Parent
resource finalizers run before owned transient children close, preserving usable dependencies for
flush and shutdown work. Cleanup aggregation records the identities of nested exception-group
members so the same concrete failure is reported exactly once without suppressing distinct errors.

When an HTTP handler completes first, the runtime now examines the drained disconnect watcher.
Non-cancellation cleanup failures are logged with trusted request context and their exception type;
private exception text is excluded. Successful response delivery and outer cancellation semantics
remain unchanged.

Permanent regressions cover parent-finalizer dependency use, handled transient retry and fallback,
unique nested cleanup leaves, and watcher cleanup failure after a completed handler.

## Eleventh-remediation local validation

| Gate | Result |
| --- | --- |
| Fresh independent additive DI probe | PASS - 7/7 |
| Fresh independent HTTP cleanup probe | PASS - 3/3 |
| Focused lifecycle and application regressions | PASS - 84 |
| Unit suite | PASS - 242 |
| Test collection | PASS - 309 collected |
| Ruff formatting and lint | PASS - 164 files |
| Python 3.13 mypy | PASS - 163 source files |
| CI-equivalent Pyright source check | PASS - 0 errors, 0 warnings |

The first full-unit attempt completed 233 assertions but hit eight setup errors because the global
Windows pytest temporary directory was inaccessible. The complete suite passed with an isolated,
verified worktree-local pytest base directory; the directory was removed after the run.

Exact-head CI and a fresh independent full Phase 1 audit remain required. These results do not
certify Phase 1 or authorize merging PR #11. PR #9 remains untouched and on hold; Phase 5 remains
unstarted.
