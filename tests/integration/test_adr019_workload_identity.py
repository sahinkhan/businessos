"""PostgreSQL authority locks and role boundaries for installation workloads."""

import asyncio
import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from businessos_identity import DatabaseWorkloadExecutionAuthority, IdentityModule
from businessos_identity.contracts import InvalidWorkloadCredential
from businessos_identity.workload_operator import main as operator_main
from businessos_tenant import TenantModule
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from businessos.config import Settings
from businessos.context import TenantContext
from businessos.migrations import MigrationCoordinator
from businessos.modules import ModuleRegistry
from businessos.persistence import Database, SQLAlchemyUnitOfWorkFactory
from tests.conftest import PostgreSQLTestDatabase


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_workload_revocation_serializes_with_tenant_transaction(
    postgres_database: PostgreSQLTestDatabase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ModuleRegistry(platform_version="0.1.0", sdk_version="0.1.0")
    registry.add(TenantModule())
    registry.add(IdentityModule())
    await MigrationCoordinator(registry).upgrade_async(postgres_database.migration_url)

    installation_id, workload_id, tenant_id = uuid4(), uuid4(), uuid4()
    tenant_b_id, tenant_b_account = uuid4(), uuid4()
    secret = b"a" * 32
    operations = Database(Settings(database_url=postgres_database.operations_url))
    runtime = Database(Settings(database_url=postgres_database.runtime_url))
    ops = SQLAlchemyUnitOfWorkFactory(operations.sessions, system_sessions=operations.sessions)
    app = SQLAlchemyUnitOfWorkFactory(runtime.sessions)
    authority = DatabaseWorkloadExecutionAuthority()
    monkeypatch.setenv("BOS_OPERATIONS_DATABASE_URL", postgres_database.operations_url)
    try:
        async with ops.system() as unit:
            await unit.persistence.execute(
                text(
                    "INSERT INTO platform_identity.installation_workloads "
                    "(installation_id, workload_id, name, process_class, allowed_purposes, "
                    "credential_reference, credential_digest, credential_generation) "
                    "VALUES (:installation, :workload, 'test-worker', 'event-worker', "
                    "ARRAY['event-delivery'], 'file-v1', :digest, 1)"
                ),
                {
                    "installation": installation_id,
                    "workload": workload_id,
                    "digest": hashlib.sha256(secret).digest(),
                },
            )
            await unit.commit()

        # Identical UUIDs are legal in the distinct tenant and installation namespaces.
        migrator = Database(Settings(database_url=postgres_database.migration_url))
        try:
            migration_factory = SQLAlchemyUnitOfWorkFactory(
                migrator.sessions, system_sessions=migrator.sessions
            )
            async with migration_factory.system() as unit:
                await unit.persistence.execute(
                    text(
                        "INSERT INTO platform_tenant.tenants "
                        "(id, tenant_id, slug, name, status, deployment_mode, region) "
                        "VALUES (:tenant, :tenant, 'workload-namespace-test', "
                        "'Workload namespace test', 'active', 'dedicated', 'test')"
                    ),
                    {"tenant": tenant_id},
                )
                await unit.persistence.execute(
                    text(
                        "INSERT INTO platform_identity.service_accounts "
                        "(id, tenant_id, name, credential_secret_reference) "
                        "VALUES (:id, :tenant, 'separate-tenant-account', 'unrelated-reference')"
                    ),
                    {"id": workload_id, "tenant": tenant_id},
                )
                await unit.persistence.execute(
                    text(
                        "INSERT INTO platform_tenant.tenants "
                        "(id, tenant_id, slug, name, status, deployment_mode, region) "
                        "VALUES (:tenant, :tenant, 'workload-namespace-test-b', "
                        "'Workload namespace test B', 'active', 'dedicated', 'test')"
                    ),
                    {"tenant": tenant_b_id},
                )
                await unit.persistence.execute(
                    text(
                        "INSERT INTO platform_identity.service_accounts "
                        "(id, tenant_id, name, credential_secret_reference) "
                        "VALUES (:id, :tenant, 'tenant-b-account', 'unrelated-reference-b')"
                    ),
                    {"id": tenant_b_account, "tenant": tenant_b_id},
                )
                await unit.commit()
        finally:
            await migrator.close()

        async with ops.system() as unit:
            verified = await authority.verify(
                unit.persistence,
                installation_id=installation_id,
                workload_id=workload_id,
                process_class="event-worker",
                purpose="event-delivery",
                credential_reference="file-v1",
                credential=secret,
            )
            await unit.commit()

        with pytest.raises(InvalidWorkloadCredential):
            async with ops.system() as unit:
                await authority.verify(
                    unit.persistence,
                    installation_id=uuid4(),
                    workload_id=workload_id,
                    process_class="event-worker",
                    purpose="event-delivery",
                    credential_reference="file-v1",
                    credential=secret,
                )

        with pytest.raises(InvalidWorkloadCredential, match="tenant"):
            async with app.for_tenant(TenantContext(installation_id, tenant_id, uuid4())) as unit:
                async with authority.bind(
                    unit.persistence,
                    verified=verified,
                    tenant_id=tenant_b_id,
                    source_event_id=uuid4(),
                    subscriber="test.mismatched-tenant",
                    attempt_id=uuid4(),
                    transaction=object(),  # type: ignore[arg-type]
                ):
                    pytest.fail("cross-tenant binding was admitted")

        with pytest.raises(DBAPIError):
            async with app.for_tenant(TenantContext(installation_id, tenant_id, uuid4())) as unit:
                await unit.persistence.execute(
                    text("SELECT workload_id FROM platform_identity.installation_workloads")
                )

        # These synthetic source IDs exercise Identity's lock and tenant check.
        # The platform source verifier establishes committed event provenance
        # before this trusted framework binding call in an actual delivery.
        # The same verified installation worker receives distinct bindings and
        # database RLS contexts for two tenants; neither account crosses over.
        for current_tenant, expected_account in (
            (tenant_id, workload_id),
            (tenant_b_id, tenant_b_account),
        ):
            async with app.for_tenant(
                TenantContext(installation_id, current_tenant, uuid4())
            ) as unit:
                transaction = object()
                async with authority.bind(
                    unit.persistence,
                    verified=verified,
                    tenant_id=current_tenant,
                    source_event_id=uuid4(),
                    subscriber="test.multitenant",
                    attempt_id=uuid4(),
                    transaction=transaction,  # type: ignore[arg-type]
                ) as binding:
                    assert binding.tenant_id == current_tenant
                    result = await unit.persistence.execute(
                        text("SELECT id FROM platform_identity.service_accounts")
                    )
                    assert result.scalars().all() == [expected_account]
                    await unit.commit()

        update_started = asyncio.Event()
        update_finished = asyncio.Event()

        async def revoke() -> None:
            update_started.set()
            await asyncio.to_thread(
                operator_main,
                ["disable", str(installation_id), str(workload_id)],
            )
            update_finished.set()

        tenant = TenantContext(installation_id, tenant_id, uuid4())
        async with app.for_tenant(tenant) as unit:
            transaction = object()
            async with authority.bind(
                unit.persistence,
                verified=verified,
                tenant_id=tenant_id,
                source_event_id=uuid4(),
                subscriber="test.subscriber",
                attempt_id=uuid4(),
                transaction=transaction,  # type: ignore[arg-type]
            ) as binding:
                binding.assert_active(transaction)  # type: ignore[arg-type]
                revocation = asyncio.create_task(revoke())
                await asyncio.wait_for(update_started.wait(), timeout=5)
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(update_finished.wait(), timeout=0.1)
                await unit.commit()
        await asyncio.wait_for(revocation, timeout=5)
        async with app.for_tenant(tenant) as unit:
            result = await unit.persistence.execute(
                text(
                    "SELECT active FROM platform_identity.service_accounts "
                    "WHERE id=:id AND tenant_id=:tenant"
                ),
                {"id": workload_id, "tenant": tenant_id},
            )
            assert result.scalar_one() is True
        async with ops.system() as unit:
            with pytest.raises(InvalidWorkloadCredential):
                await authority.verify(
                    unit.persistence,
                    installation_id=installation_id,
                    workload_id=workload_id,
                    process_class="event-worker",
                    purpose="event-delivery",
                    credential_reference="file-v1",
                    credential=secret,
                )

        rotating_id = uuid4()
        replacement = b"b" * 32
        old_file = tmp_path / "old-workload-secret"
        new_file = tmp_path / "new-workload-secret"
        await asyncio.to_thread(old_file.write_bytes, secret)
        await asyncio.to_thread(new_file.write_bytes, replacement)
        await asyncio.to_thread(
            operator_main,
            [
                "register",
                str(installation_id),
                str(rotating_id),
                "--name",
                "rotating-worker",
                "--process-class",
                "event-worker",
                "--purpose",
                "event-delivery",
                "--credential-reference",
                "file-v1",
                "--credential-file",
                str(old_file),
            ],
        )
        async with ops.system() as unit:
            old_proof = await authority.verify(
                unit.persistence,
                installation_id=installation_id,
                workload_id=rotating_id,
                process_class="event-worker",
                purpose="event-delivery",
                credential_reference="file-v1",
                credential=secret,
            )
            await unit.commit()

        rotation_started = asyncio.Event()
        rotation_finished = asyncio.Event()

        async def rotate() -> None:
            rotation_started.set()
            await asyncio.to_thread(
                operator_main,
                [
                    "rotate",
                    str(installation_id),
                    str(rotating_id),
                    "--credential-reference",
                    "file-v2",
                    "--credential-file",
                    str(new_file),
                ],
            )
            rotation_finished.set()

        async with app.for_tenant(tenant) as unit:
            transaction = object()
            async with authority.bind(
                unit.persistence,
                verified=old_proof,
                tenant_id=tenant_id,
                source_event_id=uuid4(),
                subscriber="test.rotation",
                attempt_id=uuid4(),
                transaction=transaction,  # type: ignore[arg-type]
            ):
                rotation = asyncio.create_task(rotate())
                await asyncio.wait_for(rotation_started.wait(), timeout=5)
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(rotation_finished.wait(), timeout=0.1)
                await unit.commit()
        await asyncio.wait_for(rotation, timeout=5)
        async with app.for_tenant(tenant) as unit:
            with pytest.raises(InvalidWorkloadCredential):
                async with authority.operation(
                    unit.persistence, verified=old_proof, purpose="event-delivery"
                ):
                    pytest.fail("stale credential generation was admitted")
        async with ops.system() as unit:
            with pytest.raises(InvalidWorkloadCredential):
                await authority.verify(
                    unit.persistence,
                    installation_id=installation_id,
                    workload_id=rotating_id,
                    process_class="event-worker",
                    purpose="event-delivery",
                    credential_reference="file-v1",
                    credential=secret,
                )
        async with ops.system() as unit:
            new_proof = await authority.verify(
                unit.persistence,
                installation_id=installation_id,
                workload_id=rotating_id,
                process_class="event-worker",
                purpose="event-delivery",
                credential_reference="file-v2",
                credential=replacement,
            )
            assert new_proof.credential_generation == 2
        await asyncio.to_thread(
            operator_main,
            [
                "set-authority",
                str(installation_id),
                str(rotating_id),
                "--process-class",
                "event-worker",
                "--purpose",
                "event-publisher",
            ],
        )
        async with ops.system() as unit:
            with pytest.raises(InvalidWorkloadCredential):
                await authority.verify(
                    unit.persistence,
                    installation_id=installation_id,
                    workload_id=rotating_id,
                    process_class="event-worker",
                    purpose="event-delivery",
                    credential_reference="file-v2",
                    credential=replacement,
                )
    finally:
        await runtime.close()
        await operations.close()
