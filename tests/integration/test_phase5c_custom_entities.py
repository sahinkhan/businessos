"""PostgreSQL governed custom-entity owner, authority and race certification probes."""

import asyncio
import json
from collections.abc import AsyncGenerator
from dataclasses import replace
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
import pytest_asyncio
from businessos_metadata import MetadataModule
from businessos_metadata.contracts import (
    CanonicalResourceReference,
    FieldDefinition,
    ReferenceState,
)
from businessos_metadata.custom_entities import CUSTOM_ENTITY_NAMESPACE, CustomEntityLimits
from businessos_metadata.custom_entity_definitions import CustomEntityDefinitionSnapshot
from businessos_metadata.custom_entity_store import CustomEntityStore
from businessos_metadata.module import (
    ArchiveCustomEntity,
    CreateCustomEntity,
    CreateCustomEntityDefinition,
    EditCustomEntityDraft,
    ExportCustomEntity,
    ListCustomEntities,
    PreflightPublication,
    PublishDefinition,
    ReadCustomEntity,
    RetireCustomEntityDefinition,
    UpdateCustomEntity,
)
from psycopg import sql
from psycopg.rows import dict_row

from businessos.context import RequestContext
from businessos.persistence.uow import SQLAlchemyUnitOfWork
from businessos.sdk import BusinessOSError, CustomFieldValue
from tests.conftest import PostgreSQLTestDatabase
from tests.integration.test_phase5a_metadata import (
    _app,
    _bind,
    _context,
    _Policy,
    _url,
)
from tests.integration.test_phase5a_metadata import (
    _command as _dispatch_command,
)
from tests.integration.test_phase5a_metadata import (
    _query as _dispatch_query,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.asyncio]

Harness = tuple[Any, RequestContext, _Policy, FieldDefinition, UUID]


async def _command(app: Any, command: Any, context: RequestContext) -> Any:
    if context.tenant is not None:
        _bind(context)
    return await _dispatch_command(app, command, context)


async def _query(app: Any, query: Any, context: RequestContext) -> Any:
    if context.tenant is not None:
        _bind(context)
    return await _dispatch_query(app, query, context)


@pytest_asyncio.fixture
async def entity_harness(postgres_database: PostgreSQLTestDatabase) -> AsyncGenerator[Harness]:
    policy = _Policy()
    app = _app(postgres_database, policy)
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    await app.startup()
    context = _context(uuid4())
    field = FieldDefinition(
        field_id=uuid4(), name="entity_value", value_type="text", nullable=False
    )
    try:
        identity = await _type(app, context, field)
        yield app, context, policy, field, identity
    finally:
        await app.shutdown()


async def _create(
    harness: Harness,
    *,
    context: RequestContext | None = None,
    scope_kind: str = "tenant",
    value: str = "CONFIDENTIAL-EXAMPLE",
) -> Any:
    app, original, _, field, identity = harness
    return await _command(
        app,
        CreateCustomEntity(
            entity_type_id=identity,
            scope_kind=scope_kind,
            values=(CustomFieldValue(field_id=field.field_id, value=value),),
        ),
        context or original,
    )


def _effects(database: PostgreSQLTestDatabase, context: RequestContext) -> tuple[int, int, int]:
    assert context.tenant is not None
    with psycopg.connect(_url(database.migration_url)) as connection:
        tenant = context.tenant.tenant_id
        counts = [
            connection.execute(
                f"SELECT count(*) FROM {table} WHERE tenant_id=%s {predicate}", (tenant,)
            ).fetchone()
            for table, predicate in (
                ("platform_metadata.custom_entities", ""),
                ("platform_audit.audit_logs", "AND action LIKE 'metadata.custom-entity.%%'"),
                ("eventing.outbox_messages", "AND event_type='metadata.custom-entity.changed.v1'"),
            )
        ]
        assert all(item is not None for item in counts)
        return tuple(item[0] for item in counts)  # type: ignore[index]


