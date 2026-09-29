# Phase 4.5 browser adapter

The enterprise UI uses the accepted Phase 4 Identity, Organization, and Policy contracts. This adapter adds browser transport and presentation state; it does not create another source of membership, company, role, or permission authority.

## Deployment configuration

Production browser authentication is unavailable until all of these are configured:

- `BOS_WEB_SESSION_REDIS_URL`: Redis or TLS Redis URL for opaque session and OIDC transaction storage.
- `BOS_WEB_OIDC_CALLBACK_URL`: HTTPS callback at `/api/v1/auth/callback` on the public application origin.
- `BOS_WEB_OIDC_AUTHORIZATION_URL`: HTTPS provider authorization endpoint.
- `BOS_WEB_OIDC_TOKEN_URL`: HTTPS provider token endpoint.
- `BOS_WEB_OIDC_ISSUER`: HTTPS provider issuer.
- `BOS_WEB_OIDC_CLIENT_ID`: registered OIDC client identifier.
- `BOS_WEB_OIDC_CLIENT_SECRET_FILE`: optional secret file path; never put the secret in a browser bundle.

The existing Identity OIDC provider configuration must also be admitted for the tenant. Token signature, issuer, audience, tenant, principal, MFA policy, and live membership continue through that existing validation path. The adapter uses authorization code with PKCE, nonce, state, a browser binding cookie, and server-side code exchange. Redis holds an opaque session record; it is not a business authorization store. The `__Host-` session cookie is Secure, HttpOnly, SameSite=Lax, and host-only. Mutations require the CSRF token from the current server session.

`GET /api/v1/auth/session` supplies the UI's session projection. `POST /api/v1/auth/login/start`, `GET /api/v1/auth/callback`, and `POST /api/v1/auth/logout` manage the browser credential. `GET /api/v1/organization/scopes` supplies presentation options. `POST /api/v1/organization/active-scope` invokes the existing `SelectActiveScope` command before rotating the opaque session and CSRF token. The UI treats missing, pending, or failed scope and policy projections as denied. Policy presentation uses the existing authorizer or Policy V2 evaluation; actual backend operations remain subject to their own authoritative checks.

The browser stores no bearer credential. A session, identity, or scope transition aborts in-flight frontend requests and clears query and policy state. Phase 5 metadata and Studio are outside this adapter.
