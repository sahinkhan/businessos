"""Focused PostgreSQL certification for the rebuilt ADR-017 owner path."""

import asyncio
import io
import os
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from time import monotonic
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import boto3
import psycopg
import pytest
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from businessos_data_governance import (
    DestructiveCleanupRequestedV2,
    ExecuteDestructiveLifecycleV2,
    ExpiryAction,
    HoldScope,
    PlaceRetentionHoldV2,
    ReleaseRetentionHoldV2,
    ReplaceRetentionPolicyV2,
    RetentionSubjectKey,
    SetRetentionPolicyV2,
)
from businessos_data_governance.retention_v2 import lock_governance_scope
from businessos_identity import PrincipalIdentity
from businessos_identity.contracts import TenantExecutionBinding, WorkloadIdentityFacts
from businessos_identity.principal_binding import bind_authenticated_principal
from businessos_proof.module import ProofModule, ProofStored, StoreProof
from sqlalchemy import text

from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.context import RequestContext, TenantContext, bind_request_context
from businessos.errors import BusinessOSError, ConfigurationError
from businessos.messages import EventHandlingContext, handler_transaction_view
from businessos.migrations import MigrationCoordinator
from businessos.modules import ModuleRegistry, discover_modules
from businessos.modules.installation_inventory import approved_artifacts_from_operator_inventory
from businessos.persistence import Database, SQLAlchemyUnitOfWorkFactory
from businessos.persistence.uow import SQLAlchemyUnitOfWork
from businessos.providers import S3ObjectStorageProvider
from businessos.security import Authorizer
from businessos.version import runtime_version
from tests.conftest import PostgreSQLTestDatabase
from tests.fenced_storage import InMemoryFencedStorage


@pytest.mark.integration
@pytest.mark.providers
@pytest.mark.asyncio
@pytest.mark.parametrize("state", ("Disabled", "Enabled", "Suspended"))
@pytest.mark.parametrize("key,content", (("records/item.txt", None), ("value.txt", b"survivor")))
async def test_adr017_versioned_s3_erases_all_prior_plaintext(
    request: pytest.FixtureRequest, state: str, key: str, content: bytes | None
) -> None:
    endpoint = os.getenv("BOS_TEST_S3_ENDPOINT")
    access = os.getenv("BOS_TEST_S3_ACCESS_KEY")
    secret = os.getenv("BOS_TEST_S3_SECRET_KEY")
    if not all((endpoint, access, secret)):
        pytest.skip("Real S3 test endpoint is not configured")
    bucket = f"businessos-version-erasure-{uuid4().hex}"
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name="us-east-1",
    )
    client.create_bucket(Bucket=bucket)

    def remove_bucket() -> None:
        listed = client.list_object_versions(Bucket=bucket)
        for group in ("Versions", "DeleteMarkers"):
            for item in listed.get(group, []):
                client.delete_object(Bucket=bucket, Key=item["Key"], VersionId=item["VersionId"])
        client.delete_bucket(Bucket=bucket)

    request.addfinalizer(remove_bucket)
    if state != "Disabled":
        client.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
    tenant_id = uuid4()
    object_key = f"tenant/{tenant_id}/{key}"
    old_ids = [
        client.put_object(Bucket=bucket, Key=object_key, Body=f"secret-{i}".encode()).get(
            "VersionId", "null"
        )
        for i in range(3)
    ]
    if state != "Disabled":
        client.delete_object(Bucket=bucket, Key=object_key)  # historical delete marker
        old_ids.append(
            client.put_object(Bucket=bucket, Key=object_key, Body=b"post-marker-secret")[
                "VersionId"
            ]
        )
    if state == "Suspended":
        client.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Suspended"})
        old_ids.append(
            client.put_object(Bucket=bucket, Key=object_key, Body=b"suspended-secret").get(
                "VersionId", "null"
            )
        )
    storage = S3ObjectStorageProvider(
        bucket=bucket,
        endpoint_url=endpoint,
        access_key=access,
        secret_key=secret,
        region_name="us-east-1",
    )
    with bind_request_context(_request(tenant_id)):
        prior = await storage.version(tenant_id, key)
        assert await storage.compare_and_reconcile(tenant_id, key, prior, content)
        current = await storage.version(tenant_id, key)
        assert current is not None
        await storage.erase_prior_versions(tenant_id, key, current)
        if content is None:
            with pytest.raises(FileNotFoundError):
                await storage.get(tenant_id, key)
        else:
            assert await storage.get(tenant_id, key) == content
    remaining = client.list_object_versions(Bucket=bucket, Prefix=object_key)
    assert len(remaining.get("Versions", [])) == 1
    assert not remaining.get("DeleteMarkers")
    for version_id in old_ids:
        if version_id == "null":
            continue  # Null versions are overwritten in disabled/suspended mode.
        with pytest.raises(ClientError):
            client.get_object(Bucket=bucket, Key=object_key, VersionId=version_id)


