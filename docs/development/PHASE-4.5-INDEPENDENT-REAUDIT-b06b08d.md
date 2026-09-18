# Independent Phase 4.5 re-audit — b06b08d

Date: 2026-09-18.
Verdict: **CHANGES REQUIRED — not ready for merge/certification/freeze.**

Audited [PR #9](https://github.com/sahinkhan/businessos/pull/9) at `b06b08d8e29fa68b9fa9174688c03f4888361b25`.
The clean local checkout matched GitHub before this audit. PR #9 is open and unmerged, with base
`3e551b8922397e03636db8d7ed7cf85d2477db83`.

This is a new independent audit after remediation of the six findings at `09f8f5e`.
The historical independent report and its regression tests were preserved.

## Findings

### 1. P1 — Cancelling a pending scope transition only in React desynchronizes the server session

[ScopeContext.tsx:182](https://github.com/sahinkhan/businessos/blob/b06b08d8e29fa68b9fa9174688c03f4888361b25/apps/web/src/scope/ScopeContext.tsx#L182),
[response guard:153](https://github.com/sahinkhan/businessos/blob/b06b08d8e29fa68b9fa9174688c03f4888361b25/apps/web/src/scope/ScopeContext.tsx#L153),
[server rotation:354](https://github.com/sahinkhan/businessos/blob/b06b08d8e29fa68b9fa9174688c03f4888361b25/foundations/organization/src/businessos_organization/module.py#L354).

Start in company A, select B, then select A again while B is pending. retainCurrentScope
advances the generation and returns the UI to ready/A without cancelling, serializing, or
reconciling the server mutation. The B response is subsequently discarded by the generation guard.
However, the actual Organization endpoint has already changed the server session and returns a
rotated cookie. The browser processes that cookie independently of whether React accepts the
JSON response.

Consequently the UI can display A while the server session is B, and the frontend retains A's
obsolete CSRF token. Later unsafe requests can fail CSRF verification; subsequent reads can run
in B while the display still says A. This is an active business-scope correctness defect, not a
demonstrated cross-tenant authorization bypass.

**Reproduction:** a stateful adapter probe models successful server mutation before response
delivery. Observed UI company_one / csrf-a after server completion at company_two / csrf-b.
Both assertions fail. This is a React/provider test with a controlled server boundary, not a live
browser-cookie integration test. The cookie/rotation consequence follows from the linked backend
handler. Existing late-response tests assert only the old client display and do not model
server-session mutation.

**Required change:** coordinate mutating scope transitions and reconcile the authoritative
session after an already-sent operation completes. Do not treat dropping a response as cancelling
a committed backend operation. Add a browser-to-ASGI overlap test including cookie and CSRF state.

### 2. P2 — Redis activity can move idle expiry and last-seen time backwards

[web_sessions.py:614](https://github.com/sahinkhan/businessos/blob/b06b08d8e29fa68b9fa9174688c03f4888361b25/foundations/identity/src/businessos_identity/web_sessions.py#L614)
and [atomic SET:639](https://github.com/sahinkhan/businessos/blob/b06b08d8e29fa68b9fa9174688c03f4888361b25/foundations/identity/src/businessos_identity/web_sessions.py#L639).

The new Lua check accepts same-generation concurrent touches, addressing the original false
unauthenticated result. It then unconditionally stores a complete replacement calculated before
the Redis call. An earlier request delayed until after a later touch therefore overwrites the
later last_seen_at and idle_expires_at. Generation checks do not distinguish these touches.

**Reproduction:** execute production RedisWebSessionStore with a controlled command-order double.
An earlier touch is delayed; a touch ten seconds later commits; then the earlier one completes.
Both are accepted, but the final idle expiry is ten seconds earlier than the already accepted
newer expiry. The regression assertion fails. This double models the current Lua generation,
liveness, and SET contract; it does not execute Redis Lua or constitute a real Redis integration run.

**Required change:** merge activity monotonically inside the atomic operation, preserving the
current authoritative session and security generation. Check expiry/TTL behavior under deliberately
reordered and delayed touches against real Redis.

The committed real Redis test now runs 24 concurrent touches, so the requested infrastructure
test does exist. All 24 use the same requested expiry; it does not assert monotonic timestamps,
final idle-expiry/TTL values, or force this ordering. Sequential rotation/revocation checks do not
cover in-flight races with those operations.

### 3. P2 — Drawer still steals focus from controlled inputs

[Drawer.tsx:40](https://github.com/sahinkhan/businessos/blob/b06b08d8e29fa68b9fa9174688c03f4888361b25/apps/web/src/components/overlays/Drawer.tsx#L40)
and [effect dependencies:62](https://github.com/sahinkhan/businessos/blob/b06b08d8e29fa68b9fa9174688c03f4888361b25/apps/web/src/components/overlays/Drawer.tsx#L62).

Modal's onClose-ref change fixes its earlier reproduction. Drawer retains the old focus effect
depending on onClose. An inline callback changes identity on each controlled field update, causing
cleanup and initial-focus placement to run again.

**Reproduction:** focus a Drawer text field and change its value to A. The value updates, but focus
moves to Close. The regression assertion fails.

**Required change:** apply an open/close focus lifecycle to Drawer, preserving current handlers,
Tab/Shift+Tab containment, Escape, and restoration.

### 4. P2 — Reusable production controls still bypass translation resources

[ErrorState.tsx:71](https://github.com/sahinkhan/businessos/blob/b06b08d8e29fa68b9fa9174688c03f4888361b25/apps/web/src/components/feedback/ErrorState.tsx#L71),
[Spinner.tsx:29](https://github.com/sahinkhan/businessos/blob/b06b08d8e29fa68b9fa9174688c03f4888361b25/apps/web/src/components/feedback/Spinner.tsx#L29),
[SearchInput.tsx:53](https://github.com/sahinkhan/businessos/blob/b06b08d8e29fa68b9fa9174688c03f4888361b25/apps/web/src/components/inputs/SearchInput.tsx#L53),
[DataTableFilterToolbar.tsx:88](https://github.com/sahinkhan/businessos/blob/b06b08d8e29fa68b9fa9174688c03f4888361b25/apps/web/src/components/table/DataTableFilterToolbar.tsx#L88).

Navigation contributions now have translation keys, and their locale resources are tested.
However, production reusable components still hardcode Retry, Loading, Clear search, Clear all,
and other defaults. ErrorState does not consume i18n or provide an override for its Retry label.
These are reusable controls, not domain fixture text.

**Reproduction:** render ErrorState with onRetry under Spanish I18nProvider. Its button remains
Retry, although the existing common.retry resource is Reintentar. The assertion fails.

The new i18n test manually passes a translated closeLabel to Modal; that proves the prop works,
but does not establish that reusable controls broadly honor locale changes.

**Required change:** finish the requested production-control/resource audit, including accessibility
labels, table/search/filter controls, and feedback/form primitives.

### 5. P2 — Session-service failure is still presented as ordinary logout

[AuthContext.tsx:59](https://github.com/sahinkhan/businessos/blob/b06b08d8e29fa68b9fa9174688c03f4888361b25/apps/web/src/auth/AuthContext.tsx#L59),
[AuthContext types](https://github.com/sahinkhan/businessos/blob/b06b08d8e29fa68b9fa9174688c03f4888361b25/apps/web/src/auth/types.ts#L42),
[LoginPage](https://github.com/sahinkhan/businessos/blob/b06b08d8e29fa68b9fa9174688c03f4888361b25/apps/web/src/auth/LoginPage.tsx#L22).

The 401 loading bug is fixed. But reloadSession catches all other failures, including 503/network
failure and 403, and calls invalidateSession without exposing the failure. The context has no
error/status distinguishing unavailable or forbidden from unauthenticated. LoginPage has no
bootstrap-error recovery state; its local error handles only startLogin failures.

Verified by source tracing. The new unavailable-bootstrap test supplies a test-only Reload button
that calls reloadSession; it does not verify a production recovery control or error presentation.

**Required change:** retain a deliberate recoverable/service-unavailable or authorization-denied
presentation while failing closed. Preserve normal 401 handling separately, as required by the
remediation instructions and Phase 4.5 authentication/error-state requirements.

## Assessment of the previous six findings

| Previous finding | Re-audit assessment |
| --- | --- |
| 401 bootstrap stuck loading | Original reproduction fixed and passes; broader error-state gap remains in finding 5 |
| Scope initialization loop | Original loop fixed and bounded-call tests pass; overlapping mutations remain unsafe in finding 1 |
| Redis concurrent touch falsely rejected | Original reproduction fixed; real Redis concurrency coverage added; activity ordering remains incomplete in finding 2 |
| Missing active company/site labels | Original HTTP-adapter projection reproduction fixed and passes |
| Controlled Modal input focus | Original reproduction fixed and passes; sibling Drawer remains affected in finding 3 |
| Untranslated navigation/reusable controls | Navigation improved; reusable-control requirement remains incomplete in finding 4 |

## Evidence and limits

The [exact-head GitHub Actions run](https://github.com/sahinkhan/businessos/actions/runs/35305762007)
completed successfully for `b06b08d8e29fa68b9fa9174688c03f4888361b25`. Both python-quality and web-quality succeeded.
The integration step succeeded; the workflow configures BOS_TEST_REDIS_URL, starts pinned Redis,
and runs tests/integration, which includes the 24-touch test. No claim is made that green CI covers
the new failing scenarios.

Commands executed in the matching project checkout:

| Command | Result |
| --- | --- |
| npm test, before new audit tests | PASS — 19 files, 60 tests, including previous frontend regressions |
| npm run typecheck | PASS |
| npm run lint | PASS |
| npm run format:check | PASS |
| npm run build | PASS |
| npm run bundle:check | PASS — 369.50 KB JS / 3.67 KB CSS |
| python -m pytest -q tests/unit/test_web_sessions.py tests/unit/test_web_session_reaudit.py | PASS — 11 tests |
| npx vitest run tests/audit/certificationBoundaryReaudit.test.tsx | FAIL — 3 tests, reproducing findings 1, 3, 4 |
| python -m pytest -q tests/unit/test_web_session_touch_order_reaudit.py | FAIL — activity-order regression, finding 2 |
| Ruff check/format for the new Python probe | PASS after import/format corrections |

Python commands used `D:/project/python/businessos/.venv/Scripts/python.exe` with the platform,
tenant, identity, organization, policy, audit and data-governance source roots in PYTHONPATH.
The local runtime remains Python 3.12.14 rather than the required 3.13. Docker's daemon was
unavailable. Full infrastructure, deployment, and browser-to-live-IdP testing were not rerun locally.
No new dependency installation or npm audit was performed in this independent review.

The four new regression tests intentionally remain failing. Existing CI success predates these
uncommitted audit additions. This is a focused independent review, not an assurance that every
unexercised browser/deployment scenario is defect-free.

## Audit artifacts

All additions are inside `D:/project/python/businessos/.codex-worktrees/phase45`:

- `apps/web/tests/audit/certificationBoundaryReaudit.test.tsx`
- `tests/unit/test_web_session_touch_order_reaudit.py`
- `docs/development/PHASE-4.5-INDEPENDENT-REAUDIT-b06b08d.md`

No production source, migration, public contract, existing regression test, or historical audit
was changed. Nothing was committed, pushed, merged, tagged, or certified. Phase 5 was not started.

