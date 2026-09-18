# Independent Phase 4.5 UI Foundation re-audit — 2026-09-18

**Verdict: changes required. Phase 4.5 is not ready for merge or certification.**

Audited [PR #9](https://github.com/sahinkhan/businessos/pull/9) at `09f8f5e4db10d67c6ad93b18313ddfaba8468c64`, independently of the previous audit at `aa4c935a897184a93479e4eab04f9422c8d26900`. GitHub and the local checkout matched. PR #9 remains open and unmerged; its base is `3e551b8922397e03636db8d7ed7cf85d2477db83`.

Audit artifacts are in the existing project checkout `D:/project/python/businessos/.codex-worktrees/phase45`. No production source, migration, public contract, branch, tag, PR, or remote state was changed. Only this report and two regression-test files were added.

## Findings

### 1. P1 — An ordinary unauthenticated bootstrap never finishes loading

[AuthContext.tsx:55](https://github.com/sahinkhan/businessos/blob/09f8f5e4db10d67c6ad93b18313ddfaba8468c64/apps/web/src/auth/AuthContext.tsx#L55)

A GET /api/v1/auth/session returning 401 invokes the API client's unauthorized callback. That callback advances the security generation, while HttpAuthAdapter converts the 401 to a null session. reloadSession then returns at its generation guard before clearing isLoading. invalidateSession does not clear it either. ProtectedRoute consequently retains its spinner; the login page also receives a loading button.

Reproduced with the real HttpAuthAdapter and ApiClient, substituting only fetch. Expected auth state `false:false` (loading:authenticated); received `true:false`.

Remediation: settle bootstrap/loading ownership on invalidation without allowing a stale request to overwrite a newer session. Add a provider-composition test for normal unauthenticated startup.

### 2. P1 — Successful scope selection restarts scope initialization

[AuthContext.tsx:35](https://github.com/sahinkhan/businessos/blob/09f8f5e4db10d67c6ad93b18313ddfaba8468c64/apps/web/src/auth/AuthContext.tsx#L35) and [ScopeContext.tsx:142](https://github.com/sahinkhan/businessos/blob/09f8f5e4db10d67c6ad93b18313ddfaba8468c64/apps/web/src/scope/ScopeContext.tsx#L142)

A real scope-selection response includes csrfToken and expiresAt. ScopeProvider applies it and calls updateSessionSecurity, which replaces the session object. AuthProvider creates a new user object every render. Because ScopeProvider's initialization effect depends on that object, accepting scope re-runs initialization, re-fetches the hierarchy, and selects/rotates the session again. Repeated successful responses sustain the cycle and repeatedly invalidate security state.

Reproduced by returning session-rotation fields from the scope adapter. The first successful selection caused a second fetchTenants call. The probe deliberately holds that unexpected second fetch unresolved to prevent an unbounded test loop. Existing mock scope responses omit these rotation fields.

Remediation: key scope initialization to stable principal/tenant identity and distinguish initial establishment from updates to the same session's CSRF/expiry/scope.

### 3. P1 — Concurrent Redis session touches can reject a valid request

[web_sessions.py:622](https://github.com/sahinkhan/businessos/blob/09f8f5e4db10d67c6ad93b18313ddfaba8468c64/foundations/identity/src/businessos_identity/web_sessions.py#L622)

RedisWebSessionStore.touch compares the entire previously read session JSON. Two requests can read the same live session and generation. The first touch changes last_seen_at; the second loses the full-document compare-and-set and returns None, even though the stored session remains valid at the same generation. WebSessionApplicationService.get_session returns that None, and WebSessionContextResolver treats it as unauthenticated. Protected requests can therefore fail during ordinary concurrent activity, triggering frontend session invalidation.

Reproduced by executing the production RedisWebSessionStore against a deterministic double that schedules both reads before the atomic compare-and-set. One touch returned None; the stored generation remained unchanged. **This is a controlled concurrency reproduction, not a live Redis integration run.**

Remediation: handle same-generation activity contention separately from expiry, rotation, and revocation; preserve atomic protection against the latter. Add a real Redis parallel-request regression.

### 4. P2 — The active company/site indicator loses its labels

[scopeAdapter.ts:108](https://github.com/sahinkhan/businessos/blob/09f8f5e4db10d67c6ad93b18313ddfaba8468c64/apps/web/src/scope/scopeAdapter.ts#L108) and [ScopeSwitcher.tsx:56](https://github.com/sahinkhan/businessos/blob/09f8f5e4db10d67c6ad93b18313ddfaba8468c64/apps/web/src/scope/ScopeSwitcher.tsx#L56)

HttpScopeAdapter assigns companyName and siteName to null for every successful backend scope response. ScopeSwitcher renders those exact fields, so its persistent scope indicator is only the separator instead of the active company/site. Fetching the hierarchy first does not populate them. This violates the required visible operational context.

Reproduced through the real HTTP adapter with a named hierarchy followed by a valid scope-selection response. IDs are accepted but companyName/siteName remain null.

Remediation: resolve display names from trusted hierarchy data, or render supported identifiers as a deliberate fallback while names load. Keep authority in backend-provided IDs.

### 5. P2 — Controlled modal inputs lose focus when their parent renders

[Modal.tsx:81](https://github.com/sahinkhan/businessos/blob/09f8f5e4db10d67c6ad93b18313ddfaba8468c64/apps/web/src/components/overlays/Modal.tsx#L81)

The focus initialization/restoration effect depends on onClose. A normal inline callback changes identity whenever a parent updates controlled input state. Cleanup restores old focus, then the effect initializes focus again at the Close button. Typing the first character therefore takes focus out of the field.

Reproduced with a controlled text input and an inline onClose callback: the value updates to A, but focus moves from the input to Close dialog. Initial focus/trapping/restoration tests pass because they do not edit controlled content.

Remediation: tie focus lifecycle to opening/closing, while keeping the event handler current without reinitializing focus on callback changes.

### 6. P2 — Official navigation and reusable controls still bypass translation resources

[registry.ts:17](https://github.com/sahinkhan/businessos/blob/09f8f5e4db10d67c6ad93b18313ddfaba8468c64/apps/web/src/navigation/registry.ts#L17), [Sidebar.tsx:92](https://github.com/sahinkhan/businessos/blob/09f8f5e4db10d67c6ad93b18313ddfaba8468c64/apps/web/src/shell/Sidebar.tsx#L92), and [Modal.tsx:165](https://github.com/sahinkhan/businessos/blob/09f8f5e4db10d67c6ad93b18313ddfaba8468c64/apps/web/src/components/overlays/Modal.tsx#L165)

Default navigation embeds English labels and groups, including Dashboard, System Settings, and Administration. Sidebar renders those strings directly, so changing locale cannot translate them. Modal also hardcodes its Close dialog accessible label. The Phase 4.5 specification requires translation resources for all official user-visible strings and translation keys in navigation contributions.

Verified by source tracing. Plural selection and several shell/authentication labels have been fixed; the broader translation acceptance requirement remains incomplete.

Remediation: use resource keys in navigation contributions and translated defaults or supported translated-label props in reusable controls.

## Previous seven findings

| Previous finding | Current assessment |
| --- | --- |
| Stale query result after security-context transition | Previous reproduction addressed by generation/sequence guards and cancellation; existing regression tests pass |
| Duplicate /api URL prefix | Addressed; adapter-through-client tests pass |
| Missing backend HTTP facades | Facades now registered, with ASGI tests in the repository; new composition/session defects above still prevent acceptance |
| Modal focus management | Partially addressed; initial focus/trap/restore exist, but finding 5 remains |
| Mobile drawer wiring | Addressed by shell/drawer/sidebar wiring; existing tests pass |
| Internationalization/pluralization | Partially addressed; plural rules pass, finding 6 remains |
| Internal-navigation unsaved changes | Addressed by router blocker and beforeunload integration; existing tests pass |

## Validation evidence

The [GitHub Actions run](https://github.com/sahinkhan/businessos/actions/runs/35271602234) for the audited SHA completed successfully. That is the existing committed suite; it does not contain this audit's new regressions.

Commands run locally in the frontend directory:

| Command | Result |
| --- | --- |
| npm test, before adding audit probes | PASS: 17 files, 51 tests |
| npm run typecheck | PASS |
| npm run lint | PASS |
| npm run format:check | PASS |
| npm run build | PASS |
| npm run bundle:check | PASS: 366.96 KB JavaScript; 3.67 KB CSS |
| npx prettier --write tests/audit/independentReaudit.test.tsx | Completed |
| npx vitest run tests/audit/independentReaudit.test.tsx | FAIL: four regression assertions reproduce findings 1, 2, 4, 5 |

Backend commands used `D:/project/python/businessos/.venv/Scripts/python.exe`, with PYTHONPATH set to platform/src and the tenant, identity, organization, policy, audit, and data_governance foundation src directories:

| Command | Result |
| --- | --- |
| python -m pytest -q tests/unit/test_web_sessions.py | PASS: 10 tests |
| python -m pytest -q tests/unit/test_web_session_reaudit.py | FAIL: concurrency regression reproduces finding 3 |
| python -m ruff check tests/unit/test_web_session_reaudit.py | PASS |
| python -m ruff format --check tests/unit/test_web_session_reaudit.py | PASS |

The local interpreter is Python 3.12.14, below the required 3.13. Docker's local daemon was unavailable. Full Python 3.13, PostgreSQL, real Redis, deployment, and browser-to-live-IdP acceptance were not rerun locally. Existing remote CI success does not establish coverage for the new failures.

These regression tests intentionally remain failing. Do not describe the checkout's augmented test suite as green.

## Added files and next gate

- `apps/web/tests/audit/independentReaudit.test.tsx`: four frontend regression probes.
- `tests/unit/test_web_session_reaudit.py`: controlled session-touch concurrency regression.
- `docs/development/PHASE-4.5-INDEPENDENT-REAUDIT-2026-09-18.md`: this report.

Fix the three P1 defects, close the three P2 acceptance gaps, and run the added regressions plus the existing suite. Verify startup, successful login, scope selection, concurrent authenticated requests, and logout against the composed frontend and backend. Re-run infrastructure checks on the required runtime before a fresh certification decision.

This audit identifies confirmed gaps; it is not an assertion that unexercised deployment or browser scenarios are defect-free. No merge, certification tag, or Phase 5 work was performed.

