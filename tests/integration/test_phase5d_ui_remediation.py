"""Synchronized PostgreSQL regressions for Phase 5D audit findings."""

import asyncio
import json
from dataclasses import replace
from typing import cast
from uuid import uuid4

import psycopg
import pytest
from businessos_metadata.activation_fence import MetadataActivationFence
from businessos_metadata.module import (
    CreateUIOverlay,
    EditUIOverlay,
    MetadataModule,
    ReactivateUIOverlay,
    ReadUIOverlay,
    RetireUIOverlay,
)
from businessos_metadata.ui_contracts import UIOverlayMutationResult, UIOverlayScope
from businessos_party import module as party_module
from businessos_party.ui_declarations import published_ui_declarations

from businessos.activation import ContributionGeneration
from businessos.metadata_execution import MetadataDatabaseExecutionAuthority
from businessos.modules.manifest import ModuleDependency
from businessos.persistence.uow import SQLAlchemyUnitOfWork
from businessos.sdk import (
    BusinessOSError,
    ConfigurationError,
    HandlingContext,
    MetadataDeclaration,
    ModuleManifest,
    ModuleRegistration,
)
from tests.conftest import PostgreSQLTestDatabase
from tests.integration.test_phase5a_metadata import _app, _context, _url
from tests.integration.test_phase5d_ui import (
    VIEW,
    Harness,
    PausingPolicy,
    UIPolicy,
    create,
    document,
    paused_harness,
    publish,
)
from tests.integration.test_phase5d_ui import ui_harness as ui_harness
from tests.unit.test_phase5d_ui import extension

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.asyncio]


class ExtensionModule:
    manifest = ModuleManifest(
        module_id="example.partner",
        name="UI regression extension",
        publisher="BusinessOS tests",
        version="0.1.0",
        platform=">=0.1,<1",
        sdk=">=0.1,<1",
        entry_point="tests.integration.test_phase5d_ui_remediation:ExtensionModule",
        dependencies=(ModuleDependency(module_id="foundation.party", version=">=0.3,<1"),),
    )

    def __init__(self) -> None:
        self.declaration = extension()

    async def register(self, registration: ModuleRegistration) -> None:
        registration.metadata(
            MetadataDeclaration(
                key=self.declaration.key,
                kind=self.declaration.kind,
                value=json.loads(self.declaration.document_json),
            )
        )

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


@pytest.mark.parametrize("cancel", [False, True])
async def test_extension_disable_cannot_complete_before_publication_boundary(
    postgres_database: PostgreSQLTestDatabase,
    monkeypatch: pytest.MonkeyPatch,
    cancel: bool,
) -> None:
    policy = UIPolicy()
    app = _app(postgres_database, policy)
    app.runtime.modules.add(ExtensionModule())
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    await app.startup()
    h = Harness(app, postgres_database, _context(uuid4()), policy)
    entered, release = asyncio.Event(), asyncio.Event()
    drain_entered = asyncio.Event()
    original = MetadataModule._ui_evidence
    close = app.runtime.contributions.close_and_drain

    async def draining(generation: ContributionGeneration, *, timeout_seconds: float) -> None:
        drain_entered.set()
        await close(generation, timeout_seconds=timeout_seconds)

    monkeypatch.setattr(app.runtime.contributions, "close_and_drain", draining)

    async def pause(
        self: MetadataModule, record: UIOverlayMutationResult, action: str, ctx: HandlingContext
    ) -> None:
        await original(self, record, action, ctx)
        if action == "publish":
            entered.set()
            await release.wait()

    try:
        row = await create(h)
        monkeypatch.setattr(MetadataModule, "_ui_evidence", pause)
        task = asyncio.create_task(publish(h, row))
        await asyncio.wait_for(entered.wait(), 5)
        generation = app.runtime.contributions.active_generation("example.partner")
        disabling = asyncio.create_task(app.runtime.lifecycle.disable("example.partner"))
        await asyncio.wait_for(drain_entered.wait(), 5)
        assert not app.runtime.contributions.is_active(generation)
        assert not disabling.done()
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
        else:
            release.set()
            with pytest.raises(BusinessOSError):
                await asyncio.wait_for(task, 5)
        await asyncio.wait_for(disabling, 5)
        # Successful lifecycle removal proves discard found no retained leases.
        assert not app.runtime.contributions.is_active(generation)
        with psycopg.connect(_url(postgres_database.migration_url)) as connection:
            assert connection.execute(
                "SELECT count(*) FROM platform_metadata.ui_overlay_revisions"
            ).fetchone() == (0,)
            assert connection.execute(
                "SELECT count(*) FROM eventing.outbox_messages"
            ).fetchone() == (1,)
        await app.runtime.lifecycle.enable("example.partner")
        release.set()
        published = await publish(h, row)
        assert (await h.resolve()).resolved is not None
        await app.runtime.lifecycle.disable("example.partner")
        assert (await h.resolve()).resolved is None
        await h.command(
            RetireUIOverlay(
                overlay_id=published.overlay_id,
                expected_draft_generation=published.draft_generation,
                expected_active_generation=published.active_generation,
            )
        )
        with psycopg.connect(_url(postgres_database.migration_url)) as connection:
            assert connection.execute(
                "SELECT active_bindings FROM platform_metadata.module_fence "
                "WHERE module_id='example.partner'"
            ).fetchone() == (0,)
    finally:
        release.set()
        await app.shutdown()


