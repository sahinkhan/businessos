"""Private executor isolation and one-UOW failure/cancellation witnesses."""

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import psycopg
import pytest
from businessos_metadata.module import MetadataModule, PublishUIOverlay
from businessos_metadata.ui_contracts import UIOverlayScope
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.base import Executable

from businessos.persistence.uow import SQLAlchemyTransactionalPersistence, SQLAlchemyUnitOfWork
from businessos.sdk import ConfigurationError, HandlingContext
from tests.integration.test_phase5a_metadata import _url
from tests.integration.test_phase5d_ui import Harness, create, publish
from tests.integration.test_phase5d_ui import ui_harness as ui_harness

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.asyncio]

_TABLES = (
    "platform_metadata.ui_overlay_revisions",
    "platform_metadata.ui_expected_provenance",
    "platform_metadata.ui_expected_members",
    "platform_metadata.ui_revision_module_bindings",
    "platform_metadata.ui_revision_binding_seals",
    "platform_audit.audit_logs",
    "eventing.outbox_messages",
)


def _state(h: Harness) -> list[object]:
    with psycopg.connect(_url(h.database.migration_url)) as connection:
        return [
            *[connection.execute(f"SELECT count(*) FROM {table}").fetchone() for table in _TABLES],
            connection.execute(
                "SELECT active_revision_id,active_generation FROM "
                "platform_metadata.ui_overlays ORDER BY id"
            ).fetchall(),
            connection.execute(
                "SELECT module_id,active_bindings FROM "
                "platform_metadata.module_fence ORDER BY module_id"
            ).fetchall(),
        ]


