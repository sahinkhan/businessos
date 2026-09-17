# Phase 4.5 UI Foundation Certification Audit

Audited baseline: `3e551b8922397e03636db8d7ed7cf85d2477db83`.

Remediation baseline: `25c51d497cb3d9bab27e4dc54839248e9ec9fe79` on `fix/phase4.5-certification`.

Status: remediation candidate; independent merge approval, post-merge `main` CI, final audit, and the corrective `v0.4.7-ui-foundation` tag remain pending. Historical tags `v0.4.5-ui-foundation` and `v0.4.6-ui-foundation` are unchanged.

## Certification corrections

### Lazy module route contribution — PASS

- `RouteRegistry` accepts a stable route ID, path, module owner, typed lazy component loader, optional permission/capability/scope hints, optional error boundary, and deterministic order.
- Duplicate IDs, duplicate paths, unsafe paths, and duplicate index routes are rejected. Contributions can be registered and unregistered.
- The root router consumes registry snapshots and uses `React.lazy`, `Suspense`, scope and permission presentation boundaries, and a module error boundary.
- Core page imports live in a contribution module. Future modules can register routes without editing `app/routes.tsx` or `AppShell`.
- Tests prove deferred loader execution, collision rejection, unregister behavior, contributed rendering, route-ID navigation, and the generic root-router contract.

### Backend-authoritative scope — PASS

- `HttpScopeAdapter` accepts only backend tenant, selection, and validation responses. Network failures and malformed responses produce an unavailable state.
- Production scope initialization contains no fixture fallback or browser-side authorization evaluation.
- Local storage holds identifiers as an untrusted preference. The backend must select and validate a scope before it becomes active.
- Rejected tenant/company/site selections are not applied. Query state is cleared when authentication or authoritative scope changes.
- `MockScopeAdapter` requires explicit fixture injection and is never selected automatically by the production bootstrap.

### Fail-closed Phase 4 policy presentation — PASS

- Action and field evaluation use Phase 4 backend request and response fields.
- Missing, pending, malformed, or unavailable field decisions remain unreadable, unwritable, and masked.
- Policy cache keys include principal, tenant, legal entity, company, site, resource, and action or field.
- The policy cache is cleared when the principal or authoritative scope security context changes.
- Tests cover pending and failed evaluations, exact field-response translation, malformed responses, and cache isolation.

### Production auth and credential storage — PASS

- The default `HttpAuthAdapter` depends on backend login/session/refresh/logout responses and never manufactures users, credentials, roles, or permissions.
- Mock authentication is available only through explicit dependency injection.
- Bearer access credentials follow the accepted Identity architecture and remain in memory. They are not written to local storage or restored from browser persistence.
- Login, logout, expiry, refresh failure, and HTTP 401 clear principal-bound query state. HTTP 403 remains an authorization denial.
- The API client supports `AbortSignal`, typed errors, cryptographic correlation IDs where supported, trusted scope headers, and no credential or protected-payload logging.

## Architecture and roadmap audit

1. **PASS** — The React, TypeScript, React Router, and Vite production shell builds.
2. **PASS** — Reusable design tokens, themes, accessible primitives, data tables, forms, feedback, overlays, and page shells remain present.
3. **PASS** — Route contributions are genuinely lazy and load only when rendered.
4. **PASS** — A module can register a route and navigation target without modifying the root router or shell.
5. **PASS** — Tenant, legal-entity/company, and operating-site authority comes from backend selection and validation.
6. **PASS** — Browser preferences cannot create scope authority.
7. **PASS** — Phase 4 backend decisions drive permission and field presentation.
8. **PASS** — Unknown action and field policy fails closed.
9. **PASS** — Production authentication is backend authoritative.
10. **PASS** — Production auth, scope, and policy adapters contain no silent mock fallback.
11. **PASS** — Sensitive credentials are held in memory and are absent from local storage.
12. **PASS** — query and policy cache isolation covers principal, tenant, legal entity/company, and site transitions.
13. **PASS** — accessibility tests pass; translation-key and RTL foundations remain intact.
14. **PASS** — large-data table contracts retain server-side pagination, filtering, sorting, and search.
15. **PASS** — Phase 5 metadata, Studio, and Dynamic UI work has not started.
16. **PASS** — no business-domain workflow was added.

No Phase 1–4 migration or backend contract is changed by this remediation.

## Local evidence

Frontend validation used the committed lockfile:

| Gate | Result |
| --- | --- |
| `npm ci` | PASS |
| `npm run typecheck` | PASS |
| `npm run lint` | PASS, zero warnings |
| `npm run format:check` | PASS |
| `npm test` | PASS, 13 files / 41 tests |
| `npm run test:a11y` | PASS, 6 tests |
| `npm run build` | PASS |
| `npm run bundle:check` | PASS, 315.40 KB JavaScript / 3.67 KB CSS |
| `git diff --check` | PASS |

`npm audit` reports four moderate advisories and no high or critical advisories. The available automatic remedies require major React Router or Vitest upgrades. The application is a client-rendered Vite shell, unsafe external/backslash route and return paths are rejected, and Vitest is a development-only dependency. The findings are reviewed and tracked; no forced major upgrade was applied during this bounded remediation.

Backend regression used Python 3.13.15:

| Gate | Result |
| --- | --- |
| Ruff formatting and lint | PASS, 162 files |
| Unit tests | PASS, 161 tests |
| Whole-suite collection | PASS, 225 tests |
| External conformance without local infrastructure | PASS, 8; 5 infrastructure tests skipped |
| mypy / Pyright on Windows | Four identical platform-stub diagnostics in unchanged `multiprocessing.Pipe` migration code |
| PostgreSQL/provider integration, installed wheels, images, migration replay | Pending authoritative PR CI on pinned Linux infrastructure |

The Windows-only typing diagnostics are outside this frontend remediation diff. The repository's required Linux CI runs both type checkers against Python 3.13 and is the release gate.

## Remaining release gates

The remediation is ready for PR validation when the branch diff is committed and pushed. Phase 4.5 must not be declared complete, certified, or frozen until:

1. both PR jobs, `web-quality` and `python-quality`, pass every required step;
2. the PR is independently approved and merged;
3. exact post-merge `main` CI passes;
4. a final independent audit passes; and
5. `v0.4.7-ui-foundation` is created in the separately authorized certification step.
