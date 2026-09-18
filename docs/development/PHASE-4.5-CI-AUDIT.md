# Phase 4.5 UI Foundation Certification Audit

Audited `main` baseline: `3e551b8922397e03636db8d7ed7cf85d2477db83`.

Accepted architecture checkpoint: `20e2c32d8a25e7959fcf474f70a77f5e8f96646e` on
`fix/phase4.5-certification`.

Status: **READY FOR INDEPENDENT RE-AUDIT**. The two P1 findings from the re-audit of `d3db48b`
have production fixes and regression coverage. Exact implementation-head PR CI is green and the
final read-only review found no remaining P1/P2 blocker in the authorized scope. PR #9 must not be
merged or certified without separate authorization.
Historical tags `v0.4.5-ui-foundation` and `v0.4.6-ui-foundation` are unchanged.
`v0.4.7-ui-foundation` must not be created in this step.

## 2026-09-18 independent re-audit remediation

The independent report remains intact in
`PHASE-4.5-INDEPENDENT-REAUDIT-2026-09-18.md`. Its six findings were addressed as follows:

- unauthenticated HTTP 401 bootstrap and provider failure now settle loading state, while explicit
  reload remains recoverable and stale-request generation guards remain active;
- scope initialization is keyed to stable tenant/principal identity, so same-principal CSRF,
  expiry, and scope rotation do not restart hierarchy loading, while a true principal replacement
  does;
- Redis touch atomically checks the stored generation and live expiry, then updates activity fields
  from the current stored document, so concurrent same-generation requests succeed without
  weakening rotation or revocation protection;
- the Organization hierarchy projection supplies trusted display names for backend-selected
  company and operating-site identifiers;
- modal focus lifecycle is tied to open/close state and uses a current callback reference, so
  controlled-input rerenders preserve focus; and
- official navigation contributions use translation resource keys, Sidebar and command-palette
  presentation resolves those keys, and Modal accepts a translated close-control label used by the
  session-expiry flow.

Added evidence includes the four original frontend reproductions, bounded scope lifecycle coverage
for same-scope no-ops, company/site switching, invalid selection, reload, logout, and principal replacement,
auth bootstrap/recovery coverage, non-English navigation and reusable-control accessibility labels,
a deterministic Redis concurrency regression, and a real Redis 24-way parallel touch integration
case with post-rotation and post-revocation stale-touch denial.

Local frontend gates pass: TypeScript, ESLint, Prettier, 19 test files / 60 tests, six automated
accessibility tests, production build, and bundle budget. Focused backend session tests pass 11/11,
and repository Ruff formatting/lint pass. This workstation has Python 3.12 rather than the required
Python 3.13 and no running Docker daemon, so full Python unit/static/provider/deployment evidence is
supplied by exact-head GitHub CI. No migration or public certified contract changed.

## ADR-009 implementation

The Identity foundation now publishes the additive
`foundation.identity.web-session.v1` application contract. It composes the certified tenant,
membership, and `PrincipalIdentity` behavior without changing `IdentityContract(version="1.0")`.
No database schema or certified migration changed.

The boundary provides:

- protocol-neutral session creation from a validated `PrincipalIdentity`;
- safe current-session projection and trusted `RequestContext` reconstruction;
- absolute and idle expiry, rotation, logout, individual revocation, and principal-wide revocation;
- an abstract session store with an in-memory test provider and a Redis production provider;
- opaque random handles represented in Redis by digest-only keys and maintained principal indexes;
- atomic Redis create, rotate, transaction creation, transaction consumption, replay marking, and
  browser-binding cleanup;
- atomic, bounded login-initiation rate limiting in the authorization-transaction provider;
- OIDC Authorization Code exchange behind a provider adapter with transaction-specific `state`,
  `nonce`, verifier, S256 challenge, expected issuer, and short-lived browser binding; and
- a future SAML seam at the same validated-principal session-creation boundary.

The exact HTTP facade is registered through the Identity module:

- `GET /api/v1/auth/session`
- `POST /api/v1/auth/login/start`
- `GET /api/v1/auth/callback`
- `POST /api/v1/auth/logout`

The callback consumes authorization state once, validates the browser binding, delegates token
validation (issuer, audience, signature, and nonce) to the certified OIDC resolver, revalidates the
active tenant/principal/membership, creates a new opaque session, and permits only a sanitized local
return path. Success and every terminal failure clear transient browser state. Provider tokens never
enter the session projection or React.