async def test_publication_bypasses_handler_and_never_exposes_private_sql(
    ui_harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = ui_harness
    row = await create(h)
    original = MetadataModule._ui_evidence
    captured: list[HandlingContext] = []
    assert h.app.runtime is not None
    registry = h.app.runtime.messages.commands
    original_handler = registry.invoke_registered

    async def handler(registered: Any, message: Any, context: HandlingContext) -> object:
        assert not isinstance(message, PublishUIOverlay), (
            "Private publication reached ordinary handler"
        )
        return await original_handler(registered, message, context)

    async def evidence(
        self: MetadataModule, record: Any, action: str, ctx: HandlingContext
    ) -> None:
        if action == "publish":
            captured.append(ctx)
            assert not hasattr(ctx.unit_of_work, "_owning_transaction")
            assert not hasattr(ctx.unit_of_work, "commit")
            from sqlalchemy import text

            with pytest.raises(PermissionError, match="unavailable to handlers"):
                await ctx.unit_of_work.persistence.execute(text("SELECT current_user"))
        await original(self, record, action, ctx)

    monkeypatch.setattr(MetadataModule, "_ui_evidence", evidence)
    monkeypatch.setattr(registry, "invoke_registered", handler)
    result = await publish(h, row)
    assert result.active_revision_id is not None
    assert len(captured) == 1
    from businessos.publication_execution import internal_append_publication_audit

    with pytest.raises(PermissionError, match="no longer active"):
        await internal_append_publication_audit(captured[0], object(), {})
    with psycopg.connect(_url(h.database.migration_url)) as connection:
        count = connection.execute(
            "SELECT count(*) FROM platform_metadata.ui_expected_members"
        ).fetchone()
        assert count is not None and count[0] > 1
        xids = connection.execute(
            "SELECT DISTINCT xid FROM ("
            "SELECT xmin::text AS xid FROM platform_metadata.ui_expected_provenance UNION ALL "
            "SELECT xmin::text FROM platform_metadata.ui_expected_members UNION ALL "
            "SELECT xmin::text FROM platform_metadata.ui_overlay_revisions UNION ALL "
            "SELECT xmin::text FROM platform_metadata.ui_revision_module_bindings UNION ALL "
            "SELECT xmin::text FROM platform_metadata.ui_revision_binding_seals UNION ALL "
            "SELECT xmin::text FROM platform_metadata.ui_overlays UNION ALL "
            "SELECT xmin::text FROM platform_metadata.module_fence WHERE "
            "active_bindings>0 UNION ALL "
            "SELECT xmin::text FROM platform_audit.audit_logs WHERE "
            "action='metadata.ui-overlay.publish' UNION ALL "
            "SELECT xmin::text FROM eventing.outbox_messages WHERE payload->>'action'='publish'"
            ") effects"
        ).fetchall()
        assert len(xids) == 1, (
            "Every authoritative effect must have the same PostgreSQL transaction ID"
        )


async def test_resolution_never_uses_issuer_pool(ui_harness: Harness) -> None:
    h = ui_harness
    await publish(h, await create(h))
    assert h.app.runtime is not None
    executor = h.app.runtime.messages._publication
    assert executor is not None
    await executor.authority.close()
    assert (await h.resolve()).resolved is not None
    row = await create(h, kind=UIOverlayScope.COMPANY)
    with pytest.raises(ConfigurationError, match="profile unavailable"):
        await publish(h, row)


async def test_private_profile_rotation_and_forged_registration_fail_closed(
    ui_harness: Harness,
) -> None:
    h = ui_harness
    row = await create(h)
    assert h.app.runtime is not None
    dispatcher = h.app.runtime.messages
    executor = dispatcher._publication
    assert executor is not None
    command = PublishUIOverlay(
        overlay_id=row.overlay_id,
        expected_draft_generation=row.draft_generation,
        expected_active_generation=row.active_generation,
    )
    registered = dispatcher.commands.resolve(command)
    for forged in (replace(registered), replace(registered, owner="foundation.party")):
        with pytest.raises(PermissionError):
            async with executor.authority.for_command(forged, type(command), h.context.tenant):
                pytest.fail("Unenrolled handler acquired private profile")
    with pytest.raises(ConfigurationError):
        await executor.authority.rotate(h.database.metadata_url)
    with pytest.raises(ConfigurationError, match="profile unavailable"):
        await publish(h, row)
    await executor.authority.rotate(h.database.ui_publication_url)
    assert (await publish(h, row)).active_revision_id is not None


@pytest.mark.parametrize("cancel_cleanup", [False, True])
async def test_private_pool_cancelled_commit_releases_lease_and_rolls_back(
    ui_harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    cancel_cleanup: bool,
) -> None:
    h = ui_harness
    row = await create(h)
    before = _state(h)
    entered = asyncio.Event()
    cleanup_entered, cleanup_release = asyncio.Event(), asyncio.Event()
    publication_sessions: list[AsyncSession] = []
    original = SQLAlchemyUnitOfWork.commit
    original_rollback = AsyncSession.rollback

    async def paused(unit: SQLAlchemyUnitOfWork) -> None:
        assert unit.session is not None
        publication_sessions.append(unit.session)
        entered.set()
        await asyncio.Event().wait()

    async def rollback(session: AsyncSession) -> None:
        if cancel_cleanup and session in publication_sessions:
            cleanup_entered.set()
            await cleanup_release.wait()
        await original_rollback(session)

    monkeypatch.setattr(SQLAlchemyUnitOfWork, "commit", paused)
    monkeypatch.setattr(AsyncSession, "rollback", rollback)
    task = asyncio.create_task(publish(h, row))
    try:
        await asyncio.wait_for(entered.wait(), 10)
        task.cancel()
        if cancel_cleanup:
            await asyncio.wait_for(cleanup_entered.wait(), 5)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done(), "Repeated cancellation must not abandon transaction cleanup"
            cleanup_release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
    finally:
        cleanup_release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert _state(h) == before
    assert h.app.runtime is not None
    executor = h.app.runtime.messages._publication
    assert executor is not None
    assert not any(executor.authority._leases.values())
    monkeypatch.setattr(SQLAlchemyUnitOfWork, "commit", original)
    assert (await asyncio.wait_for(publish(h, row), 10)).active_revision_id is not None


@pytest.mark.parametrize(
    "stage",
    [
        "before-expected",
        "during-members",
        "during-actual",
        "before-seal",
        "after-seal",
        "before-pointer",
        "after-pointer-and-counters",
        "audit",
        "outbox",
        "before-commit",
    ],
)
async def test_private_publication_failure_rolls_back_all_authoritative_effects(
    ui_harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    h = ui_harness
    row = await create(h)
    before = _state(h)
    original_execute = SQLAlchemyTransactionalPersistence.execute
    original_outbox = SQLAlchemyUnitOfWork.add_outbox
    original_commit = SQLAlchemyUnitOfWork.commit
    counts: dict[str, int] = {}
    reached = False

    def fail() -> None:
        nonlocal reached
        reached = True
        raise RuntimeError("injected ADR-024 failure at " + stage)

    async def execute(
        persistence: SQLAlchemyTransactionalPersistence,
        statement: Executable,
        parameters: Mapping[str, Any] | None = None,
    ) -> Result[Any]:
        table = getattr(getattr(statement, "table", None), "name", "")
        write = bool(
            getattr(statement, "is_insert", False) or getattr(statement, "is_update", False)
        )
        if write:
            counts[table] = counts.get(table, 0) + 1
            if (
                (stage == "before-expected" and table == "ui_expected_provenance")
                or (
                    stage == "during-members"
                    and table == "ui_expected_members"
                    and counts[table] == 2
                )
                or (
                    stage == "during-actual"
                    and table == "ui_revision_module_bindings"
                    and counts[table] == 2
                )
                or (stage == "before-seal" and table == "ui_revision_binding_seals")
                or (stage == "before-pointer" and table == "ui_overlays")
                or (stage == "audit" and table == "audit_logs")
            ):
                fail()
        result = await original_execute(persistence, statement, parameters)
        if write and (
            (stage == "after-seal" and table == "ui_revision_binding_seals")
            or (stage == "after-pointer-and-counters" and table == "ui_overlays")
        ):
            fail()
        return result

    def outbox(unit: SQLAlchemyUnitOfWork, message: Any) -> None:
        original_outbox(unit, message)
        if stage == "outbox":
            fail()

    async def commit(unit: SQLAlchemyUnitOfWork) -> None:
        if stage == "before-commit":
            fail()
        await original_commit(unit)

    monkeypatch.setattr(SQLAlchemyTransactionalPersistence, "execute", execute)
    monkeypatch.setattr(SQLAlchemyUnitOfWork, "add_outbox", outbox)
    monkeypatch.setattr(SQLAlchemyUnitOfWork, "commit", commit)
    with pytest.raises(RuntimeError, match="injected ADR-024 failure"):
        await publish(h, row)
    assert reached, "Failure injection must reach the intended stage"
    assert _state(h) == before
