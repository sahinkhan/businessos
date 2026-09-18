# BusinessOS Web Session Contract

Status: Accepted contract design for ADR-009. Implementation must conform to this contract and
pass the required security and conformance evidence before Phase 4.5 certification.

## Scope

This document defines the additive browser-session boundary required by the authenticated React
backoffice. It composes existing federation, `PrincipalIdentity`, membership, tenant, organization,
and policy contracts. It does not replace them and does not add local password authentication.

```text
OIDC or SAML provider
        ↓
PrincipalIdentity
        ↓
WebSessionApplicationService
        ↓
WebSessionStore provider
        ↓
opaque HttpOnly browser cookie
        ↓
trusted RequestContext per request
```

## Public application contract

The additive public contract is `foundation.identity.web-session.v1`. Its implementation owns
session orchestration and depends on published Identity, Tenant, and Organization contracts.

Conceptual operations:

```text
start_login(request) -> LoginStart
complete_oidc_login(callback) -> WebSession
get_session(session_id) -> SessionProjection
logout(session_id) -> None
resolve_request(session_id) -> RequestContext
```

`WebSessionStore` is a provider interface with at least:

```text
create(session) -> opaque_session_id
get(opaque_session_id) -> WebSession | None
touch(opaque_session_id, expected_generation) -> WebSession | None
rotate(opaque_session_id, replacement) -> opaque_session_id
revoke(opaque_session_id) -> None
revoke_principal(tenant_id, principal_id) -> None
```

Implementations must provide atomic expiry, rotation, and revocation behavior. Redis is the normal
production provider. An in-memory provider is test-only and must never be selected silently in
production.

## Authorization transaction

Every OIDC authorization request has a short-lived, single-use server-side transaction. Its
record contains transaction-specific `state`, OIDC `nonce`, PKCE verifier and `S256` challenge,
provider and expected issuer, sanitized return path, issued/expiry instants, and a non-recoverable
digest of a separate opaque browser-binding value.

`POST /api/v1/auth/login/start` supplies that browser binding in a transient cookie named
`__Host-businessos_auth_txn`. The cookie is `Secure`, `HttpOnly`, `SameSite=Lax`, has `Path=/`, has
no `Domain` attribute, and expires no later than the authorization transaction. Its value contains
no provider, tenant, principal, return-path, nonce, verifier, or credential data. It is distinct
from the authenticated web-session cookie.

The OIDC callback must compare the transient browser binding to the transaction record and consume
the transaction atomically. Exactly one callback may obtain and use its contents. Missing,
mismatched, expired, already-consumed, or replayed transactions or bindings fail closed. The
server deletes the transaction's usable state and expires the transient cookie after every
terminal callback outcome, including provider denial and validation, exchange, membership, or
session-creation failure. A consumed marker may be retained only for the bounded transaction TTL
to detect and audit replay without retaining verifier or credential material.

## Session record

A server-side session contains only the data needed to resolve trusted requests and manage the
federation lifecycle:

- session identifier digest
- contract version and generation
- `PrincipalIdentity`
- provider/session reference required by the backend adapter
- issued, last-seen, idle-expiry, and absolute-expiry instants
- authentication strength and provider identifier
- revocation status and reason
- validated active organization-scope reference when present
- correlation/audit metadata

Provider access and refresh tokens are server-side secrets. They must be encrypted or stored by an
approved secret-bearing provider and must never be serialized into the session projection, normal
logs, events, or client-visible errors.

## Browser cookie

The session cookie contract is:

```text
Name:     __Host-businessos_session
Secure:   true
HttpOnly: true
SameSite: Lax
Path:     /
Domain:   absent
```

The value is an opaque, cryptographically random identifier with at least 256 bits of entropy. It
contains no tenant, principal, scope, role, permission, or provider-token data. The server stores a
non-recoverable digest or equivalently protected lookup value. Cookie expiry must not outlive the
server-side absolute expiry.

## HTTP contract

All JSON responses use `application/json`. Errors use the standard BusinessOS error envelope with
a stable code, safe message, optional non-sensitive details, and correlation identifier.

### `GET /api/v1/auth/session`

Returns `200` only for a valid, non-expired, non-revoked session. The safe projection contains:

```json
{
  "status": "authenticated",
  "principal": {
    "id": "uuid",
    "tenant_id": "uuid",
    "type": "user",
    "display_name": "Ada Lovelace",
    "email": "optional@example.test",
    "authentication_strength": "mfa"
  },
  "active_scope": {
    "tenant_id": "uuid",
    "legal_entity_id": null,
    "company_id": null,
    "operating_site_id": null
  },
  "expires_at": "RFC3339 instant",
  "csrf_token": "per-session anti-CSRF value"
}
```

Optional display fields come from an approved projection service; absence must not invalidate the
trusted principal. Roles, permissions, OAuth tokens, refresh tokens, credential references, and
unfiltered membership claims are never returned. Missing, invalid, expired, or revoked sessions
return `401` and expire the browser cookie.

### `POST /api/v1/auth/login/start`

Accepts an optional validated same-origin application `return_to` path and an optional configured
provider identifier. It creates a short-lived, single-use authorization transaction containing
transaction-specific state and nonce, a PKCE verifier and `S256` challenge, provider and expected
issuer, sanitized return path, and the server-tracked browser-binding digest. It sets the transient
authorization-transaction cookie and returns `200` with the authorization URL and transaction
expiry. The browser performs a top-level navigation to that URL.

Unknown providers, unsafe return paths, invalid input, or unavailable federation configuration
fail without creating a session. The endpoint must be rate limited and must not reveal whether a
principal exists.

### `GET /api/v1/auth/callback` — OIDC callback

