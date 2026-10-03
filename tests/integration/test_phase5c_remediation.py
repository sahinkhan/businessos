"""Frozen v1 coexistence, low-capacity serviceability and real pool recovery."""

import asyncio
from typing import Any, cast
from uuid import uuid4

import pytest
from businessos_metadata import (
    CreateCustomEntityDefinition,
    CustomEntityDefinitionSnapshot,
    EditCustomEntityDraft,
    ReadActiveCustomEntityRevision,
    ReadCustomEntityDraft,
)
from businessos_metadata.contracts import DefinitionSnapshot, FieldDefinition
from businessos_metadata.custom_entity_store import CustomEntityStore
from businessos_metadata.module import (
    CreateCustomEntity,
    CreateDefinition,
    EditDraft,
    PreflightPublication,
    PublishDefinition,
    ReactivateRevision,
    ReadActiveRevision,
    ReadCustomEntity,
    ReadDraft,
    RetireDefinition,
    UpdateCustomEntity,
)

from businessos.database_execution import ProtectedDatabaseProfiles
from businessos.errors import ConfigurationError, ProtectedDatabaseCapacityError
from businessos.metadata_execution import MetadataDatabaseExecutionAuthority
from businessos.sdk import BusinessOSError, CustomFieldValue
from tests.conftest import PostgreSQLTestDatabase
from tests.fixtures import phase5a_v1_contracts as frozen
from tests.integration.test_phase5a_metadata import _context
from tests.integration.test_phase5c_custom_entities import (
    Harness,
    _command,
    _create,
    _query,
    _type,
)
from tests.integration.test_phase5c_custom_entities import (
    entity_harness as entity_harness,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.asyncio]


@pytest.mark.parametrize("profile_index", [0, 1])
async def test_both_protected_profiles_recover_real_capacity_timeout(
    postgres_database: PostgreSQLTestDatabase,
    profile_index: int,
) -> None:
    from businessos_data_governance import PlaceLegalHoldCommand

    from tests.integration.test_adr022_authority import _application

    app = _application(postgres_database)
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    await app.startup()
    try:
        context = _context(uuid4())
        assert context.tenant is not None
        message: Any = PlaceLegalHoldCommand(
            tenant_id=context.tenant.tenant_id,
            code="case",
            name="Case",
            reason="reason",
            entity_type="party",
            entity_id="1",
            placed_by="actor",
        )
        registered = app.runtime.messages.commands.resolve(message)
        if profile_index == 1:
            message = ReadDraft(definition_id=uuid4())
            registered = app.runtime.messages.queries.resolve(message)
        authority: Any = cast(
            ProtectedDatabaseProfiles, app.runtime.messages._protected_database
        )._profiles[profile_index]
        pool = authority._active
        assert pool is not None and cast(Any, pool.engine.pool).size() == 2
        cast(Any, pool.engine.pool)._timeout = 0.05
        async with pool.engine.connect():
            async with pool.engine.connect():
                with pytest.raises(ProtectedDatabaseCapacityError):
                    async with authority.for_command(registered, type(message), context.tenant):
                        pytest.fail("Exhausted pool admitted request")
                assert authority._active is pool
        async with authority.for_command(registered, type(message), context.tenant) as unit:
            async with unit:
                from sqlalchemy import text

                assert (
                    await unit.persistence.execute(text("SELECT current_user, session_user"))
                ).one() == (
                    "businessos_metadata" if profile_index else "businessos_governance",
                    "businessos_metadata" if profile_index else "businessos_governance",
                )
        assert authority._active is pool and not authority._leases
    finally:
        await app.shutdown()


def _authority(app: Any) -> MetadataDatabaseExecutionAuthority:
    return cast(
        MetadataDatabaseExecutionAuthority,
        cast(ProtectedDatabaseProfiles, app.runtime.messages._protected_database)._profiles[1],
    )