async def test_rollback_does_not_disclose_confidential_draft(ui_harness: Harness) -> None:
    h = ui_harness
    original = await publish(h, await create(h))
    assert original.active_revision_id is not None
    edited = await h.command(
        EditUIOverlay(
            overlay_id=original.overlay_id,
            expected_draft_generation=1,
            expected_active_generation=1,
            document=document(99, label="confidential.draft"),
        )
    )
    h.policy.denied.add("foundation.metadata.ui.draft")
    with pytest.raises(BusinessOSError):
        await h.query(ReadUIOverlay(overlay_id=original.overlay_id))
    result = await h.command(
        ReactivateUIOverlay(
            overlay_id=original.overlay_id,
            expected_draft_generation=edited.draft_generation,
            expected_active_generation=edited.active_generation,
            revision_id=original.active_revision_id,
        )
    )
    assert type(result) is UIOverlayMutationResult
    assert not hasattr(result, "draft_document")
    assert "draft_document" not in result.model_dump()
    assert "confidential" not in result.model_dump_json()
    with psycopg.connect(_url(h.database.migration_url)) as connection:
        assert "confidential" not in str(
            connection.execute("SELECT to_jsonb(a) FROM platform_audit.audit_logs a").fetchall()
        )
        assert "confidential" not in str(
            connection.execute("SELECT payload FROM eventing.outbox_messages").fetchall()
        )


