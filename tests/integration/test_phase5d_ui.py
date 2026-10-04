"Real PostgreSQL publication, scope/RLS, transactional evidence and resolver races."

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from typing import cast
from uuid import UUID, uuid4

import psycopg
import pytest
import pytest_asyncio
from businessos_identity.principal_binding import clear_authenticated_principal
from businessos_metadata.module import (
    CreateUIOverlay,
    EditUIOverlay,
    MetadataModule,
    PublishUIOverlay,
    ReactivateUIOverlay,
    ReadUIOverlay,
    ResolvePublishedUI,
    RetireUIOverlay,
)
from businessos_metadata.ui_contracts import (
    UIOverlayDocument,
    UIOverlayRecord,
    UIOverlayScope,
    UIResolution,
)
from businessos_party.ui_declarations import ui_id

from businessos.application import BusinessOSApplication
from businessos.sdk import (
    BusinessOSError,
    Command,
    HandlingContext,
    Query,
    RequestContext,
    TenantContext,
)
from tests.conftest import PostgreSQLTestDatabase
from tests.integration.test_phase5a_metadata import (
    _app,
    _bind,
    _command,
    _context,
    _Policy,
    _query,
    _url,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.asyncio]
VIEW = ui_id("detail.v1")


@dataclass
class Harness:
    app: BusinessOSApplication
    database: PostgreSQLTestDatabase
    context: RequestContext
    policy: _Policy

    async def command(
        self, value: Command, context: RequestContext | None = None
    ) -> UIOverlayRecord:
        context = context or self.context
        _bind(context)
        return cast(UIOverlayRecord, await _command(self.app, value, context))

    async def resolve(
        self, context: RequestContext | None = None, locale: str = "en"
    ) -> UIResolution:
        context = context or self.context
        _bind(context)
        return cast(
            UIResolution,
            await _query(self.app, ResolvePublishedUI(view_id=VIEW, locale=locale), context),
        )

    async def query(self, value: Query, context: RequestContext | None = None) -> object:
        context = context or self.context
        _bind(context)
        return await _query(self.app, value, context)


@pytest_asyncio.fixture
async def ui_harness(postgres_database: PostgreSQLTestDatabase) -> AsyncIterator[Harness]:
    policy = _Policy()
    app = _app(postgres_database, policy)
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    await app.startup()
    context = _context(uuid4())
    assert context.tenant is not None
    context = replace(
        context,
        tenant=replace(context.tenant, active_company_id=uuid4(), operating_site_id=uuid4()),
    )
    try:
        yield Harness(app, postgres_database, context, policy)
    finally:
        clear_authenticated_principal()
        await app.shutdown()


def document(order: int, *, label: str | None = None) -> UIOverlayDocument:
    patch: dict[str, object] = {"target_id": str(VIEW), "order": order}
    if label:
        patch["label_key"] = label
    return UIOverlayDocument.model_validate({"patches": [patch]})


async def create(
    h: Harness,
    kind: UIOverlayScope = UIOverlayScope.TENANT,
    order: int = 10,
    context: RequestContext | None = None,
) -> UIOverlayRecord:
    return await h.command(
        CreateUIOverlay(view_id=VIEW, scope_kind=kind, document=document(order)), context
    )


async def publish(
    h: Harness, row: UIOverlayRecord, context: RequestContext | None = None
) -> UIOverlayRecord:
    return await h.command(
        PublishUIOverlay(
            overlay_id=row.overlay_id,
            expected_draft_generation=row.draft_generation,
            expected_active_generation=row.active_generation,
        ),
        context,
    )


