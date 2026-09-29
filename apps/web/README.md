# Local enterprise UI demo

This preview is for inspecting the Phase 4.5 shell and component examples. It does not create
BusinessOS tenant, Identity, Organization, or Policy records in PostgreSQL.

```powershell
cd apps/web
npm ci
npm run demo
```

Open <http://127.0.0.1:3000/login>. The terminal prints a new password on every start. Use it
with either `admin@demo.businessos.test` (Settings allowed) or
`viewer@demo.businessos.test` (Settings denied). The email field starts with the admin address.

The local server provides two sample companies, Northstar Bangladesh Ltd and Northstar UAE LLC,
and validates company selection before rotating the demo session. The dashboard, data table,
form, layout, and component showcase include sample content. Data entered into the form is only
a UI demonstration and is not persisted.

`npm run demo` binds to `127.0.0.1` and keeps opaque demo sessions in its own memory. It uses a
host-only HttpOnly cookie and a CSRF token. Stopping the process removes all demo sessions.
The demo API and credential form are enabled only for this Vite development command. The normal
production build uses the configured backend OIDC and Redis browser session adapter; this local
preview is not a substitute for those authority checks or for real integration testing.
