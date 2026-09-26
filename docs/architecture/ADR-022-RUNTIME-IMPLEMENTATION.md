# ADR-022 Runtime Implementation Record

Status: STANDALONE LOCAL CERTIFICATION PASS / HOSTED AUDIT PENDING

Architecture authority: [ADR-022](../adr/ADR-022-module-scoped-database-execution-authority.md) is ACCEPTED / AUTHORITATIVE ON MAIN at `fddaa6c3880fda7f8a2ddab44d669e25915d44cc`. This record describes the implementation candidate only. ADR-017 PR #45 remains draft and blocked; this work does not merge or implement that PR.

## Implemented boundary

The framework selects a dedicated `businessos_governance` PostgreSQL pool for the exact approved first-party Data Governance command registrations named in `database_execution.py`. Ordinary commands and all queries retain the ordinary application pool. The protected selection requires the captured handler object, command type, current contribution generation, trusted registration provenance, and a restricted first-party entitlement. Request fields and module manifests do not choose a database role. The protected UOW verifies `current_database`, `current_user`, and `session_user` before setting transaction-local tenant context. A failed protected credential rotation denies further protected admissions without falling back to the app role.

The forward revisions are core `0006_governance_outbox`, Audit `audit_0004`, and Data Governance `gov_0004`. They grant enumerated outbox append, Audit append, and legacy retention/hold operations to Governance, revoke ordinary app and worker mutation of the protected legacy retention and hold tables, and add forced tenant RLS policies. The Data Governance revision also removes legacy `PUBLIC` DML and aborts atomically if effective app/worker DML, an assumable extra role, or an inventoried indirect write surface remains. An affected installation needs reviewed operator repair before upgrade; the migration does not silently certify its prior grants. The role is separately provisioned for fresh databases and existing-volume transition. No historical revision was edited.

The protected pool validates role attributes, membership, object ownership, effective grants, and forced tenant policies at startup and credential rotation. Rotation is pinned to the configured database endpoint; a failed endpoint or privilege check disables new protected admissions. A generation entering drain is rejected before a new protected pool lease after an authorization wait.

## Local evidence

| Gate | Result |
| --- | --- |
| Fresh bootstrap role, fresh upgrade, production-derived transition, replay | PASS; isolated fresh Compose volume was created, checked, and removed |
| Full integration | 153 passed in 2213.43 seconds; exit 0 |
| Full pytest | 679 passed in 3038.70 seconds; exit 0 |
| Installed-wheel migration smoke | PASS in 307.23 seconds; installed graph, transition, upgrade, replay, and safe downgrade refusal |
| Development, production, migration-smoke images | Rebuilds PASS in 174.71, 167.86, and 15.69 seconds; all migration plans PASS |
| Rebuilt image database transition and replay | PASS on a disposable PostgreSQL database; transition, upgrade, head check, Geography downgrade, re-upgrade, final head check; database removed |
| Repository mypy and Pyright commands | PASS; mypy checked 238 source files; Pyright reported 0 errors and warnings |
| Ruff and `git diff --check` | PASS after the focused remediation |
| Focused real-PostgreSQL authority checks | Role attributes and grants, forbidden SET ROLE paths, direct app/worker mutation denial, Governance tenant RLS, actual protected command dispatch, exact handler routing, SQL identity, failed and successful credential rotation, shutdown, one-UOW Governance/Audit/outbox commit, cancellation rollback, and next-tenant isolation PASS |

The first 600-second full integration timeout occurred while tests were advancing. It was not a Docker hang or pytest deadlock. Complete integration has measured 23 minutes on an earlier run and 37:16 on this final local run.

An initial full-suite run in this certification pass showed a failure marker before being stopped for isolation; it did not print a traceback. The test at the corresponding collection position, the NATS durable-cursor provider test, passed alone and with its related provider file. The final complete 676-test run passed. The initial failure's cause was not established and is not attributed to ADR-022.

## Certification boundary

ADR-022 certifies the protected database execution authority mechanism. Its PostgreSQL probe demonstrates one protected UnitOfWork and transaction across legacy Governance state, an Audit append permitted by exact grants, and the normal transactional Eventing outbox. The probe directly inserts the Audit row; it does not invoke AuditAppenderV2. It proves the infrastructure can commit or roll back those effects together, not that a real cross-owner destructive operation has done so.

No production ADR-018 participating owner operation exists in this ADR-022 runtime branch. The first real cross-owner destructive transaction is certified with ADR-017, where that production composition is introduced. ADR-017 may not be certified or merged until a real protected Governance destructive command → admitted ADR-018 owner operation → AuditAppenderV2 → transactional outbox executes in one PostgreSQL UnitOfWork and transaction. That deferred blocking proof must establish exact owner facts, action and provider generation; real owner and Governance mutations; trusted Audit provenance; Governance SQL identity and tenant RLS; atomic commit and controlled rollback of every effect; denial of stale, wrong or unapproved providers; and absence of a second UOW, nested dispatch, SET ROLE or autonomous commit. No direct Governance write to owner-private state may substitute for the owner provider.

The ADR-022 forward revisions check Governance role attributes, membership, object ownership, and target-database connectivity immediately before each authority grant. A disposable fresh PostgreSQL volume with `businessos_governance BYPASSRLS` originally allowed `businessos migrate upgrade heads` to exit 0. After the forward-only correction, the same probe exited 1 with `unsafe Governance migration role prerequisites`; the migration transaction left no Governance, Audit, outbox, or Alembic schema behind. Both disposable volumes were removed.

The first hosted candidate `1e7165d2431eba8523e376cfc459fe2425364e23` passed exact-head CI run `36250890219`, but its independent read-only audit failed at Critical 0, High 2, Medium 1, Low 0. The findings were residual ordinary write paths on upgraded databases, incomplete startup/rotation privilege and endpoint validation, and a dispatch-versus-drain admission race. Focused negative tests and the final local gates passed after remediation. A new exact-head CI run and independent read-only audit are required before owner attestation. No owner attestation has been posted.

The protected role is not an arbitrary SQL sandbox for trusted first-party Governance code. The role-level grant and RLS inventory bounds its database authority; the admitted module and owner-operation contracts still control its intended use.
