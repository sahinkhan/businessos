"""Audit V2 trusted actor, same-UOW, and historical chain certification."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from businessos_audit import (
    AUDIT_APPENDER_V2,
    AuditEvidenceV2,
    AuditModule,
    AuditRecord,
    AuditVerificationResult,
    QueryAuditLogsQuery,
    RecordAuditLogCommand,
    RecordAuditLogV2,
    VerifyAuditIntegrityQuery,
    compute_audit_checksum,
)
from businessos_identity import (
    DatabaseWorkloadExecutionAuthority,
    InvalidWorkloadCredential,
    PrincipalIdentity,
)
from businessos_identity.principal_binding import bind_authenticated_principal
from businessos_policy import PolicyDecisionRecordedV2
from pydantic import ValidationError
from sqlalchemy import text

from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.context import RequestContext, TenantContext
from businessos.errors import BusinessOSError
from businessos.messages import (
    Command,
    EventHandlingContext,
    HandlingContext,
    handler_transaction_view,
)
from businessos.modules import discover_modules
from businessos.modules.manifest import ModuleDependency, ModuleManifest
from businessos.modules.sdk import ModuleRegistration
from businessos.persistence import Database, SQLAlchemyUnitOfWorkFactory
from businessos.security import Authorizer
from tests.conftest import PostgreSQLTestDatabase


class _DenyAuditWrite:
    allow_audit = False

    async def is_allowed(self, principal_id: UUID, tenant: TenantContext, permission: str) -> bool:
        return permission != "foundation.audit.write" or self.allow_audit


class ProbeAuditCommand(Command):
    record_id: UUID
    fail_after_append: bool = False


class _ProbeModule:
    def __init__(self, *, direct_audit: bool = True) -> None:
        self.manifest = ModuleManifest(
            module_id="example.audit_v2_probe",
            name="Audit V2 transaction probe",
            publisher="test",
            version="1.0.0",
            platform=">=0.1,<1",
            sdk=">=0.1,<1",
            python=">=3.13",
            entry_point="tests.integration.test_audit_v2_runtime:_ProbeModule",
            dependencies=(
                (ModuleDependency(module_id="foundation.audit", version=">=0.4,<1"),)
                if direct_audit
                else ()
            ),
        )

    async def register(self, registration: ModuleRegistration) -> None:
        registration.command(ProbeAuditCommand, self._handle)

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def _handle(self, cmd: ProbeAuditCommand, ctx: HandlingContext) -> object:
        await ctx.unit_of_work.persistence.execute(
            text("INSERT INTO public.audit_v2_probe (id) VALUES (:id)"), {"id": cmd.record_id}
        )
        appender = await ctx.dependencies.resolve(AUDIT_APPENDER_V2)
        await appender.append(
            AuditEvidenceV2(
                action="probe.create", resource_type="probe", resource_id=str(cmd.record_id)
            ),
            ctx,
        )
        if cmd.fail_after_append:
            raise RuntimeError("deliberate rollback after mandatory evidence")
        return None


def _url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _context() -> RequestContext:
    return RequestContext(
        tenant=TenantContext(
            installation_id=uuid4(),
            tenant_id=uuid4(),
            principal_id=uuid4(),
            authentication_strength="mfa",
        )
    )


def _bind(context: RequestContext, *, principal_type: str = "user") -> None:
    assert context.tenant is not None
    bind_authenticated_principal(
        context,
        PrincipalIdentity(
            tenant_id=context.tenant.tenant_id,
            principal_id=context.tenant.principal_id,
            principal_type=principal_type,
            authentication_strength="mfa",
        ),
    )


async def _command(app: Any, cmd: Command, context: RequestContext) -> object:
    assert app.runtime is not None
    async with app.container.request_scope() as dependencies:
        return await app.runtime.messages.command(cmd, context, dependencies)


async def _query(app: Any, query: object, context: RequestContext) -> object:
    assert app.runtime is not None
    async with app.container.request_scope() as dependencies:
        return await app.runtime.messages.query(query, context, dependencies)


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_audit_v2_manual_actor_chain_and_same_uow(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    permission_policy = _DenyAuditWrite()
    app = create_application(
        Settings(environment="test", database_url=postgres_database.runtime_url),
        modules=(
            *(
                module
                for module in discover_modules()
                if module.manifest.module_id.startswith("foundation.")
            ),
            _ProbeModule(),
        ),
        authorizer=Authorizer(permission_policy),
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    with psycopg.connect(_url(postgres_database.migration_url)) as connection:
        connection.execute("CREATE TABLE public.audit_v2_probe (id uuid PRIMARY KEY)")
        connection.execute("GRANT SELECT, INSERT ON public.audit_v2_probe TO businessos_app")
    await app.startup()
    context = _context()
    assert context.tenant is not None
    _bind(context)
    try:
        with pytest.raises(BusinessOSError, match="Permission denied"):
            await _command(
                app,
                RecordAuditLogV2(evidence=AuditEvidenceV2(action="manual", resource_type="probe")),
                context,
            )
        permission_policy.allow_audit = True
        manual = await _command(
            app,
            RecordAuditLogV2(evidence=AuditEvidenceV2(action="manual.note", resource_type="probe")),
            context,
        )
        assert isinstance(manual, AuditRecord)
        assert manual.actor_id == str(context.tenant.principal_id)
        assert manual.provenance_v3 is not None
        assert manual.provenance_v3["path"] == "manual-command"
        permission_policy.allow_audit = False
        with pytest.raises(ValidationError):
            RecordAuditLogV2.model_validate(
                {
                    "evidence": {
                        "action": "spoof",
                        "resource_type": "probe",
                        "actor_id": str(uuid4()),
                    }
                }
            )

        rollback_id = uuid4()
        with pytest.raises(RuntimeError, match="deliberate rollback"):
            await _command(
                app, ProbeAuditCommand(record_id=rollback_id, fail_after_append=True), context
            )
        with psycopg.connect(_url(postgres_database.runtime_url)) as connection:
            connection.execute(
                "SELECT set_config('app.tenant_id', %s, false)", (str(context.tenant.tenant_id),)
            )
            assert (
                connection.execute(
                    "SELECT id FROM public.audit_v2_probe WHERE id = %s", (rollback_id,)
                ).fetchall()
                == []
            )
            assert (
                connection.execute(
                    "SELECT id FROM platform_audit.audit_logs WHERE resource_id = %s",
                    (str(rollback_id),),
                ).fetchall()
                == []
            )

        committed_id = uuid4()
        await _command(app, ProbeAuditCommand(record_id=committed_id), context)
        with psycopg.connect(_url(postgres_database.runtime_url)) as connection:
            connection.execute(
                "SELECT set_config('app.tenant_id', %s, false)", (str(context.tenant.tenant_id),)
            )
            assert connection.execute(
                "SELECT id FROM public.audit_v2_probe WHERE id = %s", (committed_id,)
            ).fetchone()
        rows = await _query(app, QueryAuditLogsQuery(tenant_id=context.tenant.tenant_id), context)
        assert isinstance(rows, list) and len(rows) == 2
        record = next(row for row in rows if row.action == "probe.create")
        assert isinstance(record, AuditRecord)
        assert record.actor_id == str(context.tenant.principal_id)
        assert record.actor_type == "user"
        assert record.integrity_version == "3"
        assert record.provenance_v3 is not None
        assert (
            record.provenance_v3["actual_actor"]["source"] == "identity.authenticated_principal.v1"
        )
        verified = cast(
            AuditVerificationResult,
            await _query(
                app, VerifyAuditIntegrityQuery(tenant_id=context.tenant.tenant_id), context
            ),
        )
        assert verified.is_valid and verified.total_records == 2
        permission_policy.allow_audit = True
        with pytest.raises(BusinessOSError, match="Caller-supplied Audit V1 provenance"):
            await _command(
                app,
                RecordAuditLogCommand(
                    tenant_id=context.tenant.tenant_id,
                    actor_id=str(uuid4()),
                    action="spoof",
                    resource_type="probe",
                ),
                context,
            )

        historical = _context()
        assert historical.tenant is not None
        _bind(historical)
        legacy_at = datetime(2025, 1, 1, tzinfo=UTC)
        second_at = datetime(2025, 1, 2, tzinfo=UTC)
        first_checksum = compute_audit_checksum(
            historical.tenant.tenant_id,
            legacy_at,
            "historical-claim",
            "legacy.create",
            "probe",
            "old-1",
            "success",
            integrity_version="1",
        )
        second_checksum = compute_audit_checksum(
            historical.tenant.tenant_id,
            second_at,
            "historical-claim",
            "legacy.update",
            "probe",
            "old-2",
            "success",
            previous_checksum=first_checksum,
            integrity_version="2",
        )
        with psycopg.connect(_url(postgres_database.runtime_url)) as connection:
            connection.execute(
                "SELECT set_config('app.tenant_id', %s, false)",
                (str(historical.tenant.tenant_id),),
            )
            for occurred_at, action, resource_id, previous, version, checksum in (
                (legacy_at, "legacy.create", "old-1", "", "1", first_checksum),
                (second_at, "legacy.update", "old-2", first_checksum, "2", second_checksum),
            ):
                connection.execute(
                    "INSERT INTO platform_audit.audit_logs "
                    "(id, tenant_id, occurred_at, actor_id, action, resource_type, "
                    "resource_id, previous_checksum, integrity_version, checksum) "
                    "VALUES (%s, %s, %s, %s, %s, 'probe', %s, %s, %s, %s)",
                    (
                        uuid4(),
                        historical.tenant.tenant_id,
                        occurred_at,
                        "historical-claim",
                        action,
                        resource_id,
                        previous,
                        version,
                        checksum,
                    ),
                )
        await _command(
            app,
            RecordAuditLogV2(
                evidence=AuditEvidenceV2(
                    action="modern.create",
                    resource_type="probe",
                )
            ),
            historical,
        )
        mixed = cast(
            AuditVerificationResult,
            await _query(
                app,
                VerifyAuditIntegrityQuery(tenant_id=historical.tenant.tenant_id),
                historical,
            ),
        )
        assert mixed.is_valid and mixed.total_records == 3
    finally:
        await app.shutdown()

    no_dependency = create_application(
        Settings(environment="test", database_url=postgres_database.runtime_url),
        modules=(
            *(
                module
                for module in discover_modules()
                if module.manifest.module_id.startswith("foundation.")
            ),
            _ProbeModule(direct_audit=False),
        ),
        authorizer=Authorizer(_DenyAuditWrite()),
    )
    await no_dependency.startup()
    try:
        denied_context = _context()
        _bind(denied_context)
        with pytest.raises(PermissionError, match="direct Audit dependency"):
            await _command(no_dependency, ProbeAuditCommand(record_id=uuid4()), denied_context)
    finally:
        await no_dependency.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_policy_projection_uses_workload_actor_and_unique_committed_event(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = create_application(
        Settings(environment="test", database_url=postgres_database.runtime_url),
        modules=(
            module
            for module in discover_modules()
            if module.manifest.module_id.startswith("foundation.")
        ),
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    installation_id, workload_id, tenant_id, origin_id = uuid4(), uuid4(), uuid4(), uuid4()
    secret = b"audit-v2-test-workload-secret-000001"
    operations = Database(Settings(database_url=postgres_database.operations_url))
    worker = Database(Settings(database_url=postgres_database.worker_url))
    ops_factory = SQLAlchemyUnitOfWorkFactory(
        operations.sessions, system_sessions=operations.sessions
    )
    worker_factory = SQLAlchemyUnitOfWorkFactory(worker.sessions)
    authority = DatabaseWorkloadExecutionAuthority()
    event = PolicyDecisionRecordedV2(
        tenant_id=tenant_id,
        correlation_id="policy-origin-correlation",
        principal_type="user",
        principal_id=origin_id,
        decision_at=datetime.now(UTC),
        mode="commit",
        action="resource.update",
        resource_namespace="example.resource",
        resource_version="2",
        record_id=uuid4(),
        allowed=True,
        reason_code="allowed",
        policy_ids=(uuid4(),),
    )
    tenant = TenantContext(
        installation_id=installation_id,
        tenant_id=tenant_id,
        principal_id=uuid4(),
        authentication_strength="worker-routing-only",
    )
    request = RequestContext(
        tenant=tenant, correlation_id=event.correlation_id, trace_id=uuid4().hex
    )
    audit = AuditModule()
    try:
        async with ops_factory.system() as unit:
            await unit.persistence.execute(
                text(
                    "INSERT INTO platform_identity.installation_workloads "
                    "(installation_id, workload_id, name, process_class, allowed_purposes, "
                    "credential_reference, credential_digest, credential_generation) "
                    "VALUES (:installation, :workload, 'audit-worker', 'event-worker', "
                    "ARRAY['event-delivery'], 'test-file-v1', :digest, 1)"
                ),
                {
                    "installation": installation_id,
                    "workload": workload_id,
                    "digest": hashlib.sha256(secret).digest(),
                },
            )
            await unit.commit()

        async with ops_factory.system() as verifier_unit:
            verified = await authority.verify(
                verifier_unit.persistence,
                installation_id=installation_id,
                workload_id=workload_id,
                process_class="event-worker",
                purpose="event-delivery",
                credential_reference="test-file-v1",
                credential=secret,
            )

        async with worker_factory.for_tenant(tenant) as unit:
            transaction = handler_transaction_view(unit)
            async with authority.bind(
                unit.persistence,
                verified=verified,
                tenant_id=tenant_id,
                source_event_id=event.event_id,
                subscriber="foundation.audit.policy_decision_v2",
                attempt_id=uuid4(),
                transaction=transaction,
            ) as binding:
                async with app.container.request_scope() as dependencies:
                    missing = EventHandlingContext(request, dependencies, transaction, None)
                    with pytest.raises(PermissionError, match="workload binding"):
                        await audit._materialize_policy_decision(event, missing)
                    wrong_tenant = EventHandlingContext(
                        RequestContext(
                            tenant=TenantContext(
                                installation_id=installation_id,
                                tenant_id=uuid4(),
                                principal_id=tenant.principal_id,
                            )
                        ),
                        dependencies,
                        transaction,
                        binding,
                    )
                    with pytest.raises(BusinessOSError, match="Target tenant"):
                        await audit._materialize_policy_decision(event, wrong_tenant)
                    context = EventHandlingContext(request, dependencies, transaction, binding)
                    await audit._materialize_policy_decision(event, context)
                    await audit._materialize_policy_decision(event, context)
            with pytest.raises(InvalidWorkloadCredential, match="not active"):
                await audit._materialize_policy_decision(event, context)
            await unit.commit()

        concurrent_event = event.model_copy(update={"event_id": uuid4()})

        async def duplicate_delivery(delivery_event: PolicyDecisionRecordedV2) -> None:
            async with worker_factory.for_tenant(tenant) as delivery_unit:
                delivery_transaction = handler_transaction_view(delivery_unit)
                async with authority.bind(
                    delivery_unit.persistence,
                    verified=verified,
                    tenant_id=tenant_id,
                    source_event_id=delivery_event.event_id,
                    subscriber="foundation.audit.policy_decision_v2",
                    attempt_id=uuid4(),
                    transaction=delivery_transaction,
                ) as delivery_binding:
                    async with app.container.request_scope() as delivery_dependencies:
                        await audit._materialize_policy_decision(
                            delivery_event,
                            EventHandlingContext(
                                request,
                                delivery_dependencies,
                                delivery_transaction,
                                delivery_binding,
                            ),
                        )
                await delivery_unit.commit()

        await asyncio.gather(
            duplicate_delivery(concurrent_event), duplicate_delivery(concurrent_event)
        )
        distinct_events = (
            event.model_copy(update={"event_id": uuid4()}),
            event.model_copy(update={"event_id": uuid4()}),
        )
        await asyncio.gather(*(duplicate_delivery(item) for item in distinct_events))

        with psycopg.connect(_url(postgres_database.runtime_url)) as connection:
            connection.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_id),))
            rows = connection.execute(
                "SELECT actor_id, actor_type, provenance_v3, source_event_id, "
                "previous_checksum, checksum "
                "FROM platform_audit.audit_logs WHERE tenant_id = %s "
                "ORDER BY occurred_at, id",
                (tenant_id,),
            ).fetchall()
        assert len(rows) == 4
        assert {row[3] for row in rows} == {
            event.event_id,
            concurrent_event.event_id,
            *(item.event_id for item in distinct_events),
        }
        assert [row[4] for row in rows] == ["", *(row[5] for row in rows[:-1])]
        for row in rows:
            assert row[0] == str(workload_id) and row[1] == "service_account"
            assert row[2]["origin_actor"]["id"] == str(origin_id)
            assert row[2]["actual_actor"]["id"] == str(workload_id)
    finally:
        await operations.close()
        await worker.close()