async def test_published_only_overlay_precedence_localization_draft_and_immutable_rollback(
    ui_harness: Harness,
) -> None:
    h = ui_harness
    base = await h.resolve()
    assert base.resolved is not None
    assert base.resolved.view.presentation.order == 0
    rows: list[UIOverlayRecord] = []
    for kind, order in zip(UIOverlayScope, (10, 20, 30, 40), strict=True):
        row = await create(h, kind, order)
        unpublished = await h.resolve()
        assert unpublished.resolved is not None
        assert unpublished.resolved.view.presentation.order == len(rows) * 10
        row = await publish(h, row)
        resolved = await h.resolve(locale="ar")
        assert resolved.resolved is not None
        assert resolved.resolved.view.presentation.order == order
        assert resolved.resolved.labels[0].text == "جهة"
        assert [p.scope_kind for p in resolved.resolved.provenance.overlays] == list(
            UIOverlayScope
        )[: len(rows) + 1]
        rows.append(row)
    user = rows[-1]
    old_revision = user.active_revision_id
    assert old_revision is not None
    edited = await h.command(
        EditUIOverlay(
            overlay_id=user.overlay_id,
            expected_draft_generation=1,
            expected_active_generation=1,
            document=document(99),
        )
    )
    resolved = await h.resolve()
    assert resolved.resolved is not None and resolved.resolved.view.presentation.order == 40
    user = await publish(h, edited)
    with psycopg.connect(_url(h.database.migration_url)) as connection:
        before = connection.execute(
            "SELECT to_jsonb(r) FROM platform_metadata.ui_overlay_revisions r ORDER BY id"
        ).fetchall()
    user = await h.command(
        ReactivateUIOverlay(
            overlay_id=user.overlay_id,
            expected_draft_generation=user.draft_generation,
            expected_active_generation=user.active_generation,
            revision_id=old_revision,
        )
    )
    resolved = await h.resolve()
    assert resolved.resolved is not None and resolved.resolved.view.presentation.order == 40
    with psycopg.connect(_url(h.database.migration_url)) as connection:
        assert (
            connection.execute(
                "SELECT to_jsonb(r) FROM platform_metadata.ui_overlay_revisions r ORDER BY id"
            ).fetchall()
            == before
        )
        assert connection.execute(
            "SELECT count(*) FROM platform_audit.audit_logs WHERE action LIKE "
            "'metadata.ui-overlay.%'"
        ).fetchone() == (11,)
        assert connection.execute(
            "SELECT count(*) FROM eventing.outbox_messages WHERE "
            "event_type='metadata.ui-overlay.changed.v1'"
        ).fetchone() == (11,)
    await h.command(
        RetireUIOverlay(
            overlay_id=user.overlay_id,
            expected_draft_generation=user.draft_generation,
            expected_active_generation=user.active_generation,
        )
    )
    resolved = await h.resolve()
    assert resolved.resolved is not None and resolved.resolved.view.presentation.order == 30


async def test_scope_identity_and_tenant_isolation_on_public_commands_and_queries(
    ui_harness: Harness,
) -> None:
    h = ui_harness
    for kind in UIOverlayScope:
        row = await publish(h, await create(h, kind))
        assert h.context.tenant is not None
        if kind is UIOverlayScope.TENANT:
            foreign = _context(uuid4())
        elif kind is UIOverlayScope.COMPANY:
            foreign = replace(
                h.context, tenant=replace(h.context.tenant, active_company_id=uuid4())
            )
        elif kind is UIOverlayScope.SITE:
            foreign = replace(
                h.context, tenant=replace(h.context.tenant, operating_site_id=uuid4())
            )
        else:
            foreign = replace(h.context, tenant=replace(h.context.tenant, principal_id=uuid4()))
        with pytest.raises(BusinessOSError, match="Eligible overlay unavailable"):
            await h.query(ReadUIOverlay(overlay_id=row.overlay_id), foreign)
        with pytest.raises(BusinessOSError, match="Eligible overlay unavailable"):
            await publish(h, row, foreign)
        resolved = await h.resolve(foreign)
        assert resolved.resolved is not None
        assert row.overlay_id not in {x.overlay_id for x in resolved.resolved.provenance.overlays}
    assert h.context.tenant is not None
    no_scope = replace(
        h.context, tenant=replace(h.context.tenant, active_company_id=None, operating_site_id=None)
    )
    for kind in (UIOverlayScope.COMPANY, UIOverlayScope.SITE):
        with pytest.raises(BusinessOSError, match="Eligible backend scope required"):
            await create(h, kind, context=no_scope)


