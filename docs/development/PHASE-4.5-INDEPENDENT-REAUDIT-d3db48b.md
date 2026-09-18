# Independent Phase 4.5 re-audit — d3db48b

Date: 2026-09-18.

**Verdict: CHANGES REQUIRED. Two P1 blockers remain; do not merge or certify Phase 4.5.**

Reviewed [PR #9](https://github.com/sahinkhan/businessos/pull/9) at
`d3db48ba9c140deca8ccd70b894e205ed65dec1d`. GitHub and the initially clean local checkout matched.
The PR is open and unmerged; its base remains `3e551b8922397e03636db8d7ed7cf85d2477db83`.
This review examines the remediation since `b06b08d`, preserves previous audit evidence,
and tests failure paths through the real frontend HTTP adapters and API client.

## 1. P1 — A queued scope request throwing an HTTP error loses the last committed server state

[ScopeContext.tsx:219](https://github.com/sahinkhan/businessos/blob/d3db48ba9c140deca8ccd70b894e205ed65dec1d/apps/web/src/scope/ScopeContext.tsx#L219)
and [catch/finally:245](https://github.com/sahinkhan/businessos/blob/d3db48ba9c140deca8ccd70b894e205ed65dec1d/apps/web/src/scope/ScopeContext.tsx#L245).

Reproduction:

1. Start in company A.
2. Request company B and queue a return to A before B completes.
3. B succeeds and rotates the server session to company B / CSRF B.
4. The queued A request returns HTTP 403.

HttpScopeAdapter propagates HTTP errors as exceptions. The worker saves B in its local
lastAccepted variable but does not commit it because another request is queued.
The exception leaves that variable's scope. The outer catch only sets an error, and finally
returns to ready using the old scopeRef. The display/session remain company A / CSRF A
while the server is company B / CSRF B.

The existing rejection test returns a successful adapter result containing valid:false.
That branch commits lastAccepted, but a real HTTP 403 or 500 does not take that branch.
The actual Organization endpoint delegates rejected authorization/query failures to framework
HTTP errors; it does not catch them and convert all denials into valid:false results.

**Evidence:** new test `keeps the last committed server scope when the queued request returns
HTTP 403` fails both assertions. Expected company_two / rotated-csrf-b; received
company_one / initial-csrf-a.

This creates misleading operational context and stale CSRF credentials. It is not evidence of
a backend cross-tenant authorization bypass.

**Required correction:** retain/reconcile the last confirmed authoritative session on exceptions,
and treat uncertain mutation outcomes as requiring session reconciliation rather than marking an
unverified old scope ready. Exercise HTTP 403, 5xx, and transport failure, including failure after
one accepted queued transition.

## 2. P1 — Logout queued after rotation uses stale CSRF and fails server revocation

[AuthContext.tsx:96](https://github.com/sahinkhan/businessos/blob/d3db48ba9c140deca8ccd70b894e205ed65dec1d/apps/web/src/auth/AuthContext.tsx#L96),
[logout:132](https://github.com/sahinkhan/businessos/blob/d3db48ba9c140deca8ccd70b894e205ed65dec1d/apps/web/src/auth/AuthContext.tsx#L132),
[session update:139](https://github.com/sahinkhan/businessos/blob/d3db48ba9c140deca8ccd70b894e205ed65dec1d/apps/web/src/auth/AuthContext.tsx#L139),
[transition coordinator](https://github.com/sahinkhan/businessos/blob/d3db48ba9c140deca8ccd70b894e205ed65dec1d/apps/web/src/api/securityTransition.ts#L5).

Reproduction:

1. Start a scope mutation that rotates the opaque server session.
2. Request logout while that mutation is pending.
3. Complete the scope mutation with a new CSRF token.
4. The serialized logout operation starts immediately after the mutation.

commitTrustedTransition schedules React session state, but ApiClient's CSRF provider still
captures the previous session until its useEffect runs. The promise-based coordinator starts
logout before that effect publishes the new token. HttpAuthAdapter.logout therefore sends
CSRF A with the newly rotated server session requiring CSRF B.

The actual [Identity CSRF middleware](https://github.com/sahinkhan/businessos/blob/d3db48ba9c140deca8ccd70b894e205ed65dec1d/foundations/identity/src/businessos_identity/module.py#L308)
and [logout handler](https://github.com/sahinkhan/businessos/blob/d3db48ba9c140deca8ccd70b894e205ed65dec1d/foundations/identity/src/businessos_identity/module.py#L414)
reject that token before revocation. AuthProvider still clears local state in finally, so the
interface can look logged out although the opaque server session was not revoked.

**Evidence:** new test `uses the rotated CSRF token for logout queued behind a scope mutation`
fails. The actual frontend API request sends initial-csrf-a instead of rotated-csrf-b.
The controlled backend responds 403 and its revocation flag remains false.

**Required correction:** make the authoritative token available synchronously to the next
coordinated operation, or pass the confirmed token explicitly through the shared transition
boundary. Logout success must include server revocation. Add a real browser/ASGI regression
covering the rotated cookie, CSRF header, and invalidation of the server session.

## Evidence boundaries

Both new tests use production AuthProvider, ScopeProvider, HttpAuthAdapter, HttpScopeAdapter,
and ApiClient. Only fetch is replaced with a stateful backend boundary that models successful
scope mutation, HTTP denial, and CSRF-checked logout. These are deterministic component/client
reproductions, not live browser-to-ASGI or actual browser-cookie integration runs.

The server-side consequences above follow from the reviewed Organization rotation and Identity
CSRF/revocation handlers. The tests deliberately check actual outgoing headers and the
authoritative boundary state rather than accepting React state alone.

## Previous findings

| Previous finding | Current result |
| --- | --- |
| Overlapping scope changes desynchronize the session | Successful queue path passes; exception and queued-logout paths above still block acceptance |
| Redis older activity overwrites newer timestamps | Previous regression passes; atomic monotonic guards and expanded real Redis integration tests are present |
| Drawer steals controlled-input focus | Previous regression and added focus tests pass |
| Reusable-control translations | Previous Spanish regression passes; reusable feedback/form/input/table/overlay resources now wired |
| Session-service failure appears as logout | Deliberate unavailable/authorization-denied states and production retry coverage now present and passing |

The earlier 401-loading, initialization-loop, scope-label, Modal-focus, normalized URL,
mobile drawer, pluralization, and unsaved-navigation regression coverage remains passing.
This assessment does not claim exhaustive correctness outside the exercised paths.

## Validation

[GitHub Actions run 35316128547](https://github.com/sahinkhan/businessos/actions/runs/35316128547)
for the exact audited head completed successfully. Both web-quality and python-quality passed,
including the PostgreSQL/provider integration step. The real Redis tests in the repository cover
parallel touches, monotonic activity/TTL, and delayed touches against rotation/revocation.
That CI run predates the new local audit probes.

Local commands and outcomes:

| Command | Result |
| --- | --- |
| npm test, before adding new probes | PASS — 20 files / 71 tests, including all previous audit regressions |
| npm run typecheck | PASS, including the new test file |
| npm run lint | PASS, including the new test file |
| npm run format:check | PASS, including the new test file |
| npm run build | PASS |
| npm run bundle:check | PASS — 378.71 KB JS / 3.67 KB CSS |
| python -m pytest -q tests/unit/test_web_sessions.py tests/unit/test_web_session_reaudit.py tests/unit/test_web_session_touch_order_reaudit.py | PASS — 12 tests |
| npx prettier --write tests/audit/transitionFailureReaudit.test.tsx | Completed |
| npx vitest run tests/audit/transitionFailureReaudit.test.tsx | FAIL — 2 tests reproduce the two P1 findings |

Python commands used the existing `D:/project/python/businessos/.venv/Scripts/python.exe`
and PYTHONPATH entries for platform, tenant, identity, organization, policy, audit, and
data governance. Full Python 3.13/infrastructure/deployment checks were not rerun locally;
their evidence is the verified GitHub CI run. No new dependency audit or live IdP exercise
was performed.

The augmented checkout intentionally contains failing regression tests; it must not be described
as fully green.

## Files added

Inside `D:/project/python/businessos/.codex-worktrees/phase45`:

- `apps/web/tests/audit/transitionFailureReaudit.test.tsx`
- `docs/development/PHASE-4.5-INDEPENDENT-REAUDIT-d3db48b.md`

No production source, migration, public contract, existing test, or historical audit was changed.
Nothing was committed, pushed, merged, tagged, or certified. Phase 5 was not started.
