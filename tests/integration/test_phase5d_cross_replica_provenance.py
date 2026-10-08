"""Independent approved replicas must not rename stale declarations as a new artifact."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import psycopg
import pytest
from businessos_identity.principal_binding import clear_authenticated_principal
from businessos_metadata.module import CreateUIOverlay, ReactivateUIOverlay, RetireUIOverlay
from businessos_metadata.ui_contracts import UIOverlayDocument, UIOverlayScope
from businessos_party.module import PartyModule

from businessos.application import BusinessOSApplication
from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.modules import discover_modules
from businessos.modules.artifact import ApprovedModuleArtifact
from businessos.modules.installation_inventory import approved_artifacts_from_operator_inventory
from businessos.sdk import BusinessOSError, MetadataDeclaration, ModuleRegistration
from businessos.security import Authorizer
from tests.conftest import PostgreSQLTestDatabase
from tests.integration.test_phase5a_metadata import _context, _url
from tests.integration.test_phase5d_ui import VIEW, Harness, UIPolicy, create, publish

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.asyncio]


class _CapabilityRegistration:
    """Approved test artifact Y withdraws customization through ordinary SDK declarations."""

    def __init__(self, registration: ModuleRegistration) -> None:
        self.registration = registration

    def __getattr__(self, name: str) -> Any:
        return getattr(self.registration, name)

    def metadata(self, declaration: MetadataDeclaration) -> None:
        if declaration.kind == "ui.capabilities.v1":
            value = json.loads(json.dumps(declaration.value))
            for rule in value["customization"]:
                rule["properties"].remove("order")
            declaration = declaration.model_copy(update={"value": value})
        self.registration.metadata(declaration)


class _ArtifactParty(PartyModule):
    def __init__(self, withdrawn: bool) -> None:
        super().__init__()
        self.withdrawn = withdrawn

    async def register(self, registration: ModuleRegistration) -> None:
        await super().register(
            cast(ModuleRegistration, _CapabilityRegistration(registration))
            if self.withdrawn
            else registration
        )


def _replica(
    database: PostgreSQLTestDatabase,
    artifact: str,
    *,
    changed_module: str = "foundation.party",
) -> tuple[BusinessOSApplication, UIPolicy]:
    party = _ArtifactParty(artifact == "Y" and changed_module == "foundation.party")
    modules = [
        party if module.manifest.module_id == "foundation.party" else module
        for module in discover_modules()
        if module.manifest.module_id.startswith("foundation.")
    ]
    inventory = json.loads(
        Path("tests/fixtures/approved-module-inventory.ci.json").read_text(encoding="utf-8")
    )
    for grant in inventory["approved_modules"]:
        if grant["module_id"] == "foundation.party":
            grant["loaded_type"] = f"{type(party).__module__}:{type(party).__qualname__}"
            grant["install_identity"] = "f2-party-" + (
                artifact if changed_module == "foundation.party" else "X"
            )
    approved = dict(approved_artifacts_from_operator_inventory(modules, inventory=inventory))
    if changed_module != "foundation.party":
        module = next(item for item in modules if item.manifest.module_id == changed_module)
        approved[changed_module] = ApprovedModuleArtifact(
            loaded_module=module,
            module_id=changed_module,
            publisher=module.manifest.publisher,
            package_identity="businessos-foundation-geography",
            loaded_type=f"{type(module).__module__}:{type(module).__qualname__}",
            install_identity="f2-dependency-" + artifact,
            first_party=True,
        )
    policy = UIPolicy()
    return (
        create_application(
            Settings(
                environment="test",
                database_url=database.runtime_url,
                metadata_database_url=database.metadata_url,
                ui_publication_database_url=database.ui_publication_url,
            ),
            modules=modules,
            approved_module_artifacts=approved,
            authorizer=Authorizer(policy),
        ),
        policy,
    )


def _harness(
    app: BusinessOSApplication, database: PostgreSQLTestDatabase, policy: UIPolicy
) -> Harness:
    context = _context(uuid4())
    assert context.tenant is not None
    context = replace(
        context,
        tenant=replace(context.tenant, active_company_id=uuid4(), operating_site_id=uuid4()),
    )
    return Harness(app, database, context, policy)


def _effects(database: PostgreSQLTestDatabase) -> tuple[object, ...]:
    with psycopg.connect(_url(database.migration_url)) as connection:
        return tuple(
            connection.execute(
                f"SELECT to_jsonb(t) FROM {table} t ORDER BY to_jsonb(t)::text"
            ).fetchall()
            for table in (
                "platform_metadata.ui_overlays",
                "platform_metadata.ui_overlay_revisions",
                "platform_metadata.ui_expected_provenance",
                "platform_metadata.ui_expected_members",
                "platform_metadata.module_fence",
                "platform_audit.audit_logs",
                "eventing.outbox_messages",
            )
        )


@pytest.mark.parametrize("changed_module", ["foundation.party", "foundation.geography"])
async def test_two_approved_replicas_reject_withdrawn_source_and_dependency_artifacts(
    postgres_database: PostgreSQLTestDatabase, changed_module: str
) -> None:
    database = postgres_database
    app_a, policy_a = _replica(database, "X", changed_module=changed_module)
    assert app_a.runtime is not None
    app_a.runtime.migrations.upgrade(database.migration_url)
    await app_a.startup()
    a = _harness(app_a, database, policy_a)
    app_b, policy_b = _replica(database, "Y", changed_module=changed_module)
    started_b = False
    try:
        published = await publish(a, await create(a, order=93))
        assert published.active_revision_id is not None
        # Active bindings must independently prevent a capability-withdrawing activation.
        with pytest.raises(Exception, match="active Metadata revisions"):
            await app_b.startup()
        await app_b.shutdown()
        retired = await a.command(
            RetireUIOverlay(
                overlay_id=published.overlay_id,
                expected_draft_generation=published.draft_generation,
                expected_active_generation=published.active_generation,
            )
        )
        draft = await create(a, UIOverlayScope.COMPANY, order=71)
        app_b, policy_b = _replica(database, "Y", changed_module=changed_module)
        await app_b.startup()
        started_b = True
        assert app_b.runtime is not None
        assert app_a.runtime.modules.activation_identity(changed_module) != (
            app_b.runtime.modules.activation_identity(changed_module)
        )
        before = _effects(database)
        with pytest.raises(BusinessOSError, match="UI overlay rejected") as stale_create:
            await create(a, UIOverlayScope.SITE)
        assert stale_create.value.code == "ui_stale_overlay"
        with pytest.raises(BusinessOSError, match="UI overlay rejected") as stale_publish:
            await publish(a, draft)
        assert stale_publish.value.code == "ui_stale_overlay"
        with pytest.raises(BusinessOSError, match="UI overlay rejected") as stale_reactivate:
            await a.command(
                ReactivateUIOverlay(
                    overlay_id=retired.overlay_id,
                    revision_id=published.active_revision_id,
                    expected_draft_generation=retired.draft_generation,
                    expected_active_generation=retired.active_generation,
                )
            )
        assert stale_reactivate.value.code == "ui_stale_overlay"
        stale = await a.resolve()
        assert stale.resolved is None and stale.diagnostics[0].code == "stale_overlay"
        assert _effects(database) == before, "Stale X must persist no authoritative effect"
        b = Harness(app_b, database, a.context, policy_b)
        current = await b.resolve()
        assert current.resolved is not None
        customization = current.resolved.capabilities.customization[0].properties
        assert ("order" not in customization) == (changed_module == "foundation.party")
        if changed_module == "foundation.party":
            with pytest.raises(BusinessOSError, match="UI overlay rejected"):
                await create(b, UIOverlayScope.SITE, order=72)
        row = await b.command(
            CreateUIOverlay(
                view_id=VIEW,
                scope_kind=UIOverlayScope.SITE,
                document=UIOverlayDocument.model_validate(
                    {"patches": [{"target_id": str(VIEW), "density": "compact"}]}
                ),
            )
        )
        assert (await publish(b, row)).active_revision_id is not None
        assert (await b.resolve()).resolved is not None
        with psycopg.connect(_url(database.migration_url)) as connection:
            assert connection.execute(
                "SELECT count(*) FROM platform_metadata.ui_expected_members e "
                "JOIN platform_metadata.module_fence f USING(module_id) "
                "WHERE e.module_id=%s AND e.artifact_identity=f.artifact_identity "
                "AND e.generation=f.generation",
                (changed_module,),
            ).fetchone() == (1,)
    finally:
        clear_authenticated_principal()
        if started_b:
            await app_b.shutdown()
        await app_a.shutdown()


async def test_same_approved_artifact_allows_independent_process_generations(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    database = postgres_database
    app_a, policy_a = _replica(database, "X")
    assert app_a.runtime is not None
    app_a.runtime.migrations.upgrade(database.migration_url)
    await app_a.startup()
    app_b, policy_b = _replica(database, "X")
    started_b = False
    try:
        # Policy depends on Party. Use the certified reverse-dependency drain
        # and forward enable order to obtain a distinct local generation.
        await app_a.runtime.lifecycle.disable_all()
        await app_a.runtime.lifecycle.enable_all()
        await app_b.startup()
        started_b = True
        assert app_b.runtime is not None
        assert app_a.runtime.contributions.active_generation("foundation.party").number != (
            app_b.runtime.contributions.active_generation("foundation.party").number
        )
        a = _harness(app_a, database, policy_a)
        b = Harness(app_b, database, a.context, policy_b)
        published = await publish(a, await create(a))
        resolution = await b.resolve()
        assert resolution.resolved is not None
        assert (
            resolution.resolved.provenance.overlays[0].revision_id == published.active_revision_id
        )
        module = next(
            item
            for item in resolution.resolved.provenance.modules
            if item.module_id == "foundation.party"
        )
        assert module.generation == 1
    finally:
        clear_authenticated_principal()
        if started_b:
            await app_b.shutdown()
        await app_a.shutdown()


async def test_same_artifact_return_does_not_admit_an_old_durable_generation(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    database = postgres_database
    app_a, policy_a = _replica(database, "X")
    assert app_a.runtime is not None
    app_a.runtime.migrations.upgrade(database.migration_url)
    await app_a.startup()
    a = _harness(app_a, database, policy_a)
    app_b, _ = _replica(database, "Y")
    app_c, policy_c = _replica(database, "X")
    started_b = started_c = False
    try:
        await app_b.startup()
        started_b = True
        await app_b.shutdown()
        started_b = False
        await app_c.startup()
        started_c = True
        assert app_c.runtime is not None
        assert app_a.runtime.modules.activation_identity("foundation.party") == (
            app_c.runtime.modules.activation_identity("foundation.party")
        )
        with pytest.raises(BusinessOSError, match="UI overlay rejected"):
            await create(a)
        assert (await a.resolve()).resolved is None
        c = Harness(app_c, database, a.context, policy_c)
        row = await publish(c, await create(c))
        assert row.active_revision_id is not None
        resolution = await c.resolve()
        assert resolution.resolved is not None
        assert (
            next(
                item.generation
                for item in resolution.resolved.provenance.modules
                if item.module_id == "foundation.party"
            )
            == 3
        )
    finally:
        clear_authenticated_principal()
        if started_c:
            await app_c.shutdown()
        if started_b:
            await app_b.shutdown()
        await app_a.shutdown()