async def test_old_consumer_draft_active_and_new_definition_coexistence(
    entity_harness: Harness,
) -> None:
    app, context, _, field, identity = entity_harness
    custom_snapshot = CustomEntityDefinitionSnapshot(fields=(field,))
    with pytest.raises(BusinessOSError) as error:
        await _command(
            app,
            CreateDefinition.model_construct(
                resource_namespace="foundation.metadata.custom_entity",
                owner_contract_version="1",
                kind=cast(Any, custom_snapshot.kind),
                snapshot=cast(Any, custom_snapshot),
            ),
            context,
        )
    assert error.value.code == "definition_contract_required"
    for kind in ("field_set", "reference_set"):
        created = await _command(
            app,
            CreateDefinition(
                resource_namespace="foundation.metadata.definition",
                owner_contract_version="1",
                kind=kind,
                snapshot=DefinitionSnapshot(kind=kind, fields=(field,)),
            ),
            context,
        )
        frozen.DefinitionRecord.model_validate_json(created.model_dump_json())
        draft = await _query(app, ReadDraft(definition_id=created.identity.definition_id), context)
        frozen.DraftRecord.model_validate_json(draft.model_dump_json())
        token = await _query(
            app, PreflightPublication(definition_id=created.identity.definition_id), context
        )
        await _command(app, PublishDefinition(preflight=token), context)
        active = await _query(
            app, ReadActiveRevision(definition_id=created.identity.definition_id), context
        )
        frozen.RevisionRecord.model_validate_json(active.model_dump_json())
    for operation in (
        ReadDraft(definition_id=identity),
        ReadActiveRevision(definition_id=identity),
    ):
        with pytest.raises(BusinessOSError) as error:
            await _query(app, operation, context)
        assert error.value.code == "definition_contract_required"
    for mutation in (
        EditDraft(
            definition_id=identity,
            expected_draft_generation=1,
            snapshot=DefinitionSnapshot(kind="field_set", fields=(field,)),
        ),
        RetireDefinition(definition_id=identity, expected_active_generation=1),
        EditDraft.model_construct(
            definition_id=identity, expected_draft_generation=1, snapshot=cast(Any, custom_snapshot)
        ),
    ):
        with pytest.raises(BusinessOSError) as error:
            await _command(app, mutation, context)
        assert error.value.code == "definition_contract_required"
    draft = await _query(app, ReadCustomEntityDraft(definition_id=identity), context)
    assert draft.snapshot.kind.value == "custom_entity"
    first = await _query(app, ReadActiveCustomEntityRevision(definition_id=identity), context)
    edited = await _command(
        app,
        EditCustomEntityDraft(
            definition_id=identity,
            expected_draft_generation=1,
            snapshot=CustomEntityDefinitionSnapshot(fields=(field,)),
        ),
        context,
    )
    assert edited.definition.draft_generation == 2
    token = await _query(app, PreflightPublication(definition_id=identity), context)
    second = await _command(app, PublishDefinition(preflight=token), context)
    assert second.status.value == "success"
    token = await _query(
        app,
        PreflightPublication(definition_id=identity, target_revision_id=first.revision_id),
        context,
    )
    restored = await _command(
        app, ReactivateRevision(preflight=token, revision_id=first.revision_id), context
    )
    assert restored.status.value == "success"
    assert (
        await _query(app, ReadActiveCustomEntityRevision(definition_id=identity), context)
    ).revision_id == first.revision_id
    assert (
        await _command(
            app,
            CreateCustomEntityDefinition(snapshot=CustomEntityDefinitionSnapshot(fields=(field,))),
            context,
        )
    ).identity.definition_id != identity