@pytest.mark.integration
@pytest.mark.providers
@pytest.mark.asyncio
@pytest.mark.parametrize("ordering", ("late", "before", "absent"))
async def test_adr017_versioned_s3_cancelled_write_cannot_survive_erasure(
    request: pytest.FixtureRequest, ordering: str
) -> None:
    endpoint = os.getenv("BOS_TEST_S3_ENDPOINT")
    access = os.getenv("BOS_TEST_S3_ACCESS_KEY")
    secret = os.getenv("BOS_TEST_S3_SECRET_KEY")
    if not all((endpoint, access, secret)):
        pytest.skip("Real S3 test endpoint is not configured")
    bucket = f"businessos-version-race-{uuid4().hex}"
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name="us-east-1",
    )
    client.create_bucket(Bucket=bucket)
    client.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})

    def remove_bucket() -> None:
        listed = client.list_object_versions(Bucket=bucket)
        for group in ("Versions", "DeleteMarkers"):
            for item in listed.get(group, []):
                client.delete_object(Bucket=bucket, Key=item["Key"], VersionId=item["VersionId"])
        client.delete_bucket(Bucket=bucket)

    request.addfinalizer(remove_bucket)
    tenant_id = uuid4()
    key = "records/race.txt"
    object_key = f"tenant/{tenant_id}/{key}"
    if ordering != "absent":
        client.put_object(Bucket=bucket, Key=object_key, Body=b"previous-secret")

    class PausedClient:
        exceptions = client.exceptions

        def __init__(self) -> None:
            self.started = threading.Event()
            self.release = threading.Event()
            self.finished = threading.Event()
            self.failed = False

        def __getattr__(self, name: str) -> Any:
            return getattr(client, name)

        def put_object(self, **kwargs: Any) -> Any:
            if kwargs["Body"].endswith(b"stale-secret"):
                self.started.set()
                if not self.release.wait(15):
                    raise TimeoutError("Delayed S3 request was not released")
                try:
                    return client.put_object(**kwargs)
                except ClientError:
                    self.failed = True
                    raise
                finally:
                    self.finished.set()
            return client.put_object(**kwargs)

    paused = PausedClient()
    storage = S3ObjectStorageProvider(
        bucket=bucket,
        endpoint_url=endpoint,
        access_key=access,
        secret_key=secret,
        region_name="us-east-1",
    )
    storage._client = paused
    with bind_request_context(_request(tenant_id)):
        old_version = await storage.version(tenant_id, key)
        old = asyncio.create_task(
            storage.compare_and_reconcile(tenant_id, key, old_version, b"stale-secret")
        )
        try:
            assert await asyncio.to_thread(paused.started.wait, 10)
            old.cancel()
            with pytest.raises(asyncio.CancelledError):
                await old
            if ordering == "before":
                paused.release.set()
                assert await asyncio.to_thread(paused.finished.wait, 10)
            current = await storage.version(tenant_id, key)
            assert await storage.compare_and_reconcile(tenant_id, key, current, None)
            tombstone = await storage.version(tenant_id, key)
            assert tombstone is not None
            await storage.erase_prior_versions(tenant_id, key, tombstone)
            paused.release.set()
            assert await asyncio.to_thread(paused.finished.wait, 10)
            assert paused.failed == (ordering != "before")
            with pytest.raises(FileNotFoundError):
                await storage.get(tenant_id, key)
        finally:
            paused.release.set()
    listed = client.list_object_versions(Bucket=bucket, Prefix=object_key)
    assert len(listed.get("Versions", [])) == 1
    assert not listed.get("DeleteMarkers")


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_adr017_out_of_order_projection_keeps_latest_surviving_shared_value(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    class Storage(InMemoryFencedStorage):
        pass

    storage = Storage()
    modules = tuple(discover_modules())
    app = create_application(
        Settings(
            environment="test",
            database_url=postgres_database.runtime_url,
            governance_database_url=postgres_database.governance_url,
        ),
        modules=modules,
        approved_module_artifacts=approved_artifacts_from_operator_inventory(modules),
        resource_coordinator_ids=frozenset({"foundation.data_governance"}),
        authorizer=Authorizer(_AllowAll()),
        infrastructure_providers={"object-storage": storage},
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    await app.startup()
    tenant_id = uuid4()
    request = _request(tenant_id)
    assert request.tenant is not None
    owner = next(module for module in modules if isinstance(module, ProofModule))
    worker_database = Database(Settings(database_url=postgres_database.worker_url))
    worker_factory = SQLAlchemyUnitOfWorkFactory(worker_database.sessions)
    try:
        commands = ((uuid4(), "A"), (uuid4(), "B"))
        for command_id, value in commands:
            assert await _dispatch(
                app, StoreProof(command_id=command_id, value=value), request
            ) == {"stored": True}
        with psycopg.connect(postgres_database.administrator_url) as admin:
            records: dict[UUID, UUID] = dict(
                admin.execute(
                    "SELECT command_id, id FROM mod_example_phase1_proof.proof_records"
                ).fetchall()
            )
            admin.execute(
                "UPDATE mod_example_phase1_proof.proof_records SET created_at = %s WHERE id = %s",
                (datetime.now(UTC) - timedelta(days=1), records[commands[0][0]]),
            )
            admin.commit()
        for command_id, value in reversed(commands):
            async with worker_factory.for_tenant(request.tenant) as unit:
                with bind_request_context(request):
                    async with app.container.request_scope() as dependencies:
                        await owner._project(
                            ProofStored(
                                tenant_id=tenant_id,
                                correlation_id=request.correlation_id,
                                record_id=records[command_id],
                                command_id=command_id,
                                value=value,
                            ),
                            EventHandlingContext(
                                request, dependencies, handler_transaction_view(unit)
                            ),
                        )
                    await unit.commit()
        assert storage.objects[(tenant_id, "phase1-proof/value.txt")] == b"B"
        assert (
            storage.objects[(tenant_id, ProofModule.record_object_key(records[commands[0][0]]))]
            == b"A"
        )
        assert (
            storage.objects[(tenant_id, ProofModule.record_object_key(records[commands[1][0]]))]
            == b"B"
        )
    finally:
        await worker_database.close()
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
def test_adr017_fresh_forward_migrations(postgres_database: PostgreSQLTestDatabase) -> None:
    modules = tuple(discover_modules())
    registry = ModuleRegistry(
        platform_version=runtime_version(),
        sdk_version="0.1.0",
        approved_artifacts=approved_artifacts_from_operator_inventory(modules),
    )
    for module in modules:
        registry.add(module)
    MigrationCoordinator(registry).upgrade(postgres_database.migration_url)
    with psycopg.connect(postgres_database.administrator_url) as connection:
        revisions = {
            row[0]
            for row in connection.execute("SELECT version_num FROM alembic_version").fetchall()
        }
        assert "metadata_0001" in revisions
        assert "proof_0004" in revisions
        for table in (
            "platform_gov.retention_policies_v2",
            "platform_gov.legal_holds_v2",
            "platform_gov.destructive_decisions_v2",
        ):
            assert not connection.execute(
                "SELECT has_table_privilege('businessos_app', %s, 'UPDATE')", (table,)
            ).fetchone()[0]  # type: ignore[index]
            assert connection.execute(
                "SELECT has_table_privilege('businessos_governance', %s, 'UPDATE')", (table,)
            ).fetchone()[0]  # type: ignore[index]
            for role in ("businessos_app", "businessos_worker"):
                assert not connection.execute(
                    "SELECT has_any_column_privilege(%s, %s, 'UPDATE')", (role, table)
                ).fetchone()[0]  # type: ignore[index]
        assert connection.execute(
            "SELECT rolbypassrls FROM pg_roles WHERE rolname = 'businessos_governance'"
        ).fetchone() == (False,)
        for column in ("retention_category", "retention_anchor_at", "lifecycle", "value"):
            assert not connection.execute(
                "SELECT has_column_privilege('businessos_app', "
                "'mod_example_phase1_proof.proof_records', %s, 'UPDATE')",
                (column,),
            ).fetchone()[0]  # type: ignore[index]
        assert not connection.execute(
            "SELECT has_table_privilege('businessos_governance', "
            "'mod_example_phase1_proof.proof_records', 'UPDATE')"
        ).fetchone()[0]  # type: ignore[index]
        for column in ("lifecycle", "value", "description"):
            assert connection.execute(
                "SELECT has_column_privilege('businessos_governance', "
                "'mod_example_phase1_proof.proof_records', %s, 'UPDATE')",
                (column,),
            ).fetchone()[0]  # type: ignore[index]
    for url in (postgres_database.runtime_url, postgres_database.worker_url):
        with psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://", 1)) as user:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                user.execute("SET ROLE businessos_governance")


@pytest.mark.integration
@pytest.mark.postgres
def test_adr017_existing_category_free_hold_stays_all_scope(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    modules = tuple(discover_modules())
    registry = ModuleRegistry(
        platform_version=runtime_version(),
        sdk_version="0.1.0",
        approved_artifacts=approved_artifacts_from_operator_inventory(modules),
    )
    for module in modules:
        registry.add(module)
    migrations = MigrationCoordinator(registry)
    migrations.upgrade(postgres_database.migration_url, "gov_0004")
    tenant_id, hold_id = uuid4(), uuid4()
    with psycopg.connect(postgres_database.administrator_url) as admin:
        admin.execute(
            "INSERT INTO platform_gov.legal_holds "
            "(id, tenant_id, code, name, reason, entity_type, entity_id, placed_by) "
            "VALUES (%s, %s, 'preserved', 'Preserved', 'litigation', 'proof_record', NULL, "
            "'owner')",
            (hold_id, tenant_id),
        )
        admin.commit()
    migrations.upgrade(postgres_database.migration_url)
    with psycopg.connect(postgres_database.administrator_url) as admin:
        assert admin.execute(
            "SELECT hold_scope, entity_id, reason, is_active "
            "FROM platform_gov.legal_holds WHERE id = %s",
            (hold_id,),
        ).fetchone() == ("ALL", None, "litigation", True)


@pytest.mark.integration
@pytest.mark.postgres
def test_adr017_dirty_legacy_policy_preflight_refuses_without_rewriting(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    modules = tuple(discover_modules())
    registry = ModuleRegistry(
        platform_version=runtime_version(),
        sdk_version="0.1.0",
        approved_artifacts=approved_artifacts_from_operator_inventory(modules),
    )
    for module in modules:
        registry.add(module)
    migrations = MigrationCoordinator(registry)
    migrations.upgrade(postgres_database.migration_url, "gov_0004")
    tenant_id, policy_id = uuid4(), uuid4()
    with psycopg.connect(postgres_database.administrator_url) as admin:
        admin.execute(
            "INSERT INTO platform_gov.data_classifications "
            "(code, name, sensitivity_level) VALUES ('proof', 'Proof', 1)"
        )
        admin.execute(
            "INSERT INTO platform_gov.retention_policies "
            "(id, tenant_id, code, name, entity_type, classification_code, "
            "retention_period_days, action_on_expiry) "
            "VALUES (%s, %s, 'legacy', 'Legacy', 'proof_record', 'proof', 1, 'purge')",
            (policy_id, tenant_id),
        )
        admin.commit()
    with pytest.raises(RuntimeError, match=str(policy_id)):
        migrations.upgrade(postgres_database.migration_url)
    with psycopg.connect(postgres_database.administrator_url) as admin:
        assert admin.execute(
            "SELECT code, retention_period_days, action_on_expiry "
            "FROM platform_gov.retention_policies WHERE id = %s",
            (policy_id,),
        ).fetchone() == ("legacy", 1, "purge")
        assert "gov_0005" not in {
            row[0] for row in admin.execute("SELECT version_num FROM alembic_version")
        }


class _AllowAll:
    async def is_allowed(self, principal_id: Any, tenant: TenantContext, permission: str) -> bool:
        return True


class _ReadyStorage:
    async def readiness(self) -> None:
        return None


async def _dispatch(app: Any, command: Any, request: RequestContext) -> object:
    assert app.runtime is not None
    async with app.container.request_scope() as dependencies:
        return await app.runtime.messages.command(command, request, dependencies)


@asynccontextmanager
async def _running_app(database: PostgreSQLTestDatabase) -> Any:
    modules = tuple(discover_modules())
    app = create_application(
        Settings(
            environment="test",
            database_url=database.runtime_url,
            governance_database_url=database.governance_url,
        ),
        modules=modules,
        approved_module_artifacts=approved_artifacts_from_operator_inventory(modules),
        resource_coordinator_ids=frozenset({"foundation.data_governance"}),
        authorizer=Authorizer(_AllowAll()),
        infrastructure_providers={"object-storage": _ReadyStorage()},
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(database.migration_url)
    await app.startup()
    try:
        yield app
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_adr017_hold_scopes_and_release_gate_purge(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    async with _running_app(postgres_database) as app:
        tenant_id = uuid4()
        request = _request(tenant_id)
        record_id = await _eligible_record(app, postgres_database, request)
        await _purge_policy(app, request, tenant_id)
        subject = _subject(tenant_id, record_id)
        for scope, category in (
            (HoldScope.ALL, None),
            (HoldScope.CATEGORY, "proof"),
            (HoldScope.RECORD, None),
        ):
            hold_id = await _dispatch(
                app,
                PlaceRetentionHoldV2(
                    subject=subject,
                    scope=scope,
                    retention_category=category,
                    reason="legal preservation",
                ),
                request,
            )
            with pytest.raises(BusinessOSError, match="Active legal hold"):
                await _dispatch(
                    app,
                    ExecuteDestructiveLifecycleV2(subject=subject, action=ExpiryAction.PURGE),
                    request,
                )
            await _dispatch(
                app, ReleaseRetentionHoldV2(tenant_id=tenant_id, hold_id=hold_id), request
            )
        assert await _dispatch(
            app,
            ExecuteDestructiveLifecycleV2(subject=subject, action=ExpiryAction.PURGE),
            request,
        )
        with pytest.raises(BusinessOSError):
            await _dispatch(
                app,
                ExecuteDestructiveLifecycleV2(subject=subject, action=ExpiryAction.PURGE),
                request,
            )
        with pytest.raises(BusinessOSError):
            await _dispatch(
                app,
                PlaceRetentionHoldV2(subject=subject, scope=HoldScope.RECORD, reason="too late"),
                request,
            )


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_adr017_owner_audit_decision_outbox_rollback_together(
    postgres_database: PostgreSQLTestDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _running_app(postgres_database) as app:
        tenant_id = uuid4()
        request = _request(tenant_id)
        record_id = await _eligible_record(app, postgres_database, request)
        await _purge_policy(app, request, tenant_id)
        with psycopg.connect(postgres_database.administrator_url) as admin:
            baseline = admin.execute(
                "SELECT count(*) FROM eventing.outbox_messages WHERE tenant_id = %s",
                (tenant_id,),
            ).fetchone()[0]  # type: ignore[index]
        observed: dict[str, Any] = {}

        async def fail_after_all_writes(unit: SQLAlchemyUnitOfWork) -> None:
            assert unit.session is not None
            await unit.session.flush()
            identity = await unit.session.execute(
                text(
                    "SELECT current_user, session_user, txid_current(), "
                    "(SELECT count(*) FROM platform_gov.destructive_decisions_v2 "
                    " WHERE tenant_id = :tenant), "
                    "(SELECT count(*) FROM platform_audit.audit_logs "
                    " WHERE tenant_id = :tenant), "
                    "(SELECT count(*) FROM eventing.outbox_messages "
                    " WHERE tenant_id = :tenant), "
                    "(SELECT lifecycle FROM mod_example_phase1_proof.proof_records "
                    " WHERE id = :record)"
                ),
                {"tenant": tenant_id, "record": record_id},
            )
            observed["row"] = identity.one()
            raise RuntimeError("controlled precommit failure")

        with monkeypatch.context() as patch:
            patch.setattr(SQLAlchemyUnitOfWork, "commit", fail_after_all_writes)
            with pytest.raises(RuntimeError, match="controlled precommit failure"):
                await _dispatch(
                    app,
                    ExecuteDestructiveLifecycleV2(
                        subject=_subject(tenant_id, record_id), action=ExpiryAction.PURGE
                    ),
                    request,
                )
        assert observed["row"][0:2] == ("businessos_governance", "businessos_governance")
        assert observed["row"][3:] == (1, 1, baseline + 1, "purged")
        with psycopg.connect(postgres_database.administrator_url) as admin:
            assert (
                admin.execute(
                    "SELECT lifecycle FROM mod_example_phase1_proof.proof_records WHERE id = %s",
                    (record_id,),
                ).fetchone()[0]  # type: ignore[index]
                == "current"
            )
            assert (
                admin.execute(
                    "SELECT count(*) FROM platform_gov.destructive_decisions_v2 "
                    "WHERE tenant_id = %s",
                    (tenant_id,),
                ).fetchone()[0]  # type: ignore[index]
                == 0
            )
            assert (
                admin.execute(
                    "SELECT count(*) FROM platform_audit.audit_logs WHERE tenant_id = %s",
                    (tenant_id,),
                ).fetchone()[0]  # type: ignore[index]
                == 0
            )
            assert (
                admin.execute(
                    "SELECT count(*) FROM eventing.outbox_messages WHERE tenant_id = %s",
                    (tenant_id,),
                ).fetchone()[0]  # type: ignore[index]
                == baseline
            )


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize("first_kind", ["hold", "purge", "purge_pair"])
async def test_adr017_hold_purge_commit_order_is_serial(
    postgres_database: PostgreSQLTestDatabase,
    monkeypatch: pytest.MonkeyPatch,
    first_kind: str,
) -> None:
    async with _running_app(postgres_database) as app:
        tenant_id = uuid4()
        request = _request(tenant_id)
        record_id = await _eligible_record(app, postgres_database, request)
        await _purge_policy(app, request, tenant_id)
        subject = _subject(tenant_id, record_id)
        hold = PlaceRetentionHoldV2(subject=subject, scope=HoldScope.RECORD, reason="preserve")
        purge = ExecuteDestructiveLifecycleV2(subject=subject, action=ExpiryAction.PURGE)
        first, second = (
            (hold, purge)
            if first_kind == "hold"
            else (purge, purge if first_kind == "purge_pair" else hold)
        )
        entered, release = asyncio.Event(), asyncio.Event()
        original_commit = SQLAlchemyUnitOfWork.commit
        pauses = 0

        async def paused_commit(unit: SQLAlchemyUnitOfWork) -> None:
            nonlocal pauses
            pauses += 1
            if pauses == 1:
                entered.set()
                await release.wait()
            await original_commit(unit)

        with monkeypatch.context() as patch:
            patch.setattr(SQLAlchemyUnitOfWork, "commit", paused_commit)
            first_task = asyncio.create_task(_dispatch(app, first, request))
            await asyncio.wait_for(entered.wait(), timeout=8)
            second_task = asyncio.create_task(_dispatch(app, second, request))
            try:
                await asyncio.sleep(0.15)
                assert not second_task.done()
            finally:
                release.set()
            assert await asyncio.wait_for(first_task, timeout=8)
            with pytest.raises(BusinessOSError) as error:
                await asyncio.wait_for(second_task, timeout=8)
            assert error.value.code == (
                "legal_hold_active" if first_kind == "hold" else "subject_already_removed"
            )


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_adr017_advisory_timeout_rolls_back_and_release_allows_retry(
    postgres_database: PostgreSQLTestDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    import businessos_data_governance.retention_v2 as retention_v2

    async with _running_app(postgres_database) as app:
        tenant_id = uuid4()
        request = _request(tenant_id)
        record_id = await _eligible_record(app, postgres_database, request)
        await _purge_policy(app, request, tenant_id)
        lock_key = "\x1f".join(
            ("adr017", "entity", str(tenant_id), "example.phase1-proof", "proof_record")
        )
        connection = await psycopg.AsyncConnection.connect(postgres_database.administrator_url)
        try:
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (lock_key,)
            )
            monkeypatch.setattr(retention_v2, "_LOCK_ACQUISITION_SECONDS", 0.25)
            started = monotonic()
            with pytest.raises(BusinessOSError) as error:
                await _dispatch(
                    app,
                    ExecuteDestructiveLifecycleV2(
                        subject=_subject(tenant_id, record_id), action=ExpiryAction.PURGE
                    ),
                    request,
                )
            assert error.value.code == "retention_lock_timeout"
            assert 0.2 <= monotonic() - started < 1.5
            with psycopg.connect(postgres_database.administrator_url) as admin:
                assert admin.execute(
                    "SELECT lifecycle FROM mod_example_phase1_proof.proof_records WHERE id = %s",
                    (record_id,),
                ).fetchone() == ("current",)
                assert admin.execute(
                    "SELECT count(*) FROM platform_gov.destructive_decisions_v2 "
                    "WHERE tenant_id = %s",
                    (tenant_id,),
                ).fetchone() == (0,)
        finally:
            await connection.rollback()
            await connection.close()
        assert await _dispatch(
            app,
            ExecuteDestructiveLifecycleV2(
                subject=_subject(tenant_id, record_id), action=ExpiryAction.PURGE
            ),
            request,
        )


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_adr017_advisory_release_before_deadline_and_cancellation_cleanup(
    postgres_database: PostgreSQLTestDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    import businessos_data_governance.retention_v2 as retention_v2

    async with _running_app(postgres_database) as app:
        tenant_id = uuid4()
        request = _request(tenant_id)
        record_id = await _eligible_record(app, postgres_database, request)
        await _purge_policy(app, request, tenant_id)
        subject = _subject(tenant_id, record_id)
        entity_key = "\x1f".join(
            ("adr017", "entity", str(tenant_id), "example.phase1-proof", "proof_record")
        )
        subject_key = "\x1f".join(
            (
                "adr017",
                "subject",
                str(tenant_id),
                "example.phase1-proof",
                "example.phase1-proof.proof-record",
                "proof_record",
                str(record_id),
            )
        )
        monkeypatch.setattr(retention_v2, "_LOCK_ACQUISITION_SECONDS", 1.0)
        holder = await psycopg.AsyncConnection.connect(postgres_database.administrator_url)
        try:
            await holder.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (subject_key,)
            )
            waiting = asyncio.create_task(
                _dispatch(
                    app,
                    ExecuteDestructiveLifecycleV2(subject=subject, action=ExpiryAction.PURGE),
                    request,
                )
            )
            await asyncio.sleep(0.15)
            assert not waiting.done()
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
            probe = await psycopg.AsyncConnection.connect(postgres_database.administrator_url)
            try:
                result = await probe.execute(
                    "SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))",
                    (entity_key,),
                )
                assert (await result.fetchone()) == (True,)
            finally:
                await probe.rollback()
                await probe.close()
            resumed = asyncio.create_task(
                _dispatch(
                    app,
                    ExecuteDestructiveLifecycleV2(subject=subject, action=ExpiryAction.PURGE),
                    request,
                )
            )
            await asyncio.sleep(0.15)
            assert not resumed.done()
            await holder.rollback()
            assert await asyncio.wait_for(resumed, timeout=3)
        finally:
            await holder.rollback()
            await holder.close()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_adr017_other_tenant_advisory_lock_does_not_block_purge(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    async with _running_app(postgres_database) as app:
        blocked_tenant = uuid4()
        active_tenant = uuid4()
        request = _request(active_tenant)
        record_id = await _eligible_record(app, postgres_database, request)
        await _purge_policy(app, request, active_tenant)
        other_key = "\x1f".join(
            ("adr017", "entity", str(blocked_tenant), "example.phase1-proof", "proof_record")
        )
        holder = await psycopg.AsyncConnection.connect(postgres_database.administrator_url)
        try:
            await holder.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (other_key,)
            )
            assert await asyncio.wait_for(
                _dispatch(
                    app,
                    ExecuteDestructiveLifecycleV2(
                        subject=_subject(active_tenant, record_id), action=ExpiryAction.PURGE
                    ),
                    request,
                ),
                timeout=2,
            )
        finally:
            await holder.rollback()
            await holder.close()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_adr017_policy_replacement_waits_for_active_purge(
    postgres_database: PostgreSQLTestDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _running_app(postgres_database) as app:
        tenant_id = uuid4()
        request = _request(tenant_id)
        record_id = await _eligible_record(app, postgres_database, request)
        await _purge_policy(app, request, tenant_id)
        with psycopg.connect(postgres_database.administrator_url) as admin:
            old_policy = admin.execute(
                "SELECT id FROM platform_gov.retention_policies_v2 "
                "WHERE tenant_id = %s AND retention_category = 'proof'",
                (tenant_id,),
            ).fetchone()
        assert old_policy is not None
        entered, release = asyncio.Event(), asyncio.Event()
        original_commit = SQLAlchemyUnitOfWork.commit

        async def paused_commit(unit: SQLAlchemyUnitOfWork) -> None:
            entered.set()
            await release.wait()
            await original_commit(unit)

        with monkeypatch.context() as patch:
            patch.setattr(SQLAlchemyUnitOfWork, "commit", paused_commit)
            purge = asyncio.create_task(
                _dispatch(
                    app,
                    ExecuteDestructiveLifecycleV2(
                        subject=_subject(tenant_id, record_id), action=ExpiryAction.PURGE
                    ),
                    request,
                )
            )
            await asyncio.wait_for(entered.wait(), timeout=8)
            replacement = asyncio.create_task(
                _dispatch(
                    app,
                    ReplaceRetentionPolicyV2(
                        tenant_id=tenant_id,
                        old_policy_id=old_policy[0],
                        owner_module_id="example.phase1-proof",
                        resource_namespace="example.phase1-proof.proof-record",
                        contract_version="1",
                        entity_type="proof_record",
                        retention_category="proof",
                        retention_period_days=1,
                        action_on_expiry=ExpiryAction.PURGE,
                        effective_at=datetime.now(UTC) + timedelta(hours=1),
                    ),
                    request,
                )
            )
            try:
                await asyncio.sleep(0.15)
                assert not replacement.done()
            finally:
                release.set()
            assert await asyncio.wait_for(purge, timeout=8)
            assert await asyncio.wait_for(replacement, timeout=8)


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_adr017_ordinary_owner_fact_mutations_cannot_race_with_purge(
    postgres_database: PostgreSQLTestDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _running_app(postgres_database) as app:
        tenant_id = uuid4()
        request = _request(tenant_id)
        record_id = await _eligible_record(app, postgres_database, request)
        await _purge_policy(app, request, tenant_id)
        entered, release = asyncio.Event(), asyncio.Event()
        original_commit = SQLAlchemyUnitOfWork.commit

        async def paused_commit(unit: SQLAlchemyUnitOfWork) -> None:
            entered.set()
            await release.wait()
            await original_commit(unit)

        with monkeypatch.context() as patch:
            patch.setattr(SQLAlchemyUnitOfWork, "commit", paused_commit)
            purge = asyncio.create_task(
                _dispatch(
                    app,
                    ExecuteDestructiveLifecycleV2(
                        subject=_subject(tenant_id, record_id), action=ExpiryAction.PURGE
                    ),
                    request,
                )
            )
            await asyncio.wait_for(entered.wait(), timeout=8)
            try:
                for role in ("businessos_app", "businessos_worker"):
                    role_url = (
                        postgres_database.runtime_url
                        if role == "businessos_app"
                        else postgres_database.worker_url
                    ).replace("postgresql+psycopg://", "postgresql://", 1)
                    for column, value in (
                        ("retention_category", "alternate"),
                        ("retention_anchor_at", datetime.now(UTC)),
                        ("lifecycle", "archived"),
                    ):
                        with psycopg.connect(role_url) as ordinary:
                            ordinary.execute(
                                "SELECT set_config('app.tenant_id', %s, true)",
                                (str(tenant_id),),
                            )
                            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                                ordinary.execute(
                                    "UPDATE mod_example_phase1_proof.proof_records "
                                    f"SET {column} = %s WHERE id = %s",
                                    (value, record_id),
                                )
            finally:
                release.set()
            assert await asyncio.wait_for(purge, timeout=8)


def _request(tenant_id: Any) -> RequestContext:
    principal_id = uuid4()
    request = RequestContext(
        tenant=TenantContext(
            installation_id=uuid4(),
            tenant_id=tenant_id,
            principal_id=principal_id,
            authentication_strength="mfa",
        )
    )
    bind_authenticated_principal(
        request,
        PrincipalIdentity(
            tenant_id=tenant_id,
            principal_id=principal_id,
            principal_type="user",
            authentication_strength="mfa",
        ),
    )
    return request


def _subject(tenant_id: Any, record_id: Any) -> RetentionSubjectKey:
    return RetentionSubjectKey(
        tenant_id=tenant_id,
        owner_module_id="example.phase1-proof",
        resource_namespace="example.phase1-proof.proof-record",
        contract_version="1",
        entity_type="proof_record",
        record_id=record_id,
    )


async def _eligible_record(
    app: Any, database: PostgreSQLTestDatabase, request: RequestContext
) -> Any:
    command_id = uuid4()
    assert await _dispatch(app, StoreProof(command_id=command_id, value="sensitive"), request) == {
        "stored": True
    }
    with psycopg.connect(database.administrator_url) as admin:
        record_id = admin.execute(
            "SELECT id FROM mod_example_phase1_proof.proof_records WHERE command_id = %s",
            (command_id,),
        ).fetchone()[0]  # type: ignore[index]
        admin.execute(
            "UPDATE mod_example_phase1_proof.proof_records SET retention_anchor_at = %s "
            "WHERE id = %s",
            (datetime.now(UTC) - timedelta(days=2), record_id),
        )
        admin.commit()
    return record_id


async def _purge_policy(app: Any, request: RequestContext, tenant_id: Any) -> None:
    await _dispatch(
        app,
        SetRetentionPolicyV2(
            tenant_id=tenant_id,
            owner_module_id="example.phase1-proof",
            resource_namespace="example.phase1-proof.proof-record",
            contract_version="1",
            entity_type="proof_record",
            retention_category="proof",
            retention_period_days=1,
            action_on_expiry=ExpiryAction.PURGE,
            valid_from=datetime.now(UTC) - timedelta(days=1),
        ),
        request,
    )


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_adr017_policy_overlap_elapsed_hours_action_and_identity(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    async with _running_app(postgres_database) as app:
        tenant_id = uuid4()
        request = _request(tenant_id)
        record_id = await _eligible_record(app, postgres_database, request)
        subject = _subject(tenant_id, record_id)
        await _purge_policy(app, request, tenant_id)
        with pytest.raises(BusinessOSError, match="overlaps"):
            await _purge_policy(app, request, tenant_id)
        with pytest.raises(BusinessOSError) as wrong_owner:
            await _dispatch(
                app,
                ExecuteDestructiveLifecycleV2(
                    subject=subject.model_copy(update={"owner_module_id": "foundation.party"}),
                    action=ExpiryAction.PURGE,
                ),
                request,
            )
        assert wrong_owner.value.code == "owner_mismatch"
        with pytest.raises(BusinessOSError) as wrong_tenant:
            await _dispatch(
                app,
                ExecuteDestructiveLifecycleV2(
                    subject=subject.model_copy(update={"tenant_id": uuid4()}),
                    action=ExpiryAction.PURGE,
                ),
                request,
            )
        assert wrong_tenant.value.code == "tenant_mismatch"
        with pytest.raises(BusinessOSError):
            await _dispatch(
                app,
                ExecuteDestructiveLifecycleV2(
                    subject=subject.model_copy(update={"record_id": uuid4()}),
                    action=ExpiryAction.PURGE,
                ),
                request,
            )
        with pytest.raises(BusinessOSError) as wrong_action:
            await _dispatch(
                app,
                ExecuteDestructiveLifecycleV2(subject=subject, action=ExpiryAction.ARCHIVE),
                request,
            )
        assert wrong_action.value.code == "retention_action_mismatch"
        with psycopg.connect(postgres_database.administrator_url) as admin:
            admin.execute(
                "UPDATE mod_example_phase1_proof.proof_records SET retention_anchor_at = %s "
                "WHERE id = %s",
                (datetime.now(UTC) - timedelta(hours=23), record_id),
            )
            admin.commit()
        with pytest.raises(BusinessOSError) as too_early:
            await _dispatch(
                app,
                ExecuteDestructiveLifecycleV2(subject=subject, action=ExpiryAction.PURGE),
                request,
            )
        assert too_early.value.code == "retention_not_elapsed"
        with psycopg.connect(postgres_database.administrator_url) as admin:
            admin.execute(
                "UPDATE mod_example_phase1_proof.proof_records SET retention_anchor_at = %s "
                "WHERE id = %s",
                (datetime.now(UTC) - timedelta(hours=25), record_id),
            )
            admin.commit()
        assert await _dispatch(
            app, ExecuteDestructiveLifecycleV2(subject=subject, action=ExpiryAction.PURGE), request
        )


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_adr017_tenant_hold_does_not_authorize_or_block_another_tenant(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    async with _running_app(postgres_database) as app:
        first_tenant, second_tenant = uuid4(), uuid4()
        first_request, second_request = _request(first_tenant), _request(second_tenant)
        first_record = await _eligible_record(app, postgres_database, first_request)
        second_record = await _eligible_record(app, postgres_database, second_request)
        await _purge_policy(app, first_request, first_tenant)
        await _purge_policy(app, second_request, second_tenant)
        first_subject = _subject(first_tenant, first_record)
        second_subject = _subject(second_tenant, second_record)
        await _dispatch(
            app,
            PlaceRetentionHoldV2(
                subject=first_subject, scope=HoldScope.ALL, reason="tenant one preservation"
            ),
            first_request,
        )
        with pytest.raises(BusinessOSError, match="Active legal hold"):
            await _dispatch(
                app,
                ExecuteDestructiveLifecycleV2(subject=first_subject, action=ExpiryAction.PURGE),
                first_request,
            )
        assert await _dispatch(
            app,
            ExecuteDestructiveLifecycleV2(subject=second_subject, action=ExpiryAction.PURGE),
            second_request,
        )
        with pytest.raises(BusinessOSError) as cross_tenant:
            await _dispatch(
                app,
                ExecuteDestructiveLifecycleV2(subject=first_subject, action=ExpiryAction.PURGE),
                second_request,
            )
        assert cross_tenant.value.code == "tenant_mismatch"


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_adr017_real_protected_proof_owner_commit(
    postgres_database: PostgreSQLTestDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    modules = tuple(discover_modules())
    app = create_application(
        Settings(
            environment="test",
            database_url=postgres_database.runtime_url,
            governance_database_url=postgres_database.governance_url,
        ),
        modules=modules,
        approved_module_artifacts=approved_artifacts_from_operator_inventory(modules),
        resource_coordinator_ids=frozenset({"foundation.data_governance"}),
        authorizer=Authorizer(_AllowAll()),
        infrastructure_providers={"object-storage": _ReadyStorage()},
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    await app.startup()
    tenant_id = uuid4()
    principal_id = uuid4()
    request = RequestContext(
        tenant=TenantContext(
            installation_id=uuid4(),
            tenant_id=tenant_id,
            principal_id=principal_id,
            authentication_strength="mfa",
        )
    )
    bind_authenticated_principal(
        request,
        PrincipalIdentity(
            tenant_id=tenant_id,
            principal_id=principal_id,
            principal_type="user",
            authentication_strength="mfa",
        ),
    )
    try:
        command_id = uuid4()
        assert await _dispatch(
            app, StoreProof(command_id=command_id, value="sensitive"), request
        ) == {"stored": True}
        with psycopg.connect(postgres_database.administrator_url) as admin:
            record_id = admin.execute(
                "SELECT id FROM mod_example_phase1_proof.proof_records WHERE command_id = %s",
                (command_id,),
            ).fetchone()[0]  # type: ignore[index]
            admin.execute(
                "UPDATE mod_example_phase1_proof.proof_records "
                "SET retention_anchor_at = %s WHERE id = %s",
                (datetime.now(UTC) - timedelta(days=2), record_id),
            )
            admin.commit()
        await _dispatch(
            app,
            SetRetentionPolicyV2(
                tenant_id=tenant_id,
                owner_module_id="example.phase1-proof",
                resource_namespace="example.phase1-proof.proof-record",
                contract_version="1",
                entity_type="proof_record",
                retention_category="proof",
                retention_period_days=1,
                action_on_expiry=ExpiryAction.PURGE,
                valid_from=datetime.now(UTC) - timedelta(days=1),
            ),
            request,
        )
        observed: dict[str, Any] = {}
        original_commit = SQLAlchemyUnitOfWork.commit

        async def inspect_then_commit(unit: SQLAlchemyUnitOfWork) -> None:
            assert unit.session is not None
            await unit.session.flush()
            observed["identity"] = (
                await unit.session.execute(
                    text(
                        "SELECT current_user, session_user, txid_current(), "
                        "(SELECT count(*) FROM platform_gov.destructive_decisions_v2 "
                        " WHERE tenant_id = :tenant), "
                        "(SELECT count(*) FROM platform_audit.audit_logs "
                        " WHERE tenant_id = :tenant), "
                        "(SELECT count(*) FROM eventing.outbox_messages "
                        " WHERE tenant_id = :tenant), "
                        "(SELECT lifecycle FROM mod_example_phase1_proof.proof_records "
                        " WHERE id = :record)"
                    ),
                    {"tenant": tenant_id, "record": record_id},
                )
            ).one()
            await original_commit(unit)

        with monkeypatch.context() as patch:
            patch.setattr(SQLAlchemyUnitOfWork, "commit", inspect_then_commit)
            decision_id = await _dispatch(
                app,
                ExecuteDestructiveLifecycleV2(
                    subject=_subject(tenant_id, record_id),
                    action=ExpiryAction.PURGE,
                ),
                request,
            )
        assert observed["identity"][0:2] == (
            "businessos_governance",
            "businessos_governance",
        )
        assert isinstance(observed["identity"][2], int)
        assert observed["identity"][3:] == (1, 1, 2, "purged")
        with psycopg.connect(postgres_database.administrator_url) as admin:
            owner = admin.execute(
                "SELECT lifecycle, value FROM mod_example_phase1_proof.proof_records WHERE id = %s",
                (record_id,),
            ).fetchone()
            decision = admin.execute(
                "SELECT external_cleanup_status FROM platform_gov.destructive_decisions_v2 "
                "WHERE id = %s",
                (decision_id,),
            ).fetchone()
            assert owner == ("purged", "")
            assert decision == ("pending",)
            assert (
                admin.execute(
                    "SELECT count(*) FROM platform_audit.audit_logs WHERE tenant_id = %s",
                    (tenant_id,),
                ).fetchone()[0]  # type: ignore[index]
                >= 1
            )
            assert (
                admin.execute(
                    "SELECT count(*) FROM eventing.outbox_messages WHERE tenant_id = %s",
                    (tenant_id,),
                ).fetchone()[0]  # type: ignore[index]
                >= 1
            )
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_adr017_concurrent_cleanup_cannot_restore_purged_shared_plaintext(
    postgres_database: PostgreSQLTestDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    class PausedStorage(InMemoryFencedStorage):
        def __init__(self) -> None:
            super().__init__()
            self.before_shared_write = asyncio.Event()
            self.resume_shared_write = asyncio.Event()

        async def compare_and_reconcile(
            self,
            tenant_id: UUID,
            key: str,
            expected_version: str | None,
            content: bytes | None,
        ) -> bool:
            if key == "phase1-proof/value.txt" and content == b"B":
                self.before_shared_write.set()
                await self.resume_shared_write.wait()
            return await super().compare_and_reconcile(tenant_id, key, expected_version, content)

    storage = PausedStorage()
    modules = tuple(discover_modules())
    app = create_application(
        Settings(
            environment="test",
            database_url=postgres_database.runtime_url,
            governance_database_url=postgres_database.governance_url,
        ),
        modules=modules,
        approved_module_artifacts=approved_artifacts_from_operator_inventory(modules),
        resource_coordinator_ids=frozenset({"foundation.data_governance"}),
        authorizer=Authorizer(_AllowAll()),
        infrastructure_providers={"object-storage": storage},
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    await app.startup()
    tenant_id = uuid4()
    request = _request(tenant_id)
    assert request.tenant is not None
    tenant = request.tenant
    owner = next(module for module in modules if isinstance(module, ProofModule))
    worker_database = Database(Settings(database_url=postgres_database.worker_url))
    worker_factory = SQLAlchemyUnitOfWorkFactory(worker_database.sessions)
    # The separate real-worker test proves admission. Here the binding is
    # substituted solely to control the two owner cleanup interleavings.
    monkeypatch.setattr(TenantExecutionBinding, "assert_active", lambda self, transaction: None)

    def event_binding(event: DestructiveCleanupRequestedV2) -> TenantExecutionBinding:
        binding = object.__new__(TenantExecutionBinding)
        object.__setattr__(binding, "tenant_id", tenant_id)
        object.__setattr__(binding, "source_event_id", event.event_id)
        object.__setattr__(binding, "subscriber", "example.phase1-proof.external-retention-cleanup")
        object.__setattr__(binding, "purpose", "event-delivery")
        object.__setattr__(
            binding,
            "workload",
            WorkloadIdentityFacts(
                installation_id=tenant.installation_id,
                workload_id=uuid4(),
                principal_type="service_account",
                purpose="event-delivery",
                process_class="event-worker",
                credential_reference="test",
                credential_generation=1,
                verification_method="test",
                verification_reference=uuid4(),
            ),
        )
        return binding

    async def consume(event: DestructiveCleanupRequestedV2) -> None:
        async with worker_factory.for_tenant(tenant) as unit:
            with bind_request_context(request):
                async with app.container.request_scope() as dependencies:
                    await owner._cleanup_destructive(
                        event,
                        EventHandlingContext(
                            request,
                            dependencies,
                            handler_transaction_view(unit),
                            event_binding(event),
                        ),
                    )
                await unit.commit()

    try:
        first_command, second_command = uuid4(), uuid4()
        await _dispatch(app, StoreProof(command_id=first_command, value="A"), request)
        await _dispatch(app, StoreProof(command_id=second_command, value="B"), request)
        with psycopg.connect(postgres_database.administrator_url) as admin:
            rows: dict[UUID, UUID] = dict(
                admin.execute(
                    "SELECT command_id, id FROM mod_example_phase1_proof.proof_records"
                ).fetchall()
            )
            first_record, second_record = rows[first_command], rows[second_command]
            admin.execute(
                "UPDATE mod_example_phase1_proof.proof_records "
                "SET retention_anchor_at = %s WHERE id IN (%s, %s)",
                (datetime.now(UTC) - timedelta(days=2), first_record, second_record),
            )
            admin.commit()
        await _purge_policy(app, request, tenant_id)
        first_decision = await _dispatch(
            app,
            ExecuteDestructiveLifecycleV2(
                subject=_subject(tenant_id, first_record), action=ExpiryAction.PURGE
            ),
            request,
        )
        storage.objects[(tenant_id, ProofModule.record_object_key(first_record))] = b"A"
        storage.objects[(tenant_id, ProofModule.record_object_key(second_record))] = b"B"
        storage.objects[(tenant_id, "phase1-proof/value.txt")] = b"B"
        first_event = DestructiveCleanupRequestedV2(
            tenant_id=tenant_id,
            correlation_id="first-cleanup",
            decision_id=first_decision,
            owner_module_id="example.phase1-proof",
            resource_namespace="example.phase1-proof.proof-record",
            contract_version="1",
            entity_type="proof_record",
            record_id=first_record,
            action=ExpiryAction.PURGE,
        )
        with psycopg.connect(postgres_database.administrator_url) as admin:
            first_source = admin.execute(
                "SELECT id FROM eventing.outbox_messages WHERE tenant_id = %s "
                "AND event_type = %s AND payload->>'decision_id' = %s",
                (tenant_id, DestructiveCleanupRequestedV2.event_type, str(first_decision)),
            ).fetchone()
            assert first_source is not None
            first_source_id = first_source[0]
        first_event = first_event.model_copy(update={"event_id": first_source_id})
        first_task = asyncio.create_task(consume(first_event))
        await asyncio.wait_for(storage.before_shared_write.wait(), timeout=8)
        second_decision = await _dispatch(
            app,
            ExecuteDestructiveLifecycleV2(
                subject=_subject(tenant_id, second_record), action=ExpiryAction.PURGE
            ),
            request,
        )
        second_event = first_event.model_copy(
            update={"decision_id": second_decision, "record_id": second_record}
        )
        with psycopg.connect(postgres_database.administrator_url) as admin:
            second_source = admin.execute(
                "SELECT id FROM eventing.outbox_messages WHERE tenant_id = %s "
                "AND event_type = %s AND payload->>'decision_id' = %s",
                (tenant_id, DestructiveCleanupRequestedV2.event_type, str(second_decision)),
            ).fetchone()
            assert second_source is not None
            second_source_id = second_source[0]
        second_event = second_event.model_copy(update={"event_id": second_source_id})
        second_task = asyncio.create_task(consume(second_event))
        try:
            await asyncio.sleep(0.15)
            assert not second_task.done()
        finally:
            storage.resume_shared_write.set()
        await asyncio.wait_for(first_task, timeout=8)
        await asyncio.wait_for(second_task, timeout=8)
        assert (tenant_id, "phase1-proof/value.txt") not in storage.objects
        assert (tenant_id, ProofModule.record_object_key(first_record)) not in storage.objects
        assert (tenant_id, ProofModule.record_object_key(second_record)) not in storage.objects
        with psycopg.connect(postgres_database.administrator_url) as admin:
            statuses = admin.execute(
                "SELECT external_cleanup_status FROM platform_gov.destructive_decisions_v2 "
                "WHERE id IN (%s, %s)",
                (first_decision, second_decision),
            ).fetchall()
            assert statuses == [("completed",), ("completed",)]
    finally:
        storage.resume_shared_write.set()
        await worker_database.close()
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize("key", ("phase1-proof/value.txt", "phase1-proof/records/late-write.txt"))
async def test_adr017_late_noncancellable_s3_write_is_fenced_after_lock_release(
    postgres_database: PostgreSQLTestDatabase,
    key: str,
) -> None:
    class PausedS3Client:
        exceptions = SimpleNamespace(ClientError=ClientError)

        def __init__(self) -> None:
            self.body: bytes | None = None
            self.metadata: dict[str, str] = {}
            self.etag: str | None = None
            self.serial = 0
            self.lock = threading.Lock()
            self.started = threading.Event()
            self.release = threading.Event()
            self.finished = threading.Event()
            self.stale_done = threading.Event()
            self.stale_rejected = False

        def head_object(self, **_: Any) -> dict[str, str]:
            with self.lock:
                if self.etag is None:
                    raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
                return {"ETag": self.etag}

        def put_object(self, **kwargs: Any) -> dict[str, str]:
            body: bytes = kwargs["Body"]
            if body.endswith(b"B"):
                self.started.set()
                if not self.release.wait(10):
                    raise TimeoutError("Test did not release the synchronous S3 write")
            with self.lock:
                expected = kwargs.get("IfMatch")
                if (kwargs.get("IfNoneMatch") == "*" and self.etag is not None) or (
                    expected is not None and expected != self.etag
                ):
                    self.stale_rejected = True
                    self.finished.set()
                    self.stale_done.set()
                    raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
                self.serial += 1
                self.etag = f'"generation-{self.serial}"'
                self.body = body
                self.metadata = kwargs.get("Metadata", {}).copy()
                self.finished.set()
                return {"ETag": self.etag}

        def get_object(self, **_: Any) -> dict[str, Any]:
            with self.lock:
                assert self.body is not None
                return {"Body": io.BytesIO(self.body), "Metadata": self.metadata.copy()}

    client = PausedS3Client()
    storage = S3ObjectStorageProvider(bucket="fenced-proof-test")
    storage._client = client
    database = Database(Settings(database_url=postgres_database.worker_url))
    factory = SQLAlchemyUnitOfWorkFactory(database.sessions)
    tenant_id = uuid4()
    request = _request(tenant_id)
    assert request.tenant is not None
    tenant = request.tenant

    async def reconcile(content: bytes | None) -> None:
        async with factory.for_tenant(tenant) as unit:
            with bind_request_context(request):
                await lock_governance_scope(unit, "proof-shared-object", tenant_id)
                version = await storage.version(tenant_id, key)
                assert await storage.compare_and_reconcile(tenant_id, key, version, content)
                await unit.commit()

    first = asyncio.create_task(reconcile(b"B"))
    try:
        assert await asyncio.to_thread(client.started.wait, 8)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        # A's transaction has rolled back and released its advisory lock,
        # while the synchronous S3 request is still blocked in its thread.
        assert not client.finished.is_set()
        await asyncio.wait_for(reconcile(None), timeout=8)
        assert client.body is not None
        assert client.body.endswith(b"\x00")  # plaintext-free tombstone
        client.release.set()
        assert await asyncio.to_thread(client.stale_done.wait, 8)
        assert client.stale_rejected
        with bind_request_context(request):
            with pytest.raises(FileNotFoundError):
                await storage.get(tenant_id, key)
            current_version = await storage.version(tenant_id, key)
            assert not await storage.compare_and_reconcile(
                tenant_id, key, None, b"B"
            )  # stale delivery cannot overwrite the tombstone
            assert await storage.version(tenant_id, key) == current_version
    finally:
        client.release.set()
        await database.close()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "surface",
    ("direct", "view", "nested_view", "function", "trigger", "rule", "role", "default_acl"),
)
async def test_adr017_owner_relation_rejects_ordinary_indirect_writers(
    postgres_database: PostgreSQLTestDatabase, surface: str
) -> None:
    modules = tuple(discover_modules())
    app = create_application(
        Settings(
            environment="test",
            database_url=postgres_database.runtime_url,
            governance_database_url=postgres_database.governance_url,
        ),
        modules=modules,
        approved_module_artifacts=approved_artifacts_from_operator_inventory(modules),
        resource_coordinator_ids=frozenset({"foundation.data_governance"}),
        authorizer=Authorizer(_AllowAll()),
        infrastructure_providers={"object-storage": _ReadyStorage()},
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    await app.startup()
    authority = app.runtime.messages._protected_database
    assert authority is not None
    suffix = uuid4().hex
    source = f"adr017_owner_source_{suffix}"
    inner = f"adr017_owner_inner_{suffix}"
    routine = f"adr017_owner_routine_{suffix}"
    role = f"adr017_owner_role_{suffix}"
    table = "mod_example_phase1_proof.proof_records"
    cleanup: list[str] = []
    try:
        with psycopg.connect(postgres_database.administrator_url, autocommit=True) as admin:
            if surface == "direct":
                admin.execute(f"GRANT UPDATE (lifecycle) ON {table} TO businessos_app")
                cleanup = [f"REVOKE UPDATE (lifecycle) ON {table} FROM businessos_app"]
            elif surface in {"view", "nested_view"}:
                admin.execute(f"CREATE VIEW public.{inner} AS SELECT id, lifecycle FROM {table}")
                source_view = inner
                cleanup = [f"DROP VIEW public.{inner}"]
                if surface == "nested_view":
                    admin.execute(
                        f"CREATE VIEW public.{source} AS SELECT id, lifecycle FROM public.{inner}"
                    )
                    source_view = source
                    cleanup.insert(0, f"DROP VIEW public.{source}")
                admin.execute(f"GRANT UPDATE (lifecycle) ON public.{source_view} TO businessos_app")
            elif surface == "function":
                admin.execute(
                    f"CREATE FUNCTION public.{routine}() RETURNS void LANGUAGE plpgsql "
                    "SECURITY DEFINER AS $$ BEGIN "
                    f"UPDATE {table} SET lifecycle = 'purged' WHERE false; END $$"
                )
                cleanup = [f"DROP FUNCTION public.{routine}()"]
            elif surface in {"trigger", "rule"}:
                admin.execute(f"CREATE TABLE public.{source} (id integer)")
                admin.execute(f"GRANT INSERT ON public.{source} TO businessos_app")
                cleanup = [f"DROP TABLE public.{source}"]
                if surface == "trigger":
                    admin.execute(
                        f"CREATE FUNCTION public.{routine}() RETURNS trigger LANGUAGE plpgsql "
                        "SECURITY DEFINER AS $$ BEGIN "
                        f"UPDATE {table} SET lifecycle = 'purged' WHERE false; RETURN NEW; END $$"
                    )
                    admin.execute(f"REVOKE ALL ON FUNCTION public.{routine}() FROM PUBLIC")
                    admin.execute(
                        f"CREATE TRIGGER {routine} BEFORE INSERT ON public.{source} "
                        f"FOR EACH ROW EXECUTE FUNCTION public.{routine}()"
                    )
                    cleanup.append(f"DROP FUNCTION public.{routine}()")
                else:
                    admin.execute(
                        f"CREATE RULE {source}_write AS ON INSERT TO public.{source} "
                        f"DO ALSO UPDATE {table} SET lifecycle = 'purged' WHERE false"
                    )
            elif surface == "role":
                admin.execute(f"CREATE ROLE {role}")
                admin.execute(f"GRANT UPDATE (lifecycle) ON {table} TO {role}")
                admin.execute(f"GRANT {role} TO businessos_app")
                cleanup = [
                    f"REVOKE {role} FROM businessos_app",
                    f"REVOKE UPDATE (lifecycle) ON {table} FROM {role}",
                    f"DROP ROLE {role}",
                ]
            else:
                admin.execute(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA mod_example_phase1_proof "
                    "GRANT UPDATE ON TABLES TO businessos_governance"
                )
                cleanup = [
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA mod_example_phase1_proof "
                    "REVOKE UPDATE ON TABLES FROM businessos_governance"
                ]
        with pytest.raises(ConfigurationError):
            await authority.validate()
    finally:
        with psycopg.connect(postgres_database.administrator_url, autocommit=True) as admin:
            for statement in cleanup:
                admin.execute(statement)
        await app.shutdown()