async def test_compound_read_fence_denies_revoked_ui_permission(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    h = await paused_harness(postgres_database)
    policy = cast(PausingPolicy, h.policy)
    try:
        policy.pause = True
        task = asyncio.create_task(h.resolve())
        await asyncio.wait_for(policy.entered.wait(), 5)
        await policy.revoke(h.context, "foundation.metadata.ui.read")
        policy.release.set()
        with pytest.raises(BusinessOSError):
            await asyncio.wait_for(task, 5)
        policy.pause = False
        with pytest.raises(BusinessOSError):
            await h.resolve()
    finally:
        policy.release.set()
        await h.app.shutdown()


async def test_authority_fence_is_held_through_outer_commit_without_global_serialization(
    ui_harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = ui_harness
    row = await create(h)
    entered, release, revoke_entered = asyncio.Event(), asyncio.Event(), asyncio.Event()
    commit = SQLAlchemyUnitOfWork.commit

    async def paused_commit(uow: SQLAlchemyUnitOfWork) -> None:
        entered.set()
        await release.wait()
        await commit(uow)

    monkeypatch.setattr(SQLAlchemyUnitOfWork, "commit", paused_commit)
    publishing = asyncio.create_task(publish(h, row))
    await asyncio.wait_for(entered.wait(), 5)
    assert h.policy.lock(h.context).locked()

    async def revoking() -> None:
        revoke_entered.set()
        await h.policy.revoke(h.context, "foundation.metadata.ui.publish")

    revocation = asyncio.create_task(revoking())
    await asyncio.wait_for(revoke_entered.wait(), 5)
    assert not revocation.done()
    assert h.context.tenant is not None
    other = replace(h.context, tenant=replace(h.context.tenant, principal_id=uuid4()))
    await asyncio.wait_for(h.policy.revoke(other, "unrelated.permission"), 1)
    assert other.tenant is not None
    other_tenant = replace(other, tenant=replace(other.tenant, tenant_id=uuid4()))
    await asyncio.wait_for(h.policy.revoke(other_tenant, "unrelated.permission"), 1)
    release.set()
    result = await asyncio.wait_for(publishing, 5)
    await asyncio.wait_for(revocation, 5)
    assert result.active_revision_id is not None
    assert not h.policy.lock(h.context).locked()
    with pytest.raises(BusinessOSError):
        await publish(h, result)
    with psycopg.connect(_url(h.database.migration_url)) as connection:
        assert connection.execute(
            "SELECT active_revision_id FROM platform_metadata.ui_overlays"
        ).fetchone() == (result.active_revision_id,)


async def test_publish_revocation_during_evidence_rolls_back_all_effects(
    ui_harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = ui_harness
    row = await create(h)
    entered, release = asyncio.Event(), asyncio.Event()
    original = MetadataModule._ui_evidence

    async def pause(
        self: MetadataModule, record: UIOverlayMutationResult, action: str, ctx: HandlingContext
    ) -> None:
        await original(self, record, action, ctx)
        entered.set()
        await release.wait()

    monkeypatch.setattr(MetadataModule, "_ui_evidence", pause)
    task = asyncio.create_task(publish(h, row))
    await asyncio.wait_for(entered.wait(), 5)
    await h.policy.revoke(h.context, "foundation.metadata.ui.publish")
    release.set()
    with pytest.raises(BusinessOSError):
        await asyncio.wait_for(task, 5)
    with psycopg.connect(_url(h.database.migration_url)) as connection:
        assert connection.execute(
            "SELECT count(*) FROM platform_metadata.ui_overlay_revisions"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT active_generation,active_revision_id FROM platform_metadata.ui_overlays"
        ).fetchone() == (0, None)
        assert connection.execute("SELECT count(*) FROM platform_audit.audit_logs").fetchone() == (
            1,
        )
        assert connection.execute("SELECT count(*) FROM eventing.outbox_messages").fetchone() == (
            1,
        )


@pytest.mark.parametrize("module_id", ["foundation.party", "foundation.identity"])
async def test_active_overlay_pins_activation_until_retired(
    ui_harness: Harness,
    module_id: str,
) -> None:
    h = ui_harness
    assert h.app.runtime is not None
    row = await publish(h, await create(h))
    authority = MetadataDatabaseExecutionAuthority(
        governance_url=h.database.metadata_url,
        database_name=h.database.metadata_url.rsplit("/", 1)[1],
        pool_size=2,
        pool_timeout=10,
        gate=h.app.runtime.contributions,
    )
    fence = MetadataActivationFence(authority.internal_installation)
    with psycopg.connect(_url(h.database.migration_url)) as connection:
        state = connection.execute(
            "SELECT artifact_identity,generation,active_bindings "
            "FROM platform_metadata.module_fence "
            "WHERE module_id=%s",
            (module_id,),
        ).fetchone()
    assert state is not None
    identity, _generation, bindings = state
    assert bindings == 1
    async with fence.activation(module_id, identity):
        pass
    with pytest.raises(ConfigurationError, match="active Metadata revisions"):
        async with fence.activation(module_id, identity + "-incompatible"):
            pass
    assert (await h.resolve()).resolved is not None

    await h.command(
        RetireUIOverlay(
            overlay_id=row.overlay_id,
            expected_draft_generation=row.draft_generation,
            expected_active_generation=row.active_generation,
        )
    )
    async with fence.activation(module_id, identity + "-compatible-after-retirement"):
        pass
    await authority.close()


async def test_activation_counts_all_tenants_until_last_overlay_is_retired(
    ui_harness: Harness,
) -> None:
    h = ui_harness
    assert h.app.runtime is not None
    assert h.context.tenant is not None
    second = replace(
        h.context,
        tenant=replace(h.context.tenant, tenant_id=uuid4(), principal_id=uuid4()),
    )
    rows = [(await publish(h, await create(h)), h.context)]
    rows.append((await publish(h, await create(h, context=second), second), second))
    authority = MetadataDatabaseExecutionAuthority(
        governance_url=h.database.metadata_url,
        database_name=h.database.metadata_url.rsplit("/", 1)[1],
        pool_size=2,
        pool_timeout=10,
        gate=h.app.runtime.contributions,
    )
    fence = MetadataActivationFence(authority.internal_installation)
    try:
        for remaining, (row, context) in zip((2, 1), rows, strict=True):
            with psycopg.connect(_url(h.database.migration_url)) as connection:
                state = connection.execute(
                    "SELECT artifact_identity,active_bindings FROM platform_metadata.module_fence "
                    "WHERE module_id='foundation.party'"
                ).fetchone()
            assert state is not None
            identity, bindings = state
            assert bindings == remaining
            with pytest.raises(ConfigurationError):
                async with fence.activation("foundation.party", identity + "-changed"):
                    pass
            await h.command(
                RetireUIOverlay(
                    overlay_id=row.overlay_id,
                    expected_draft_generation=row.draft_generation,
                    expected_active_generation=row.active_generation,
                ),
                context,
            )
        async with fence.activation("foundation.party", identity + "-changed"):
            pass
    finally:
        await authority.close()


@pytest.mark.parametrize("scope", list(UIOverlayScope))
async def test_owner_opt_in_change_fails_closed_at_every_overlay_boundary(
    ui_harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    scope: UIOverlayScope,
) -> None:
    h = ui_harness
    row = await publish(h, await create(h, scope))
    assert row.active_revision_id is not None
    await h.app.shutdown()
    declarations = published_ui_declarations()

    def declined() -> tuple[MetadataDeclaration, ...]:
        return tuple(
            d.model_copy(update={"value": {**d.value, "customization": []}})
            if d.kind == "ui.capabilities.v1"
            else d
            for d in declarations
        )

    # Actual module registration on restart supplies the changed owner contract;
    # neither browser data nor a resolver-only test stub supplies capabilities.
    monkeypatch.setattr(party_module, "published_ui_declarations", declined)
    app = _app(h.database, h.policy)
    await app.startup()
    changed = Harness(app, h.database, h.context, h.policy)
    try:
        resolved = await changed.resolve()
        assert resolved.resolved is None
        assert resolved.diagnostics[0].code == "stale_overlay"
        with pytest.raises(BusinessOSError) as rejected:
            await changed.command(
                CreateUIOverlay(view_id=VIEW, scope_kind=scope, document=document(30))
            )
        assert rejected.value.code == "ui_capability_unavailable"
        with pytest.raises(BusinessOSError) as rejected:
            await changed.command(
                EditUIOverlay(
                    overlay_id=row.overlay_id,
                    expected_draft_generation=row.draft_generation,
                    expected_active_generation=row.active_generation,
                    document=document(30),
                )
            )
        assert rejected.value.code == "ui_capability_unavailable"
        with pytest.raises(BusinessOSError) as rejected:
            await publish(changed, row)
        assert rejected.value.code == "ui_stale_overlay"
        with pytest.raises(BusinessOSError) as rejected:
            await changed.command(
                ReactivateUIOverlay(
                    overlay_id=row.overlay_id,
                    expected_draft_generation=row.draft_generation,
                    expected_active_generation=row.active_generation,
                    revision_id=row.active_revision_id,
                )
            )
        assert rejected.value.code == "ui_stale_overlay"
        with psycopg.connect(_url(h.database.migration_url)) as connection:
            assert connection.execute(
                "SELECT active_generation,active_revision_id FROM platform_metadata.ui_overlays"
            ).fetchone() == (1, row.active_revision_id)
    finally:
        await app.shutdown()
