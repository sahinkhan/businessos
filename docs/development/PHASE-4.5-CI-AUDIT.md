# Phase 4.5 UI Foundation Certification Audit

Audited `main` baseline: `3e551b8922397e03636db8d7ed7cf85d2477db83`.

Accepted architecture checkpoint: `20e2c32d8a25e7959fcf474f70a77f5e8f96646e` on
`fix/phase4.5-certification`.

Status: **READY FOR INDEPENDENT RE-AUDIT**. The six findings from the 2026-09-18 independent
re-audit have regression coverage and remediation. Exact implementation-head PR CI is green and
the final read-only review found no remaining P1/P2 blocker in the authorized scope. PR #9 must not
be merged or certified without separate authorization.
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
