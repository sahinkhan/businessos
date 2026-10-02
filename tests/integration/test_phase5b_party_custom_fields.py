"""Real PostgreSQL owner persistence, protected schema reads and transaction races."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from businessos_metadata.contracts import DefinitionSnapshot, FieldDefinition
from businessos_metadata.custom_schema import PublishedSchemaReader
from businessos_metadata.module import (
    CreateDefinition,
    EditDraft,
    PreflightPublication,
    PublishDefinition,
    RetireDefinition,
)
from businessos_party import CreatePersonParty, UpdateParty
from businessos_party.custom_fields import (
    ClearPartyCustomValues,
    ExportPartyCustomValues,
    ReadPartyCustomValues,
    WritePartyCustomValues,
)
from sqlalchemy import text

from businessos.custom_fields import CustomFieldValue
from businessos.errors import BusinessOSError
from businessos.migrations import MigrationCoordinator
from businessos.modules import ModuleRegistry, discover_modules
from businessos.modules.installation_inventory import approved_artifacts_from_operator_inventory
from businessos.persistence.uow import SQLAlchemyUnitOfWork
from businessos.version import runtime_version
from tests.conftest import PostgreSQLTestDatabase
from tests.integration.test_phase5a_metadata import _app, _command, _context, _Policy, _query, _url

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.asyncio]


async def test_certified_heads_upgrade_preserves_party_and_refuses_retained_downgrade(
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
    candidate_heads = set(migrations.plan().heads)
    assert "party_0003_custom_fields" in candidate_heads
    baseline_heads = (candidate_heads - {"party_0003_custom_fields"}) | {"party_0002"}
    for head in sorted(baseline_heads):
        migrations.upgrade(postgres_database.migration_url, head)
    tenant_id, party_id = uuid4(), uuid4()
    with psycopg.connect(_url(postgres_database.migration_url)) as db:
        assert {
            row[0] for row in db.execute("SELECT version_num FROM alembic_version")
        } == baseline_heads
        assert db.execute("SELECT to_regclass('platform_party.custom_values')").fetchone() == (
            None,
        )
        # The current coordinator catalogs all shipped revisions even at an older
        # target. Restore the exact old Party catalog to exercise a real additive
        # upgrade from a previously installed artifact, not a pre-announced edge.
        db.execute(
            "UPDATE platform_module.installed_module_migrations "
            "SET revision_ids = revision_ids - 'party_0003_custom_fields', "
            "revision_manifest = (SELECT jsonb_agg(value) "
            "FROM jsonb_array_elements(revision_manifest) "
            "WHERE value->>'revision' <> 'party_0003_custom_fields') "
            "WHERE module_id='foundation.party'"
        )
        assert db.execute(
            "SELECT revision_ids FROM platform_module.installed_module_migrations "
            "WHERE module_id='foundation.party'"
        ).fetchone() == (["party_0001", "party_0002"],)
        db.execute(
            "INSERT INTO platform_party.parties "
            "(id, tenant_id, party_number, party_type, display_name) "
            "VALUES (%s, %s, 'UPGRADE-1', 'person', 'Preserved Party')",
            (party_id, tenant_id),
        )
        before = db.execute("SELECT to_jsonb(p) FROM platform_party.parties p").fetchall()
    migrations.upgrade(postgres_database.migration_url)
    migrations.upgrade(postgres_database.migration_url)
    with psycopg.connect(_url(postgres_database.migration_url)) as db:
        assert {
            row[0] for row in db.execute("SELECT version_num FROM alembic_version")
        } == candidate_heads
        assert db.execute("SELECT to_jsonb(p) FROM platform_party.parties p").fetchall() == before
        assert db.execute("SELECT count(*) FROM platform_party.custom_values").fetchone() == (0,)
        db.execute(
            "INSERT INTO platform_party.custom_values "
            "(tenant_id, party_id, definition_id, revision_id, revision_digest, value_version, "
            "value_document, cleared, updated_by) VALUES (%s, %s, %s, %s, %s, 1, '{}', true, %s)",
            (tenant_id, party_id, uuid4(), uuid4(), "a" * 64, uuid4()),
        )
        retained = db.execute("SELECT to_jsonb(v) FROM platform_party.custom_values v").fetchall()
    with pytest.raises(RuntimeError, match="destructive downgrade is prohibited"):
        migrations.downgrade(postgres_database.migration_url, "party_0002")
    with psycopg.connect(_url(postgres_database.migration_url)) as db:
        assert (
            db.execute("SELECT to_jsonb(v) FROM platform_party.custom_values v").fetchall()
            == retained
        )
        assert {
            row[0] for row in db.execute("SELECT version_num FROM alembic_version")
        } == candidate_heads


async def _setup(
    database: PostgreSQLTestDatabase, *, publish: bool = True
) -> tuple[Any, Any, _Policy, Any, Any]:
    policy = _Policy()
    app = _app(database, policy)
    app.runtime.migrations.upgrade(database.migration_url)
    await app.startup()
    context = _context(uuid4())
    assert context.tenant is not None
    party = await _command(
        app,
        CreatePersonParty(
            tenant_id=context.tenant.tenant_id, first_name="Custom", last_name="Party"
        ),
        context,
    )
    field = FieldDefinition(
        field_id=uuid4(), name="custom_label", value_type="text", nullable=False
    )
    definition = await _command(
        app,
        CreateDefinition(
            resource_namespace="foundation.party.party",
            owner_contract_version="1",
            kind="field_set",
            snapshot=DefinitionSnapshot(kind="field_set", fields=(field,)),
        ),
        context,
    )
    if publish:
        preflight = await _query(
            app, PreflightPublication(definition_id=definition.identity.definition_id), context
        )
        result = await _command(app, PublishDefinition(preflight=preflight), context)
        assert result.status.value == "success"
    return app, context, policy, party, field


async def test_party_custom_value_lifecycle_policy_and_persistence(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app, context, policy, party, field = await _setup(postgres_database)
    tenant_id = context.tenant.tenant_id
    identity = {"tenant_id": tenant_id, "party_id": party.id}
    try:
        assert await _query(app, ReadPartyCustomValues(**identity), context) is None
        written = await _command(
            app,
            WritePartyCustomValues(
                **identity,
                expected_version=0,
                values=(CustomFieldValue(field_id=field.field_id, value="hello"),),
            ),
            context,
        )
        assert written.value_version == 1
        assert (await _query(app, ReadPartyCustomValues(**identity), context)) == written
        assert (await _query(app, ExportPartyCustomValues(**identity), context)) == written
        with pytest.raises(BusinessOSError) as conflict:
            await _command(
                app, WritePartyCustomValues(**identity, expected_version=0, values=()), context
            )
        assert conflict.value.code == "custom_value_conflict"
        policy.allowed = False
        for operation, dispatch in (
            (ReadPartyCustomValues(**identity), _query),
            (ClearPartyCustomValues(**identity, expected_version=1), _command),
        ):
            with pytest.raises(BusinessOSError):
                await dispatch(app, operation, context)
        policy.allowed = True
        other = _context(uuid4())
        assert other.tenant is not None
        with pytest.raises(BusinessOSError):
            await _query(app, ReadPartyCustomValues(**identity), other)
        with pytest.raises(BusinessOSError):
            await _query(app, ReadPartyCustomValues(**identity), _context())
        with pytest.raises(BusinessOSError) as missing:
            await _query(app, ReadPartyCustomValues(tenant_id=tenant_id, party_id=uuid4()), context)
        assert missing.value.code == "not_found"
        with pytest.raises(BusinessOSError) as unsupported:
            await _query(app, ReadPartyCustomValues(**identity, query_operation="filter"), context)
        assert unsupported.value.code == "custom_query_unsupported"
        with pytest.raises(BusinessOSError):
            await _query(
                app,
                ReadPartyCustomValues(tenant_id=other.tenant.tenant_id, party_id=party.id),
                other,
            )
        cleared = await _command(
            app, ClearPartyCustomValues(**identity, expected_version=1), context
        )
        assert cleared.value_version == 2 and cleared.cleared and cleared.values == ()
        replacement = await _command(
            app,
            WritePartyCustomValues(
                **identity,
                expected_version=2,
                values=(CustomFieldValue(field_id=field.field_id, value="retained"),),
            ),
            context,
        )
        assert replacement.value_version == 3
        await _command(app, UpdateParty(**identity, is_active=False), context)
        with pytest.raises(BusinessOSError) as inactive:
            await _command(app, ClearPartyCustomValues(**identity, expected_version=3), context)
        assert inactive.value.code == "party_inactive"
        assert (await _query(app, ExportPartyCustomValues(**identity), context)) == replacement
        with psycopg.connect(_url(postgres_database.migration_url)) as db:
            rows = db.execute(
                "SELECT payload FROM eventing.outbox_messages "
                "WHERE event_type='party.custom-values.changed.v1'"
            ).fetchall()
            assert len(rows) == 3
            assert all("hello" not in str(row) and "retained" not in str(row) for row in rows)
    finally:
        await app.shutdown()


async def test_unknown_schema_policy_retirement_and_generation_replacement(
    postgres_database: PostgreSQLTestDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, context, policy, party, field = await _setup(postgres_database)
    identity = {"tenant_id": context.tenant.tenant_id, "party_id": party.id}
    command = WritePartyCustomValues(
        **identity,
        expected_version=0,
        values=(CustomFieldValue(field_id=field.field_id, value="historical"),),
    )

    async def unknown_policy(principal: Any, tenant: Any, permission: str) -> Any:
        return None if permission == "foundation.metadata.definition.read" else True

    try:
        monkeypatch.setattr(policy, "is_allowed", unknown_policy)
        with pytest.raises(BusinessOSError) as denied:
            await _command(app, command, context)
        assert denied.value.code == "forbidden"
        monkeypatch.undo()
        old_reader = app.runtime.modules.get("foundation.metadata").module._schema_reader
        old_binding = app.runtime.resources.resolve_owner("foundation.party.party", "1")
        await app.runtime.lifecycle.disable_all()
        with pytest.raises(BusinessOSError):
            app.runtime.resources.resolve_owner("foundation.party.party", "1")
        await app.runtime.lifecycle.enable_all()
        new_binding = app.runtime.resources.resolve_owner("foundation.party.party", "1")
        assert old_binding.generation != new_binding.generation
        new_reader = app.runtime.modules.get("foundation.metadata").module._schema_reader
        assert new_reader is not old_reader and not old_reader.active

        async def stale(*args: Any, **kwargs: Any) -> Any:
            return await old_reader.resolve(*args, **kwargs)

        # Even a cached reader's stale lifecycle flag cannot bypass current DI admission.
        old_reader.active = True
        monkeypatch.setattr(new_reader, "resolve", stale)
        with pytest.raises(BusinessOSError) as stale_failure:
            await _command(app, command, context)
        assert stale_failure.value.code == "custom_schema_unavailable"
        old_reader.active = False
        monkeypatch.undo()
        written = await _command(app, command, context)
        await _command(
            app,
            RetireDefinition(definition_id=written.definition_id, expected_active_generation=1),
            context,
        )
        with pytest.raises(BusinessOSError) as retired:
            await _command(
                app,
                WritePartyCustomValues(**identity, expected_version=1, values=command.values),
                context,
            )
        assert retired.value.code == "custom_schema_unavailable"
        assert (await _query(app, ExportPartyCustomValues(**identity), context)) == written
        assert (
            await _command(app, ClearPartyCustomValues(**identity, expected_version=1), context)
        ).cleared
    finally:
        await app.shutdown()


async def test_draft_never_supplies_business_schema(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app, context, _, party, field = await _setup(postgres_database, publish=False)
    try:
        with pytest.raises(BusinessOSError) as draft:
            await _command(
                app,
                WritePartyCustomValues(
                    tenant_id=context.tenant.tenant_id,
                    party_id=party.id,
                    expected_version=0,
                    values=(CustomFieldValue(field_id=field.field_id, value="draft"),),
                ),
                context,
            )
        assert draft.value.code == "custom_schema_unavailable"
    finally:
        await app.shutdown()


async def test_competing_writes_one_winner_and_explicit_retry(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app, context, _, party, field = await _setup(postgres_database)
    identity = {"tenant_id": context.tenant.tenant_id, "party_id": party.id}
    try:
        results = await asyncio.gather(
            *(
                _command(
                    app,
                    WritePartyCustomValues(
                        **identity,
                        expected_version=0,
                        values=(CustomFieldValue(field_id=field.field_id, value=value),),
                    ),
                    context,
                )
                for value in ("first", "second")
            ),
            return_exceptions=True,
        )
        conflicts = [result for result in results if isinstance(result, BusinessOSError)]
        assert len(conflicts) == 1 and conflicts[0].code == "custom_value_conflict"
        current = await _query(app, ReadPartyCustomValues(**identity), context)
        assert current.value_version == 1
        assert current.values[0].value in {"first", "second"}
        retry = await _command(
            app,
            WritePartyCustomValues(
                **identity,
                expected_version=1,
                values=(CustomFieldValue(field_id=field.field_id, value="explicit retry"),),
            ),
            context,
        )
        assert retry.value_version == 2
    finally:
        await app.shutdown()


async def test_schema_publication_race_pins_resolved_revision(
    postgres_database: PostgreSQLTestDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, context, _, party, field = await _setup(postgres_database)
    identity = {"tenant_id": context.tenant.tenant_id, "party_id": party.id}
    reached, resume = asyncio.Event(), asyncio.Event()
    original = PublishedSchemaReader.resolve
    pinned: list[Any] = []

    async def paused(reader: Any, *args: Any, **kwargs: Any) -> Any:
        schema = await original(reader, *args, **kwargs)
        pinned.append(schema.pin)
        reached.set()
        await resume.wait()
        return schema

    try:
        monkeypatch.setattr(PublishedSchemaReader, "resolve", paused)
        writer = asyncio.create_task(
            _command(
                app,
                WritePartyCustomValues(
                    **identity,
                    expected_version=0,
                    values=(CustomFieldValue(field_id=field.field_id, value="old revision"),),
                ),
                context,
            )
        )
        async with asyncio.timeout(30):
            await reached.wait()
        pin = pinned[0]
        await _command(
            app,
            EditDraft(
                definition_id=pin.definition_id,
                expected_draft_generation=1,
                snapshot=DefinitionSnapshot(
                    kind="field_set",
                    fields=(
                        FieldDefinition(
                            field_id=field.field_id,
                            name="custom_number",
                            value_type="integer",
                            nullable=False,
                        ),
                    ),
                ),
            ),
            context,
        )
        preflight = await _query(
            app, PreflightPublication(definition_id=pin.definition_id), context
        )
        published = await _command(app, PublishDefinition(preflight=preflight), context)
        assert published.status.value == "success" and published.revision_id != pin.revision_id
        resume.set()
        written = await asyncio.wait_for(writer, 30)
        assert written.revision_id == pin.revision_id
        monkeypatch.setattr(PublishedSchemaReader, "resolve", original)
        assert (await _query(app, ReadPartyCustomValues(**identity), context)) == written
        with pytest.raises(BusinessOSError) as incompatible:
            await _command(
                app,
                WritePartyCustomValues(
                    **identity,
                    expected_version=1,
                    values=(CustomFieldValue(field_id=field.field_id, value="old revision"),),
                ),
                context,
            )
        assert incompatible.value.code == "custom_values_invalid"
        replacement = await _command(
            app,
            WritePartyCustomValues(
                **identity,
                expected_version=1,
                values=(CustomFieldValue(field_id=field.field_id, value=42),),
            ),
            context,
        )
        assert replacement.revision_id == published.revision_id and replacement.value_version == 2
    finally:
        resume.set()
        await app.shutdown()


async def test_party_inactivation_wins_lock_race(postgres_database: PostgreSQLTestDatabase) -> None:
    app, context, _, party, field = await _setup(postgres_database)
    identity = {"tenant_id": context.tenant.tenant_id, "party_id": party.id}
    try:
        async with await psycopg.AsyncConnection.connect(
            _url(postgres_database.migration_url)
        ) as lock:
            await lock.execute(
                "SELECT id FROM platform_party.parties WHERE id=%s FOR UPDATE", (party.id,)
            )
            writer = asyncio.create_task(
                _command(
                    app,
                    WritePartyCustomValues(
                        **identity,
                        expected_version=0,
                        values=(CustomFieldValue(field_id=field.field_id, value="race"),),
                    ),
                    context,
                )
            )
            # Synchronize on an observed PostgreSQL row-lock wait, not elapsed sleep.
            async with await psycopg.AsyncConnection.connect(
                _url(postgres_database.administrator_url), autocommit=True
            ) as observer:
                async with asyncio.timeout(30):
                    while True:
                        cursor = await observer.execute(
                            "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                            "WHERE datname=current_database() AND usename='businessos_app' "
                            "AND wait_event_type='Lock' "
                            "AND query LIKE '%%platform_party.parties%%')"
                        )
                        row = await cursor.fetchone()
                        if row and row[0]:
                            break
                        await asyncio.sleep(0.01)
            await lock.execute(
                "UPDATE platform_party.parties SET is_active=false WHERE id=%s", (party.id,)
            )
            await lock.commit()
        with pytest.raises(BusinessOSError) as inactive:
            await asyncio.wait_for(writer, 30)
        assert inactive.value.code == "party_inactive"
        assert await _query(app, ReadPartyCustomValues(**identity), context) is None
    finally:
        await app.shutdown()


async def test_cancellation_and_commit_failure_leave_no_values_or_events(
    postgres_database: PostgreSQLTestDatabase, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, context, _, party, field = await _setup(postgres_database)
    identity = {"tenant_id": context.tenant.tenant_id, "party_id": party.id}
    command = WritePartyCustomValues(
        **identity,
        expected_version=0,
        values=(CustomFieldValue(field_id=field.field_id, value="retry"),),
    )
    reached = asyncio.Event()
    original_resolve = PublishedSchemaReader.resolve

    async def paused(reader: Any, *args: Any, **kwargs: Any) -> Any:
        schema = await original_resolve(reader, *args, **kwargs)
        reached.set()
        await asyncio.Event().wait()
        return schema

    async def failed_commit(unit: SQLAlchemyUnitOfWork) -> None:
        raise RuntimeError("injected pre-commit failure")

    try:
        monkeypatch.setattr(PublishedSchemaReader, "resolve", paused)
        writer = asyncio.create_task(_command(app, command, context))
        await asyncio.wait_for(reached.wait(), 30)
        writer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(writer, 30)
        monkeypatch.setattr(PublishedSchemaReader, "resolve", original_resolve)
        original_commit = SQLAlchemyUnitOfWork.commit
        monkeypatch.setattr(SQLAlchemyUnitOfWork, "commit", failed_commit)
        with pytest.raises(RuntimeError, match="injected pre-commit"):
            await _command(app, command, context)
        monkeypatch.setattr(SQLAlchemyUnitOfWork, "commit", original_commit)
        assert await _query(app, ReadPartyCustomValues(**identity), context) is None
        with psycopg.connect(_url(postgres_database.migration_url)) as db:
            assert db.execute(
                "SELECT count(*) FROM eventing.outbox_messages "
                "WHERE event_type='party.custom-values.changed.v1'"
            ).fetchone() == (0,)
        assert (await _command(app, command, context)).value_version == 1
    finally:
        await app.shutdown()


async def test_rls_grants_and_private_schema_transaction_read_only(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app, context, _, party, field = await _setup(postgres_database)
    tenant_id = context.tenant.tenant_id
    identity = {"tenant_id": tenant_id, "party_id": party.id}
    try:
        await _command(
            app,
            WritePartyCustomValues(
                **identity,
                expected_version=0,
                values=(CustomFieldValue(field_id=field.field_id, value="private"),),
            ),
            context,
        )
        with psycopg.connect(_url(postgres_database.runtime_url), autocommit=True) as db:
            assert db.execute("SELECT count(*) FROM platform_party.custom_values").fetchone() == (
                0,
            )
            db.execute("SELECT set_config('app.tenant_id',%s,false)", (str(uuid4()),))
            assert db.execute("SELECT count(*) FROM platform_party.custom_values").fetchone() == (
                0,
            )
            assert (
                db.execute(
                    "UPDATE platform_party.custom_values SET cleared=true,value_document='{}'"
                ).rowcount
                == 0
            )
            db.execute("SELECT set_config('app.tenant_id','malformed',false)")
            with pytest.raises(psycopg.errors.InvalidTextRepresentation):
                db.execute("SELECT * FROM platform_party.custom_values")
            db.execute("SELECT set_config('app.tenant_id',%s,false)", (str(tenant_id),))
            assert db.execute("SELECT count(*) FROM platform_party.custom_values").fetchone() == (
                1,
            )
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db.execute("DELETE FROM platform_party.custom_values")
        with psycopg.connect(_url(postgres_database.metadata_url), autocommit=True) as db:
            for sql in (
                "SELECT * FROM platform_party.custom_values",
                "UPDATE platform_party.custom_values SET cleared=true,value_document='{}'",
                "INSERT INTO platform_party.custom_values "
                "SELECT * FROM platform_party.custom_values",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    db.execute(sql)
        with psycopg.connect(_url(postgres_database.migration_url)) as db:
            assert db.execute(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE oid='platform_party.custom_values'::regclass"
            ).fetchone() == (True, True)
            fks = db.execute(
                "SELECT confrelid::regclass::text FROM pg_constraint "
                "WHERE conrelid='platform_party.custom_values'::regclass AND contype='f'"
            ).fetchall()
            assert fks == [("platform_party.parties",)]
        module = app.runtime.modules.get("foundation.metadata").module
        reader = module._schema_reader
        async with reader._factory(context.tenant) as unit:
            assert (
                await unit.persistence.execute(text("SHOW transaction_read_only"))
            ).scalar_one() == "on"
            with pytest.raises(Exception) as read_only:
                await unit.persistence.execute(
                    text("UPDATE platform_metadata.definitions SET updated_at=now()")
                )
            assert "read-only" in str(read_only.value)
    finally:
        await app.shutdown()