async def test_stale_generations_and_dependency_artifacts_refuse_publication_and_resolution(
    ui_harness: Harness,
) -> None:
    h = ui_harness
    row = await create(h)
    published = await publish(h, row)
    with pytest.raises(BusinessOSError, match="UI overlay rejected"):
        await publish(h, row)
    with psycopg.connect(_url(h.database.migration_url)) as connection:
        connection.execute(
            "UPDATE platform_metadata.module_fence SET artifact_identity='upgraded', "
            "generation=generation+1 WHERE module_id='foundation.party'"
        )
    resolution = await h.resolve()
    assert resolution.resolved is None
    assert resolution.diagnostics[0].code == "stale_overlay"
    with pytest.raises(BusinessOSError, match="UI overlay rejected"):
        await h.command(
            ReactivateUIOverlay(
                overlay_id=published.overlay_id,
                expected_draft_generation=published.draft_generation,
                expected_active_generation=published.active_generation,
                revision_id=cast(UUID, published.active_revision_id),
            )
        )
    edited = await h.command(
        EditUIOverlay(
            overlay_id=published.overlay_id,
            expected_draft_generation=published.draft_generation,
            expected_active_generation=published.active_generation,
            document=document(20),
        )
    )
    await publish(h, edited)
    assert (await h.resolve()).resolved is not None


async def test_rls_grants_cross_tenant_writes_and_retained_identity_history(
    ui_harness: Harness,
) -> None:
    h = ui_harness
    row = await publish(h, await create(h))
    assert h.context.tenant is not None
    with psycopg.connect(_url(h.database.metadata_url)) as connection:
        connection.execute("SELECT set_config('app.tenant_id',%s,true)", (str(uuid4()),))
        assert connection.execute("SELECT id FROM platform_metadata.ui_overlays").fetchall() == []
        assert (
            connection.execute("SELECT id FROM platform_metadata.ui_overlay_revisions").fetchall()
            == []
        )
        assert (
            connection.execute(
                "UPDATE platform_metadata.ui_overlays SET lifecycle='retired' WHERE id=%s",
                (row.overlay_id,),
            ).rowcount
            == 0
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                (
                    "INSERT INTO platform_metadata.ui_overlays "
                    "(id,tenant_id,view_id,scope_kind,scope_id,draft_document,draft_compatibi"
                    "lity_digest,created_by) VALUES (%s,%s,%s,'tenant',%s,'{}',%s,%s)"
                ),
                (
                    uuid4(),
                    h.context.tenant.tenant_id,
                    VIEW,
                    h.context.tenant.tenant_id,
                    "a" * 64,
                    h.context.tenant.principal_id,
                ),
            )
        connection.rollback()
        connection.execute(
            "SELECT set_config('app.tenant_id',%s,true)", (str(h.context.tenant.tenant_id),)
        )
        with pytest.raises(psycopg.errors.RaiseException, match="identity is immutable"):
            connection.execute(
                "UPDATE platform_metadata.ui_overlays SET scope_id=%s WHERE id=%s",
                (uuid4(), row.overlay_id),
            )
        connection.rollback()
    for url in (h.database.runtime_url, h.database.worker_url, h.database.operations_url):
        with psycopg.connect(_url(url)) as connection:
            for table in ("ui_overlays", "ui_overlay_revisions"):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    connection.execute(f"SELECT * FROM platform_metadata.{table}")
                connection.rollback()
    with psycopg.connect(_url(h.database.migration_url)) as connection:
        with pytest.raises(psycopg.errors.RaiseException, match="revision is immutable"):
            connection.execute("UPDATE platform_metadata.ui_overlay_revisions SET document='{}'")
        connection.rollback()
        assert connection.execute(
            "SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE "
            "oid='platform_metadata.ui_overlays'::regclass"
        ).fetchone() == (True, True)


class PausingPolicy(_Policy):
    def __init__(self) -> None:
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.owner_calls = 0
        self.pause = False
        self.revoke = False
        self.logout = False

    async def is_allowed(self, principal_id: UUID, tenant: TenantContext, permission: str) -> bool:
        if self.pause and permission == "foundation.party.read":
            self.owner_calls += 1
            if self.owner_calls == 2:
                self.entered.set()
                await self.release.wait()
                if self.logout:
                    clear_authenticated_principal()
                if self.revoke:
                    return False
        return self.allowed


async def paused_harness(database: PostgreSQLTestDatabase) -> Harness:
    policy = PausingPolicy()
    app = _app(database, policy)
    app.runtime.migrations.upgrade(database.migration_url)
    await app.startup()
    return Harness(app, database, _context(uuid4()), policy)


