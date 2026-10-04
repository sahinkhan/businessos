"""Real database sealing and cross-tenant availability witnesses."""

import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import psycopg
import pytest
from businessos_metadata.activation_fence import MetadataActivationFence
from businessos_metadata.module import MetadataModule, ReactivateUIOverlay, RetireUIOverlay
from businessos_metadata.ui_contracts import UIOverlayMutationResult
from sqlalchemy.exc import DBAPIError

from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.metadata_execution import MetadataDatabaseExecutionAuthority
from businessos.modules import discover_modules
from businessos.modules.installation_inventory import approved_artifacts_from_operator_inventory
from businessos.persistence.uow import SQLAlchemyUnitOfWork
from businessos.sdk import (
    BusinessOSError,
    HandlingContext,
    RequestContext,
    TransactionalPersistence,
)
from businessos.security import Authorizer
from tests.conftest import PostgreSQLTestDatabase
from tests.integration.test_phase5a_metadata import (
    _Policy,
    _url,
)
from tests.integration.test_phase5d_ui import (
    Harness,
    UIPolicy,
    _wait_for_publication_lock,
    create,
    publish,
)
from tests.integration.test_phase5d_ui import ui_harness as ui_harness

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.asyncio]


async def test_stalled_publication_bounds_activation_wait_and_releases_on_cancel(
    ui_harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = ui_harness
    assert h.app.runtime is not None
    row = await create(h)
    authority = MetadataDatabaseExecutionAuthority(
        governance_url=h.database.metadata_url,
        database_name=h.database.metadata_url.rsplit("/", 1)[1],
        pool_size=2,
        pool_timeout=10,
        gate=h.app.runtime.contributions,
    )
    fence = MetadataActivationFence(authority.internal_installation)
    entered, release = asyncio.Event(), asyncio.Event()
    original = MetadataModule._ui_evidence

    async def pause(
        self: MetadataModule,
        result: UIOverlayMutationResult,
        action: str,
        ctx: HandlingContext,
    ) -> None:
        await original(self, result, action, ctx)
        entered.set()
        await release.wait()

    monkeypatch.setattr(MetadataModule, "_ui_evidence", pause)
    task = asyncio.create_task(publish(h, row))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        started = time.monotonic()
        with pytest.raises(DBAPIError, match="lock timeout"):
            async with asyncio.timeout(8):
                async with fence.activation("foundation.party", "changed-artifact"):
                    pytest.fail("Activation crossed an in-flight publication")
        assert time.monotonic() - started < 8
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        async with asyncio.timeout(3):
            async with fence.activation("foundation.party", "changed-artifact"):
                pass
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await authority.close()


@pytest.mark.parametrize("reactivate", [False, True])
async def test_publication_seal_serializes_two_direct_late_inserts(
    ui_harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    reactivate: bool,
) -> None:
    h = ui_harness
    row = await create(h)
    if reactivate:
        row = await publish(h, row)
    assert h.context.tenant is not None
    tenant = h.context.tenant.tenant_id
    entered, release = asyncio.Event(), asyncio.Event()
    revision_ids = []
    original = MetadataModule._ui_evidence

    async def pause(
        self: MetadataModule,
        result: UIOverlayMutationResult,
        action: str,
        ctx: HandlingContext,
    ) -> None:
        await original(self, result, action, ctx)
        revision_ids.append(result.active_revision_id)
        entered.set()
        await release.wait()

    async def insert_late() -> None:
        async with await psycopg.AsyncConnection.connect(
            _url(h.database.metadata_url)
        ) as connection:
            await connection.execute("SET LOCAL lock_timeout='3s'")
            await connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant),))
            with pytest.raises(psycopg.errors.RaiseException, match="binding set is sealed"):
                await connection.execute(
                    "INSERT INTO platform_metadata.ui_revision_module_bindings "
                    "(tenant_id,overlay_id,revision_id,module_id,artifact_identity,generation) "
                    "SELECT %s,%s,%s,module_id,artifact_identity,generation "
                    "FROM platform_metadata.module_fence WHERE module_id='foundation.metadata'",
                    (tenant, row.overlay_id, revision_ids[0]),
                )
            await connection.rollback()

    monkeypatch.setattr(MetadataModule, "_ui_evidence", pause)
    operation = (
        h.command(
            ReactivateUIOverlay(
                overlay_id=row.overlay_id,
                revision_id=row.active_revision_id,
                expected_draft_generation=row.draft_generation,
                expected_active_generation=row.active_generation,
            )
        )
        if reactivate
        else publish(h, row)
    )
    task = asyncio.create_task(operation)
    insertions = []
    try:
        await asyncio.wait_for(entered.wait(), 5)
        insertions = [asyncio.create_task(insert_late()) for _ in range(2)]
        await _wait_for_publication_lock(h.database)
        assert not task.done()
        release.set()
        await asyncio.wait_for(task, 5)
        await asyncio.wait_for(asyncio.gather(*insertions), 5)
        with psycopg.connect(_url(h.database.migration_url)) as connection:
            assert connection.execute(
                "SELECT active_bindings FROM platform_metadata.module_fence "
                "WHERE module_id='foundation.party'"
            ).fetchone() == (1,)
    finally:
        release.set()
        for pending in [task, *insertions]:
            if not pending.done():
                pending.cancel()
        await asyncio.gather(task, *insertions, return_exceptions=True)


