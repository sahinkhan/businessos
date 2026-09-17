# ADR-009: Browser Authentication and Web Session Boundary

Status: Proposed

## Context

The authenticated React backoffice needs a browser-safe authentication boundary. The certified
Phase 2 Identity foundation verifies federated credentials and resolves them to
`PrincipalIdentity`, membership, and trusted request context, but it does not issue or manage
browser sessions. Phase 4.5 must not invent users, passwords, permissions, access tokens, or
tenant authority in the browser.

Allowing the single-page application to own OAuth access and refresh tokens would place token
storage, rotation, revocation, federation interoperability, and logout behavior in a long-lived
browser runtime. Adding local username/password authentication would introduce a separate
credential lifecycle that is outside Phase 4.5 and the accepted federation-first architecture.

## Decision

BusinessOS will use a backend-for-frontend web-session boundary for the authenticated enterprise
backoffice:

1. Authentication providers use OIDC Authorization Code with PKCE. A future SAML adapter may
   terminate into the same boundary.
2. The backend performs authorization-code exchange and provider-token handling.
3. Existing Identity federation and membership contracts resolve the provider identity to the
   authoritative `PrincipalIdentity`.
4. A new, separately versioned web-session application contract creates an opaque server-side
   session. This contract is additive and does not change `IdentityContract` version 1.0.
5. The browser receives only an opaque session identifier in a cookie named
   `__Host-businessos_session` with `Secure`, `HttpOnly`, `SameSite=Lax`, and `Path=/`. The cookie
   has no `Domain` attribute.
6. The React application receives a safe session projection. It never receives or persists OAuth
   access tokens or refresh tokens.
7. Session persistence is accessed through a provider interface. Redis is the expected production
   provider, but Identity and the web-session application service do not depend directly on Redis.
8. Local username/password authentication is not introduced in Phase 4.5. Break-glass and other
   non-federated mechanisms remain separate, explicitly governed Identity adapters.

The version 1 browser HTTP surface is:

```text
GET  /api/v1/auth/session
POST /api/v1/auth/login/start
GET  /api/v1/auth/callback
POST /api/v1/auth/logout
```

The detailed application, HTTP, provider, cookie, CSRF, and failure contracts are defined in
[`WEB-SESSIONS.md`](../architecture/WEB-SESSIONS.md).

## Security properties

- Authentication credentials and provider tokens never enter browser storage or frontend logs.
- Login state, nonce, PKCE verifier, return location, and callback state are bound to one
  short-lived authentication transaction and consumed once.
- Session identifiers contain at least 256 bits of cryptographic randomness, are rotated after
  authentication and security-sensitive changes, and are stored server-side only as a one-way
  digest or equivalent non-recoverable lookup key.
- Sessions have absolute and idle expiry, support immediate revocation, and fail closed when the
  session store or trusted identity resolution is unavailable.
- Cookie-authenticated unsafe requests require the BusinessOS CSRF contract in addition to cookie
  attributes. Login return locations are restricted to validated same-origin application paths.
- Every authenticated request resolves an immutable BusinessOS `RequestContext`; client tenant and
  organization headers do not create authority.
- Authentication, scope, policy, and server-state caches are cleared or invalidated on logout,
  principal change, session expiry, and authoritative scope transition.

## Ownership and compatibility

The web-session application contract is owned by the Identity foundation as an additive public
contract. Provider-specific OIDC and future SAML adapters remain behind that contract. The
protected framework continues to own HTTP dispatch and trusted request-context integration; it
does not acquire Identity business semantics.

The contract is versioned independently as `foundation.identity.web-session.v1`. Breaking changes
require a new contract version and the compatibility process from ADR-007. Existing Phase 2
migrations and `IdentityContract(version="1.0")` remain unchanged.

## Consequences

- The current React bearer-token and password-login assumptions must be replaced after this ADR is
  accepted.
- A session-store provider, OIDC authorization transaction service, web-session application
  service, cookie/CSRF handling, and thin Identity-owned HTTP routes are required.
- Logout, revocation, session expiry, tenant suspension, membership removal, and provider failure
  have one backend-authoritative lifecycle.
- Self-hosted deployments must configure an approved OIDC provider and session-store provider.
- Implementation requires security review and conformance tests before Phase 4.5 certification.
- No schema migration is implied by this decision. If an implementation requires persistent
  relational session state or changes certified Identity tables, work must stop for migration and
  architecture review.

## Rejected alternatives

### SPA-owned OAuth tokens

Authorization Code with PKCE in the SPA is standards-compliant, but it leaves provider tokens and
more lifecycle responsibility in the browser. It is not the default for the enterprise
backoffice.

### Local username/password authentication in Phase 4.5

This would require password hashing, recovery, lockout, throttling, MFA, credential rotation, and
new security governance. It is outside this phase.

### Browser-supplied tenant or permission authority

Browser state remains presentation input only. Trusted membership, active scope, and policy
decisions are resolved and enforced by the backend.
