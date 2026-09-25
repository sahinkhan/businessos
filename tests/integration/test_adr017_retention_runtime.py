"""ADR-017 proof owner exercises the public operation and Audit boundaries."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from businessos_data_governance.migrations.versions.gov_0004_retention_purge_v2 import preflight
from businessos_data_governance.models import ExpiryAction
from businessos_data_governance.retention_v2 import (
    ExecuteDestructiveLifecycleV2,
    HoldScope,
    PlaceRetentionHoldV2,
    ReleaseRetentionHoldV2,
    ReplaceRetentionPolicyV2,
    RetentionSubjectKey,
    SetRetentionPolicyV2,
)
from businessos_identity import PrincipalIdentity
from businessos_identity.principal_binding import (
    bind_authenticated_principal,
    clear_authenticated_principal,
)
from sqlalchemy import create_engine, text

from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.context import RequestContext, TenantContext
from businessos.errors import BusinessOSError
from businessos.messages import Command, HandlerTransaction, HandlingContext
from businessos.modules import discover_modules
from businessos.modules.artifact import ApprovedModuleArtifact
from businessos.modules.installation_inventory import approved_artifacts_from_operator_inventory
from businessos.modules.manifest import ModuleManifest, ResourceOwnership
from businessos.modules.sdk import ModuleRegistration
from businessos.resources import (
    ResourceLocator,
    ResourceOwnerFacts,
    lock_resource_subject_facts,
)
from businessos.security import Authorizer
from tests.conftest import PostgreSQLTestDatabase

INVENTORY = json.loads(
    Path("tests/fixtures/approved-module-inventory.ci.json").read_text(encoding="utf-8")
)


class _Permit:
    async def is_allowed(self, principal_id: UUID, tenant: TenantContext, permission: str) -> bool:
        return True


class _ChangeCategory(Command):
    tenant_id: UUID
    record_id: UUID
    category: str


class _ChangeAnchor(Command):
    tenant_id: UUID
    record_id: UUID
    anchor_at: datetime


class _Owner:
    supported_actions = frozenset({"archive", "anonymize", "purge"})
    declared_entity_types = frozenset({"proof"})

    def __init__(self, *, version: str = "1.0.0") -> None:
        self.pause_validate: tuple[asyncio.Event, asyncio.Event] | None = None
        self.pause_facts: tuple[asyncio.Event, asyncio.Event] | None = None
        self.pause_change: tuple[asyncio.Event, asyncio.Event] | None = None
        self.fail_after_apply = False
        self.manifest = ModuleManifest(
            module_id="example.retention_owner",
            name="Retention proof owner",
            publisher="test",
            version=version,
            platform=">=0.1,<1",
            sdk=">=0.1,<1",
            python=">=3.13",
            entry_point="tests.integration.test_adr017_retention_runtime:_Owner",
            resource_ownership=(
                ResourceOwnership(
                    resource_namespace="example.retention_owner.record",
                    owner_module_id="example.retention_owner",
                    contract_version="1",
                ),
            ),
        )

    async def register(self, registration: ModuleRegistration) -> None:
        registration.resource_owner_facts("example.retention_owner.record", "1", self)
        registration.resource_owner_operation("example.retention_owner.record", "1", self)
        registration.command(_ChangeCategory, self._change_category)
        registration.command(_ChangeAnchor, self._change_anchor)

    async def _change_category(self, cmd: _ChangeCategory, ctx: HandlingContext) -> None:
        locator = ResourceLocator(
            "example.retention_owner.record", "1", cmd.record_id, cmd.tenant_id
        )
        await lock_resource_subject_facts(
            locator, "example.retention_owner", "proof", ctx.request, ctx.unit_of_work
        )
        row = await self._row(locator, ctx.unit_of_work, lock=True)
        if self.pause_change is not None:
            entered, release = self.pause_change
            entered.set()
            await release.wait()
        if row.lifecycle != "current":
            raise BusinessOSError("owner_state_changed", "Owner state changed", status_code=409)
        await ctx.unit_of_work.persistence.execute(
            text(
                "UPDATE public.adr017_owner SET category=:category "
                "WHERE tenant_id=:tenant AND record_id=:record"
            ),
            {"category": cmd.category, "tenant": cmd.tenant_id, "record": cmd.record_id},
        )

    async def _change_anchor(self, cmd: _ChangeAnchor, ctx: HandlingContext) -> None:
        locator = ResourceLocator(
            "example.retention_owner.record", "1", cmd.record_id, cmd.tenant_id
        )
        await lock_resource_subject_facts(
            locator, "example.retention_owner", "proof", ctx.request, ctx.unit_of_work
        )
        row = await self._row(locator, ctx.unit_of_work, lock=True)
        if self.pause_change is not None:
            entered, release = self.pause_change
            entered.set()
            await release.wait()
        if row.lifecycle != "current":
            raise BusinessOSError("owner_state_changed", "Owner state changed", status_code=409)
        await ctx.unit_of_work.persistence.execute(
            text(
                "UPDATE public.adr017_owner SET anchor_at=:anchor "
                "WHERE tenant_id=:tenant AND record_id=:record"
            ),
            {"anchor": cmd.anchor_at, "tenant": cmd.tenant_id, "record": cmd.record_id},
        )

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def _row(
        self, locator: ResourceLocator, transaction: HandlerTransaction, *, lock: bool
    ) -> Any:
        sql = (
            "SELECT tenant_id, record_id, category, anchor_at, lifecycle "
            "FROM public.adr017_owner WHERE tenant_id=:tenant AND record_id=:record"
        )
        if lock:
            sql += " FOR UPDATE"
        result = await transaction.persistence.execute(
            text(sql), {"tenant": locator.tenant_id, "record": locator.record_id}
        )
        row = result.first()
        if row is None:
            raise BusinessOSError("owner_missing", "Owner record not found", status_code=404)
        return row

    def _facts(self, locator: ResourceLocator, row: Any) -> ResourceOwnerFacts:
        return ResourceOwnerFacts(
            tenant_id=row.tenant_id,
            namespace=locator.namespace,
            record_id=row.record_id,
            owner_module_id="example.retention_owner",
            contract_version="1",
            lifecycle=row.lifecycle,
            facts={
                "entity_type": "proof",
                "retention_category": row.category,
                "retention_anchor_at": row.anchor_at,
                "supported_actions": (
                    frozenset({"archive"}) if row.category == "limited" else self.supported_actions
                ),
            },
        )

    async def read_facts(
        self, locator: ResourceLocator, request: RequestContext, transaction: HandlerTransaction
    ) -> ResourceOwnerFacts:
        return self._facts(locator, await self._row(locator, transaction, lock=False))

    async def read_locked_facts(
        self,
        locator: ResourceLocator,
        action: str,
        request: RequestContext,
        transaction: HandlerTransaction,
    ) -> ResourceOwnerFacts:
        row = await self._row(locator, transaction, lock=True)
        if self.pause_facts is not None:
            entered, release = self.pause_facts
            entered.set()
            await release.wait()
        return self._facts(locator, row)

    async def validate_operation(
        self,
        locator: ResourceLocator,
        action: str,
        request: RequestContext,
        transaction: HandlerTransaction,
    ) -> ResourceOwnerFacts:
        row = await self._row(locator, transaction, lock=True)
        if self.pause_validate is not None:
            entered, release = self.pause_validate
            entered.set()
            await release.wait()
        return self._facts(locator, row)

    async def apply_operation(
        self,
        locator: ResourceLocator,
        action: str,
        request: RequestContext,
        transaction: HandlerTransaction,
    ) -> None:
        result = await transaction.persistence.execute(
            text(
                "UPDATE public.adr017_owner SET lifecycle=:action "
                "WHERE tenant_id=:tenant AND record_id=:record AND lifecycle='current' "
                "RETURNING record_id"
            ),
            {"action": action, "tenant": locator.tenant_id, "record": locator.record_id},
        )
        if result.first() is None:
            raise BusinessOSError("owner_state_changed", "Owner state changed", status_code=409)
        if self.fail_after_apply:
            raise RuntimeError("proof owner failure after mutation")


def _context(tenant_id: UUID | None = None) -> RequestContext:
    context = RequestContext(
        tenant=TenantContext(
            installation_id=uuid4(),
            tenant_id=tenant_id or uuid4(),
            principal_id=uuid4(),
            authentication_strength="mfa",
        )
    )
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
    return context


async def _command(app: Any, command: Any, context: RequestContext) -> object:
    assert app.runtime is not None
    async with app.container.request_scope() as dependencies:
        return await app.runtime.messages.command(command, context, dependencies)


def _url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _seed_owner(
    database: PostgreSQLTestDatabase,
    key: RetentionSubjectKey,
    anchor: datetime,
    *,
    category: str = "customer",
) -> None:
    with psycopg.connect(_url(database.administrator_url)) as connection:
        connection.execute(
            "INSERT INTO public.adr017_owner VALUES (%s, %s, %s, %s, %s)",
            (key.tenant_id, key.record_id, category, anchor, "current"),
        )


@pytest.mark.integration
@pytest.mark.postgres
def test_forward_preflight_blocks_unmapped_policies_and_preserves_legacy_holds(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    modules = tuple(
        module
        for module in discover_modules()
        if module.manifest.module_id.startswith("foundation.")
    )
    app = create_application(
        Settings(environment="test", database_url=postgres_database.runtime_url),
        modules=modules,
        approved_module_artifacts=approved_artifacts_from_operator_inventory(
            modules, inventory=INVENTORY
        ),
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url, "gov_0003")
    tenant_id, policy_id, hold_id, ambiguous_hold_id = uuid4(), uuid4(), uuid4(), uuid4()
    with psycopg.connect(_url(postgres_database.administrator_url)) as connection:
        connection.execute(
            "INSERT INTO platform_gov.retention_policies "
            "(id, tenant_id, code, name, entity_type, classification_ref, "
            "retention_period_days, action_on_expiry) "
            "VALUES (%s, %s, 'legacy', 'legacy', 'proof', 'canonical:internal', 30, 'purge')",
            (policy_id, tenant_id),
        )
        connection.execute(
            "INSERT INTO platform_gov.legal_holds "
            "(id, tenant_id, code, name, reason, entity_type, placed_by) "
            "VALUES (%s, %s, 'hold', 'hold', 'litigation', 'proof', 'legal')",
            (hold_id, tenant_id),
        )
        connection.execute(
            "INSERT INTO platform_gov.legal_holds "
            "(id, tenant_id, code, name, reason, entity_type, entity_id, placed_by) "
            "VALUES (%s, %s, 'ambiguous', 'ambiguous', 'litigation', 'proof', 'legacy-1', 'legal')",
            (ambiguous_hold_id, tenant_id),
        )
    engine = create_engine(postgres_database.migration_url)
    try:
        with engine.connect() as connection:
            with pytest.raises(RuntimeError, match=str(policy_id)):
                preflight(connection)
    finally:
        engine.dispose()
    with psycopg.connect(_url(postgres_database.administrator_url)) as connection:
        connection.execute("DELETE FROM platform_gov.retention_policies WHERE id=%s", (policy_id,))
    engine = create_engine(postgres_database.migration_url)
    try:
        with engine.connect() as connection:
            with pytest.raises(RuntimeError, match=str(ambiguous_hold_id)):
                preflight(connection)
    finally:
        engine.dispose()
    with psycopg.connect(_url(postgres_database.administrator_url)) as connection:
        connection.execute("DELETE FROM platform_gov.legal_holds WHERE id=%s", (ambiguous_hold_id,))
    app.runtime.migrations.upgrade(postgres_database.migration_url, "gov_0004")
    with psycopg.connect(_url(postgres_database.administrator_url)) as connection:
        row = connection.execute(
            "SELECT hold_scope, entity_id, is_active FROM platform_gov.legal_holds WHERE id=%s",
            (hold_id,),
        ).fetchone()
    assert row == ("ALL", None, True)


@pytest.mark.integration
@pytest.mark.postgres
def test_governance_advisory_lock_timeout_and_holder_rollback(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    # The same canonical entity gate must fail within the configured database
    # timeout, and rollback of the holder must make a fresh attempt possible.
    key = "\x1f".join(("adr017", "entity", str(uuid4()), "example.retention_owner", "proof"))
    lock_sql = "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))"
    with psycopg.connect(_url(postgres_database.runtime_url)) as holder:
        holder.execute(lock_sql, (key,))
        with psycopg.connect(_url(postgres_database.runtime_url)) as waiter:
            waiter.execute("SET LOCAL lock_timeout = '200ms'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                waiter.execute(lock_sql, (key,))
            waiter.rollback()
        holder.rollback()
        with psycopg.connect(_url(postgres_database.runtime_url)) as retry:
            retry.execute("SET LOCAL lock_timeout = '1s'")
            retry.execute(lock_sql, (key,))


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_destructive_lifecycle_uses_owner_facts_policy_holds_and_one_uow(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    owner = _Owner()
    modules = (
        *(
            module
            for module in discover_modules()
            if module.manifest.module_id.startswith("foundation.")
        ),
        owner,
    )
    approved = dict(approved_artifacts_from_operator_inventory(modules, inventory=INVENTORY))
    approved[owner.manifest.module_id] = ApprovedModuleArtifact(
        loaded_module=owner,
        module_id=owner.manifest.module_id,
        publisher=owner.manifest.publisher,
        package_identity="adr017-proof-owner",
        loaded_type=f"{type(owner).__module__}:{type(owner).__qualname__}",
        install_identity="adr017-proof-owner-install",
    )
    app = create_application(
        Settings(environment="test", database_url=postgres_database.runtime_url),
        modules=modules,
        authorizer=Authorizer(_Permit()),
        approved_module_artifacts=approved,
        resource_coordinator_ids=frozenset({"foundation.data_governance"}),
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    with psycopg.connect(_url(postgres_database.administrator_url)) as connection:
        connection.execute(
            "CREATE TABLE public.adr017_owner (tenant_id uuid NOT NULL, record_id uuid NOT NULL, "
            "category text NOT NULL, anchor_at timestamptz NOT NULL, lifecycle text NOT NULL, "
            "PRIMARY KEY (tenant_id, record_id))"
        )
        connection.execute("ALTER TABLE public.adr017_owner ENABLE ROW LEVEL SECURITY")
        connection.execute("ALTER TABLE public.adr017_owner FORCE ROW LEVEL SECURITY")
        connection.execute(
            "CREATE POLICY adr017_owner_tenant ON public.adr017_owner TO businessos_app "
            "USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)"
        )
        connection.execute("GRANT SELECT, UPDATE ON public.adr017_owner TO businessos_app")
    await app.startup()
    context = _context()
    assert context.tenant is not None
    key = RetentionSubjectKey(
        tenant_id=context.tenant.tenant_id,
        owner_module_id="example.retention_owner",
        resource_namespace="example.retention_owner.record",
        contract_version="1",
        entity_type="proof",
        record_id=uuid4(),
    )
    anchor = datetime.now(UTC) - timedelta(days=2)
    _seed_owner(postgres_database, key, anchor)
    try:
        policy = SetRetentionPolicyV2(
            tenant_id=key.tenant_id,
            owner_module_id=key.owner_module_id,
            resource_namespace=key.resource_namespace,
            contract_version="1",
            entity_type="proof",
            retention_category="customer",
            retention_period_days=1,
            action_on_expiry=ExpiryAction.PURGE,
            valid_from=datetime.now(UTC) - timedelta(days=1),
        )
        policy_id = await _command(app, policy, context)
        assert isinstance(policy_id, UUID)
        await _command(
            app,
            policy.model_copy(update={"retention_category": "other_category"}),
            context,
        )
        category_other = key.model_copy(update={"record_id": uuid4()})
        _seed_owner(postgres_database, category_other, anchor, category="other_category")
        all_hold_id = await _command(
            app,
            PlaceRetentionHoldV2(subject=key, scope=HoldScope.ALL, reason="entity-wide"),
            context,
        )
        with psycopg.connect(_url(postgres_database.administrator_url)) as connection:
            assert connection.execute(
                "SELECT hold_scope, record_id, retention_category "
                "FROM platform_gov.legal_holds_v2 WHERE id=%s",
                (all_hold_id,),
            ).fetchone() == ("ALL", None, None)
        with pytest.raises(BusinessOSError, match="Active legal hold"):
            await _command(
                app,
                ExecuteDestructiveLifecycleV2(subject=category_other, action=ExpiryAction.PURGE),
                context,
            )
        await _command(
            app,
            ReleaseRetentionHoldV2(tenant_id=key.tenant_id, hold_id=all_hold_id),
            context,
        )
        with pytest.raises(BusinessOSError, match="Owner did not declare"):
            await _command(
                app,
                policy.model_copy(update={"entity_type": "unclaimed"}),
                context,
            )
        with pytest.raises(BusinessOSError, match="Owner did not declare"):
            await _command(
                app,
                PlaceRetentionHoldV2(
                    subject=key.model_copy(update={"entity_type": "unclaimed"}),
                    scope=HoldScope.ALL,
                    reason="cannot falsely claim coverage",
                ),
                context,
            )
        other_tenant = uuid4()
        with psycopg.connect(_url(postgres_database.runtime_url)) as connection:
            connection.execute("SELECT set_config('app.tenant_id', %s, true)", (str(other_tenant),))
            assert connection.execute(
                "SELECT count(*) FROM platform_gov.retention_policies_v2 WHERE id=%s",
                (policy_id,),
            ).fetchone() == (0,)
            assert (
                connection.execute(
                    "UPDATE platform_gov.retention_policies_v2 SET is_active=false WHERE id=%s "
                    "RETURNING id",
                    (policy_id,),
                ).fetchone()
                is None
            )
        with pytest.raises(BusinessOSError, match="interval overlaps"):
            await _command(app, policy, context)
        wrong_tenant_context = _context()
        with pytest.raises(BusinessOSError, match="Tenant identity mismatch"):
            await _command(
                app,
                ExecuteDestructiveLifecycleV2(subject=key, action=ExpiryAction.PURGE),
                wrong_tenant_context,
            )
        bind_authenticated_principal(
            context,
            PrincipalIdentity(
                tenant_id=context.tenant.tenant_id,
                principal_id=context.tenant.principal_id,
                principal_type="user",
                authentication_strength="mfa",
            ),
        )
        with pytest.raises(BusinessOSError, match="Policy does not authorize"):
            await _command(
                app,
                ExecuteDestructiveLifecycleV2(
                    subject=key,
                    action=ExpiryAction.ARCHIVE,
                ),
                context,
            )
        hold_id = await _command(
            app,
            PlaceRetentionHoldV2(
                subject=key,
                scope=HoldScope.RECORD,
                reason="case hold",
            ),
            context,
        )
        assert isinstance(hold_id, UUID)
        with psycopg.connect(_url(postgres_database.runtime_url)) as connection:
            connection.execute(
                "SELECT set_config('app.tenant_id', %s, true)", (str(key.tenant_id),)
            )
            assert connection.execute(
                "SELECT hold_scope, record_id FROM platform_gov.legal_holds_v2 WHERE id=%s",
                (hold_id,),
            ).fetchone() == ("RECORD", key.record_id)
        with psycopg.connect(_url(postgres_database.runtime_url)) as connection:
            connection.execute("SELECT set_config('app.tenant_id', %s, true)", (str(other_tenant),))
            assert connection.execute(
                "SELECT count(*) FROM platform_gov.legal_holds_v2 WHERE id=%s", (hold_id,)
            ).fetchone() == (0,)
        with pytest.raises(BusinessOSError, match="Active legal hold"):
            await _command(
                app,
                ExecuteDestructiveLifecycleV2(
                    subject=key,
                    action=ExpiryAction.PURGE,
                ),
                context,
            )
        await _command(
            app,
            ReleaseRetentionHoldV2(
                tenant_id=key.tenant_id,
                hold_id=hold_id,
            ),
            context,
        )
        decision_id = await _command(
            app,
            ExecuteDestructiveLifecycleV2(
                subject=key,
                action=ExpiryAction.PURGE,
            ),
            context,
        )
        assert isinstance(decision_id, UUID)
        with pytest.raises(BusinessOSError, match="Owner operation requires current"):
            await _command(
                app,
                ExecuteDestructiveLifecycleV2(
                    subject=key,
                    action=ExpiryAction.PURGE,
                ),
                context,
            )
        with psycopg.connect(_url(postgres_database.administrator_url)) as connection:
            row = connection.execute(
                "SELECT lifecycle FROM public.adr017_owner WHERE record_id=%s", (key.record_id,)
            ).fetchone()
            decision = connection.execute(
                "SELECT external_cleanup_status FROM platform_gov.destructive_decisions_v2 "
                "WHERE id=%s",
                (decision_id,),
            ).fetchone()
            cleanup_event = connection.execute(
                "SELECT event_type FROM eventing.outbox_messages WHERE tenant_id=%s "
                "AND event_type='governance.destructive.cleanup_requested.v2' "
                "AND payload ->> 'decision_id'=%s",
                (key.tenant_id, str(decision_id)),
            ).fetchone()
            audit_evidence = connection.execute(
                "SELECT action, evidence_v3 -> 'details' ->> 'policy_id', "
                "evidence_v3 -> 'details' ->> 'decision_id' "
                "FROM platform_audit.audit_logs WHERE tenant_id=%s AND resource_id=%s "
                "AND action='governance.destructive.purge'",
                (key.tenant_id, str(key.record_id)),
            ).fetchone()
        assert row == ("purge",)
        assert decision == ("pending",)
        assert cleanup_event == ("governance.destructive.cleanup_requested.v2",)
        assert audit_evidence == ("governance.destructive.purge", str(policy_id), str(decision_id))

        # Hold-first: the hold commits while purge waits at the entity gate.
        hold_first = key.model_copy(update={"record_id": uuid4()})
        _seed_owner(postgres_database, hold_first, anchor)
        entered, release = asyncio.Event(), asyncio.Event()
        owner.pause_facts = (entered, release)
        placing = asyncio.create_task(
            _command(
                app,
                PlaceRetentionHoldV2(
                    subject=hold_first,
                    scope=HoldScope.RECORD,
                    reason="first",
                ),
                context,
            )
        )
        await asyncio.wait_for(entered.wait(), 10)
        purging = asyncio.create_task(
            _command(
                app,
                ExecuteDestructiveLifecycleV2(
                    subject=hold_first,
                    action=ExpiryAction.PURGE,
                ),
                context,
            )
        )
        release.set()
        assert isinstance(await asyncio.wait_for(placing, 10), UUID)
        with pytest.raises(BusinessOSError, match="Active legal hold"):
            await asyncio.wait_for(purging, 10)
        owner.pause_facts = None

        # Purge-first: a later record hold re-reads the changed owner state.
        purge_first = key.model_copy(update={"record_id": uuid4()})
        _seed_owner(postgres_database, purge_first, anchor)
        entered, release = asyncio.Event(), asyncio.Event()
        owner.pause_validate = (entered, release)
        purging = asyncio.create_task(
            _command(
                app,
                ExecuteDestructiveLifecycleV2(
                    subject=purge_first,
                    action=ExpiryAction.PURGE,
                ),
                context,
            )
        )
        await asyncio.wait_for(entered.wait(), 10)
        placing = asyncio.create_task(
            _command(
                app,
                PlaceRetentionHoldV2(
                    subject=purge_first,
                    scope=HoldScope.RECORD,
                    reason="too late",
                ),
                context,
            )
        )
        release.set()
        assert isinstance(await asyncio.wait_for(purging, 10), UUID)
        with pytest.raises(BusinessOSError, match="Locked owner facts"):
            await asyncio.wait_for(placing, 10)
        owner.pause_validate = None

        # Two purgers cannot apply the owner action twice.
        double = key.model_copy(update={"record_id": uuid4()})
        _seed_owner(postgres_database, double, anchor)
        entered, release = asyncio.Event(), asyncio.Event()
        owner.pause_validate = (entered, release)
        first = asyncio.create_task(
            _command(
                app,
                ExecuteDestructiveLifecycleV2(
                    subject=double,
                    action=ExpiryAction.PURGE,
                ),
                context,
            )
        )
        await asyncio.wait_for(entered.wait(), 10)
        second = asyncio.create_task(
            _command(
                app,
                ExecuteDestructiveLifecycleV2(
                    subject=double,
                    action=ExpiryAction.PURGE,
                ),
                context,
            )
        )
        release.set()
        assert isinstance(await asyncio.wait_for(first, 10), UUID)
        with pytest.raises(BusinessOSError, match="current resource state"):
            await asyncio.wait_for(second, 10)
        owner.pause_validate = None

        # Distinct subjects under the same entity gate both complete after the
        # first owner operation releases its transaction locks.
        subject_a = key.model_copy(update={"record_id": uuid4()})
        subject_b = key.model_copy(update={"record_id": uuid4()})
        _seed_owner(postgres_database, subject_a, anchor)
        _seed_owner(postgres_database, subject_b, anchor)
        entered, release = asyncio.Event(), asyncio.Event()
        owner.pause_validate = (entered, release)
        first_subject = asyncio.create_task(
            _command(
                app,
                ExecuteDestructiveLifecycleV2(subject=subject_a, action=ExpiryAction.PURGE),
                context,
            )
        )
        await asyncio.wait_for(entered.wait(), 10)
        second_subject = asyncio.create_task(
            _command(
                app,
                ExecuteDestructiveLifecycleV2(subject=subject_b, action=ExpiryAction.PURGE),
                context,
            )
        )
        release.set()
        assert isinstance(await asyncio.wait_for(first_subject, 10), UUID)
        assert isinstance(await asyncio.wait_for(second_subject, 10), UUID)
        owner.pause_validate = None

        releasing_key = key.model_copy(update={"record_id": uuid4()})
        _seed_owner(postgres_database, releasing_key, anchor)
        releasing_hold = await _command(
            app,
            PlaceRetentionHoldV2(
                subject=releasing_key,
                scope=HoldScope.RECORD,
                reason="release race",
            ),
            context,
        )
        assert isinstance(releasing_hold, UUID)
        release_task = asyncio.create_task(
            _command(
                app,
                ReleaseRetentionHoldV2(
                    tenant_id=key.tenant_id,
                    hold_id=releasing_hold,
                ),
                context,
            )
        )
        purge_task = asyncio.create_task(
            _command(
                app,
                ExecuteDestructiveLifecycleV2(
                    subject=releasing_key,
                    action=ExpiryAction.PURGE,
                ),
                context,
            )
        )
        released, purge_outcome = await asyncio.wait_for(
            asyncio.gather(release_task, purge_task, return_exceptions=True), 10
        )
        assert released is None
        assert isinstance(purge_outcome, UUID) or (
            isinstance(purge_outcome, BusinessOSError) and purge_outcome.code == "legal_hold_active"
        )

        # A failure after owner mutation rolls the owner row and decision back.
        rollback = key.model_copy(update={"record_id": uuid4()})
        _seed_owner(postgres_database, rollback, anchor)
        owner.fail_after_apply = True
        with pytest.raises(RuntimeError, match="proof owner failure"):
            await _command(
                app,
                ExecuteDestructiveLifecycleV2(
                    subject=rollback,
                    action=ExpiryAction.PURGE,
                ),
                context,
            )
        owner.fail_after_apply = False
        with psycopg.connect(_url(postgres_database.administrator_url)) as connection:
            row = connection.execute(
                "SELECT lifecycle FROM public.adr017_owner WHERE record_id=%s",
                (rollback.record_id,),
            ).fetchone()
            count = connection.execute(
                "SELECT count(*) FROM platform_gov.destructive_decisions_v2 WHERE record_id=%s",
                (rollback.record_id,),
            ).fetchone()
            audit_count = connection.execute(
                "SELECT count(*) FROM platform_audit.audit_logs WHERE resource_id=%s",
                (str(rollback.record_id),),
            ).fetchone()
        assert row == ("current",)
        assert count == (0,)
        assert audit_count == (0,)

        # Every policy/action pairing is evaluated without substitution.
        for policy_action in ExpiryAction:
            category = f"cat_{policy_action.value}"
            await _command(
                app,
                policy.model_copy(
                    update={
                        "retention_category": category,
                        "action_on_expiry": policy_action,
                    }
                ),
                context,
            )
            for requested_action in ExpiryAction:
                action_key = key.model_copy(update={"record_id": uuid4()})
                _seed_owner(postgres_database, action_key, anchor, category=category)
                command = ExecuteDestructiveLifecycleV2(
                    subject=action_key,
                    action=requested_action,
                )
                if requested_action is policy_action:
                    assert isinstance(await _command(app, command, context), UUID)
                else:
                    with pytest.raises(BusinessOSError, match="Policy does not authorize"):
                        await _command(app, command, context)
                    with psycopg.connect(_url(postgres_database.administrator_url)) as connection:
                        lifecycle = connection.execute(
                            "SELECT lifecycle FROM public.adr017_owner WHERE record_id=%s",
                            (action_key.record_id,),
                        ).fetchone()
                    assert lifecycle == ("current",)

        # Same UUID and entity type in another tenant ignores tenant A's hold.
        tenant_b = _context()
        assert tenant_b.tenant is not None
        other_key = hold_first.model_copy(update={"tenant_id": tenant_b.tenant.tenant_id})
        _seed_owner(postgres_database, other_key, anchor)
        await _command(
            app,
            policy.model_copy(update={"tenant_id": other_key.tenant_id}),
            tenant_b,
        )
        assert isinstance(
            await _command(
                app,
                ExecuteDestructiveLifecycleV2(subject=other_key, action=ExpiryAction.PURGE),
                tenant_b,
            ),
            UUID,
        )
        bind_authenticated_principal(
            context,
            PrincipalIdentity(
                tenant_id=context.tenant.tenant_id,
                principal_id=context.tenant.principal_id,
                principal_type="user",
                authentication_strength="mfa",
            ),
        )

        # Policy replacement takes the scope lock while a purge holds its
        # category-independent subject lock. The future boundary is atomic.
        replacement_key = key.model_copy(update={"record_id": uuid4()})
        _seed_owner(postgres_database, replacement_key, anchor)
        entered, release = asyncio.Event(), asyncio.Event()
        owner.pause_validate = (entered, release)
        purging = asyncio.create_task(
            _command(
                app,
                ExecuteDestructiveLifecycleV2(
                    subject=replacement_key,
                    action=ExpiryAction.PURGE,
                ),
                context,
            )
        )
        await asyncio.wait_for(entered.wait(), 10)
        effective_at = datetime.now(UTC) + timedelta(days=3)
        replacement = ReplaceRetentionPolicyV2(
            tenant_id=key.tenant_id,
            old_policy_id=policy_id,
            owner_module_id=key.owner_module_id,
            resource_namespace=key.resource_namespace,
            contract_version="1",
            entity_type=key.entity_type,
            retention_category="customer",
            retention_period_days=2,
            action_on_expiry=ExpiryAction.PURGE,
            effective_at=effective_at,
        )
        new_policy_id = await asyncio.wait_for(_command(app, replacement, context), 10)
        assert isinstance(new_policy_id, UUID)
        release.set()
        assert isinstance(await asyncio.wait_for(purging, 10), UUID)
        owner.pause_validate = None
        with psycopg.connect(_url(postgres_database.administrator_url)) as connection:
            intervals = connection.execute(
                "SELECT id, valid_from, valid_until FROM platform_gov.retention_policies_v2 "
                "WHERE id IN (%s, %s) ORDER BY valid_from",
                (policy_id, new_policy_id),
            ).fetchall()
        assert len(intervals) == 2
        assert intervals[0][2] == intervals[1][1] == effective_at
        with pytest.raises(BusinessOSError, match="future-only and non-weakening"):
            await _command(
                app,
                replacement.model_copy(
                    update={
                        "old_policy_id": new_policy_id,
                        "retention_period_days": 1,
                        "effective_at": effective_at + timedelta(days=1),
                    }
                ),
                context,
            )

        boundary_start = datetime.now(UTC) + timedelta(days=2)
        boundary_end = boundary_start + timedelta(days=1)
        await _command(
            app,
            policy.model_copy(
                update={
                    "retention_category": "bounded",
                    "valid_from": boundary_start,
                    "valid_until": boundary_end,
                }
            ),
            context,
        )
        with psycopg.connect(_url(postgres_database.administrator_url)) as connection:
            for instant, expected in (
                (boundary_start - timedelta(microseconds=1), 0),
                (boundary_start, 1),
                (boundary_end - timedelta(microseconds=1), 1),
                (boundary_end, 0),
            ):
                count = connection.execute(
                    "SELECT count(*) FROM platform_gov.retention_policies_v2 "
                    "WHERE tenant_id=%s AND retention_category='bounded' "
                    "AND valid_from <= %s AND (valid_until IS NULL OR valid_until > %s)",
                    (key.tenant_id, instant, instant),
                ).fetchone()
                assert count == (expected,)
        future_key = key.model_copy(update={"record_id": uuid4()})
        _seed_owner(postgres_database, future_key, anchor, category="bounded")
        with pytest.raises(BusinessOSError, match="Exactly one effective policy"):
            await _command(
                app,
                ExecuteDestructiveLifecycleV2(
                    subject=future_key,
                    action=ExpiryAction.PURGE,
                ),
                context,
            )
        await _command(
            app,
            policy.model_copy(
                update={
                    "retention_category": "expired",
                    "valid_from": datetime.now(UTC) - timedelta(days=3),
                    "valid_until": datetime.now(UTC) - timedelta(days=2),
                }
            ),
            context,
        )
        expired_key = key.model_copy(update={"record_id": uuid4()})
        _seed_owner(postgres_database, expired_key, anchor, category="expired")
        with pytest.raises(BusinessOSError, match="Exactly one effective policy"):
            await _command(
                app,
                ExecuteDestructiveLifecycleV2(
                    subject=expired_key,
                    action=ExpiryAction.PURGE,
                ),
                context,
            )

        await _command(
            app,
            policy.model_copy(update={"retention_category": "limited"}),
            context,
        )
        limited_key = key.model_copy(update={"record_id": uuid4()})
        _seed_owner(postgres_database, limited_key, anchor, category="limited")
        with pytest.raises(BusinessOSError, match="Owner facts do not support"):
            await _command(
                app,
                ExecuteDestructiveLifecycleV2(
                    subject=limited_key,
                    action=ExpiryAction.PURGE,
                ),
                context,
            )

        changed = key.model_copy(update={"record_id": uuid4()})
        _seed_owner(postgres_database, changed, anchor)
        entered, release = asyncio.Event(), asyncio.Event()
        owner.pause_change = (entered, release)
        changing = asyncio.create_task(
            _command(
                app,
                _ChangeCategory(
                    tenant_id=changed.tenant_id,
                    record_id=changed.record_id,
                    category="supplier",
                ),
                context,
            )
        )
        await asyncio.wait_for(entered.wait(), 10)
        purging = asyncio.create_task(
            _command(
                app,
                ExecuteDestructiveLifecycleV2(
                    subject=changed,
                    action=ExpiryAction.PURGE,
                ),
                context,
            )
        )
        release.set()
        await asyncio.wait_for(changing, 10)
        with pytest.raises(BusinessOSError, match="Exactly one effective policy"):
            await asyncio.wait_for(purging, 10)
        owner.pause_change = None

        recent = key.model_copy(update={"record_id": uuid4()})
        _seed_owner(postgres_database, recent, anchor)
        entered, release = asyncio.Event(), asyncio.Event()
        owner.pause_change = (entered, release)
        changing = asyncio.create_task(
            _command(
                app,
                _ChangeAnchor(
                    tenant_id=recent.tenant_id,
                    record_id=recent.record_id,
                    anchor_at=datetime.now(UTC),
                ),
                context,
            )
        )
        await asyncio.wait_for(entered.wait(), 10)
        purging = asyncio.create_task(
            _command(
                app,
                ExecuteDestructiveLifecycleV2(
                    subject=recent,
                    action=ExpiryAction.PURGE,
                ),
                context,
            )
        )
        release.set()
        await asyncio.wait_for(changing, 10)
        with pytest.raises(BusinessOSError, match="Retention period has not elapsed"):
            await asyncio.wait_for(purging, 10)
        owner.pause_change = None

        unaudited = key.model_copy(update={"record_id": uuid4()})
        _seed_owner(postgres_database, unaudited, anchor)
        clear_authenticated_principal()
        with pytest.raises(BusinessOSError, match="Trusted principal"):
            await _command(
                app,
                ExecuteDestructiveLifecycleV2(
                    subject=unaudited,
                    action=ExpiryAction.PURGE,
                ),
                context,
            )
        with psycopg.connect(_url(postgres_database.administrator_url)) as connection:
            row = connection.execute(
                "SELECT lifecycle FROM public.adr017_owner WHERE record_id=%s",
                (unaudited.record_id,),
            ).fetchone()
        assert row == ("current",)

        bind_authenticated_principal(
            context,
            PrincipalIdentity(
                tenant_id=context.tenant.tenant_id,
                principal_id=context.tenant.principal_id,
                principal_type="user",
                authentication_strength="mfa",
            ),
        )
        old_generation = app.runtime.resources.resolve_owner(
            key.resource_namespace, key.contract_version
        ).generation.number
        draining_key = key.model_copy(update={"record_id": uuid4()})
        _seed_owner(postgres_database, draining_key, anchor)
        entered, release = asyncio.Event(), asyncio.Event()
        owner.pause_validate = (entered, release)
        purging = asyncio.create_task(
            _command(
                app,
                ExecuteDestructiveLifecycleV2(
                    subject=draining_key,
                    action=ExpiryAction.PURGE,
                ),
                context,
            )
        )
        await asyncio.wait_for(entered.wait(), 10)
        disabling = asyncio.create_task(app.runtime.lifecycle.disable(owner.manifest.module_id))
        await asyncio.sleep(0.05)
        assert not disabling.done()
        release.set()
        assert isinstance(await asyncio.wait_for(purging, 10), UUID)
        await asyncio.wait_for(disabling, 10)
        replacement_owner = _Owner(version="1.1.0")
        app.runtime.modules.replace(
            replacement_owner,
            ApprovedModuleArtifact(
                loaded_module=replacement_owner,
                module_id=replacement_owner.manifest.module_id,
                publisher=replacement_owner.manifest.publisher,
                package_identity="adr017-proof-owner",
                loaded_type=(
                    f"{type(replacement_owner).__module__}:{type(replacement_owner).__qualname__}"
                ),
                install_identity="adr017-proof-owner-replacement",
            ),
        )
        await app.runtime.lifecycle.enable(replacement_owner.manifest.module_id)
        new_generation = app.runtime.resources.resolve_owner(
            key.resource_namespace, key.contract_version
        ).generation.number
        assert new_generation > old_generation
        replacement_key = key.model_copy(update={"record_id": uuid4()})
        _seed_owner(postgres_database, replacement_key, anchor)
        assert isinstance(
            await _command(
                app,
                ExecuteDestructiveLifecycleV2(
                    subject=replacement_key,
                    action=ExpiryAction.PURGE,
                ),
                context,
            ),
            UUID,
        )
    finally:
        await app.shutdown()
