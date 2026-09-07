# ADR-009: Trusted database tenant binding and module persistence authority

Status: Proposed — blocks Phase 1 Release Hardening Batch A

Revision 2 audited base: `ef8ccc8bac25147200d2f8a69d9cf638a0b128f0` on frozen
`codex/adr-009-security-review`; revision branch: `codex/adr-009-revision-2`.
This revision is documentation-only. Prior proposal review base was
`4ab2434c90b9155518cf212ab4dadda700c6ea2c`. It authorizes no runtime or migration
implementation, acceptance, merge, release certification or Phase 2 work.

## Accepted rules and observed limitation

ADR-003 requires database-enforced isolation in certified shared-schema mode.
ADR-008 permits module-owned SQLAlchemy repositories and reviewed SQL inside
framework-owned transactions. ADR-005 requires atomic state/outbox and
inbox/subscriber effects. ADR-006 preserves bounded-context data ownership.
ADR-004 requires process isolation for hostile executable modules. ADR-007
requires explicit compatibility preflight and tested recovery. These rules remain
authoritative; this proposal changes the public authority surface, not those rules.

The current `TransactionalPersistence.execute(Executable, parameters)` exposes SQL
through a shared application login. RLS trusts the caller-writable custom GUC
`app.tenant_id`. The regression in
`tests/integration/test_release_hardening_tenant_binding.py` commits tenant A and B
outbox rows, confirms A's visibility, changes the GUC to B, verifies that change
succeeded, and requires the same A-only visibility afterward. On the unchanged
runtime the last assertion fails. Database errors are not accepted as success.
The fixture uses the internal UoW to obtain persistence; the attack uses the public
SDK protocol. This is kernel-eventing evidence, not installed-module certification.

FORCE RLS and a non-owner NOBYPASSRLS role cannot secure a caller-replaceable policy
input. SQL keyword filtering, private Python attributes, resetting the GUC before
every query, or a privileged setter accepting any caller-supplied UUID are not
solutions. Removing commit methods alone does not remove transaction-control SQL.

## Threat model and authority boundaries

Protect trusted in-process modules against accidental misuse, confused tenant
context, and injection through the supported persistence/expression surfaces.
Tenant identity for certified RLS-managed tenant relations must survive arbitrary
SQL executed with a runtime credential, including a compromised query compiler.
This is not a guarantee for every PostgreSQL storage or communication channel;
R2-8 defines the non-RLS boundary and exclusions. RLS does not provide business permissions
or prevent destructive authorized operations within that tenant.

Python is not a sandbox: hostile code in the web process could inspect framework
memory, steal other runtime credentials or import private internals. Such code
requires ADR-004 process/container isolation, scoped service identity, explicit
contracts, network restrictions and no direct database credentials. Database/host
administrators, migrators, the credential router, reviewed internal adapters and
signed migration artifacts are trusted. A compromise of those authorities is
outside this RLS guarantee and requires operational containment and audit.

## Proposed tenant binding by deployment mode

| Mode | Authoritative binding | Required verification |
| --- | --- | --- |
| Dedicated installation | Deployment-provisioned installation/tenant/database/login tuple, authenticated independently of request data | Authenticated TenantContext must match the sole provisioned tenant and database binding before checkout. A dedicated installation hosting multiple tenants must select one of the following two modes explicitly. |
| Database-per-tenant | Protected placement directory selects a database and tenant-specific login/credential generation from authenticated TenantContext | Verify installation, tenant, database identity and login at connection creation and checkout; credentials have CONNECT only to the assigned tenant database, with HBA/network restrictions. Never reuse one all-database login. |
| Certified shared-schema | PostgreSQL authenticated `session_user`, mapped to one active tenant by protected `bos_security.trusted_tenant_id()` | One tenant per authenticated connection for its entire lifetime. Compare resolver result with trusted TenantContext before handing out any capability; mismatch is fatal and closes the connection. |

Every mode retains tenant IDs, tenant-aware integrity constraints and scoped
capabilities. The proposed uniform policy baseline uses the same resolver/RLS
contract in dedicated and database-per-tenant databases as defense in depth;
their routing and database access restrictions remain independent boundaries.
No tenant is inferred from company, installation ID alone, a header, SQL parameter,
GUC, `current_user`, application name, search path or module-selected DSN.
Workers, jobs, workflows, event consumers and internal tenant work use the same
routing/binding checks. Broker payload identity requires trusted envelope validation.

### Protected no-argument resolver

`bos_security.trusted_tenant_id() RETURNS uuid` is a narrowly scoped SECURITY
DEFINER function owned by a separate NOLOGIN resolver owner. It looks up exactly
one active mapping for `session_user` in an administrator-controlled table. There
is no tenant argument, setter, dynamic SQL or caller-controlled expression.
The mapping records database/installation identity, role OID, exact role name,
tenant UUID and credential generation/status. The lookup cross-checks OID and name
against the current role catalog; identifiers may never be rebound to another
tenant. Absent, disabled, ambiguous or inconsistent bindings raise an error with
no fallback. Constraints enforce uniqueness per login; rotation may temporarily
map two distinct logins to the same tenant.

