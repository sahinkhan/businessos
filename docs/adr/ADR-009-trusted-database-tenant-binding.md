# ADR-009: Trusted database tenant binding and module persistence authority

Status: Proposed — blocks Phase 1 Release Hardening Batch A

Review base: `fix/phase1-release-hardening` at
`4ab2434c90b9155518cf212ab4dadda700c6ea2c`.
This revision is documentation/test-only. It authorizes no runtime or migration
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
Database identity must survive arbitrary SQL executed with a runtime credential,
including a compromised query compiler. RLS does not provide business permissions
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
creation, then grant only required callers. Apply equivalent default privileges
for each object-creating owner. See
[SECURITY DEFINER precautions](https://www.postgresql.org/docs/17/sql-createfunction.html).

### Roles, grants and policies

The PostgreSQL 17 membership model is the minimum certification baseline; later
versions require the same guarantees to be revalidated.

| Principal | Attributes and authority |
| --- | --- |
| Tenant login (one per tenant/credential generation) | LOGIN, NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION, NOBYPASSRLS, NOINHERIT; owns no database/schema/table/function; direct CONNECT and protected-schema USAGE/resolver EXECUTE only, plus the membership below. |
| Runtime DML role | NOLOGIN with all elevated attributes disabled; owns nothing; explicit SELECT/INSERT/UPDATE/DELETE only on runtime-required tables, schema USAGE, resolver EXECUTE and required sequence USAGE only. No blanket ALL, grant option, TRUNCATE, REFERENCES, TRIGGER, DDL, policy/owner changes or mapping access. |
| Module/table owner | Separate NOLOGIN non-bypass role per owning bounded context; owns its schema/tables/policies and migration-created objects. No runtime membership path. FORCE RLS applies even to this owner during ordinary DML; its ability to alter policies makes it privileged. |
| Security owner / resolver owner | Separate NOLOGIN roles as above; no runtime membership path. Security owner changes binding data only through isolated provisioning operations. |
| Migrator | Separately authenticated, restricted operational login allowed to assume only approved ownership roles for reviewed migrations. No web-process secret or dependency. |
| Operations | Separately authenticated least-privilege operational identity, distinct from migrator. Specific cross-tenant maintenance requires explicit grants/policies or a separately reviewed narrow privileged function, not a general runtime bypass. |

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
| Event enqueue capability | Validated declared events for commands; framework stamps tenant/actor/correlation and writes the outbox atomically. Subscribers receive repository capability only; framework claims inbox receipt and commits receipt plus effects together. No direct publisher, receipt acknowledgement, UnitOfWork, commit/rollback/savepoint or transaction-control surface. |
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
Audit findings do not accept this ADR. Explicit acceptance remains a separate gate;
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
   direct partitions, view/function/trigger execution, foreign keys/unique leakage,
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

## Validation of this documentation/test revision (2026-09-07)

Only this ADR and the regression test changed from the review base. Checks ran in
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
for this revision. This is a reviewed proposal and strengthened red gate, not a
security fix or release candidate. Freeze the pushed review commit for the two
requested read-only audits; any follow-up revision requires a separate decision.