async def test_tenant_scope_and_unavailable_trusted_scope_fail_closed(
    entity_harness: Harness,
) -> None:
    app, context, _, _field, identity = entity_harness
    assert context.tenant is not None
    other = _context(uuid4())
    row = await _create(entity_harness)
    for query in (
        ReadCustomEntity(instance_id=row.identity.instance_id),
        ExportCustomEntity(instance_id=row.identity.instance_id),
        ListCustomEntities(entity_type_id=identity),
    ):
        with pytest.raises(BusinessOSError):
            await _query(app, query, other)
    for cmd in (
        UpdateCustomEntity(instance_id=row.identity.instance_id, expected_version=1, values=()),
        ArchiveCustomEntity(instance_id=row.identity.instance_id, expected_version=1),
    ):
        with pytest.raises(BusinessOSError):
            await _command(app, cmd, other)
    with pytest.raises(BusinessOSError):
        await _query(app, ReadCustomEntity(instance_id=row.identity.instance_id), _context())
    for kind, attribute in (
        ("company", "active_company_id"),
        ("operating_site", "operating_site_id"),
        ("warehouse", "warehouse_id"),
    ):
        with pytest.raises(BusinessOSError, match="Trusted scope"):
            await _create(entity_harness, scope_kind=kind)
        changes: dict[str, Any] = {attribute: uuid4()}
        scoped = replace(context, tenant=replace(context.tenant, **changes))
        _bind(scoped)
        scoped_row = await _create(entity_harness, context=scoped, scope_kind=kind)
        switched = replace(context, tenant=replace(context.tenant, **{attribute: uuid4()}))  # type: ignore[arg-type]
        _bind(switched)
        with pytest.raises(BusinessOSError):
            await _query(
                app, ReadCustomEntity(instance_id=scoped_row.identity.instance_id), switched
            )
        with pytest.raises(BusinessOSError):
            await _command(
                app,
                ArchiveCustomEntity(
                    instance_id=scoped_row.identity.instance_id, expected_version=1
                ),
                switched,
            )
        assert not (
            await _query(
                app, ListCustomEntities(entity_type_id=identity, scope_kind=kind), switched
            )
        ).records
        assert (
            await _query(app, ReadCustomEntity(instance_id=scoped_row.identity.instance_id), scoped)
        ).scope_id == changes[attribute]


async def test_competing_updates_archive_retry_and_safe_evidence(
    entity_harness: Harness, postgres_database: PostgreSQLTestDatabase
) -> None:
    app, context, _, field, _ = entity_harness
    row = await _create(entity_harness)
    results = await asyncio.gather(
        *[
            _command(
                app,
                UpdateCustomEntity(
                    instance_id=row.identity.instance_id,
                    expected_version=1,
                    values=(CustomFieldValue(field_id=field.field_id, value=f"replacement-{n}"),),
                ),
                context,
            )
            for n in range(2)
        ],
        return_exceptions=True,
    )
    winners = [r for r in results if not isinstance(r, BaseException)]
    losers = [r for r in results if isinstance(r, BusinessOSError)]
    assert len(winners) == len(losers) == 1
    assert losers[0].code == "custom_entity_conflict"
    assert winners[0].value_version == 2
    assert _effects(postgres_database, context) == (1, 2, 2)
    current = await _command(
        app,
        UpdateCustomEntity(
            instance_id=row.identity.instance_id,
            expected_version=2,
            values=(CustomFieldValue(field_id=field.field_id, value="retry"),),
        ),
        context,
    )
    assert current.value_version == 3
    race = await asyncio.gather(
        _command(
            app,
            ArchiveCustomEntity(instance_id=row.identity.instance_id, expected_version=3),
            context,
        ),
        _command(
            app,
            UpdateCustomEntity(
                instance_id=row.identity.instance_id,
                expected_version=3,
                values=(CustomFieldValue(field_id=field.field_id, value="last"),),
            ),
            context,
        ),
        return_exceptions=True,
    )
    assert sum(not isinstance(r, BaseException) for r in race) == 1
    assert _effects(postgres_database, context) == (1, 4, 4)
    with psycopg.connect(_url(postgres_database.migration_url)) as connection:
        payloads = connection.execute(
            "SELECT payload FROM eventing.outbox_messages WHERE "
            "event_type='metadata.custom-entity.changed.v1'"
        ).fetchall()
        assert len(payloads) == 4
        assert "CONFIDENTIAL-EXAMPLE" not in json.dumps(payloads)
        assert all("value_document" not in json.dumps(p) for p in payloads)