async def test_publish_and_retirement_cannot_double_transition(
    ui_harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = ui_harness
    row = await create(h)
    entered, release = asyncio.Event(), asyncio.Event()
    original = MetadataModule._ui_evidence

    async def pause(
        self: MetadataModule,
        result: UIOverlayMutationResult,
        action: str,
        ctx: HandlingContext,
    ) -> None:
        await original(self, result, action, ctx)
        if action == "publish":
            entered.set()
            await release.wait()

    monkeypatch.setattr(MetadataModule, "_ui_evidence", pause)
    publication = asyncio.create_task(publish(h, row))
    retirement = None
    try:
        await asyncio.wait_for(entered.wait(), 5)
        retirement = asyncio.create_task(
            h.command(
                RetireUIOverlay(
                    overlay_id=row.overlay_id,
                    expected_draft_generation=row.draft_generation,
                    expected_active_generation=row.active_generation,
                )
            )
        )
        await _wait_for_publication_lock(h.database)
        release.set()
        current = await asyncio.wait_for(publication, 5)
        with pytest.raises(BusinessOSError):
            await asyncio.wait_for(retirement, 5)
        await h.command(
            RetireUIOverlay(
                overlay_id=current.overlay_id,
                expected_draft_generation=current.draft_generation,
                expected_active_generation=current.active_generation,
            )
        )
        with psycopg.connect(_url(h.database.migration_url)) as connection:
            assert connection.execute(
                "SELECT count(*) FROM platform_metadata.module_fence WHERE active_bindings<>0"
            ).fetchone() == (0,)
    finally:
        release.set()
        tasks = [publication] + ([retirement] if retirement is not None else [])
        for pending in tasks:
            if not pending.done():
                pending.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_sealed_binding_set_rejects_direct_role_late_inserts(ui_harness: Harness) -> None:
    h = ui_harness
    row = await publish(h, await create(h))
    assert h.context.tenant is not None
    tenant = h.context.tenant.tenant_id
    with psycopg.connect(_url(h.database.migration_url)) as connection:
        before = connection.execute(
            "SELECT module_id,active_bindings FROM platform_metadata.module_fence ORDER BY 1"
        ).fetchall()
    for _ in range(2):
        with psycopg.connect(_url(h.database.metadata_url)) as connection:
            connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant),))
            with pytest.raises(psycopg.errors.RaiseException, match="binding set is sealed"):
                connection.execute(
                    "INSERT INTO platform_metadata.ui_revision_module_bindings "
                    "(tenant_id,overlay_id,revision_id,module_id,artifact_identity,generation) "
                    "SELECT %s,%s,%s,module_id,artifact_identity,generation "
                    "FROM platform_metadata.module_fence WHERE module_id='foundation.metadata'",
                    (tenant, row.overlay_id, row.active_revision_id),
                )
            connection.rollback()
    with psycopg.connect(_url(h.database.migration_url)) as connection:
        assert (
            connection.execute(
                "SELECT module_id,active_bindings FROM platform_metadata.module_fence ORDER BY 1"
            ).fetchall()
            == before
        )
    await h.command(
        RetireUIOverlay(
            overlay_id=row.overlay_id,
            expected_draft_generation=row.draft_generation,
            expected_active_generation=row.active_generation,
        )
    )
    with psycopg.connect(_url(h.database.migration_url)) as connection:
        assert connection.execute(
            "SELECT count(*) FROM platform_metadata.module_fence WHERE active_bindings<>0"
        ).fetchone() == (0,)


async def test_direct_role_cannot_commit_unsealed_revision_or_reopen_seal(
    ui_harness: Harness,
) -> None:
    h = ui_harness
    row = await create(h)
    assert h.context.tenant is not None
    tenant = h.context.tenant.tenant_id
    with psycopg.connect(_url(h.database.metadata_url)) as connection:
        connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant),))
        connection.execute(
            "INSERT INTO platform_metadata.ui_overlay_revisions "
            "(id,tenant_id,overlay_id,sequence,document,digest,compatibility_digest,published_by) "
            "SELECT %s,tenant_id,id,1,draft_document,%s,draft_compatibility_digest,created_by "
            "FROM platform_metadata.ui_overlays WHERE id=%s",
            (uuid4(), "a" * 64, row.overlay_id),
        )
        with pytest.raises(psycopg.errors.RaiseException, match="requires sealed bindings"):
            connection.commit()
        connection.rollback()
    row = await publish(h, row)
    for table in ("ui_revision_binding_seals", "ui_revision_module_bindings"):
        for statement in (
            f"DELETE FROM platform_metadata.{table} WHERE revision_id=%s",
            f"UPDATE platform_metadata.{table} SET tenant_id=tenant_id WHERE revision_id=%s",
        ):
            with psycopg.connect(_url(h.database.metadata_url)) as connection:
                connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant),))
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    connection.execute(statement, (row.active_revision_id,))
                connection.rollback()
    assert (await h.resolve()).resolved is not None