`session_user` is immutable **to the non-superuser runtime principal under the
role restrictions below**, not globally immutable to PostgreSQL administrators.
`SET ROLE` and SECURITY DEFINER execution change effective identity, not this
binding. The resolver must not use `current_user`. See PostgreSQL's
[session identity semantics](https://www.postgresql.org/docs/17/functions-info.html).

The function has a fixed `search_path = pg_catalog, bos_security, pg_temp`, with
`pg_temp` last; referenced relations, functions and types are schema-qualified.
Only trusted owners can CREATE in those schemas. Its definition is STABLE, never
IMMUTABLE or LEAKPROOF; it must not fold tenant identity into cached plans across
sessions. The resolver owner has SELECT on the mapping only, no mapping writes,
no ownership of tenant tables and no bypass privileges. A distinct security owner
owns the mapping/schema. Revoke PUBLIC EXECUTE in the same transaction as function
creation, then grant only required callers. Apply global routine default revocation and existing-ACL repair for every actual
creator as specified in R2-6; R2-7 specifies exact resolver-owner privileges. See
[SECURITY DEFINER precautions](https://www.postgresql.org/docs/17/sql-createfunction.html).

### Roles, grants and policies

The PostgreSQL 17 membership model is the minimum certification baseline; later
versions require the same guarantees to be revalidated.

| Principal | Attributes and authority |
| --- | --- |
| Tenant login (one per tenant/credential generation) | LOGIN, NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION, NOBYPASSRLS, NOINHERIT; owns no database/schema/table/function; direct CONNECT and protected-schema USAGE/resolver and full-binding attestor EXECUTE only, plus the membership below. |
| Runtime DML role | NOLOGIN with all elevated attributes disabled; owns nothing; explicit SELECT/INSERT/UPDATE/DELETE only on runtime-required tables, schema USAGE, resolver/attestor EXECUTE and required sequence USAGE only. No blanket ALL, grant option, TRUNCATE, REFERENCES, TRIGGER, DDL, policy/owner changes or mapping access. |
| Module/table owner | Separate NOLOGIN non-bypass role per owning bounded context; owns its schema/tables/policies and migration-created objects. No runtime membership path. FORCE RLS applies even to this owner during ordinary DML; its ability to alter policies makes it privileged. |
| Security owner / resolver owner | Separate NOLOGIN roles as above; no runtime membership path. Security owner changes binding data only through isolated provisioning operations. |
| Migrator | Separately authenticated, restricted operational login allowed to assume only approved ownership roles for reviewed migrations. No web-process secret or dependency. |
| Operations | Separately authenticated least-privilege operational identity, distinct from migrator. R2-4 fixes the grants, role-targeted policies, activation and recovery profiles for maintenance/backfill and separate backup authority; no runtime bypass. |

Tenant login membership in runtime DML is granted with `INHERIT FALSE, SET TRUE,
ADMIN FALSE`. The framework selects that DML role after authentication. It cannot
become another tenant: every tenant policy uses `session_user`. This permits DML
role reuse across tenant logins without using it as an authentication identity.
Login-to-login memberships are prohibited. Runtime DML has no other memberships.
Neither tenant nor DML roles have direct or transitive membership in owner,
resolver-owner, security-owner, migrator, operations, superuser or predefined
privileged roles. NOINHERIT alone does not prohibit SET ROLE: certify the complete
membership graph and all three membership options. See
[PostgreSQL role membership](https://www.postgresql.org/docs/17/role-membership.html).

No runtime connection is initially authenticated as an administrator and then
impersonated with SET SESSION AUTHORIZATION. Runtime attempts to change session
authorization to another identity must fail; resetting to its original login is
harmless. Do not grant parameter SET/ALTER SYSTEM authority, database CREATE/TEMP,
schema CREATE, untrusted procedural languages, extensions, foreign-server/user
mappings, file/program execution or administrative functions. Audit PUBLIC and
default grants, including EXECUTE, and revoke unsafe inherited availability.
Database PUBLIC CONNECT/TEMP and writable public-schema privileges are revoked.

For every tenant-owned table, including outbox, inbox, receipts, partitions and
module tables: `tenant_id uuid NOT NULL`, ENABLE ROW LEVEL SECURITY and FORCE ROW
LEVEL SECURITY. Require an explicit restrictive tenant fence for all runtime
roles: `USING (tenant_id = bos_security.trusted_tenant_id())` and
`WITH CHECK (tenant_id = bos_security.trusted_tenant_id())`. Pair it with explicit
permissive policies only for the permitted operations/roles; restrictive policies
alone permit nothing. Apply corresponding fences to any separately authorized
operations DML roles; cross-tenant exceptions must be separate, reviewed policies.
No additional permissive policy may OR away the tenant fence. SELECT/DELETE scope
existing rows; UPDATE checks both old visibility and new ownership; INSERT checks
new ownership. Never grant TRUNCATE as a substitute for DELETE.

Tenant-scoped unique keys and permitted foreign keys include tenant_id; global
constraints must be explicitly justified. Audit referential-integrity side
channels, views (security-invoker or equivalently certified), functions, triggers,
partition-direct access, COPY and bulk paths. RLS does not cover all table
operations and superusers/BYPASSRLS bypass it; see
[PostgreSQL RLS limits](https://www.postgresql.org/docs/17/ddl-rowsecurity.html).
Views/functions must not expose owner authority accidentally. No runtime-writable
function can be called by privileged code.

DML grants reflect the trusted runtime's required table union; the request-bound
repository capability separately enforces module ownership. This is explicitly
not database isolation between hostile modules sharing a Python process. Modules
cannot obtain a raw connection or select tables outside their registered namespace.
Internal eventing adapters alone operate on kernel outbox/inbox tables.

## Connection pools and privileged execution

Pool keys include installation, tenant, database endpoint/identity, authenticated
login and credential generation. Never retarget a connection with SET ROLE/GUC or
use a proxy's common server login. A pooler must preserve the authenticated server
session identity; otherwise that configuration is uncertifiable. No fallback to
an all-tenant connection when a tenant pool is unavailable.

Pools are lazy with zero minimum idle connections, finite per-tenant connection
and overflow limits, finite active-pool cardinality, idle TTL and LRU eviction of
idle pools only. Checked-out work is never reassigned. Eviction closes connections
and releases budget; failed reset, cancellation or uncertain transaction state
invalidates and closes the connection. Bound acquire/statement/transaction timeouts.

Enforce a global budget per PostgreSQL instance across **all** web replicas,
workers, maintenance and rotation overlap:

`sum(runtime connections) <= max_connections - reserved admin/maintenance capacity - safety margin`.

Use admission leases or statically allocated per-replica quotas whose total,
including rolling-deployment surge and pool overflow, cannot exceed that budget.
A local pool limit alone is insufficient. Lease loss must stop new acquisitions;
never reissue uncertain live capacity until connections are confirmed closed.
Bound queued acquisitions and waiting time per tenant and globally; fair admission,
rate limits and explicit retryable overload responses provide backpressure without
unbounded memory growth. Existing allocated capacity can continue during control
plane outages; no unbudgeted new capacity is allowed. Publish pool count, checked
out/idle connections, waits, rejection, eviction and binding failures without
credentials or unbounded tenant metric labels. Numerical limits and p95/p99 load
budgets must be recorded for each certified deployment profile before production.

Rotate by provisioning a new unique tenant login/secret generation, testing its
binding/grants, atomically switching routing, and draining the old generation with
a bounded deadline. Both generations consume the budget. Disable old LOGIN and
terminate remaining sessions at deadline, then remove membership/mapping/secret.
Password changes or NOLOGIN alone do not terminate existing sessions. Never reuse
a retired login/name/mapping for another tenant.

Retirement first disables ingress, new checkout and scheduled/event work, drains
or cancels active work, disables login, terminates and verifies absence of sessions,
then revokes grants/mapping and removes pools/credentials. Retention/legal hold,
exports, backups, messages and object/cache cleanup follow audited tenant lifecycle
policy; retirement is not automatic data destruction. Mapping removal alone is
insufficient because existing transaction snapshots may retain old visibility.

Operations and migrator credentials run only in separately deployed processes,
with independent secret-store ACLs, service identities and network policy. They
are unavailable in web/ordinary worker environment, settings, dependency graphs,
module callbacks and the public SDK. Bootstrap/migrations are explicit deployment
steps, never application startup. Approved cross-tenant tasks run there with
purpose-scoped authority and audit; normal workers use tenant runtime credentials.

## Replacement public SDK and single compatibility epoch

Propose exactly one breaking compatibility epoch: `sdk_epoch = 2`, with the
replacement SDK version `2.0.0`. Existing/missing epoch declarations are epoch 1;
this default is used only to reject them on an epoch-2 runtime. Exact integer epoch
match plus normal platform/SDK semantic-version ranges are mandatory. Reject
unknown, malformed, missing or mismatched epochs before module imports/registration,
migrations or activation. Artifact manifests must be readable without executing
module entry points. No compatibility aliases, unsafe feature flags, dual surface
or implicit adapter may keep epoch-1 authority active in epoch 2.

| Replacement surface | Contract and restriction |
| --- | --- |
| Immutable module declarations | Manifest, routes, permissions, metadata, event/command/query schemas and provider requirements are validated and frozen by the loader. No mutable registry, activation handle, router/container or framework registration object returns to the module. |
| Typed handler injection | Constructor/handler arguments receive only approved request-scoped capability protocols and immutable context. No DependencyKey, RequestDependencyScope, resolve/container access, MESSAGE_DISPATCHER/OBJECT_STORAGE internal keys or internal provider registry. |
| TenantRepository capability | Bound to the authenticated invocation and owning module/table declarations. Typed get/list/insert/update/delete with registered field IDs, bounded pagination and copied data DTOs/counts. No SQLAlchemy Executable/Result, Session, Connection, cursor, engine, lazy ORM object or transaction handle. |
| Closed query grammar | Field IDs, bound scalar/UUID/date/decimal values, equality/order comparisons, bounded IN, AND/OR/NOT, approved sort and pagination only. No SQL text/fragments, arbitrary functions/operators/casts, callbacks, subqueries, joins or user-defined expressions. Expansion requires a versioned reviewed contract; complex queries use reviewed internal adapters behind typed operation IDs. |
| Command and query clients | Versioned typed dispatch with framework authorization/context propagation; no tenant override or dispatcher internals. Queries are read-only. Nested commands join the framework transaction under defined failure propagation, not independent commit. |
| Event enqueue capability | Validated declared events/jobs for commands, subscribers and transactional jobs per R2-1; framework stamps tenant/actor/correlation and writes outgoing work atomically with state and inbox receipt where applicable. No direct publisher, receipt acknowledgement, UnitOfWork, commit/rollback/savepoint or transaction-control surface. |
| Tenant cache | Bound tenant/module namespace, validated relative key, bounded values/TTL/quota; no raw Redis client, global scan, arbitrary prefix, tenant argument or unbound provider. |
| Tenant object storage | Bound tenant/module namespace and authorized object IDs; bounded upload/download/delete/list and narrowly scoped short-lived URLs. No raw client, bucket/key override, traversal, arbitrary signing or unbound provider. |

All capabilities expire with invocation completion, failure or cancellation and
reject use/replay in another request, tenant, task or module. Returned values do
not expose internal authority through properties, iterators, repr or serialization.
The framework compiles repository operations using owned SQLAlchemy mappings and
owns authorization, transactions and dependency lifetimes. Repository adapters and
migrations remain bounded-context-owned; reviewed SQL stays internal per ADR-008.
Caches/object storage are not rolled back by SQL: externally visible transactional
side effects require committed outbox/job workflows and idempotency.

Ship module conversion guidance, exact replacement imports and an upgraded proof
package together at epoch 2. Inventory every installed module, reject incompatible
sets deterministically before mutation, and prohibit mixed epochs in one serving
runtime. Public event/API schema versions remain independently versioned; epoch 2
does not silently rewrite them. Existing tenant/domain UUIDs and data are preserved.

## Provisioning, transition and recovery

After acceptance only, separately reviewed administration and forward-only Alembic
revisions must implement this design. Never rewrite historical revisions, recorded
checksums, the Phase 1 tag or retained data. Provisioning is idempotent and audited:
validate tenancy mode and placement; create owner/security/DML roles and default
privileges; install protected binding/resolver; apply owning-module migrations and
RLS; provision tenant logins/grants; certify role graph and positive/negative
probes; publish routing and activate only after every gate passes. Partial failure
leaves the tenant unavailable, with resumable evidence and no default credential.

For retained databases, inventory schemas/owners/ACLs/functions/policies, module
migration history and all tenant IDs first. Reject orphan/ambiguous tenant data,
privileged legacy logins or unapproved grants. Take a verified encrypted backup and
restore checkpoint including role/ACL/binding reconstruction records and secret
references (never plaintext secrets). Stage additive changes and validate data,
then enter an explicit maintenance cutover: stop web/workers/publishers, revoke
legacy ingress/login and terminate all legacy sessions, transfer ownership and
replace every GUC policy with the certified fences, deploy the epoch-2 module set,
verify binding/pools/atomicity, and resume traffic. Preserve volumes/databases.
No live overlap of vulnerable epoch-1 processes with a certified epoch-2 database.
Delayed cleanup follows ADR-007 after the recovery window; additive staging alone
is not security certification.

Use one canonical migration graph, reviewed artifacts, exclusive migration
coordination, resumable backfills and durable inventory as already required.
Partial transition must be detected at preflight and block readiness. Forward
repair is preferred. A migration downgrade restoring GUC policies, old broad grants
or epoch-1 runtime access is **not** a supported live rollback. New security
revisions must refuse such downgrades; legacy downgrade tests remain historical
baseline evidence, not a production recovery plan.

Application rollback is allowed only to an artifact certified for epoch 2 and the
current secured schema. Otherwise remain in maintenance and restore into an
isolated target with ingress disabled. Verify backup integrity, tenant/installation
placement, migration inventory and ACLs; reconstruct bindings against fresh role
OIDs without reassigning tenant identity, issue fresh credentials, apply the secure
forward transition to older backups and rerun certification before traffic.
Fence/terminate the old deployment, revoke stale secrets, reconcile outbox/inbox
and external side effects with idempotency, and prevent two writable deployments.
Record RPO/RTO and any lost commits explicitly. Restoring a vulnerable backup never
authorizes serving it; backup rollback is not credential rollback.

## Required adversarial and production certification

Before implementation, obtain independent **Astra Extra High architecture audit**
and **GPT-5.6 Sol Max/Ultra PostgreSQL security audit** of the frozen revision.
Even two APPROVE ADR verdicts only make the proposal eligible for the user's
explicit implementation approval; they do not accept this ADR or authorize work.
REVISE ADR requires amendments/re-audit; REJECT ADR requires another tenant-binding
design. The stricter combined requirements govern any disagreement. Never amend
the frozen Revision 2 after these audits without a separate user decision.
Explicit acceptance remains a separate gate;
Batch A blockers A–F and all implementation remain stopped while Status is Proposed.

After acceptance and implementation, certification must include all of the following:

1. Real PostgreSQL tests for every supported version/mode: two tenants with known
   positive rows, before/after identity and visibility assertions, successful SET,
   SET LOCAL, set_config, RESET and RESET ALL mutations. Verify session_user and
   resolver remain A while GUC becomes B. Unexpected read/schema/connection errors
   fail. Test expected denials separately with exact SQLSTATE and narrow operation
   scopes, then prove usable A-bound behavior on a fresh transaction.
2. Denied SET ROLE/SET SESSION AUTHORIZATION to other tenants/owners/ops/migrators,
   transitive membership and INHERIT/SET/ADMIN options, row_security off, altered
   search_path/temp shadowing, function replacement/overloads, mapping writes,
   role recreation, missing/disabled bindings, default/PUBLIC grants and owner/
   BYPASSRLS misconfiguration. Catalog preflight rejects all unsafe configurations.
3. Cross-tenant SELECT/INSERT/UPDATE/DELETE, tenant-ID reassignment, UPSERT, bulk/COPY,
   PostgreSQL 17 MERGE including RETURNING (R2-9), direct partitions,
   view/function/trigger execution, foreign keys/unique leakage,
   joins and approved adapter paths. Prove FORCE RLS and USING/WITH CHECK on every
   tenant table; test that a permissive policy cannot remove the restrictive fence.
4. SDK injection through fields/values/expressions, raw Executable/Result and
   transaction SQL attempts, internal dependency keys, mutable declarations,
   returned object authority, expired/context-replayed capabilities, unauthorized
   cross-module tables, unbound cache/object access, key traversal and signed URLs.
   Missing/mismatched authenticated context must fail closed across all subsystems.
5. Pool reuse under concurrent tenants, prepared statements, reset failure, timeout,
   cancellation, failover and wrong database/credential mapping. Load-test global
   budgets across replicas/rolling surge, fairness, bounded queues, idle eviction,
   rotation overlap, retirement races and control-plane/secret-provider outages.
6. Atomic state/outbox and inbox/subscriber effects, exception/cancellation and
   uncertain commit outcomes, duplicate delivery, retry and nested dispatch; prove
   modules cannot prematurely commit or acknowledge framework-owned effects.
7. Fresh provisioning plus retained populated database transition, ownership/ACL
   drift, interrupted/backfilled migration resume, tampered inventory, old module
   rejection before execution, forbidden insecure downgrade, forward repair,
   isolated restore, credential revocation and measured RPO/RTO drills.
8. Ruff formatting/lint, strict mypy and configured Pyright, complete Phase 1 unit,
   integration, tenant-isolation, authorization and contract/conformance suites;
   installed-wheel proof module using only epoch-2 public contracts; actual
   production Uvicorn composition with separate operational credentials; secret
   canaries across errors/traceback/repr/serialization/logging and artifact scans.
   Verify jobs/events/cache/storage/search/audit tenant propagation, production
   health/readiness failure behavior, TLS/HBA/secret ACLs and operational telemetry.

Publish signed artifact/commit identities, PostgreSQL/pooler topology and versions,
role/ACL/policy inventories, migration and SDK manifests, complete test results,
load thresholds/results and restore evidence for each certified profile. A skipped
infrastructure test or passing baseline suite is not certification. Cross-tenant
exposure, unresolved authority escapes or exhausted-budget fallback blocks release.
No unsupported topology may be advertised as certified shared-schema operation.

## Revision 2 mandatory clauses and implementation acceptance tests

These clauses refine the proposal above; they do not authorize implementation.
Each `AT-R2-*` is a required future acceptance-test family, **not an executed test**.
The eight existing certification families remain mandatory together with these.
Both independent audits of ef8ccc8 returned **REVISE ADR**, not REJECT ADR, and
considered the session_user design viable. Astra Extra High identified the P2
subscriber inconsistency; GPT-5.6 Sol Ultra identified five P1 and three P2
amendments. Both accepted the recorded PostgreSQL 17.11 deliberately red regression
as valid vulnerability evidence, not a Phase 1 release-audit failure; neither
independently reran its reported checks. See the Revision 2 validation record.

### R2-1 — Invocation capability matrix (P2)

All entries require authorization, immutable context and invocation-bound capability
lifetimes. Framework code alone owns transaction creation, inbox claiming, commit,
rollback and broker acknowledgement. No row grants transaction-control authority.

| Invocation | Repository and dispatch | Outgoing events/jobs and external effects |
| --- | --- | --- |
| Route | Validate transport; typed command/query clients only, no repository | No direct enqueue; delegate to command. No transactional external mutation. |
| Command | Owning-module read/write repository; queries and nested commands join existing transaction | Declared event/job enqueue in same transaction; no precommit external mutation. |
| Query | Owning-module read-only repository and read-only query dispatch | No command, enqueue or external mutation; authorized scoped reads only. |
| Subscriber | Owning-module read/write repository; typed query/command dispatch joins inbox transaction | Declared event/job enqueue allowed inside existing transaction. No direct external mutation, publisher or acknowledgement. |
| Job | Transactional job has owning-module repository and nested dispatch in framework transaction | May enqueue declared work atomically. External-effect job runs only from committed work, gets narrowly scoped provider capability and a deterministic idempotency key; never treats provider effects as SQL rollbackable. |

Subscriber inbox receipt + state + outgoing-work records must commit atomically.
An exception/cancellation rolls all three back and permits redelivery. Unknown
commit outcome is resolved by durable receipt/work identity before acknowledgement;
redelivery cannot duplicate outgoing work. Downstream jobs also deduplicate, and
provider retries must use tenant/module/event/job-scoped idempotency keys.
Providers without a safe idempotency or reconciliation strategy are not certified
for irreversible work. The framework records external completion in a subsequent
transaction; a crash after provider success must be recoverable without duplication.

Convert the proof subscriber's current `_project` storage write into a relational
projection update plus declared storage job enqueue in the inbox transaction.
Only after commit may that job put the object and record completion. Use an
immutable event/version-specific object and a guarded latest-version pointer so
out-of-order retries cannot overwrite a newer projection. The existing mutable
`phase1-proof/value.txt` write is not itself adequate idempotency. This is conversion
guidance only; the proof module remains unchanged here.

**AT-R2-1:** Exercise all five invocation rows, denied capabilities and capability
expiry; successful subscriber enqueue; failure before/after enqueue; cancellation,
unknown commit, concurrent duplicate delivery and redelivery. Assert atomic inbox,
state and outgoing counts; no provider call before commit; crash after object put,
retry and reversed event order preserve exactly one logical result and latest value.

### R2-2 — Password-ineligible authentication and drift (P1)

Provision each tenant login with `PASSWORD NULL` as baseline credential state.
That is insufficient alone: after RESET ROLE an ordinary login can change its own
password and session defaults. Require certificate, GSS or equivalent external
identity authentication that tenant SQL cannot mint or modify. Every reachable
pg_hba rule, Unix socket, proxy, failover endpoint and direct connection path must
exclude password authentication fallback for tenant logins, including after a
self-assigned password. Client certificate verification merely added to a password
method does not satisfy password-ineligibility. External credential issuance and
revocation belong to the protected deployment authority, never a module.

A separately deployed protected security provisioner/attestation authority checks
role attributes, complete membership/ownership graph, password-null state and
`pg_db_role_setting` (role-wide and per-database), against an approved baseline.
Its narrowly authorized catalog reader may inspect required `pg_authid` columns;
password verifiers must never be returned to runtime or logs. HBA/proxy/network
configuration is checked by the deployment authority too. This is not a new module
permission, SDK capability or broadly granted `pg_authid` access.

Check before activation/connect admission, on each checkout through a fresh
protected health attestation, and continuously with a proposed maximum 30-second
recheck interval for active sessions. Self-password/default changes may succeed;
no tenant isolation claim relies on SQL denying them. Detection quarantines the
binding, stops checkout/readiness for affected tenants, fences and terminates all
its sessions, invalidates pool generations, and records redacted drift evidence.
Only isolated authority repairs password/defaults/attributes; it issues a fresh
external credential generation and re-certifies before reconnect. RESET ALL on a
pooled session is not repair of persistent role defaults. Stale generations fail
connect and checkout even if their external credential has not yet expired.

**AT-R2-2:** RESET ROLE, self-password/default changes and reconnect through every
certified HBA/proxy/socket path; prove password-only authentication cannot succeed.
Inject each role/credential/role-setting drift, including database-specific defaults;
assert detection bounds, quarantine, session termination, readiness, privileged
repair, clean new-generation reconnect and denial of stale/retired credentials.
Verify catalog privileges and secret canaries remain outside module/runtime access.

See PostgreSQL [ALTER ROLE](https://www.postgresql.org/docs/17/sql-alterrole.html)
for self-service role changes; these restrictions supplement those semantics.

### R2-3 — Full deployment-binding attestation (P1)

Keep `bos_security.trusted_tenant_id()` as the no-argument policy resolver. Add
protected no-argument `bos_security.trusted_deployment_binding()` returning only
the authenticated login's installation UUID, deployment/database UUID, actual
`current_database()` name and `pg_database` OID, tenant UUID, session login OID and
recorded exact name, credential generation, enabled/status and deployment fencing
generation. Both functions use session_user, fixed trusted search_path, static
qualified catalog/mapping access and the same fail-closed uniqueness checks.
No current_user or GUC is an identity source. Database UUID and installation UUID
are provisioned binding fields; neither OID nor database name alone is identity.

At physical connect **and every checkout**, the protected router compares the full
attestor tuple and resolver tenant to trusted expectations in an externally anchored
placement/credential directory (or signed local deployment manifest). That anchor
is outside the inspected database, not a row read back from the same clone.
Authenticate the expected endpoint/server identity as well. Require a current
exclusive writable-deployment fencing lease or equivalent offline operator fence;
a copied tuple is not proof that a writable clone is the authorized server.
Mismatch, missing/disabled state, expired fencing authority or stale generation
closes the connection before any tenant capability; there is no degraded fallback.

A copied database or writable clone may preserve OIDs and all local mapping values.
Reject it through external endpoint identity and exclusive activation fencing,
including split-brain promotion. Failover promotion must fence the old writer and
renew externally recorded activation before serving. Restore starts quarantined:
regenerate deployment/database UUID and fencing generation, reconcile actual OIDs,
rebuild login mappings and issue fresh credential generations. Preserve business
tenant UUIDs; installation UUID is preserved only for an authorized replacement,
and regenerated for a new installation. Atomically update external expectations
only after old-deployment fencing and certification. Existing allocated capacity
during control-plane outage is allowed only while its preauthorized fence remains
valid; expiration blocks work and fences sessions, not just new pool creation.

**AT-R2-3:** Mismatch each tuple field independently at connect and checkout, including
correct tenant in wrong installation/database; role rename/recreation; disabled and
stale generation; copied OID/UUID database; writable clone with identical local
mapping; wrong TLS endpoint; expired lease; concurrent promotion and restore.
Prove no capability escapes, old writer/session fencing, identity regeneration and
successful certified reconnect. Mutate GUC/current role without changing identity.

### R2-4 — Isolated operational authority (P1)

No normal web/runtime/module/public SDK process possesses these credentials or can
assume these roles. Use distinct external service identities, secret-store ACLs,
network paths and bounded activation credentials; all except the explicitly named
physical-backup role are NOREPLICATION, and all are NOSUPERUSER/NOCREATEDB/
NOCREATEROLE/NOINHERIT with no grant/admin option. Privileged bootstrap remains an
operator-controlled deployment operation, outside all ordinary processes.

| Profile | Exact proposed privilege boundary |
| --- | --- |
| Schema migration | Isolated login, NOBYPASSRLS, CONNECT and SET only to named NOLOGIN module-owner roles for signed migration artifacts; no security-owner membership. Security topology changes use separate protected provisioner. DDL ownership is inherently trusted and never exposed as module callback authority. |
| Maintenance/backfill | Isolated per-operation login, NOBYPASSRLS, CONNECT, schema USAGE and only reviewed SELECT/INSERT/UPDATE/DELETE on named tables/columns as required; no ownership, DDL, TRUNCATE or runtime/owner memberships. Default is no grants. |
| Outbox/obligation operations | Separate publisher process, NOBYPASSRLS; SELECT and only delivery-state column UPDATE on outbox, SELECT/INSERT on obligation metadata where needed; no general domain DML, inbox claiming or subscriber authority. |
| Full logical backup | Isolated expiring login with BYPASSRLS, CONNECT, schema USAGE and SELECT on enumerated backup tables/sequences only; no DML, ownership, replication or role memberships. BYPASSRLS alone does not grant SELECT. This authority is trusted across tenants and is unavailable to other profiles. |
| Physical backup | Isolated expiring REPLICATION login, no ordinary database CONNECT/table grants, HBA limited to physical replication source; no superuser or BYPASSRLS. Base-backup/WAL access is cluster-wide sensitive authority, not tenant-scoped. |

For maintenance/backfill and publisher, create distinct role-targeted permissive
policies plus restrictive USING/WITH CHECK fences keyed to a protected operation
allowlist using authenticated session_user, permitted tenant set, operation ID,
expiry and activation generation. Runtime fences apply TO tenant/DML roles, not
PUBLIC; operation fences apply only TO the approved operation role. Thus FORCE RLS
stays enabled while approved cross-tenant DML can operate within its explicit set.
No universal OR exception is added to runtime policies; no GUC selects operation
scope. An expired/missing operation activation fails closed. Mapping reads use a
separate narrow protected helper, not the tenant resolver with a fake tenant.
DDL migrators needing data backfills must use this DML profile separately.

Before activation, fence affected traffic (all traffic for schema/security cutover),
drain/terminate affected sessions, check exclusive operation lease, role/ACL/policy/
binding/default catalogs, prepared-xact absence, migration inventory and per-table,
per-tenant row counts/checksums at a consistent snapshot. Record purpose, approver,
artifact digest, scope, expiry, expected deltas and recovery checkpoint. Readiness
stays false for affected scope until postconditions pass. Online publisher service
is a separately certified standing operation with bounded renewable activation;
its approved delivery-state changes do not require taking ordinary traffic down.

After work, assert exact expected row deltas/invariants and unchanged out-of-scope
tenants, catalog/security topology, migration inventory and no prepared residue.
Revoke activation/grants/credentials, terminate sessions and verify their absence
before releasing the fence. Expiry alone cannot invalidate an old MVCC snapshot.
Interrupted work stays fenced, recovers only from durable operation/chunk journal
with idempotent resume or forward repair, and repeats pre/post assertions. Never
resume by silently granting runtime bypass or serving a half-transitioned schema.

Full logical backup uses ordinary pg_dump with row_security off (its default) and
the isolated SELECT+BYPASSRLS profile. Under FORCE RLS, owner status alone is not
sufficient: pg_dump normally errors rather than silently dumping filtered rows.
Do not use `--enable-row-security` for full backups. Tenant-filtered exports may
use that option and INSERT output with certified tenant login, but must be labeled
partial exports, not disaster-recovery backups. See
[pg_dump RLS behavior](https://www.postgresql.org/docs/17/app-pgdump.html).

Logical completeness proof inventories all schemas/tables/partitions, sequences,
routines, ACLs, non-tenant metadata and every tenant's counts/checksums under the
same exported snapshot; separately capture reviewed role/topology reconstruction
and secret references. Physical profile requires verified base-backup manifest,
continuous WAL coverage/timeline through target recovery point, all tablespaces
and isolated recovery drill. Both restore profiles compare recovered inventory,
per-tenant counts/checksums at the stated recovery point, constraints, RLS, bindings,
ACLs and outbox/inbox obligations. Account for external object-store backup and
reconciliation separately. Record RPO/RTO; exit code alone proves no completeness.

**AT-R2-4:** Each profile's positive operation and forbidden privilege paths; runtime
cannot obtain/assume any profile. Under FORCE RLS prove selected multi-tenant DML
and denial outside activation set, expiry/session termination, interrupted chunk
resume, expected counts and untouched tenants. Exercise startup/readiness fences,
publisher separation and revocation. Show ordinary non-bypass pg_dump fails on
RLS-filtered data; full logical and physical restore contain every expected tenant,
metadata and obligation; partial export cannot satisfy full-backup certification.

### R2-5 — No prepared transactions (P1)

Require `max_prepared_transactions = 0` on every serving/failover server unless a
separate 2PC ADR becomes Accepted. SQL prepared statements remain distinct and are
covered by pool tests. Protected deployment preflight, startup/readiness and
certification must assert the setting and empty `pg_prepared_xacts` across the
cluster. Retirement and restore also require no residue. Session termination does
not clear prepared transactions: unexpected residue quarantines activation until
isolated administrator review resolves each transaction with recorded business
outcome; never automatically commit or discard it. See PostgreSQL
[prepared-transaction configuration](https://www.postgresql.org/docs/17/runtime-config-resource.html#GUC-MAX-PREPARED-TRANSACTIONS).

**AT-R2-5:** Tenant PREPARE TRANSACTION fails with the expected disabled-feature
SQLSTATE and leaves no prepared transaction, durable state or outbox residue after
rollback. Prove empty catalog before/after cancellation and retirement. In isolated
future misconfiguration fixtures, nonzero setting or preexisting prepared state
blocks activation/restore; terminating the origin session is not accepted as cleanup.

### R2-6 — Global routine privilege defaults (P1)

For **each actual routine creator**, in each database, execute the global form
`ALTER DEFAULT PRIVILEGES FOR ROLE <creator> REVOKE EXECUTE ON ROUTINES FROM PUBLIC`
with no IN SCHEMA. Per-schema revocation cannot cancel global PUBLIC defaults.
Inventory direct migrator creation and creation after SET ROLE: defaults belong
to the effective creator, not inherited memberships. Repair existing function,
procedure and aggregate ACLs explicitly. Create both protected functions and
revoke PUBLIC EXECUTE in the same transaction; only then grant exact signatures
to required callers. Reject PUBLIC or unapproved grants restored by replacement,
new overloads or ownership transfer. Owner transfer is not default-ACL repair.
See [default privilege semantics](https://www.postgresql.org/docs/17/sql-alterdefaultprivileges.html).

**AT-R2-6:** Catalog-check pg_default_acl and effective routine ACLs (including null
ACL meaning built-in defaults); direct creation, SET ROLE creation, replacement,
overloads and ownership transfer must preserve exact intended grants. A fixture
with only per-schema revoke must fail certification. Concurrent sessions must
never observe a committed publicly executable resolver/attestor creation window.

### R2-7 — Resolver owner access (P2)

Distinct security owner owns bos_security schema and binding table. Resolver owner
is NOLOGIN/NOBYPASSRLS with no elevated attributes or memberships: USAGE on
bos_security, **no CREATE**, SELECT only on the binding table and only ordinary
catalog access required for qualified OID/name checks. It owns exactly the resolver
and full-binding attestor functions, with no other data ownership. Ownership entails
ability to replace those functions, so no runtime membership can reach it. Runtime
logins/DML get schema USAGE and EXECUTE only on those exact no-argument signatures,
never SELECT on mapping. Required EXECUTE on a separately reviewed operations
helper is granted only to its operational callers under R2-4, not runtime.

**AT-R2-7:** Positive resolver and attestor calls under SET ROLE, RESET ROLE and
SECURITY DEFINER; catalog assertions for distinct schema/table/function owners,
USAGE, no CREATE, exact SELECT/EXECUTE, search_path and role graph. Deny mapping
reads/writes, schema creation, shadow/overload attacks and owner assumption; detect
missing USAGE as a provisioning failure before traffic rather than masking it.

### R2-8 — Non-RLS channels and honest isolation scope (P2)

The arbitrary-SQL tenant isolation guarantee is limited to certified RLS-managed
tenant relations and audited relation access paths. It does not promise database
metadata secrecy, freedom from timing/constraint side channels or denial of service.
RLS does not isolate LISTEN/NOTIFY channels or PostgreSQL large objects. In shared
schema deployments never put sensitive data, authorization or trusted work on
LISTEN/NOTIFY; tenants sharing a database can communicate there and channel names
are not ACLs. SDK grammar rejects LISTEN/NOTIFY and arbitrary function calls, but
this is not a PostgreSQL per-role privilege that blocks arbitrary injected SQL.
A requirement to prevent that channel itself demands separate database/process
isolation and separate certification, not an invented GRANT/REVOKE control.

Forbid tenant large-object storage; use scoped object storage through committed
workflows. Audit/revoke runtime/PUBLIC access to large-object creation and access
routines where configurable, validate existing large-object ACLs and absence of
sensitive legacy objects. Such ACLs are not RLS. Inventory all reachable built-in
and extension routines, views, triggers, foreign tables, unsafe SECURITY DEFINER
paths and other non-RLS storage/communication surfaces; deny unsafe grants or reject
the profile when it cannot keep tenant content inside secured paths. Certification
must document residual catalog/notification channels rather than claiming their
absence. Hostile Python in a trusted process remains excluded under ADR-004.

**AT-R2-8:** SDK channel/large-object/expression injection rejection; raw runtime-SQL
notification probe documents the residual communication limit without pretending
denial. Prove no sensitive platform payload or authoritative work uses that channel;
exercise large-object ACL/creation paths, unsafe views/routines/extensions and
legacy-object inventory. Fail certification for sensitive non-RLS exposure; require
a separately isolated profile when the threat model requires channel suppression.

See PostgreSQL [NOTIFY](https://www.postgresql.org/docs/17/sql-notify.html) and
[large-object permissions](https://www.postgresql.org/docs/17/lo-implementation.html).

### R2-9 — Mandatory execution and proposed scale envelope (P2)

After implementation, require a dedicated mandatory tenant-binding certification
job for PostgreSQL 17 (and each additionally claimed version/topology/mode). It must
fail for absent database configuration, missing cases, any skipped tenant-binding
case or xfail, including unexpected-pass xfail. Ordinary developer invocations may
retain optional infrastructure skips; those runs cannot satisfy this required job.
This document adds no CI job. The existing one-login deliberately red reproduction
is valid historical vulnerability evidence, not the future two-login certification.

Use two real tenant logins A/B with distinct authenticated physical pools and known
positive rows. For each login, PostgreSQL 17 MERGE must exercise matched UPDATE/
DELETE, unmatched INSERT and NOT MATCHED BY SOURCE paths as applicable, tenant-ID
reassignment and RETURNING. Assert exact affected/returned rows and unchanged other
tenant rows; invisible cross-tenant targets may affect zero rows or yield specified
constraint errors, never expose/mutate another tenant. Include INSERT/UPDATE/DELETE
RETURNING, UPSERT, bulk/COPY and prepared-statement reuse. Expected denials use exact
SQLSTATE and fresh-transaction positive controls, not swallowed errors. See
[PostgreSQL 17 MERGE](https://www.postgresql.org/docs/17/sql-merge.html).

Proposed initial certification envelope (requirements, **not measured evidence**):
max_connections 200; reserve 20 admin/maintenance and 20 safety, leaving runtime
budget 160 including workers, rotation and rolling surge. Cap five runtime process
slots including surge at 32 connections each; unallocated slots confer no extra
capacity. Each tenant pool has minimum idle 0, maximum 4 and overflow 0; maximum
128 cached pools per process with 60-second idle eviction. All per-process pools
share the 32 cap. Queue limits: 8 per tenant per process, 64 per process (at most
320 globally); acquisition deadline 2 seconds, statement 5 seconds, transaction
15 seconds, rotation drain 30 seconds. Operational connections stay within the
reserved 20; no reservation may be double counted. More demanding profiles need
explicitly published budgets and fresh certification, not extrapolation.

**AT-R2-9:** Deliberately omit configuration/cases, introduce skip/xfail and prove
mandatory job failure; execute two-login isolation and MERGE/RETURNING matrix.
Run the proposed envelope with 1,000 registered tenants, at least 200 concurrently
requesting tenants, five process slots, skewed hot-tenant load and rotation overlap
for 30 minutes. Record admission fairness, rejection and errors, connection/pool/
queue maxima and eviction; require admitted-request p95 <= 500 ms and p99 <= 1 s
for a published indexed point-read/single-row-write workload and dataset/hardware.
Overload must reject within 2 seconds without cross-tenant fallback or memory
unboundedness. Publish measured values including failures; no scale claim until
these gates pass. Repeat failover, lease loss, cancellation and retirement under load.

## Consequences and alternatives

This adds tenant-role provisioning, credential rotation, bounded routing/pooling
and a deliberate SDK break while retaining PostgreSQL/SQLAlchemy/psycopg/Alembic,
module ownership and modular monolith architecture. Later tenant lifecycle,
localization, verticals, marketplace, cloud placement and LTS work must use these
contracts without new tenant hierarchies or core forks. Performance and recovery
costs require measured certification, not a silent switch to shared credentials.

A separately authenticated signed transaction assertion would require a different
ADR covering keys, replay and database verification. This proposal selects login
identity; it does not approve improvised signing, custom PostgreSQL extensions,
UUID-taking privileged setters or an all-tenant credential with SET ROLE.

No runtime fix or migration is implemented here. ADR-009 remains Proposed and the
unchanged runtime's failing regression remains a release blocker.

## Historical validation at ef8ccc8 (2026-09-07; not Revision 2 checks)

In that prior revision, only this ADR and the regression test changed from its review base. Checks ran in
`bos-review-118:development` with this checkout mounted read-only at `/app` and
`PYTHONPATH=/app/platform/src:/app/examples/proof_module/src`, selecting the exact
checkout's runtime and proof source. Commands and final outcomes:

- `ruff format --check --no-cache platform/src examples tests`: passed, 88 files.
- `ruff check --no-cache platform/src examples tests`: passed.
- `mypy --cache-dir=/tmp/mypy platform/src tests examples/proof_module/src`:
  passed, 88 source files under strict repository settings.
- `pyright platform/src examples/proof_module/src tests/integration/test_release_hardening_tenant_binding.py`:
  passed, zero errors/warnings. The tool container downloaded its Node runtime.
- `pytest -q -p no:cacheprovider tests/unit`: 111 passed.
- `pytest -q -p no:cacheprovider tests/integration/test_release_hardening_tenant_binding.py`:
  one deliberate failure at the final A-only visibility assertion; GUC mutation,
  readback and unchanged session_user assertions succeeded. PostgreSQL 17.11 exposed
  B's row instead of A's. No database exception was swallowed and no xfail added.
- `git diff --check`: passed.

Initial formatting and mypy comparison issues were corrected before the final
runs; scalar IDs avoid comparing SQLAlchemy Row objects against typed tuples.
PostgreSQL used a new `bos-adr009-revision-pg` container, network none, tmpfs data,
no host ports/retained volumes, and disposable test-only roles. The test runner
shared only that container's network namespace. Its fixture created and removed
its own unique database and replayed the five existing baseline upgrades and
teardown downgrades; no migration source was added or modified. Those historical
teardown paths do not certify the proposed secure transition or recovery.

The full integration/conformance/provider suites, installed-wheel/production
composition, load, migration-transition and restore certification were not run
for that prior revision. This is a reviewed proposal and strengthened red gate, not a
security fix or release candidate. Freeze the pushed review commit for the two
requested read-only audits; any follow-up revision requires a separate decision.
