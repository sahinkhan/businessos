# Phase 4.5 UI Foundation Certification Audit

Audited baseline: `3e551b8922397e03636db8d7ed7cf85d2477db83`.

Remediation baseline: `25c51d497cb3d9bab27e4dc54839248e9ec9fe79` on `fix/phase4.5-certification`.

Status: remediation blocked pending review and acceptance of proposed ADR-009. PR #9 must not be
merged or certified. Historical tags `v0.4.5-ui-foundation` and `v0.4.6-ui-foundation` are
unchanged, and `v0.4.7-ui-foundation` must not be created.

## Current architecture blocker

The certified Identity foundation validates federated OIDC credentials and resolves effective
membership to a trusted `PrincipalIdentity`/`RequestContext`, but it publishes no browser login,
session issuance, refresh, logout/revocation, or current-session application contract. The current
React adapter assumes such a contract and therefore cannot be connected by a thin HTTP facade
without inventing a new authentication security model.

ADR-009 proposes OIDC Authorization Code with PKCE, backend token exchange, an opaque server-side
session, a Secure HttpOnly cookie, and a separately versioned additive
`foundation.identity.web-session.v1` contract. The accompanying web-session specification defines
the application, provider, HTTP, cookie, CSRF, lifecycle, and test contracts. No authentication
implementation is included in this documentation-only change.

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

### Production auth and credential storage — BLOCKED

- The default `HttpAuthAdapter` assumes backend login/session/refresh/logout responses that do not
  exist in the certified Identity application contract.
- Mock authentication remains available only through explicit dependency injection, and the
  frontend does not persist bearer credentials in local storage. Those protections do not provide
  a deployable production authentication path.
- The proposed ADR-009 removes browser-owned bearer credentials in favor of an opaque server-side
  session and Secure HttpOnly cookie. No implementation is permitted until that ADR is accepted.
- The API client already supports `AbortSignal`, typed errors, cryptographic correlation IDs where
  supported, and protected-payload logging restrictions. Request-generation enforcement remains a
  separate open remediation item.

## Known remaining remediation

The current PR head is not a certification candidate. Independent review confirmed:

1. **P1** — a late query response can update a mounted hook after principal, tenant, legal entity,
   company, or site context changes;
2. **P1** — frontend base and adapter paths can compose as `/api/api/v1/...`;
3. **P1** — browser auth, organization scope, and policy adapters do not yet correspond to a
   complete real ASGI HTTP surface;
4. **P2** — modal initial focus, focus trap, and focus restoration are incomplete;
5. **P2** — the mobile navigation state is not connected to an accessible drawer;
6. **P2** — official shell strings and pluralization do not yet satisfy the i18n contract; and
7. **P2** — unsaved-change protection does not block internal React Router navigation.

ADR-009 and `WEB-SESSIONS.md` address contract design for the authentication portion of item 3
only. All seven findings remain implementation work after architecture acceptance.

## Architecture and roadmap audit

1. **PASS** — The React, TypeScript, React Router, and Vite production shell builds.
2. **PASS** — Reusable design tokens, themes, accessible primitives, data tables, forms, feedback, overlays, and page shells remain present.
3. **PASS** — Route contributions are genuinely lazy and load only when rendered.
4. **PASS** — A module can register a route and navigation target without modifying the root router or shell.
5. **PASS** — Tenant, legal-entity/company, and operating-site authority comes from backend selection and validation.
6. **PASS** — Browser preferences cannot create scope authority.
7. **PASS** — Phase 4 backend decisions drive permission and field presentation.
8. **PASS** — Unknown action and field policy fails closed.
9. **BLOCKED** — Production browser authentication has no accepted web-session application
   contract or complete backend HTTP path.
10. **PASS** — Production auth, scope, and policy adapters contain no silent mock fallback.
11. **PASS** — Sensitive credentials are held in memory and are absent from local storage.
12. **FAIL** — cache keys are security-context scoped, but late requests can still update the
   current hook instance after a context transition.
13. **PARTIAL** — existing accessibility tests and RTL foundations pass, while modal focus,
   responsive navigation, official-string translation, and pluralization acceptance remain open.
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

Phase 4.5 must not be declared complete, certified, or frozen until:

1. ADR-009 is reviewed and accepted;
2. the seven known P1/P2 findings are remediated and covered by the required real integration and
   interaction tests;
3. both PR jobs, `web-quality` and `python-quality`, pass every required step;
4. the PR is independently approved and merged;
5. exact post-merge `main` CI passes;
6. a final independent audit passes; and
7. `v0.4.7-ui-foundation` is created in the separately authorized certification step.