The `__Host-businessos_session` and transaction cookies are host scoped with `Secure`, `HttpOnly`,
`SameSite=Lax`, and `Path=/`. Authenticated unsafe methods require the session-bound CSRF value and
same-origin browser metadata. Session rotation changes both the opaque handle and CSRF value. Logout
revokes server state before expiring the browser cookie.

## Organization and Policy HTTP contracts

Organization registers hierarchy, validation, and active-scope routes under
`/api/v1/organization`. Each handler derives tenant/principal authority from trusted session context
and delegates to the certified `ReadOrganization` and `SelectActiveScope` queries. Active-scope
selection rotates the web session and returns the new safe scope, expiry, and CSRF presentation data.

Policy registers authorize, field-access, and approval-limit routes under `/api/v1/policy`. The
handlers overwrite tenant, subject, and active organization scope from trusted context and delegate
to the certified Phase 4 query handlers. The browser supplies requested action/resource inputs only;
it cannot manufacture tenant or subject authority.

## Frontend remediation

- `ApiClient` owns the single `/api/v1` base. Auth, Organization, and Policy adapters use relative
  resource paths, and adapter-through-client tests reject any `/api/api/` composition.
- Authentication bootstraps from `GET /auth/session`, uses same-origin credentials and session-bound
  CSRF for unsafe methods, and contains no access/refresh token state, bearer header, or browser
  credential persistence.
- Logout and principal replacement invalidate active requests, query state, policy state, scope
  state, and principal-bound presentation data.
- Query execution combines `AbortController`, request sequence, and security-context generation.
  Late responses cannot update data, errors, callbacks, or caches after tenant, company, site,
  principal, logout, or unmount transitions.
- Scope changes become active only after backend selection. Session rotation updates the frontend's
  CSRF/expiry presentation state before later unsafe calls.
- Modal and drawer primitives implement initial focus, forward/reverse focus trapping, Escape,
  overlay close where applicable, title/description association, cleanup, and focus restoration.
- The shared navigation registry renders in both desktop sidebar and mobile drawer. Mobile route
  selection closes the drawer, while responsive desktop navigation occupies no mobile width.
- Official authentication, shell, notification, scope, and generic system-state strings use the
  translation service. Plural selection uses `Intl.PluralRules` and CLDR categories with English and
  Arabic regression evidence; locale switching, fallback, RTL, number, currency, date, and timezone
  behavior remain intact.
- Dirty forms use the supported React Router blocker plus `beforeunload`; internal link and browser
  navigation can be cancelled or confirmed without monkey-patching history.

## Security and integration evidence

Deterministic backend tests cover S256 enforcement, provider/issuer and nonce forwarding, missing or
wrong state, browser-binding mismatch, one-time atomic consumption, expiry, replay, failed-exchange
cleanup, unsafe return paths, session fixation resistance, expiry, rotation, logout/revocation, and
hardened cookies.

Real ASGI tests construct the BusinessOS application with actual Tenant, Identity, Organization, and
Policy modules. Only the external IdP boundary is simulated. They exercise request parsing, trusted
session context, serialization, current session, login/callback, CSRF for every unsafe method,
logout, organization hierarchy/validation/selection, session rotation, and all three policy
presentation routes. A Redis provider integration test exercises atomic session rotation,
principal-wide revocation, transaction consumption, and replay denial against the CI Redis service.

Frontend tests cover normalized adapter URLs, auth bootstrap/logout, delayed stale responses,
principal/scope cache lifecycle, modal focus, mobile drawer interaction, plural rules, and both
cancelled and confirmed dirty-route navigation. Existing lazy-route, fail-closed policy, RTL,
accessibility, server-side table, and module registration tests remain enabled.

The ASGI framework resolves routes inside the composed middleware chain. Authenticated unsafe
requests therefore cannot bypass CSRF enforcement by targeting an unknown path or unsupported
method. Organization active-scope and validation responses serialize their nested Pydantic scope
projection explicitly before returning JSON. The event-worker restart integration uses the shared
committed-receipt polling boundary, so handler completion is not mistaken for transaction commit.

## Exact-head PR CI evidence