Validates the transaction-specific state, nonce, PKCE `S256` material, expected issuer, and
browser binding and atomically consumes the authorization transaction exactly once. It exchanges
the authorization code on the backend, validates issuer/audience/signature/nonce/time claims, and
resolves the existing `PrincipalIdentity` and effective membership. It then creates and rotates
the opaque session, sets the cookie, and responds with `303` to the sanitized application path.

Missing or mismatched browser binding, state mismatch, replay, an expired or already-consumed
transaction, invalid provider response, inactive tenant, or ineffective membership fails closed.
Transient authorization state and its cookie are cleared after every terminal success or failure.
No provider error details or tokens are reflected to the browser.

### `POST /api/v1/auth/logout`

Requires a valid CSRF token when a session cookie is present. It revokes the server-side session,
expires the cookie, clears authoritative active-scope state tied to the session, and returns `204`.
The operation is idempotent. Provider single logout is adapter-specific and must not prevent local
session revocation.

## CSRF and request integrity

Every unsafe cookie-authenticated request must pass the BusinessOS CSRF check. The session
projection supplies a per-session token for an `X-CSRF-Token` header. The backend binds that token
to the current session generation and also validates same-origin `Origin`/`Sec-Fetch-Site` signals
where available. Session rotation invalidates the previous CSRF token.

OIDC callback integrity is provided by the transaction-specific state, nonce, PKCE `S256`
validation, and the short-lived server-tracked browser binding. The transaction is consumed
atomically once. Cookie attributes supplement these checks; they are not the sole CSRF defense.

## Future SAML compatibility

`GET /api/v1/auth/callback` is the OIDC callback. Future SAML HTTP-POST/ACS support may add a
separate Identity-owned endpoint; it is not part of the Phase 4.5 implementation. The ACS must use
the certified `SAMLAssertionValidator` adapter so raw SAML does not reach application or domain
code. The validated `PrincipalIdentity` then enters the same `WebSessionApplicationService`
session-creation boundary used by OIDC.

The SAML flow must provide equivalent short-lived browser-transaction correlation, atomic
single-use consumption, assertion replay protection, sanitized same-origin `RelayState`, and
clearing of transient state after every terminal outcome. Provider single logout may be supported
by its adapter, but it must never delay or prevent immediate revocation of the local BusinessOS
web session.

## Trusted request resolution

The web-session resolver runs at the framework transport boundary before module handlers. It:

1. reads the opaque cookie;
2. retrieves a live session from `WebSessionStore`;
3. checks revocation, idle expiry, absolute expiry, provider requirements, active tenant, and
   effective membership according to bounded revalidation policy;
4. creates an immutable `RequestContext`/`TenantContext` from the trusted session identity and
   backend-validated active scope; and
5. touches the session without extending its absolute lifetime.

Client headers may carry correlation and untrusted selection intent. They never override tenant,
principal, company, legal-entity, or site authority resolved from the session.

## Lifecycle and invalidation

The following transitions revoke or rotate the session and invalidate browser-visible security
state as applicable:

- logout or administrative revocation
- tenant suspension/deletion
- membership suspension/revocation/expiry
- principal disablement
- provider-token or federation-session failure
- authentication-strength change
- absolute or idle expiry

Principal change, logout, expiry, and active-scope change increment the frontend security-context
generation. Query and policy caches are cleared, active requests are aborted or made obsolete, and
late results from the prior generation are ignored.

## Organization and policy composition

Authentication establishes the principal and tenant boundary. It does not grant a company or site
selection. Organization endpoints validate and activate scope using certified Organization
contracts. Policy endpoints consume the resulting trusted `RequestContext` and certified Phase 4
queries. The browser cannot manufacture membership, scope, roles, permissions, or policy results.

## Failure semantics

- `400`: malformed request or unsafe return path
- `401`: missing, invalid, expired, or revoked session; invalid authentication callback
- `403`: authenticated principal lacks effective tenant/scope authority
- `404`: configured provider or public resource is unavailable without disclosing private state
- `409`: consumed/replayed authentication transaction or incompatible session generation
- `422`: well-formed request violates a stable boundary contract
- `429`: authentication initiation rate limit
- `503`: required session/federation provider unavailable

Production responses contain no stack traces, tokens, verifier values, secrets, or provider-private
payloads. Authentication and revocation audit records include correlation ID, tenant/principal when
known, provider, outcome, reason code, and time without credential material.

## Frontend contract

The React authentication adapter will expose browser-session operations rather than bearer-token
operations:

```text
getSession() -> SessionProjection | null
startLogin(returnTo?) -> navigation target
logout(csrfToken) -> None
```

`ApiClient` will use same-origin credentials and the CSRF header for unsafe methods. It will not
store, restore, or attach bearer tokens. A `401` clears principal, scope, policy, and query state.
The `/api` base is composed exactly once with versioned adapter paths.

## Required implementation evidence

After ADR approval, implementation must include:

- provider-contract unit and conformance tests
- OIDC browser-binding plus state/nonce/PKCE `S256` success, expiry, atomic consumption, replay,
  mismatch, and terminal-cleanup tests
- cookie attribute, rotation, expiry, revocation, and CSRF tests
- active-tenant and effective-membership negative tests
- cross-tenant and cross-principal session-isolation tests
- real ASGI tests for session, login start, callback, and logout routes
- frontend `ApiClient` plus adapter path-contract tests
- browser-state invalidation and stale-request-generation tests
- tests proving no access or refresh token appears in browser storage, JSON, or logs

No Phase 1-4 migration may be changed. If a schema migration or certified Identity contract change
is required, implementation stops for separate architecture and migration review.