@pytest.mark.parametrize("interval", ["audit", "outbox", "policy", "commit"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_unrelated_tenant_resolves_while_publisher_paused(
    ui_harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    cancel: bool,
    interval: str,
) -> None:
    h = ui_harness
    assert h.context.tenant is not None
    other = replace(
        h.context,
        tenant=replace(
            h.context.tenant,
            tenant_id=uuid4(),
            principal_id=uuid4(),
        ),
    )
    row = await create(h)
    entered, release = asyncio.Event(), asyncio.Event()
    original = MetadataModule._ui_evidence

    async def pause_here() -> None:
        entered.set()
        await release.wait()

    async def pause(
        self: MetadataModule,
        result: UIOverlayMutationResult,
        action: str,
        ctx: HandlingContext,
    ) -> None:
        if action == "publish" and interval == "audit":
            await pause_here()
        await original(self, result, action, ctx)
        if action == "publish" and interval == "outbox":
            await pause_here()

    original_fence = UIPolicy.permission_fence

    @asynccontextmanager
    async def policy_fence(
        self: UIPolicy,
        context: RequestContext,
        permissions: frozenset[str],
        persistence: TransactionalPersistence,
    ) -> AsyncIterator[None]:
        if interval == "policy" and context == h.context:
            await pause_here()
        async with original_fence(self, context, permissions, persistence):
            yield

    original_commit = SQLAlchemyUnitOfWork.commit

    async def commit(uow: SQLAlchemyUnitOfWork) -> None:
        task = asyncio.current_task()
        if interval == "commit" and task is not None and task.get_name() == "paused-publisher":
            await pause_here()
        await original_commit(uow)

    monkeypatch.setattr(MetadataModule, "_ui_evidence", pause)
    monkeypatch.setattr(UIPolicy, "permission_fence", policy_fence)
    monkeypatch.setattr(SQLAlchemyUnitOfWork, "commit", commit)
    publisher = asyncio.create_task(publish(h, row), name="paused-publisher")
    try:
        await asyncio.wait_for(entered.wait(), 5)
        started = time.monotonic()
        result = await asyncio.wait_for(h.resolve(other), 2)
        elapsed = time.monotonic() - started
        assert result.resolved is not None
        assert result.resolved.view.presentation.order == 0
        assert not publisher.done()
        print(f"OTHER_TENANT_RESOLVED_WHILE_PUBLICATION_PAUSED seconds={elapsed:.4f}")
        if cancel:
            publisher.cancel()
            with pytest.raises(asyncio.CancelledError):
                await publisher
        else:
            release.set()
            assert (await asyncio.wait_for(publisher, 5)).active_revision_id is not None
    finally:
        release.set()
        if not publisher.done():
            publisher.cancel()
            await asyncio.gather(publisher, return_exceptions=True)


@pytest.mark.parametrize(
    "environment,enabled,fenced,status",
    [
        ("production", True, False, 503),
        ("production", True, True, 200),
        ("production", False, False, 200),
        ("development", True, False, 200),
        ("test", True, False, 200),
    ],
)
async def test_production_ui_readiness_requires_fenced_policy(
    postgres_database: PostgreSQLTestDatabase,
    environment: str,
    enabled: bool,
    fenced: bool,
    status: int,
) -> None:
    modules = [
        m
        for m in discover_modules()
        if m.manifest.module_id.startswith("foundation.")
        and (enabled or m.manifest.module_id != "foundation.metadata")
    ]
    settings = Settings.model_validate(
        dict(
            environment=environment,
            database_url=postgres_database.runtime_url,
            metadata_database_url=postgres_database.metadata_url,
            database_readiness_enabled=False,
        )
    )
    inventory = json.loads(
        await asyncio.to_thread(
            Path("tests/fixtures/approved-module-inventory.ci.json").read_text, encoding="utf-8"
        )
    )
    app = create_application(
        settings,
        modules=modules,
        authorizer=Authorizer(UIPolicy() if fenced else _Policy()),
        approved_module_artifacts=approved_artifacts_from_operator_inventory(
            modules, inventory=inventory
        ),
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    await app.startup()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=cast(Any, app)), base_url="http://test"
        ) as client:
            response = await client.get("/readyz")
        assert response.status_code == status
        checks = {item["name"]: item for item in response.json()["checks"]}
        if environment == "production" and enabled:
            assert checks["published-ui-authority-fence"]["ready"] is fenced
        else:
            assert "published-ui-authority-fence" not in checks
    finally:
        await app.shutdown()
