"""Real PostgreSQL certification probes for the bounded Phase 5A foundation."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from businessos_identity import PrincipalIdentity
from businessos_identity.principal_binding import bind_authenticated_principal
from businessos_metadata import MetadataModule
from businessos_metadata.activation_fence import MetadataActivationFence
from businessos_metadata.contracts import (
    DefinitionSnapshot,
    FieldDefinition,
    FieldType,
    PublicationResult,
    PublicationStatus,
    RevisionRecord,
)
from businessos_metadata.module import (
    CreateDefinition,
    EditDraft,
    PreflightPublication,
    PublishDefinition,
    ReactivateRevision,
    ReadActiveRevision,
    ReadDraft,
)

from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.context import RequestContext, TenantContext
from businessos.modules import discover_modules
from businessos.modules.installation_inventory import approved_artifacts_from_operator_inventory
from businessos.publication_database import PublicationDatabaseAuthority
from businessos.sdk import BusinessOSError
from businessos.security import Authorizer
from tests.conftest import PostgreSQLTestDatabase


class _Policy:
    allowed = True

    async def is_allowed(self, principal_id: UUID, tenant: TenantContext, permission: str) -> bool:
        return self.allowed


def _context(tenant_id: UUID | None = None) -> RequestContext:
    if tenant_id is None:
        return RequestContext()
    context = RequestContext(
        tenant=TenantContext(
            installation_id=uuid4(),
            tenant_id=tenant_id,
            principal_id=uuid4(),
            authentication_strength="mfa",
        )
    )
    _bind(context)
    return context


def _bind(context: RequestContext) -> None:
    assert context.tenant is not None
    bind_authenticated_principal(
        context,
        PrincipalIdentity(
            tenant_id=context.tenant.tenant_id,
            principal_id=context.tenant.principal_id,
            principal_type="user",
            authentication_strength="mfa",
        ),
    )


def _snapshot(name: str = "custom_label") -> DefinitionSnapshot:
    return DefinitionSnapshot(
        kind="field_set",
        fields=(FieldDefinition(field_id=uuid4(), name=name, value_type=FieldType.TEXT),),
    )


def _app(database: PostgreSQLTestDatabase, policy: _Policy) -> Any:
    modules = list(
        module
        for module in discover_modules()
        if module.manifest.module_id.startswith("foundation.")
    )
    if not any(module.manifest.module_id == "foundation.metadata" for module in modules):
        modules.append(MetadataModule())
    inventory = json.loads(
        Path("tests/fixtures/approved-module-inventory.ci.json").read_text(encoding="utf-8")
    )
    return create_application(
        Settings(
            environment="test",
            database_url=database.runtime_url,
            metadata_database_url=database.metadata_url,
            ui_publication_database_url=database.ui_publication_url,
        ),
        modules=modules,
        authorizer=Authorizer(policy),
        approved_module_artifacts=approved_artifacts_from_operator_inventory(
            modules, inventory=inventory
        ),
    )


async def _command(app: Any, command: Any, context: RequestContext) -> Any:
    async with app.container.request_scope() as dependencies:
        return await app.runtime.messages.command(command, context, dependencies)


async def _query(app: Any, query: Any, context: RequestContext) -> Any:
    async with app.container.request_scope() as dependencies:
        return await app.runtime.messages.query(query, context, dependencies)


def _url(value: str) -> str:
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_phase5a_publish_rollback_fence_rls_and_evidence(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    policy = _Policy()
    app = _app(postgres_database, policy)
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    await app.startup()
    context = _context(uuid4())
    other = _context(uuid4())
    missing = _context()
    assert context.tenant is not None
    assert other.tenant is not None
    _bind(context)
    try:
        created = await _command(
            app,
            CreateDefinition(
                resource_namespace="foundation.data_governance.data-classification",
                owner_contract_version="2",
                kind="field_set",
                snapshot=_snapshot(),
            ),
            context,
        )
        definition_id = created.identity.definition_id
        assert await _query(app, ReadActiveRevision(definition_id=definition_id), context) is None
        assert await _query(app, ReadDraft(definition_id=definition_id), other) is None
        assert await _query(app, ReadActiveRevision(definition_id=definition_id), other) is None
        with pytest.raises(BusinessOSError):
            await _query(app, ReadDraft(definition_id=definition_id), missing)

        first_preflight = await _query(
            app, PreflightPublication(definition_id=definition_id), context
        )
        assert first_preflight.expected_active_revision_id is None
        authority = PublicationDatabaseAuthority(
            governance_url=postgres_database.ui_publication_url,
            database_name=postgres_database.ui_publication_url.rsplit("/", 1)[1],
            pool_size=2,
            pool_timeout=10,
            gate=app.runtime.contributions,
        )
        fence = MetadataActivationFence(authority.internal_installation)
        owner_id = first_preflight.expected_base.module_id
        original_artifact = first_preflight.expected_base.artifact_identity
        # Activation and publication take the same database row lock. An
        # activation that wins the race invalidates the earlier preflight.
        async with fence.activation(owner_id, "phase5a-race-upgrade"):
            losing_publish = asyncio.create_task(
                _command(app, PublishDefinition(preflight=first_preflight), context)
            )
            await asyncio.sleep(0.05)
            assert not losing_publish.done()
        assert (await losing_publish).status is PublicationStatus.MODULE_BASE_CHANGED
        assert await _query(app, ReadActiveRevision(definition_id=definition_id), context) is None
        async with fence.activation(owner_id, original_artifact):
            pass
        first_preflight = await _query(
            app, PreflightPublication(definition_id=definition_id), context
        )
        competing = await asyncio.gather(
            _command(app, PublishDefinition(preflight=first_preflight), context),
            _command(app, PublishDefinition(preflight=first_preflight), context),
        )
        assert {item.status for item in competing} == {
            PublicationStatus.SUCCESS,
            PublicationStatus.ACTIVE_REVISION_CONFLICT,
        }
        first = next(item for item in competing if item.status is PublicationStatus.SUCCESS)
        assert isinstance(first, PublicationResult)
        assert first.status is PublicationStatus.SUCCESS
        assert first.revision_id is not None
        with pytest.raises(Exception, match="active Metadata revisions"):
            async with fence.activation(owner_id, "phase5a-blocked-upgrade"):
                pass
        active = await _query(app, ReadActiveRevision(definition_id=definition_id), context)
        assert isinstance(active, RevisionRecord)
        assert active.revision_id == first.revision_id
        assert active.digest == active.snapshot.digest()

        stale = await _command(app, PublishDefinition(preflight=first_preflight), context)
        assert stale.status is PublicationStatus.ACTIVE_REVISION_CONFLICT
        assert (
            await _query(app, ReadActiveRevision(definition_id=definition_id), context)
        ).revision_id == first.revision_id

        stale_draft = await _query(app, PreflightPublication(definition_id=definition_id), context)
        edit = await _command(
            app,
            EditDraft(
                definition_id=definition_id,
                expected_draft_generation=1,
                snapshot=_snapshot("second_label"),
            ),
            context,
        )
        assert edit.definition.draft_generation == 2
        assert (
            await _command(app, PublishDefinition(preflight=stale_draft), context)
        ).status is PublicationStatus.STALE_DRAFT
        assert (
            await _query(app, ReadActiveRevision(definition_id=definition_id), context)
        ).revision_id == first.revision_id
        second_preflight = await _query(
            app, PreflightPublication(definition_id=definition_id), context
        )
        second = await _command(app, PublishDefinition(preflight=second_preflight), context)
        assert second.status is PublicationStatus.SUCCESS
        assert second.revision_id != first.revision_id
        rollback_preflight = await _query(
            app,
            PreflightPublication(definition_id=definition_id, target_revision_id=first.revision_id),
            context,
        )
        rolled_back = await _command(
            app,
            ReactivateRevision(preflight=rollback_preflight, revision_id=first.revision_id),
            context,
        )
        assert rolled_back.status is PublicationStatus.SUCCESS
        assert (
            await _query(app, ReadActiveRevision(definition_id=definition_id), context)
        ).revision_id == first.revision_id

        classified = DefinitionSnapshot(
            kind="reference_set",
            fields=(
                FieldDefinition(
                    field_id=uuid4(),
                    name="sensitive_code",
                    value_type=FieldType.TEXT,
                    classification_ref="foundation.data_governance.classification",
                ),
            ),
        )
        classified_draft = await _command(
            app,
            CreateDefinition(
                resource_namespace="foundation.data_governance.data-classification",
                owner_contract_version="2",
                kind="reference_set",
                snapshot=classified,
            ),
            context,
        )
        with pytest.raises(BusinessOSError, match="Classified custom fields"):
            await _query(
                app,
                PreflightPublication(definition_id=classified_draft.identity.definition_id),
                context,
            )

        with psycopg.connect(_url(postgres_database.metadata_url)) as connection:
            for table in ("definitions", "revisions", "revision_module_bindings"):
                state = connection.execute(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE oid = %s::regclass",
                    (f"platform_metadata.{table}",),
                ).fetchone()
                assert state == (True, True)
            assert connection.execute(
                "SELECT count(*) FROM platform_metadata.definitions"
            ).fetchone() == (0,)
            connection.execute(
                "SELECT set_config('app.tenant_id', %s, true)", (str(other.tenant.tenant_id),)
            )
            assert connection.execute(
                "SELECT count(*) FROM platform_metadata.definitions"
            ).fetchone() == (0,)
            assert (
                connection.execute(
                    "UPDATE platform_metadata.definitions SET draft_generation = 9"
                ).rowcount
                == 0
            )
            connection.execute(
                "SELECT set_config('app.tenant_id', %s, true)", (str(context.tenant.tenant_id),)
            )
            assert connection.execute(
                "SELECT count(*) FROM platform_metadata.definitions"
            ).fetchone() == (2,)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    "UPDATE platform_metadata.revisions SET digest = %s WHERE id = %s",
                    ("0" * 64, first.revision_id),
                )
            connection.rollback()
            with pytest.raises(psycopg.Error):
                connection.execute("SELECT set_config('app.tenant_id', 'not-a-uuid', true)")
                connection.execute("SELECT count(*) FROM platform_metadata.definitions")
            connection.rollback()
            with pytest.raises(psycopg.Error):
                connection.execute("DELETE FROM platform_metadata.definitions")
            connection.rollback()

        with psycopg.connect(_url(postgres_database.migration_url)) as connection:
            evidence = connection.execute(
                "SELECT status, count(*) FROM platform_audit.audit_logs "
                "WHERE tenant_id = %s AND resource_type = 'foundation.metadata.definition' "
                "GROUP BY status",
                (context.tenant.tenant_id,),
            ).fetchall()
            outbox = connection.execute(
                "SELECT count(*) FROM eventing.outbox_messages "
                "WHERE tenant_id = %s AND event_type = 'metadata.lifecycle.v1'",
                (context.tenant.tenant_id,),
            ).fetchone()
            assert dict(evidence) == {
                "success": 6,
                "module_base_changed": 1,
                "active_revision_conflict": 2,
                "stale_draft": 1,
            }
            assert outbox == (6,)
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_metadata_effective_privileges_and_invalid_publication(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    import businessos.sdk as sdk

    policy = _Policy()
    app = _app(postgres_database, policy)
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    await app.startup()
    try:
        assert not hasattr(sdk, "InstallationUnitOfWorkFactory")
        async with app.container.request_scope() as dependencies:
            factory = await dependencies.resolve(sdk.UNIT_OF_WORK_FACTORY)
            assert not hasattr(factory, "installation")
        for url in (postgres_database.runtime_url, postgres_database.worker_url):
            with psycopg.connect(_url(url), autocommit=True) as connection:
                for table in (
                    "module_fence",
                    "contract_fence",
                    "definitions",
                    "revisions",
                    "revision_module_bindings",
                ):
                    qualified = f"platform_metadata.{table}"
                    assert connection.execute(
                        "SELECT has_table_privilege(current_user,c.oid,"
                        "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') OR "
                        "has_any_column_privilege(current_user,c.oid,'SELECT,INSERT,UPDATE') "
                        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname='platform_metadata' AND c.relname=%s",
                        (table,),
                    ).fetchone() == (False,)
                    for statement in (
                        f"SELECT * FROM {qualified}",
                        f"DELETE FROM {qualified}",
                        f"INSERT INTO {qualified} DEFAULT VALUES",
                    ):
                        with pytest.raises(psycopg.errors.InsufficientPrivilege):
                            connection.execute(statement)
                for column, value in (
                    ("artifact_identity", "'forged'"),
                    ("generation", "99"),
                    ("active_bindings", "0"),
                ):
                    with pytest.raises(psycopg.errors.InsufficientPrivilege):
                        connection.execute(
                            f"UPDATE platform_metadata.module_fence SET {column}={value}"
                        )
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    connection.execute(
                        "UPDATE platform_metadata.contract_fence SET schema_generation=99"
                    )
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    connection.execute("SET ROLE businessos_metadata")
                if url == postgres_database.worker_url:
                    assert connection.execute(
                        "SELECT pg_has_role(current_user,'businessos_app','MEMBER')"
                    ).fetchone() == (True,)
                    connection.execute("SET ROLE businessos_app")
                    with pytest.raises(psycopg.errors.InsufficientPrivilege):
                        connection.execute(
                            "UPDATE platform_metadata.module_fence SET active_bindings=0"
                        )
                    connection.execute("RESET ROLE")
        context = _context(uuid4())
        created = await _command(
            app,
            CreateDefinition(
                resource_namespace="foundation.data_governance.data-classification",
                owner_contract_version="2",
                kind="field_set",
                snapshot=_snapshot(),
            ),
            context,
        )
        preflight = await _query(
            app, PreflightPublication(definition_id=created.identity.definition_id), context
        )
        for kind, value, options in (
            ("date", "not-a-date", {}),
            ("instant", "2026-01-01", {}),
            ("uuid", "invalid", {}),
            ("email", "not-email", {}),
            ("url", "javascript:x", {}),
            ("decimal", "1.25", {}),
            ("money", "1.25", {"precision": 6, "scale": 2}),
            ("boolean", "true", {}),
        ):
            invalid: dict[str, Any] = {
                "kind": "field_set",
                "fields": [
                    {
                        "field_id": str(uuid4()),
                        "name": "custom_label",
                        "value_type": kind,
                        "literal_default": value,
                        **options,
                    }
                ],
            }
            if kind == "boolean":
                invalid["fields"][0]["literal_default"] = True
                invalid["rules"] = [
                    {
                        "left_field": "custom_label",
                        "comparison": "eq",
                        "right_literal": "true",
                    }
                ]
            with psycopg.connect(_url(postgres_database.migration_url)) as connection:
                connection.execute(
                    "UPDATE platform_metadata.definitions SET draft_snapshot=%s::jsonb WHERE id=%s",
                    (json.dumps(invalid), created.identity.definition_id),
                )
            result = await _command(app, PublishDefinition(preflight=preflight), context)
            assert result.status is PublicationStatus.QUOTA_VALIDATION_FAILURE
        with psycopg.connect(_url(postgres_database.migration_url)) as connection:
            assert connection.execute(
                "SELECT count(*) FROM platform_metadata.revisions"
            ).fetchone() == (0,)
            assert connection.execute(
                "SELECT sum(active_bindings) FROM platform_metadata.module_fence"
            ).fetchone() == (0,)
            assert connection.execute(
                "SELECT active_revision_id FROM platform_metadata.definitions"
            ).fetchone() == (None,)
            # Only draft creation emits an event; invalid publications emit none.
            assert connection.execute(
                "SELECT count(*) FROM eventing.outbox_messages"
            ).fetchone() == (1,)
        policy.allowed = False
        with pytest.raises(BusinessOSError):
            await _command(app, PublishDefinition(preflight=preflight), context)
        with pytest.raises(BusinessOSError):
            await _query(app, ReadDraft(definition_id=created.identity.definition_id), context)
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_metadata_publication_atomicity_and_binding_lifecycle(
    postgres_database: PostgreSQLTestDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from businessos_audit.v2_runtime import AuditAppenderProvider
    from businessos_metadata.module import RetireDefinition

    from businessos.persistence.uow import SQLAlchemyUnitOfWork

    app = _app(postgres_database, _Policy())
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    await app.startup()
    context = _context(uuid4())

    def state() -> tuple[Any, ...]:
        with psycopg.connect(_url(postgres_database.migration_url)) as connection:
            return (
                connection.execute(
                    "SELECT active_revision_id,active_generation,lifecycle "
                    "FROM platform_metadata.definitions ORDER BY id"
                ).fetchall(),
                connection.execute(
                    "SELECT id,digest FROM platform_metadata.revisions ORDER BY id"
                ).fetchall(),
                connection.execute(
                    "SELECT module_id,active_bindings "
                    "FROM platform_metadata.module_fence ORDER BY module_id"
                ).fetchall(),
                connection.execute("SELECT count(*) FROM platform_audit.audit_logs").fetchone(),
                connection.execute("SELECT count(*) FROM eventing.outbox_messages").fetchone(),
            )

    try:
        created = await _command(
            app,
            CreateDefinition(
                resource_namespace="foundation.data_governance.data-classification",
                owner_contract_version="2",
                kind="field_set",
                snapshot=_snapshot(),
            ),
            context,
        )
        definition_id = created.identity.definition_id
        preflight = await _query(app, PreflightPublication(definition_id=definition_id), context)
        before = state()
        original_append = AuditAppenderProvider.append
        original_outbox = SQLAlchemyUnitOfWork.add_outbox
        for fault in ("audit-failure", "audit-cancel", "outbox-cancel"):
            with monkeypatch.context() as patch:

                async def append(self: Any, evidence: Any, ctx: Any, injected: str = fault) -> Any:
                    result = await original_append(self, evidence, ctx)
                    if injected == "audit-failure":
                        raise RuntimeError("injected audit append failure")
                    if injected == "audit-cancel":
                        raise asyncio.CancelledError
                    return result

                def outbox(self: Any, message: Any) -> None:
                    original_outbox(self, message)
                    raise asyncio.CancelledError

                patch.setattr(AuditAppenderProvider, "append", append)
                if fault == "outbox-cancel":
                    patch.setattr(SQLAlchemyUnitOfWork, "add_outbox", outbox)
                with pytest.raises((RuntimeError, asyncio.CancelledError)):
                    await _command(app, PublishDefinition(preflight=preflight), context)
            assert state() == before
        first = await _command(app, PublishDefinition(preflight=preflight), context)
        assert first.status is PublicationStatus.SUCCESS
        assert sum(count for _, count in state()[2]) == 1
        replacement = DefinitionSnapshot(
            kind="field_set",
            fields=(
                *_snapshot("replacement").fields,
                FieldDefinition(
                    field_id=uuid4(),
                    name="linked_definition",
                    value_type=FieldType.REFERENCE,
                    reference_namespace="foundation.metadata.definition",
                    reference_contract_version="1",
                ),
            ),
        )
        await _command(
            app,
            EditDraft(
                definition_id=definition_id,
                expected_draft_generation=1,
                snapshot=replacement,
            ),
            context,
        )
        preflight = await _query(app, PreflightPublication(definition_id=definition_id), context)
        second = await _command(app, PublishDefinition(preflight=preflight), context)
        assert second.status is PublicationStatus.SUCCESS
        assert sum(count for _, count in state()[2]) == 2
        rollback = await _query(
            app,
            PreflightPublication(definition_id=definition_id, target_revision_id=first.revision_id),
            context,
        )
        before = state()
        with monkeypatch.context() as patch:

            async def cancel_append(self: Any, evidence: Any, ctx: Any) -> Any:
                await original_append(self, evidence, ctx)
                raise asyncio.CancelledError

            patch.setattr(AuditAppenderProvider, "append", cancel_append)
            with pytest.raises(asyncio.CancelledError):
                await _command(
                    app,
                    ReactivateRevision(preflight=rollback, revision_id=first.revision_id),
                    context,
                )
        assert state() == before
        result = await _command(
            app, ReactivateRevision(preflight=rollback, revision_id=first.revision_id), context
        )
        assert result.status is PublicationStatus.SUCCESS
        assert sum(count for _, count in state()[2]) == 1
        await _command(
            app,
            RetireDefinition(
                definition_id=definition_id, expected_active_generation=result.active_generation
            ),
            context,
        )
        assert sum(count for _, count in state()[2]) == 0
        assert all(count >= 0 for _, count in state()[2])
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_publication_wins_activation_race_at_real_postgresql_lock(
    postgres_database: PostgreSQLTestDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from businessos_audit.v2_runtime import AuditAppenderProvider

    app = _app(postgres_database, _Policy())
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    await app.startup()
    authority = PublicationDatabaseAuthority(
        governance_url=postgres_database.ui_publication_url,
        database_name=postgres_database.ui_publication_url.rsplit("/", 1)[1],
        pool_size=2,
        pool_timeout=10,
        gate=app.runtime.contributions,
    )
    fence = MetadataActivationFence(authority.internal_installation)
    reached, release = asyncio.Event(), asyncio.Event()
    tasks: list[asyncio.Task[Any]] = []
    try:
        context = _context(uuid4())
        record = await _command(
            app,
            CreateDefinition(
                resource_namespace="foundation.data_governance.data-classification",
                owner_contract_version="2",
                kind="field_set",
                snapshot=_snapshot(),
            ),
            context,
        )
        preflight = await _query(
            app, PreflightPublication(definition_id=record.identity.definition_id), context
        )
        original = AuditAppenderProvider.append

        async def paused_append(self: Any, evidence: Any, ctx: Any) -> Any:
            result = await original(self, evidence, ctx)
            reached.set()
            await release.wait()
            return result

        async def replacement() -> None:
            async with fence.activation(preflight.expected_base.module_id, "d" * 64):
                pytest.fail("replacement became active while a published revision binds the owner")

        async def wait_for_database_lock() -> None:
            async with await psycopg.AsyncConnection.connect(
                postgres_database.administrator_url, autocommit=True
            ) as connection:
                while True:
                    cursor = await connection.execute(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                        "AND usename='businessos_ui_publication' AND wait_event_type='Lock' "
                        "AND query LIKE '%%module_fence%%' AND cardinality(pg_blocking_pids(pid))>0"
                    )
                    row = await cursor.fetchone()
                    if row is not None and row[0] > 0:
                        return
                    if replacing.done():
                        await replacing
                        pytest.fail("activation ended before acquiring the contested row lock")

        with monkeypatch.context() as patch:
            patch.setattr(AuditAppenderProvider, "append", paused_append)
            publishing = asyncio.create_task(
                _command(app, PublishDefinition(preflight=preflight), context)
            )
            tasks.append(publishing)
            await asyncio.wait_for(reached.wait(), 5)
            replacing = asyncio.create_task(replacement())
            tasks.append(replacing)
            await asyncio.wait_for(wait_for_database_lock(), 5)
            assert not replacing.done()
            release.set()
            assert (await publishing).status is PublicationStatus.SUCCESS
            with pytest.raises(Exception, match="active Metadata revisions"):
                await replacing
        with psycopg.connect(_url(postgres_database.migration_url)) as connection:
            assert connection.execute(
                "SELECT artifact_identity,generation,active_bindings "
                "FROM platform_metadata.module_fence "
                "WHERE module_id=%s",
                (preflight.expected_base.module_id,),
            ).fetchone() == (
                preflight.expected_base.artifact_identity,
                preflight.expected_base.generation,
                1,
            )
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await authority.close()
        await app.shutdown()