async def test_pool_two_slow_reference_writer_queue_and_unrelated_progress(
    entity_harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, context, _, field, _ = entity_harness
    target = await _create(entity_harness)
    unrelated = await _create(entity_harness)
    other_type = await _type(app, context, field)
    other_record = await _command(
        app, CreateCustomEntity(entity_type_id=other_type, values=target.values), context
    )
    other_context = _context(uuid4())
    other_identity = await _type(app, other_context, field)
    other_tenant = await _command(
        app, CreateCustomEntity(entity_type_id=other_identity, values=target.values), other_context
    )
    link = FieldDefinition(
        field_id=uuid4(),
        name="link",
        value_type="reference",
        nullable=True,
        reference_namespace="foundation.metadata.custom_entity",
        reference_contract_version="1",
    )
    link_type = await _type(app, context, link)
    source = await _command(app, CreateCustomEntity(entity_type_id=link_type, values=()), context)
    assert context.tenant is not None
    value = CustomFieldValue(
        field_id=link.field_id,
        value={
            "tenant_id": str(context.tenant.tenant_id),
            "resource_namespace": "foundation.metadata.custom_entity",
            "contract_version": "1",
            "record_id": str(target.identity.instance_id),
        },
    )
    ready, release = asyncio.Event(), asyncio.Event()
    original = CustomEntityStore._references

    async def pause(self: CustomEntityStore, references: Any, ctx: Any, *, writing: bool) -> Any:
        result = await original(self, references, ctx, writing=writing)
        if writing and references and not ready.is_set():
            ready.set()
            await release.wait()
        return result

    monkeypatch.setattr(CustomEntityStore, "_references", pause)
    authority = _authority(app)
    pool = authority._active
    assert pool is not None and cast(Any, pool.engine.pool).size() == 2
    writer = asyncio.create_task(
        _command(
            app,
            UpdateCustomEntity(
                instance_id=source.identity.instance_id, expected_version=1, values=(value,)
            ),
            context,
        )
    )
    queued: asyncio.Task[Any] | None = None
    try:
        await asyncio.wait_for(ready.wait(), 5)
        queued = asyncio.create_task(
            _command(
                app,
                UpdateCustomEntity(
                    instance_id=target.identity.instance_id,
                    expected_version=1,
                    values=target.values,
                ),
                context,
            )
        )
        admission = authority._mutation_admission
        async with admission._condition:
            await asyncio.wait_for(
                admission._condition.wait_for(lambda: len(admission._tickets) == 2), 5
            )
        assert cast(Any, pool.engine.pool).checkedout() == 1
        assert not queued.done()
        for row, ctx in (
            (unrelated, context),
            (other_record, context),
            (other_tenant, other_context),
        ):
            result = await asyncio.wait_for(
                _command(
                    app,
                    UpdateCustomEntity(
                        instance_id=row.identity.instance_id, expected_version=1, values=row.values
                    ),
                    ctx,
                ),
                5,
            )
            assert result.value_version == 2
        assert (
            await asyncio.wait_for(
                _query(
                    app,
                    ReadCustomEntity(instance_id=other_tenant.identity.instance_id),
                    other_context,
                ),
                5,
            )
        ).value_version == 2
        assert authority._active is pool
        await authority.rotate(pool.engine.url.render_as_string(hide_password=False))
        release.set()
        assert (await asyncio.wait_for(writer, 5)).value_version == 2
        assert (await asyncio.wait_for(queued, 5)).value_version == 2
        assert not authority._mutation_admission._tickets
    finally:
        release.set()
        for task in (writer, queued):
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


async def test_real_pool_timeout_cancellation_recovery_and_security_revocation(
    entity_harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, context, _, _, _ = entity_harness
    row = await _create(entity_harness)
    authority = _authority(app)
    pool = authority._active
    assert pool is not None
    # Same real pool-size-two boundary; shorten only the deliberate capacity probe.
    cast(Any, pool.engine.pool)._timeout = 0.05
    query = ReadCustomEntity(instance_id=row.identity.instance_id)
    async with pool.engine.connect():
        async with pool.engine.connect():
            with pytest.raises(ProtectedDatabaseCapacityError) as error:
                await _query(app, query, context)
            assert (
                error.value.code == "protected_database_capacity" and error.value.status_code == 503
            )
            assert authority._active is pool
            entered = asyncio.Event()
            validate = pool.validate

            async def signal() -> None:
                entered.set()
                await validate()

            monkeypatch.setattr(pool, "validate", signal)
            cast(Any, pool.engine.pool)._timeout = 10
            pending = asyncio.create_task(_query(app, query, context))
            await entered.wait()
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert authority._active is pool
            monkeypatch.setattr(pool, "validate", validate)
    assert (await _query(app, query, context)).value_version == 1
    assert (
        await _command(
            app,
            UpdateCustomEntity(
                instance_id=row.identity.instance_id, expected_version=1, values=row.values
            ),
            context,
        )
    ).value_version == 2

    async def unsafe() -> None:
        raise ConfigurationError("Metadata database identity mismatch")

    monkeypatch.setattr(pool, "validate", unsafe)
    with pytest.raises(ConfigurationError):
        await _query(app, query, context)
    assert authority._active is None
    await authority.rotate(pool.engine.url.render_as_string(hide_password=False))
    assert (await _query(app, query, context)).value_version == 2


async def test_two_way_reference_database_lock_order_without_process_admission(
    entity_harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import MethodType

    from businessos.database_execution import ProtectedDatabaseExecutionAuthority

    app, context, _, _, _ = entity_harness
    assert context.tenant is not None
    field = FieldDefinition(
        field_id=uuid4(),
        name="link",
        value_type="reference",
        nullable=True,
        reference_namespace="foundation.metadata.custom_entity",
        reference_contract_version="1",
    )
    identity = await _type(app, context, field)
    rows = [
        await _command(app, CreateCustomEntity(entity_type_id=identity, values=()), context)
        for _ in range(2)
    ]
    authority = _authority(app)
    # Independent processes do not share the scheduler. Exercise database safety
    # with that optimization deliberately bypassed, never runtime validation.
    monkeypatch.setattr(
        authority,
        "for_message",
        MethodType(ProtectedDatabaseExecutionAuthority.for_message, authority),
    )
    original = CustomEntityStore._locks
    count, ready = 0, asyncio.Event()

    async def barrier(self: CustomEntityStore, ids: Any, types: Any, ctx: Any) -> None:
        nonlocal count
        count += 1
        if count == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), 5)
        await original(self, ids, types, ctx)

    monkeypatch.setattr(CustomEntityStore, "_locks", barrier)
    commands = [
        UpdateCustomEntity(
            instance_id=rows[i].identity.instance_id,
            expected_version=1,
            values=(
                CustomFieldValue(
                    field_id=field.field_id,
                    value={
                        "tenant_id": str(context.tenant.tenant_id),
                        "resource_namespace": "foundation.metadata.custom_entity",
                        "contract_version": "1",
                        "record_id": str(rows[1 - i].identity.instance_id),
                    },
                ),
            ),
        )
        for i in range(2)
    ]
    results = await asyncio.wait_for(
        asyncio.gather(*[_command(app, cmd, context) for cmd in commands]), 10
    )
    assert [record.value_version for record in results] == [2, 2]


async def test_type_retirement_waits_for_involved_writer(
    entity_harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    from businessos_metadata import RetireCustomEntityDefinition
    from businessos_metadata.store import MetadataStore

    app, context, _, _, identity = entity_harness
    row = await _create(entity_harness)
    resolved, release, retiring = asyncio.Event(), asyncio.Event(), asyncio.Event()
    active, retire = CustomEntityStore._active, MetadataStore.retire

    async def pause(self: CustomEntityStore, definition_id: Any, ctx: Any) -> Any:
        result = await active(self, definition_id, ctx)
        resolved.set()
        await release.wait()
        return result

    async def signal(self: MetadataStore, cmd: Any, ctx: Any) -> Any:
        retiring.set()
        return await retire(self, cmd, ctx)

    monkeypatch.setattr(CustomEntityStore, "_active", pause)
    monkeypatch.setattr(MetadataStore, "retire", signal)
    writer = asyncio.create_task(
        _command(
            app,
            UpdateCustomEntity(
                instance_id=row.identity.instance_id, expected_version=1, values=row.values
            ),
            context,
        )
    )
    retirement: asyncio.Task[Any] | None = None
    try:
        await asyncio.wait_for(resolved.wait(), 5)
        retirement = asyncio.create_task(
            _command(
                app,
                RetireCustomEntityDefinition(definition_id=identity, expected_active_generation=1),
                context,
            )
        )
        await asyncio.wait_for(retiring.wait(), 5)
        assert not retirement.done()
        release.set()
        assert (await asyncio.wait_for(writer, 5)).value_version == 2
        assert (await asyncio.wait_for(retirement, 5)).lifecycle.value == "retired"
        with pytest.raises(BusinessOSError) as error:
            await _command(
                app,
                UpdateCustomEntity(
                    instance_id=row.identity.instance_id, expected_version=2, values=row.values
                ),
                context,
            )
        assert error.value.code == "custom_type_inactive"
    finally:
        release.set()
        for task in (writer, retirement):
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


async def test_close_wakes_queued_mutation_and_drains_lease(
    entity_harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, _context, _, _, _ = entity_harness
    ready, release = asyncio.Event(), asyncio.Event()
    original = CustomEntityStore._active

    async def pause(self: CustomEntityStore, identity: Any, ctx: Any) -> Any:
        result = await original(self, identity, ctx)
        ready.set()
        await release.wait()
        return result

    monkeypatch.setattr(CustomEntityStore, "_active", pause)
    authority = _authority(app)
    writer = asyncio.create_task(_create(entity_harness))
    queued: asyncio.Task[Any] | None = None
    try:
        await asyncio.wait_for(ready.wait(), 5)
        queued = asyncio.create_task(_create(entity_harness))
        admission = authority._mutation_admission
        async with admission._condition:
            await asyncio.wait_for(
                admission._condition.wait_for(lambda: len(admission._tickets) == 2), 5
            )
        await authority.close()
        with pytest.raises(ConfigurationError):
            await asyncio.wait_for(queued, 5)
        release.set()
        assert (await asyncio.wait_for(writer, 5)).value_version == 1
        assert not admission._tickets and not authority._leases
    finally:
        release.set()
        for task in (writer, queued):
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