async def test_type_retirement_preserves_pin_read_export_archive(entity_harness: Harness) -> None:
    app, context, _, field, identity = entity_harness
    row = await _create(entity_harness)
    await _command(
        app,
        RetireCustomEntityDefinition(definition_id=identity, expected_active_generation=1),
        context,
    )
    assert (
        await _query(app, ReadCustomEntity(instance_id=row.identity.instance_id), context)
    ).revision_id == row.revision_id
    assert (
        await _query(app, ExportCustomEntity(instance_id=row.identity.instance_id), context)
    ).record == row
    with pytest.raises(BusinessOSError):
        await _create(entity_harness)
    with pytest.raises(BusinessOSError):
        await _command(
            app,
            UpdateCustomEntity(
                instance_id=row.identity.instance_id,
                expected_version=1,
                values=(CustomFieldValue(field_id=field.field_id, value="new"),),
            ),
            context,
        )
    archived = await _command(
        app, ArchiveCustomEntity(instance_id=row.identity.instance_id, expected_version=1), context
    )
    assert archived.values == row.values and archived.revision_id == row.revision_id


async def test_publication_race_commits_resolved_immutable_pin(
    entity_harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, context, _, field, identity = entity_harness
    ready, resume = asyncio.Event(), asyncio.Event()
    original = CustomEntityStore._active
    paused = False

    async def resolve(self: CustomEntityStore, definition_id: UUID, ctx: Any) -> Any:
        nonlocal paused
        revision = await original(self, definition_id, ctx)
        if not paused:
            paused = True
            ready.set()
            await resume.wait()
        return revision

    monkeypatch.setattr(CustomEntityStore, "_active", resolve)
    writer = asyncio.create_task(_create(entity_harness))
    await asyncio.wait_for(ready.wait(), 10)
    try:
        replacement = FieldDefinition(
            field_id=field.field_id, name=field.name, value_type="integer", nullable=False
        )
        await _command(
            app,
            EditCustomEntityDraft(
                definition_id=identity,
                expected_draft_generation=1,
                snapshot=CustomEntityDefinitionSnapshot(
                    kind="custom_entity", fields=(replacement,)
                ),
            ),
            context,
        )
        preflight = await _query(app, PreflightPublication(definition_id=identity), context)
        new_revision = await _command(app, PublishDefinition(preflight=preflight), context)
        assert new_revision.status.value == "success"
    finally:
        resume.set()
    row = await asyncio.wait_for(writer, 15)
    assert row.revision_id != new_revision.revision_id
    assert (
        await _query(app, ReadCustomEntity(instance_id=row.identity.instance_id), context)
    ).values == row.values
    with pytest.raises(BusinessOSError):
        await _command(
            app,
            UpdateCustomEntity(
                instance_id=row.identity.instance_id, expected_version=1, values=row.values
            ),
            context,
        )
    next_row = await _command(
        app,
        UpdateCustomEntity(
            instance_id=row.identity.instance_id,
            expected_version=1,
            values=(CustomFieldValue(field_id=field.field_id, value=7),),
        ),
        context,
    )
    assert next_row.revision_id == new_revision.revision_id and next_row.value_version == 2


async def _type(app: Any, context: RequestContext, field: FieldDefinition) -> UUID:
    created = await _command(
        app,
        CreateCustomEntityDefinition(
            resource_namespace=CUSTOM_ENTITY_NAMESPACE,
            owner_contract_version="1",
            kind="custom_entity",
            snapshot=CustomEntityDefinitionSnapshot(kind="custom_entity", fields=(field,)),
        ),
        context,
    )
    preflight = await _query(
        app, PreflightPublication(definition_id=created.identity.definition_id), context
    )
    published = await _command(app, PublishDefinition(preflight=preflight), context)
    assert published.status.value == "success"
    return cast(UUID, created.identity.definition_id)


async def test_policy_and_validation_denials_have_no_effects(
    entity_harness: Harness,
    postgres_database: PostgreSQLTestDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, context, policy, _field, identity = entity_harness
    row = await _create(entity_harness)
    baseline = _effects(postgres_database, context)
    commands = (
        ("create", CreateCustomEntity(entity_type_id=identity, values=row.values)),
        (
            "update",
            UpdateCustomEntity(
                instance_id=row.identity.instance_id, expected_version=1, values=row.values
            ),
        ),
        ("archive", ArchiveCustomEntity(instance_id=row.identity.instance_id, expected_version=1)),
    )
    queries = (
        ("read", ReadCustomEntity(instance_id=row.identity.instance_id)),
        ("export", ExportCustomEntity(instance_id=row.identity.instance_id)),
        ("read", ListCustomEntities(entity_type_id=identity)),
    )
    denied = ""
    mode = "deny"

    async def selective(principal_id: UUID, tenant: Any, permission: str) -> bool:
        if permission == denied:
            if mode == "error":
                raise RuntimeError("Policy unavailable")
            if mode == "unknown":
                return cast(bool, None)
            return False
        return True

    monkeypatch.setattr(policy, "is_allowed", selective)
    for name, message in (*commands, *queries):
        denied = f"foundation.metadata.custom_entity.{name}"
        for next_mode in ("deny", "unknown", "error"):
            mode = next_mode
            with pytest.raises((BusinessOSError, RuntimeError)):
                await (
                    _command(app, message, context)
                    if (name, message) in commands
                    else _query(app, message, context)
                )
            assert _effects(postgres_database, context) == baseline
    denied, mode = "foundation.metadata.definition.read", "deny"
    for message in (commands[0][1], commands[1][1], commands[2][1]):
        with pytest.raises(BusinessOSError):
            await _command(app, message, context)
    for _, message in queries:
        with pytest.raises(BusinessOSError):
            await _query(app, message, context)
    denied = ""
    with pytest.raises(BusinessOSError):
        await _command(
            app,
            CreateCustomEntity(
                entity_type_id=identity,
                values=(CustomFieldValue(field_id=uuid4(), value="arbitrary"),),
            ),
            context,
        )
    with pytest.raises(BusinessOSError):
        await _query(
            app, ListCustomEntities(entity_type_id=identity, query_operation="filter"), context
        )
    assert _effects(postgres_database, context) == baseline
    assert (
        await _query(app, ReadCustomEntity(instance_id=row.identity.instance_id), context)
    ) == row


async def test_cancel_and_failed_commit_rollback_values_audit_outbox(
    entity_harness: Harness,
    postgres_database: PostgreSQLTestDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _app_instance, context, _, _, _ = entity_harness
    reached, release = asyncio.Event(), asyncio.Event()
    original_evidence = MetadataModule._entity_evidence

    async def pause(self: MetadataModule, record: Any, action: str, ctx: Any) -> None:
        await original_evidence(self, record, action, ctx)
        reached.set()
        await release.wait()

    monkeypatch.setattr(MetadataModule, "_entity_evidence", pause)
    writer = asyncio.create_task(_create(entity_harness))
    try:
        await asyncio.wait_for(reached.wait(), 10)
        assert _effects(postgres_database, context) == (0, 0, 0)
        writer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await writer
    finally:
        release.set()
        if not writer.done():
            writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)
    assert _effects(postgres_database, context) == (0, 0, 0)
    monkeypatch.setattr(MetadataModule, "_entity_evidence", original_evidence)
    original_commit = SQLAlchemyUnitOfWork.commit

    async def fail_commit(unit: SQLAlchemyUnitOfWork) -> None:
        raise RuntimeError("injected pre-commit failure")

    monkeypatch.setattr(SQLAlchemyUnitOfWork, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="injected pre-commit"):
        await _create(entity_harness)
    assert _effects(postgres_database, context) == (0, 0, 0)
    monkeypatch.setattr(SQLAlchemyUnitOfWork, "commit", original_commit)
    assert (await _create(entity_harness)).value_version == 1
    assert _effects(postgres_database, context) == (1, 1, 1)


async def test_same_owner_reference_archive_race_and_retained_diagnostics(
    entity_harness: Harness,
    postgres_database: PostgreSQLTestDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, context, _, _, _ = entity_harness
    assert context.tenant is not None
    target = await _create(entity_harness)
    field = FieldDefinition(
        field_id=uuid4(),
        name="linked_record",
        value_type="reference",
        nullable=False,
        reference_namespace=CUSTOM_ENTITY_NAMESPACE,
        reference_contract_version="1",
    )
    identity = await _type(app, context, field)
    reference = CanonicalResourceReference(
        tenant_id=context.tenant.tenant_id,
        resource_namespace=CUSTOM_ENTITY_NAMESPACE,
        contract_version="1",
        record_id=target.identity.instance_id,
    )

    async def create_ref(ref: Any) -> Any:
        return await _command(
            app,
            CreateCustomEntity(
                entity_type_id=identity,
                values=(CustomFieldValue(field_id=field.field_id, value=ref),),
            ),
            context,
        )

    for bad in (
        str(target.identity.instance_id),
        reference.model_copy(update={"record_id": uuid4()}).model_dump(mode="json"),
        reference.model_copy(update={"tenant_id": uuid4()}).model_dump(mode="json"),
        reference.model_copy(update={"resource_namespace": "foundation.party.party"}).model_dump(
            mode="json"
        ),
    ):
        with pytest.raises(BusinessOSError):
            await create_ref(bad)
    scoped_context = replace(context, tenant=replace(context.tenant, active_company_id=uuid4()))
    company_target = await _create(entity_harness, context=scoped_context, scope_kind="company")
    with pytest.raises(BusinessOSError):
        await create_ref(
            reference.model_copy(
                update={"record_id": company_target.identity.instance_id}
            ).model_dump(mode="json")
        )
    validated, release = asyncio.Event(), asyncio.Event()
    original_refs = CustomEntityStore._references
    paused = False

    async def references(self: CustomEntityStore, refs: Any, ctx: Any, *, writing: bool) -> Any:
        nonlocal paused
        result = await original_refs(self, refs, ctx, writing=writing)
        if writing and refs and not paused:
            paused = True
            validated.set()
            await release.wait()
        return result

    monkeypatch.setattr(CustomEntityStore, "_references", references)
    writer = asyncio.create_task(create_ref(reference.model_dump(mode="json")))
    archiver: asyncio.Task[Any] | None = None
    try:
        await asyncio.wait_for(validated.wait(), 10)
        archiver = asyncio.create_task(
            _command(
                app,
                ArchiveCustomEntity(instance_id=target.identity.instance_id, expected_version=1),
                context,
            )
        )
        authority = app.runtime.messages._protected_database._profiles[1]
        admission = authority._mutation_admission
        async with admission._condition:
            await asyncio.wait_for(
                admission._condition.wait_for(lambda: len(admission._tickets) == 2), 10
            )
        # Same target is queued before checkout; only the slow writer owns capacity.
        assert authority._active.engine.pool.checkedout() == 1
        with psycopg.connect(_url(postgres_database.migration_url)) as db:
            with pytest.raises(psycopg.errors.LockNotAvailable):
                db.execute(
                    "SELECT id FROM platform_metadata.custom_entities "
                    "WHERE id=%s FOR UPDATE NOWAIT",
                    (target.identity.instance_id,),
                )
        assert not archiver.done()
        release.set()
        source = await asyncio.wait_for(writer, 15)
        await asyncio.wait_for(archiver, 15)
    finally:
        release.set()
        for task in (writer, archiver):
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    retained = await _query(app, ReadCustomEntity(instance_id=source.identity.instance_id), context)
    assert retained.values == source.values and retained.value_version == 1
    assert retained.revision_id == source.revision_id
    assert retained.references[0].state is ReferenceState.RETIRED
    assert not retained.references[0].referenceable
    with pytest.raises(BusinessOSError):
        await create_ref(reference.model_dump(mode="json"))
    exported = await _query(
        app, ExportCustomEntity(instance_id=source.identity.instance_id), context
    )
    assert exported.record == retained
    cross_owner = field.model_copy(update={"reference_namespace": "foundation.party.party"})
    other_type = await _type(app, context, cross_owner)
    with pytest.raises(BusinessOSError, match="Cross-owner"):
        await _command(app, CreateCustomEntity(entity_type_id=other_type, values=()), context)


async def test_serialized_first_write_quotas_and_deterministic_pagination(
    entity_harness: Harness,
    postgres_database: PostgreSQLTestDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, context, _, field, identity = entity_harness
    metadata = app.runtime.modules.get("foundation.metadata").module
    monkeypatch.setattr(
        metadata._entities,
        "_limits",
        CustomEntityLimits(max_instances_per_tenant=2, max_instances_per_type=1, max_page_size=1),
    )
    results = await asyncio.gather(
        _create(entity_harness), _create(entity_harness), return_exceptions=True
    )
    assert sum(not isinstance(r, BaseException) for r in results) == 1
    assert sum(isinstance(r, BusinessOSError) and r.code == "quota_exceeded" for r in results) == 1
    first = next(r for r in results if not isinstance(r, BaseException))
    await _command(
        app,
        ArchiveCustomEntity(instance_id=first.identity.instance_id, expected_version=1),
        context,
    )
    with pytest.raises(BusinessOSError, match="quota"):
        await _create(entity_harness)
    second_type = await _type(app, context, field)
    await _command(
        app, CreateCustomEntity(entity_type_id=second_type, values=first.values), context
    )
    third_type = await _type(app, context, field)
    with pytest.raises(BusinessOSError, match="quota"):
        await _command(
            app, CreateCustomEntity(entity_type_id=third_type, values=first.values), context
        )
    with pytest.raises(BusinessOSError, match="Page size"):
        await _query(app, ListCustomEntities(entity_type_id=identity, page_size=2), context)
    monkeypatch.setattr(metadata._entities, "_limits", CustomEntityLimits(max_page_size=2))
    rows = [await _create(entity_harness) for _ in range(4)]
    expected = sorted([first.identity.instance_id, *(r.identity.instance_id for r in rows)])
    seen: list[UUID] = []
    after = None
    while True:
        page = await _query(
            app, ListCustomEntities(entity_type_id=identity, page_size=2, after=after), context
        )
        seen.extend(r.identity.instance_id for r in page.records)
        if page.next_after is None:
            break
        assert page.next_after == seen[-1]
        after = page.next_after
    assert seen == expected and len(seen) == len(set(seen))
    assert _effects(postgres_database, context) == (6, 7, 7)


async def test_database_rls_effective_grants_and_structural_constraints(
    entity_harness: Harness, postgres_database: PostgreSQLTestDatabase
) -> None:
    app, context, _, field, _ = entity_harness
    assert context.tenant is not None
    row = await _create(entity_harness)
    with psycopg.connect(_url(postgres_database.metadata_url)) as db:
        assert db.execute(
            "SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
            "WHERE oid='platform_metadata.custom_entities'::regclass"
        ).fetchone() == (True, True)
        assert db.execute("SELECT count(*) FROM platform_metadata.custom_entities").fetchone() == (
            0,
        )
        db.execute("SELECT set_config('app.tenant_id',%s,true)", (str(uuid4()),))
        assert db.execute("SELECT count(*) FROM platform_metadata.custom_entities").fetchone() == (
            0,
        )
        assert (
            db.execute("UPDATE platform_metadata.custom_entities SET value_version=2").rowcount == 0
        )
        db.execute("SELECT set_config('app.tenant_id',%s,true)", (str(context.tenant.tenant_id),))
        assert db.execute("SELECT count(*) FROM platform_metadata.custom_entities").fetchone() == (
            1,
        )
        for permission in (
            "SELECT",
            "INSERT",
            "UPDATE",
            "DELETE",
            "TRUNCATE",
            "REFERENCES",
            "TRIGGER",
        ):
            assert db.execute(
                "SELECT has_table_privilege(current_user,'platform_metadata.custom_entities',%s)",
                (permission,),
            ).fetchone() == (permission in {"SELECT", "INSERT", "UPDATE"},)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute("DELETE FROM platform_metadata.custom_entities")
        db.rollback()
        with pytest.raises(psycopg.Error):
            db.execute("SELECT set_config('app.tenant_id','malformed',true)")
            db.execute("SELECT count(*) FROM platform_metadata.custom_entities")
        db.rollback()
    for url in (
        postgres_database.runtime_url,
        postgres_database.worker_url,
        postgres_database.operations_url,
    ):
        with psycopg.connect(_url(url)) as db:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db.execute("SELECT * FROM platform_metadata.custom_entities")
    second_type = await _type(app, context, field)
    second = await _command(
        app, CreateCustomEntity(entity_type_id=second_type, values=row.values), context
    )
    with psycopg.connect(_url(postgres_database.migration_url), row_factory=dict_row) as db:
        original = db.execute(
            "SELECT * FROM platform_metadata.custom_entities WHERE id=%s",
            (row.identity.instance_id,),
        ).fetchone()
        assert original is not None
        invalid_changes: tuple[dict[str, Any], ...] = (
            {"value_version": 0},
            {"value_version": 2},
            {"lifecycle": "purged"},
            {"lifecycle": "archived"},
            {"scope_kind": "branch"},
            {"scope_id": uuid4()},
            {"scope_id": None},
            {"revision_digest": "bad"},
            {"value_document": []},
            {"revision_id": uuid4()},
            {"revision_digest": "0" * 64},
            {"revision_id": second.revision_id, "revision_digest": second.revision_digest},
            {"tenant_id": uuid4()},
        )
        for changes in invalid_changes:
            candidate = {**original, "id": uuid4(), **changes}
            columns = list(candidate)
            parameters = [
                psycopg.types.json.Jsonb(candidate[key])
                if key == "value_document"
                else candidate[key]
                for key in columns
            ]
            statement = sql.SQL(
                "INSERT INTO platform_metadata.custom_entities ({}) VALUES ({})"
            ).format(
                sql.SQL(",").join(map(sql.Identifier, columns)),
                sql.SQL(",").join(sql.Placeholder() for _ in columns),
            )
            with pytest.raises(psycopg.Error):
                db.execute(statement, parameters)
            db.rollback()
        for update_statement, update_parameters in (
            (
                "UPDATE platform_metadata.custom_entities SET definition_id=%s,"
                "value_version=2 WHERE id=%s",
                (second_type, row.identity.instance_id),
            ),
            (
                "UPDATE platform_metadata.custom_entities SET scope_kind='company',scope_id=%s,"
                "value_version=2 WHERE id=%s",
                (uuid4(), row.identity.instance_id),
            ),
            (
                "UPDATE platform_metadata.definitions SET "
                "resource_namespace='foundation.party.party' WHERE id=%s",
                (second_type,),
            ),
            (
                "DELETE FROM platform_metadata.custom_entities WHERE id=%s",
                (row.identity.instance_id,),
            ),
        ):
            with pytest.raises(psycopg.Error):
                db.execute(update_statement, update_parameters)
            db.rollback()
    assert (
        await _query(app, ReadCustomEntity(instance_id=row.identity.instance_id), context)
    ) == row


async def test_draft_classification_and_definition_quota_fail_closed(
    entity_harness: Harness,
    postgres_database: PostgreSQLTestDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from businessos_metadata.contracts import MetadataLimits

    app, context, _, field, _ = entity_harness
    draft = await _command(
        app,
        CreateCustomEntityDefinition(
            resource_namespace=CUSTOM_ENTITY_NAMESPACE,
            owner_contract_version="1",
            kind="custom_entity",
            snapshot=CustomEntityDefinitionSnapshot(kind="custom_entity", fields=(field,)),
        ),
        context,
    )
    with pytest.raises(BusinessOSError, match="Published"):
        await _command(
            app, CreateCustomEntity(entity_type_id=draft.identity.definition_id, values=()), context
        )
    classified = field.model_copy(
        update={"classification_ref": "foundation.data_governance.classification"}
    )
    sensitive = await _command(
        app,
        CreateCustomEntityDefinition(
            resource_namespace=CUSTOM_ENTITY_NAMESPACE,
            owner_contract_version="1",
            kind="custom_entity",
            snapshot=CustomEntityDefinitionSnapshot(kind="custom_entity", fields=(classified,)),
        ),
        context,
    )
    with pytest.raises(BusinessOSError, match="Classified"):
        await _query(
            app, PreflightPublication(definition_id=sensitive.identity.definition_id), context
        )
    # Publication and retained-use gates independently reject classified schemas.
    module = app.runtime.modules.get("foundation.metadata").module
    classified_snapshot = CustomEntityDefinitionSnapshot(kind="custom_entity", fields=(classified,))
    with pytest.raises(BusinessOSError, match="classification"):
        module._entities._schema(
            classified_snapshot.model_dump(mode="json"), classified_snapshot.digest()
        )
    monkeypatch.setattr(module._store, "_limits", MetadataLimits(max_definitions_per_tenant=4))
    command = CreateCustomEntityDefinition(
        resource_namespace=CUSTOM_ENTITY_NAMESPACE,
        owner_contract_version="1",
        kind="custom_entity",
        snapshot=CustomEntityDefinitionSnapshot(kind="custom_entity", fields=(field,)),
    )
    results = await asyncio.gather(
        _command(app, command, context), _command(app, command, context), return_exceptions=True
    )
    assert sum(not isinstance(r, BaseException) for r in results) == 1
    assert sum(isinstance(r, BusinessOSError) and r.code == "quota_exceeded" for r in results) == 1
    assert _effects(postgres_database, context) == (0, 0, 0)


async def test_retained_classified_pin_never_leaks_or_allows_mutation(
    entity_harness: Harness,
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app, context, _, field, identity = entity_harness
    row = await _create(entity_harness)
    assert context.tenant is not None
    classified = CustomEntityDefinitionSnapshot(
        kind="custom_entity",
        fields=(
            field.model_copy(
                update={"classification_ref": "foundation.data_governance.classification"}
            ),
        ),
    )
    revision = uuid4()
    # Inject an operator-retained immutable classified revision; normal publication
    # refuses this schema. This checks every runtime operation independently.
    with psycopg.connect(_url(postgres_database.migration_url)) as db:
        db.execute(
            "INSERT INTO platform_metadata.revisions (id,tenant_id,definition_id,sequence,"
            "snapshot,digest,schema_generation,ui_generation,published_by,provenance) "
            "VALUES (%s,%s,%s,2,%s::jsonb,%s,1,1,%s,'retained-classification-probe')",
            (
                revision,
                context.tenant.tenant_id,
                identity,
                classified.model_dump_json(),
                classified.digest(),
                context.tenant.principal_id,
            ),
        )
        db.execute(
            "UPDATE platform_metadata.custom_entities SET revision_id=%s,revision_digest=%s,"
            "value_version=2 WHERE id=%s",
            (revision, classified.digest(), row.identity.instance_id),
        )
    baseline = _effects(postgres_database, context)
    for query in (
        ReadCustomEntity(instance_id=row.identity.instance_id),
        ExportCustomEntity(instance_id=row.identity.instance_id),
        ListCustomEntities(entity_type_id=identity),
    ):
        with pytest.raises(BusinessOSError, match="classification"):
            await _query(app, query, context)
    for command in (
        ArchiveCustomEntity(instance_id=row.identity.instance_id, expected_version=2),
        UpdateCustomEntity(
            instance_id=row.identity.instance_id, expected_version=2, values=row.values
        ),
    ):
        with pytest.raises(BusinessOSError, match="classification"):
            await _command(app, command, context)
    assert _effects(postgres_database, context) == baseline
    with psycopg.connect(_url(postgres_database.migration_url)) as db:
        assert db.execute(
            "SELECT revision_id,value_version FROM platform_metadata.custom_entities WHERE id=%s",
            (row.identity.instance_id,),
        ).fetchone() == (revision, 2)


async def test_multiple_types_create_read_replace_archive_export_and_page(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = _app(postgres_database, _Policy())
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    await app.startup()
    context = _context(uuid4())
    assert context.tenant is not None
    first = FieldDefinition(
        field_id=uuid4(), name="registration_no", value_type="text", nullable=False
    )
    second = FieldDefinition(
        field_id=uuid4(), name="warranty_no", value_type="text", nullable=False
    )
    try:
        type_a = await _type(app, context, first)
        type_b = await _type(app, context, second)
        assert type_a != type_b
        row = await _command(
            app,
            CreateCustomEntity(
                entity_type_id=type_a,
                values=(CustomFieldValue(field_id=first.field_id, value="PRIVATE-REGISTRATION"),),
            ),
            context,
        )
        assert row.value_version == 1
        assert row.identity.entity_type_id == type_a
        assert row.scope_id == context.tenant.tenant_id
        assert (
            await _query(app, ReadCustomEntity(instance_id=row.identity.instance_id), context)
        ) == row
        with pytest.raises(BusinessOSError, match="Unknown stable"):
            await _command(
                app,
                CreateCustomEntity(
                    entity_type_id=type_a,
                    values=(CustomFieldValue(field_id=second.field_id, value="wrong"),),
                ),
                context,
            )
        assert not (await _query(app, ListCustomEntities(entity_type_id=type_b), context)).records
        page = await _query(app, ListCustomEntities(entity_type_id=type_a, page_size=1), context)
        assert page.records == (row,)
        changed = await _command(
            app,
            UpdateCustomEntity(
                instance_id=row.identity.instance_id,
                expected_version=1,
                values=(CustomFieldValue(field_id=first.field_id, value="replacement"),),
            ),
            context,
        )
        assert changed.value_version == 2
        archived = await _command(
            app,
            ArchiveCustomEntity(instance_id=row.identity.instance_id, expected_version=2),
            context,
        )
        assert archived.lifecycle.value == "archived"
        assert archived.value_version == 3
        assert archived.values == changed.values
        assert archived.archived_at is not None
        exported = await _query(
            app, ExportCustomEntity(instance_id=row.identity.instance_id), context
        )
        assert exported.record == archived
        with pytest.raises(BusinessOSError, match="immutable"):
            await _command(
                app,
                UpdateCustomEntity(
                    instance_id=row.identity.instance_id, expected_version=3, values=()
                ),
                context,
            )
    finally:
        await app.shutdown()