GitHub Actions run
[`35304332034`](https://github.com/sahinkhan/businessos/actions/runs/35304332034) executed for PR #9
implementation head `7fed8d8f99e39e11a2da624fe144c832eba8a97e` and completed successfully.

| Gate | Result |
| --- | --- |
| `web-quality` | PASS |
| Frontend typecheck, lint, format, 60 tests, accessibility, build, and bundle budget | PASS |
| `python-quality` | PASS |
| Ruff format and lint | PASS |
| Static typing | PASS |
| Unit tests and whole-suite collection | PASS |
| PostgreSQL and provider integration tests, including real ASGI and Redis coverage | PASS, 54 tests |
| External module conformance | PASS |
| Installed-wheel migration smoke | PASS |
| Development and production image builds | PASS |
| Production-derived migration upgrade and replay | PASS |
| Committed patch whitespace | PASS |

## Local evidence

The frontend validation uses the committed lockfile:

| Gate | Result |
| --- | --- |
| `npm ci` | PASS |
| `npm run typecheck` | PASS |
| `npm run lint` | PASS, zero warnings |
| `npm run format:check` | PASS |
| `npm test` | PASS, 19 files / 60 tests |
| `npm run test:a11y` | PASS, 6 tests |
| `npm run build` | PASS |
| `npm run bundle:check` | PASS, within configured budget |
| `npm audit --audit-level=high` | Environment blocked registry access; authoritative CI install remains required |

Backend validation available in the local Python 3.12 environment:

| Gate | Result |
| --- | --- |
| Ruff format | PASS, 165 files |
| Ruff lint | PASS |
| Focused mypy for all changed Python | PASS, 18 source files |
| Focused Pyright for all changed production Python | PASS, zero diagnostics |
| Focused web-session unit tests | PASS, 11 tests |
| Provider integration collection | PASS; skipped locally because CI services are absent |
| Real ASGI integration collection | PASS; execution requires the project Python 3.13 runtime |

The repository requires Python 3.13. The local interpreter is Python 3.12, so full foundation unit,
conformance, PostgreSQL/provider integration, wheel, image, and migration-replay certification is
reserved for the pinned Linux PR workflow. The new tests are collected by that workflow and are not
excluded by its commands.

## Scope and remaining gate

No Phase 5 metadata/Studio/Dynamic UI implementation and no business module were added. Existing
lazy route contribution, backend-authoritative scope, fail-closed policy/field access, and
server-side large-data contracts remain unchanged.

The branch is **READY FOR INDEPENDENT RE-AUDIT**. Phase 4.5 remains not complete, not certified, and
not frozen until the separately authorized merge, post-merge `main` CI, final audit, and tag step.

## Second re-audit remediation — 2026-09-18

The independent audit at `b06b08d8e29fa68b9fa9174688c03f4888361b25` identified five remaining
gaps. Implementation commit `98d9959` addresses them as follows:

- scope-changing requests share the authentication provider's serialized security-transition
  coordinator; superseded responses pass rotated CSRF material to the next request and only the
  final requested trusted snapshot is committed;
- Redis touch compares candidate and current `last_seen_at` and `idle_expires_at` inside Lua and
  returns the authoritative record without rewriting its TTL when the candidate is stale;
- Drawer keeps its close callback in a ref, so its focus lifecycle runs only on closed/open state
  changes;
- reusable feedback, search, form, overlay, table, action, input, and accessibility labels resolve
  through English, Spanish, and Arabic resources with English/key fallback;
- authentication exposes initializing, authenticated, unauthenticated, service-unavailable, and
  authorization-denied states, with explicit retry UI and malformed-response failure handling.

Regression evidence includes the preserved independent audit tests, serialized overlap/rejection
and cache invalidation tests, controlled Drawer rerender/focus tests, non-English navigation,
control, and accessibility tests, and 500/network/timeout/malformed/retry authentication tests.
The real Redis provider test now proves delayed older activity cannot replace newer activity or
shorten TTL, and proves delayed touches lose to rotation and revocation.

Local results: frontend typecheck/lint/format PASS; 71 frontend tests PASS; 6 accessibility tests
PASS; production build and 378.71 KB JS / 3.67 KB CSS bundle budget PASS; focused session tests
12 PASS; Ruff PASS; focused mypy PASS. `npm audit` reports 4 moderate, 0 high, and 0 critical
advisories; available fixes require separately authorized major upgrades.

PR run `35315427827` on `98d9959` passed `web-quality` and every substantive `python-quality`
step, including static analysis, unit/collection, PostgreSQL/provider integration with the real
Redis regressions, conformance, wheel migration, images, and production migration replay. Its
final whitespace step detected one extra blank line at the end of the preserved independent audit
report; the follow-up commit removes only that blank line. A new exact-head run remains the final
branch gate. Phase 4.5 is not certified or frozen, PR #9 must not be merged, and Phase 5 must not
start before independent re-audit.

## Final P1 transition remediation — 2026-09-18

The independent report at `d3db48ba9c140deca8ccd70b894e205ed65dec1d` remains unchanged in
`PHASE-4.5-INDEPENDENT-REAUDIT-d3db48b.md`. It identified two final state-coherence defects:

- a failed queued scope request discarded the last confirmed server result and could leave the UI,
  CSRF material, query context, and policy context on the earlier scope; and
- logout read CSRF through a React effect, so a logout serialized immediately behind scope rotation
  could send the previous token, fail server revocation, and still clear local authentication.

The frontend now maintains one synchronous authoritative session snapshot behind AuthProvider.
The API client's CSRF provider and coordinated logout both read that snapshot, and logout passes the
token explicitly to the adapter. Local authentication is cleared only after logout succeeds, a 401
confirms session absence, or current-session reconciliation confirms no live session. An
`invalid_csrf` response triggers one current-session read and at most one logout retry. A genuine
denial, network failure, 5xx, or failed retry retains the live projection and exposes the existing
recoverable session-service or authorization-denied state.

Scope transitions use the same reusable current-session reconciliation path. Ambiguous 403,
conflict, 5xx, and transport outcomes no longer invent rollback. A trusted current-session response
atomically replaces principal, active-scope IDs, derived hierarchy labels, expiry, and CSRF state;
query requests are cancelled and query/policy presentation caches are invalidated by the security
generation and derived policy key. Reconciliation that loses its generation cannot overwrite a
newer transition. When a newer selection arrives during reconciliation, the worker obtains a fresh
snapshot before continuing with its CSRF token. If current-session service is unavailable, the
frontend removes the uncertain local authority and exposes a recoverable unavailable state.

The preserved real-adapter audit probes now pass. Additional controlled-backend tests cover an
ambiguous mutation followed by authoritative reconciliation, a newer selection arriving while an
older reconciliation is pending, confirmed 401 session loss, reconciliation 5xx/network failure,
bounded stale-CSRF logout recovery, direct logout 5xx/network failure, and queued logout winning
without authentication resurrection. The real ASGI test now proves that a stale pre-rotation CSRF
token cannot revoke the rotated session, current-session returns the rotated token and scope, the
authoritative token revokes the session, and the subsequent current-session request returns 401.

Local frontend gates after `npm ci` pass: TypeScript, ESLint, Prettier, 22 test files / 85 tests,
six accessibility tests, production build, and the 381.56 KB JavaScript / 3.67 KB CSS bundle
budget. The two independent audit probes and twelve added recovery cases pass 14/14. Focused
web-session unit tests pass 12/12. Ruff format and lint pass for all 167 checked Python files, and
the complete suite collects 242 tests. This workstation remains on Python 3.12, so the Python
3.13-only full unit/static/infrastructure/deployment results are supplied by the pinned PR workflow.
The local Python 3.12 full run predictably rejects Python 3.13 module manifests and reports the
known multiprocessing typing difference; it is not certification evidence.

`npm audit` reports four moderate advisories and zero high or critical advisories. Available fixes
require breaking Vitest 5 or React Router 7 upgrades and remain outside this bounded remediation.

GitHub Actions run
[`35327678802`](https://github.com/sahinkhan/businessos/actions/runs/35327678802) executed for exact
implementation head `9f96597ebf7fcbc6f0c5533402e249167c08b278`. Both `web-quality` and
`python-quality` completed successfully. The Python job passed Ruff, mypy, Pyright, unit and
collection gates, PostgreSQL/provider integration including the real ASGI and Redis cases,
conformance, installed-wheel migration smoke, development/production/migration image builds,
production-derived migration replay, and committed-patch whitespace.

No Identity 1.0 contract, migration, ADR-009 decision, historical tag, or Phase 5 implementation
changed. Phase 4.5 remains not complete, not certified, and not frozen. PR #9 remains open and must
not be merged before an independent re-audit.