async def test_revocation_and_logout_reject_inflight_schema_and_never_reuse_cached_result(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    h = await paused_harness(postgres_database)
    policy = cast(PausingPolicy, h.policy)
    try:
        assert (await h.resolve()).resolved is not None
        for logout in (False, True):
            policy.owner_calls = 0
            policy.pause = True
            policy.revoke = not logout
            policy.logout = logout
            policy.entered.clear()
            policy.release.clear()
            task = asyncio.create_task(h.resolve())
            await asyncio.wait_for(policy.entered.wait(), timeout=5)
            policy.release.set()
            with pytest.raises(BusinessOSError):
                await task
            policy.pause = False
        policy.allowed = False
        with pytest.raises(BusinessOSError):
            await h.resolve()
        policy.allowed = True
        assert (await h.resolve()).resolved is not None
    finally:
        await h.app.shutdown()


async def _wait_for_advisory(database: PostgreSQLTestDatabase) -> None:
    async with asyncio.timeout(5):
        async with await psycopg.AsyncConnection.connect(
            _url(database.administrator_url), autocommit=True
        ) as connection:
            while True:
                result = await connection.execute(
                    "SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND "
                    "wait_event='advisory'"
                )
                if await result.fetchone():
                    return
                await asyncio.sleep(0)


async def test_resolve_publish_and_rollback_are_serialized_and_cancellation_cleans_locks(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    h = await paused_harness(postgres_database)
    policy = cast(PausingPolicy, h.policy)
    try:
        row = await publish(h, await create(h))
        previous = cast(UUID, row.active_revision_id)
        row = await h.command(
            EditUIOverlay(
                overlay_id=row.overlay_id,
                expected_draft_generation=1,
                expected_active_generation=1,
                document=document(20),
            )
        )
        for rollback in (False, True):
            policy.owner_calls = 0
            policy.pause = True
            policy.entered.clear()
            policy.release.clear()
            resolving = asyncio.create_task(h.resolve())
            await asyncio.wait_for(policy.entered.wait(), timeout=5)
            command = (
                ReactivateUIOverlay(
                    overlay_id=row.overlay_id,
                    expected_draft_generation=row.draft_generation,
                    expected_active_generation=row.active_generation,
                    revision_id=previous,
                )
                if rollback
                else PublishUIOverlay(
                    overlay_id=row.overlay_id,
                    expected_draft_generation=row.draft_generation,
                    expected_active_generation=row.active_generation,
                )
            )
            publishing = asyncio.create_task(h.command(command))
            await _wait_for_advisory(postgres_database)
            assert not publishing.done()
            policy.release.set()
            result = await resolving
            assert result.resolved is not None
            assert result.resolved.provenance.overlays[0].revision_id == row.active_revision_id
            row = await publishing
            policy.pause = False
            after = await h.resolve()
            assert after.resolved is not None
            assert after.resolved.provenance.overlays[0].revision_id == row.active_revision_id
        policy.owner_calls = 0
        policy.pause = True
        policy.entered.clear()
        policy.release.clear()
        resolving = asyncio.create_task(h.resolve())
        await asyncio.wait_for(policy.entered.wait(), timeout=5)
        resolving.cancel()
        with pytest.raises(asyncio.CancelledError):
            await resolving
        policy.pause = False
        edited = await h.command(
            EditUIOverlay(
                overlay_id=row.overlay_id,
                expected_draft_generation=row.draft_generation,
                expected_active_generation=row.active_generation,
                document=document(30),
            )
        )
        await publish(h, edited)
        assert (await h.resolve()).resolved is not None
    finally:
        policy.release.set()
        await h.app.shutdown()


async def test_failed_evidence_rolls_back_revision_pointer_and_outbox(
    ui_harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = ui_harness
    row = await create(h)

    async def unavailable(
        self: MetadataModule, record: UIOverlayRecord, action: str, ctx: HandlingContext
    ) -> None:
        raise BusinessOSError("audit_unavailable", "Audit unavailable", status_code=503)

    with monkeypatch.context() as patch:
        patch.setattr(MetadataModule, "_ui_evidence", unavailable)
        with pytest.raises(BusinessOSError, match="Audit unavailable"):
            await publish(h, row)
    with psycopg.connect(_url(h.database.migration_url)) as connection:
        assert connection.execute(
            "SELECT active_revision_id,active_generation FROM platform_metadata.ui_overlays"
        ).fetchone() == (None, 0)
        assert connection.execute(
            "SELECT count(*) FROM platform_metadata.ui_overlay_revisions"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM eventing.outbox_messages WHERE "
            "event_type='metadata.ui-overlay.changed.v1'"
        ).fetchone() == (1,)
    await publish(h, row)
    assert (await h.resolve()).resolved is not None


async def test_module_drain_refuses_inflight_and_upgrade_waits_for_resolution(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    h = await paused_harness(postgres_database)
    policy = cast(PausingPolicy, h.policy)
    assert h.app.runtime is not None
    gate = h.app.runtime.contributions
    generation = gate.active_generation("foundation.party")
    try:
        row = await publish(h, await create(h))
        policy.pause = True
        policy.owner_calls = 0
        resolving = asyncio.create_task(h.resolve())
        await asyncio.wait_for(policy.entered.wait(), timeout=5)
        draining = asyncio.create_task(gate.close_and_drain(generation, timeout_seconds=5))
        await asyncio.sleep(0)
        assert not gate.is_active(generation)
        policy.release.set()
        result = await resolving
        assert result.resolved is None and result.diagnostics[0].code == "incompatible"
        await draining
        gate.publish(generation)
        policy.owner_calls = 0
        policy.entered.clear()
        policy.release.clear()
        resolving = asyncio.create_task(h.resolve())
        await asyncio.wait_for(policy.entered.wait(), timeout=5)

        async def upgrade() -> None:
            async with await psycopg.AsyncConnection.connect(
                _url(postgres_database.migration_url)
            ) as connection:
                await connection.execute("SET LOCAL lock_timeout='5s'")
                await connection.execute(
                    "UPDATE platform_metadata.module_fence SET generation=generation+1, "
                    "artifact_identity='upgrade-race' WHERE module_id='foundation.party'"
                )

        upgrading = asyncio.create_task(upgrade())
        async with asyncio.timeout(5):
            async with await psycopg.AsyncConnection.connect(
                _url(postgres_database.administrator_url), autocommit=True
            ) as connection:
                while True:
                    cursor = await connection.execute(
                        "SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND "
                        "wait_event IN ('transactionid','tuple')"
                    )
                    if await cursor.fetchone():
                        break
                    await asyncio.sleep(0)
        assert not upgrading.done()
        policy.release.set()
        result = await resolving
        assert result.resolved is not None
        assert result.resolved.provenance.overlays[0].revision_id == row.active_revision_id
        await upgrading
        policy.pause = False
        result = await h.resolve()
        assert result.resolved is None and result.diagnostics[0].code == "stale_overlay"
    finally:
        policy.release.set()
        gate.publish(generation)
        await h.app.shutdown()


async def test_scope_transition_unknown_and_errored_policy_refuse(
    ui_harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import businessos_metadata.ui_runtime as runtime

    h = ui_harness
    with pytest.raises(BusinessOSError):
        await _query(h.app, ResolvePublishedUI(view_id=VIEW, locale="en"), _context())
    original = runtime._policy
    calls = 0

    async def switching(ctx: HandlingContext, permissions: tuple[str, ...]) -> None:
        nonlocal calls
        await original(ctx, permissions)
        calls += 1
        if calls == 3:
            assert ctx.request.tenant is not None
            ctx.request = replace(
                ctx.request, tenant=replace(ctx.request.tenant, active_company_id=uuid4())
            )

    with monkeypatch.context() as patch:
        patch.setattr(runtime, "_policy", switching)
        result = await h.resolve()
        assert result.resolved is None and result.diagnostics[0].code == "stale_context"

    async def unknown(principal_id: UUID, tenant: TenantContext, permission: str) -> bool:
        return cast(bool, None)

    async def failed(principal_id: UUID, tenant: TenantContext, permission: str) -> bool:
        raise BusinessOSError("policy_unavailable", "Policy unavailable", status_code=503)

    for evaluator in (unknown, failed):
        with monkeypatch.context() as patch:
            patch.setattr(h.policy, "is_allowed", evaluator)
            with pytest.raises(BusinessOSError):
                await h.resolve()
    assert (await h.resolve()).resolved is not None


async def test_revision_and_tenant_quotas_retain_history(ui_harness: Harness) -> None:
    h = ui_harness
    row = await publish(h, await create(h))
    assert h.context.tenant is not None
    with psycopg.connect(_url(h.database.migration_url)) as connection:
        for sequence in range(2, 65):
            connection.execute(
                (
                    "INSERT INTO platform_metadata.ui_overlay_revisions "
                    "(id,tenant_id,overlay_id,sequence,document,digest,compatibility_digest,p"
                    "ublished_by) SELECT "
                    "%s,tenant_id,overlay_id,%s,document,digest,compatibility_digest,publishe"
                    "d_by FROM platform_metadata.ui_overlay_revisions WHERE id=%s"
                ),
                (uuid4(), sequence, row.active_revision_id),
            )
        for _ in range(1023):
            connection.execute(
                (
                    "INSERT INTO platform_metadata.ui_overlays "
                    "(id,tenant_id,view_id,scope_kind,scope_id,draft_document,draft_compatibi"
                    "lity_digest,created_by) SELECT "
                    "%s,tenant_id,%s,scope_kind,scope_id,draft_document,draft_compatibility_d"
                    "igest,created_by FROM platform_metadata.ui_overlays WHERE id=%s"
                ),
                (uuid4(), uuid4(), row.overlay_id),
            )
    with pytest.raises(BusinessOSError) as failure:
        await publish(h, row)
    assert failure.value.code == "ui_limit_exceeded"
    with pytest.raises(BusinessOSError) as failure:
        await create(h, UIOverlayScope.COMPANY)
    assert failure.value.code == "ui_limit_exceeded"
    with psycopg.connect(_url(h.database.migration_url)) as connection:
        assert connection.execute(
            "SELECT count(*) FROM platform_metadata.ui_overlay_revisions"
        ).fetchone() == (64,)
        assert connection.execute(
            "SELECT count(*) FROM platform_metadata.ui_overlays"
        ).fetchone() == (1024,)


async def test_identical_edit_revalidates_security_before_success(
    ui_harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = ui_harness
    row = await create(h)
    with psycopg.connect(_url(h.database.migration_url)) as connection:
        before = connection.execute(
            "SELECT to_jsonb(o) FROM platform_metadata.ui_overlays o"
        ).fetchall()
        evidence = connection.execute("SELECT count(*) FROM platform_audit.audit_logs").fetchone()
    for revoked_permission in ("foundation.party.read", "foundation.metadata.ui.draft"):
        revoked = False

        async def revoke_after_admission(
            principal_id: UUID,
            tenant: TenantContext,
            permission: str,
            *,
            target_permission: str = revoked_permission,
        ) -> bool:
            nonlocal revoked
            if revoked and permission == target_permission:
                return False
            if permission == "foundation.party.read":
                revoked = True
            return True

        with monkeypatch.context() as patch:
            patch.setattr(h.policy, "is_allowed", revoke_after_admission)
            with pytest.raises(BusinessOSError):
                await h.command(
                    EditUIOverlay(
                        overlay_id=row.overlay_id,
                        expected_draft_generation=row.draft_generation,
                        expected_active_generation=row.active_generation,
                        document=row.draft_document,
                    )
                )
    with psycopg.connect(_url(h.database.migration_url)) as connection:
        assert (
            connection.execute("SELECT to_jsonb(o) FROM platform_metadata.ui_overlays o").fetchall()
            == before
        )
        assert (
            connection.execute("SELECT count(*) FROM platform_audit.audit_logs").fetchone()
            == evidence
        )


async def test_resolver_rechecks_its_own_permission_after_owner_admission(
    ui_harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = ui_harness
    revoked = False

    async def revoke_read_after_admission(
        principal_id: UUID, tenant: TenantContext, permission: str
    ) -> bool:
        nonlocal revoked
        if revoked and permission == "foundation.metadata.ui.read":
            return False
        if permission == "foundation.party.read":
            revoked = True
        return True

    with monkeypatch.context() as patch:
        patch.setattr(h.policy, "is_allowed", revoke_read_after_admission)
        with pytest.raises(BusinessOSError):
            await h.resolve()
    assert (await h.resolve()).resolved is not None
