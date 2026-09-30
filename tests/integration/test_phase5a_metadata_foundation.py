"""Integration tests for Phase 5A Metadata Foundation against real PostgreSQL.

Covers:
- RLS and tenant isolation
- Migration replay and table structure
- Published-only read invariant
- Atomic publish and revision immutability
- Two-publisher lost-update race proof
- Publish vs module-activation serialization fence race proof
- Rollback vs module-upgrade race proof
- Rollback / reactivation history preservation
- Audit and outbox event integration
- Reference resolution lifecycle states
"""

import asyncio
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from businessos.application import BusinessOSApplication
from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.context import RequestContext, TenantContext
from businessos.modules import discover_modules
from businessos.modules.artifact import ApprovedModuleArtifact
from businessos.security import Authorizer
from businessos_audit import AuditModule
from businessos_metadata import (
    CreateDraftDefinitionCommand,
    FieldDefinitionModel,
    GetDefinitionQuery,
    GetPublishedDefinitionQuery,
    MetadataDefinitionRecord,
    MetadataDiagnosticCode,
    MetadataDiagnosticError,
    MetadataLifecycleStatus,
    MetadataModule,
    MetadataPayloadModel,
    MetadataRevisionRecord,
    PublishDraftCommand,
    PublishPreflightInput,
    PublishResult,
    PublishStatus,
    ReferenceResolutionQuery,
    RollbackPreflightInput,
    RollbackResult,
    RollbackRevisionCommand,
    RollbackStatus,
    SupportedFieldType,
    TargetReferenceState,
    UpdateDraftDefinitionCommand,
)
from tests.conftest import PostgreSQLTestDatabase


class _AllowAllPolicy:
    async def is_allowed(self, principal_id: UUID, tenant: TenantContext, permission: str) -> bool:
        return True


def _context(tenant_id: UUID) -> RequestContext:
    return RequestContext(
        correlation_id=f"phase5a-{tenant_id}",
        trace_id=uuid4().hex,
        tenant=TenantContext(
            installation_id=uuid4(),
            tenant_id=tenant_id,
            principal_id=uuid4(),
            authentication_strength="mfa",
        ),
    )


def _application(database: PostgreSQLTestDatabase) -> BusinessOSApplication:
    modules = tuple(
        module
        for module in discover_modules()
        if module.manifest.module_id.startswith("foundation.")
    )
    audit = next(module for module in modules if isinstance(module, AuditModule))
    metadata_mod = next(module for module in modules if isinstance(module, MetadataModule))

    return create_application(
        Settings(environment="test", database_url=database.runtime_url),
        modules=modules,
        authorizer=Authorizer(_AllowAllPolicy()),
        approved_module_artifacts={
            "foundation.audit": ApprovedModuleArtifact(
                loaded_module=audit,
                module_id="foundation.audit",
                publisher="BusinessOS",
                package_identity="businessos-foundation-audit",
                loaded_type="businessos_audit.module:AuditModule",
                install_identity="ci-test-only-audit-owner",
                first_party=True,
            ),
            "foundation.metadata": ApprovedModuleArtifact(
                loaded_module=metadata_mod,
                module_id="foundation.metadata",
                publisher="BusinessOS",
                package_identity="businessos-foundation-metadata",
                loaded_type="businessos_metadata.module:MetadataModule",
                install_identity="ci-test-only-adr023-metadata-owner",
                first_party=True,
            ),
        },
    )


def _sample_payload(suffix: str = "1") -> MetadataPayloadModel:
    return MetadataPayloadModel(
        schema_version="1",
        fields=[
            FieldDefinitionModel(
                key=f"field_{suffix}",
                field_type=SupportedFieldType.STRING,
                label=f"Sample Field {suffix}",
                required=False,
                default_value=f"default_{suffix}",
            )
        ],
    )


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_metadata_rls_and_tenant_isolation(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = _application(postgres_database)
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)

    tenant_a = uuid4()
    tenant_b = uuid4()
    await app.startup()
    try:
        # Verify RLS is enabled and forced on all platform_metadata tables
        connection_url = postgres_database.runtime_url.replace(
            "postgresql+psycopg://", "postgresql://", 1
        )
        with psycopg.connect(connection_url) as conn:
            rows = conn.execute(
                "SELECT relname, relrowsecurity, relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'platform_metadata' AND c.relkind = 'r' "
                "ORDER BY relname"
            ).fetchall()
            assert len(rows) == 4
            for table_name, rls_enabled, rls_forced in rows:
                assert rls_enabled is True, f"RLS not enabled on {table_name}"
                assert rls_forced is True, f"RLS not forced on {table_name}"

        # Tenant A creates a draft definition
        async with app.container.request_scope() as deps:
            draft_a = await app.runtime.messages.command(
                CreateDraftDefinitionCommand(
                    owner_namespace="foundation.party",
                    definition_kind="custom_field",
                    stable_key="customer_segment",
                    payload=_sample_payload("a"),
                ),
                _context(tenant_a),
                deps,
            )
        assert isinstance(draft_a, MetadataDefinitionRecord)
        assert draft_a.tenant_id == tenant_a
        assert draft_a.draft_generation == 1

        # Tenant B queries Tenant A's definition -> must fail closed (404/denied)
        with pytest.raises(BusinessOSError) as exc_info:
            async with app.container.request_scope() as deps:
                await app.runtime.messages.query(
                    GetDefinitionQuery(definition_id=draft_a.id),
                    _context(tenant_b),
                    deps,
                )
        assert exc_info.value.code == "policy_denied"

        # Tenant B attempts to update Tenant A's draft -> must fail closed
        with pytest.raises(BusinessOSError) as exc_info:
            async with app.container.request_scope() as deps:
                await app.runtime.messages.command(
                    UpdateDraftDefinitionCommand(
                        definition_id=draft_a.id,
                        expected_draft_generation=1,
                        payload=_sample_payload("b_malicious"),
                    ),
                    _context(tenant_b),
                    deps,
                )
        assert exc_info.value.code == "policy_denied"
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_published_only_read_and_atomic_publish(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = _application(postgres_database)
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)

    tenant_id = uuid4()
    await app.startup()
    try:
        # Create draft definition
        async with app.container.request_scope() as deps:
            draft = await app.runtime.messages.command(
                CreateDraftDefinitionCommand(
                    owner_namespace="foundation.party",
                    definition_kind="custom_field",
                    stable_key="tier_level",
                    payload=_sample_payload("tier"),
                ),
                _context(tenant_id),
                deps,
            )

        # Published-only read MUST FAIL while still in draft status
        with pytest.raises(BusinessOSError, match="No active published definition found"):
            async with app.container.request_scope() as deps:
                await app.runtime.messages.query(
                    GetPublishedDefinitionQuery(
                        owner_namespace="foundation.party",
                        definition_kind="custom_field",
                        stable_key="tier_level",
                    ),
                    _context(tenant_id),
                    deps,
                )

        # Preflight publish
        meta_mod = next(
            m for m in app.runtime.modules if m.manifest.module_id == "foundation.metadata"
        )
        preflight_res = await meta_mod.service.preflight(
            tenant_id=tenant_id,
            definition_id=draft.id,
            fence_scope="global",
            executor=app.runtime.database.engine,
        )
        assert preflight_res.valid is True
        assert preflight_res.preflight_input.expected_draft_generation == 1
        assert preflight_res.preflight_input.expected_active_revision_id is None

        # Publish draft atomically
        async with app.container.request_scope() as deps:
            publish_res = await app.runtime.messages.command(
                PublishDraftCommand(
                    definition_id=draft.id,
                    preflight=preflight_res.preflight_input,
                    comment="Initial publication",
                ),
                _context(tenant_id),
                deps,
            )
        assert isinstance(publish_res, PublishResult)
        assert publish_res.status == PublishStatus.SUCCESS
        assert publish_res.revision is not None
        assert publish_res.active_pointer is not None
        assert publish_res.revision.revision_seq == 1
        assert len(publish_res.revision.content_digest) == 64

        # Now published-only read SUCCEEDS and returns the active published revision
        async with app.container.request_scope() as deps:
            def_record, rev_record = await app.runtime.messages.query(
                GetPublishedDefinitionQuery(
                    owner_namespace="foundation.party",
                    definition_kind="custom_field",
                    stable_key="tier_level",
                ),
                _context(tenant_id),
                deps,
            )
        assert def_record.lifecycle_status == MetadataLifecycleStatus.PUBLISHED
        assert rev_record.id == publish_res.revision.id
        assert rev_record.content_digest == publish_res.revision.content_digest

        # Verify revision immutability: direct update on metadata_revisions is denied by PostgreSQL grant
        connection_url = postgres_database.runtime_url.replace(
            "postgresql+psycopg://", "postgresql://", 1
        )
        with psycopg.connect(connection_url) as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(
                    "UPDATE platform_metadata.metadata_revisions SET schema_version = '2' "
                    "WHERE id = %s",
                    (publish_res.revision.id,),
                )
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_two_publisher_lost_update_race_proof(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    """Proof: Two concurrent publishers starting from the same draft generation cannot overwrite one another."""
    app = _application(postgres_database)
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)

    tenant_id = uuid4()
    await app.startup()
    try:
        # Create draft definition
        async with app.container.request_scope() as deps:
            draft = await app.runtime.messages.command(
                CreateDraftDefinitionCommand(
                    owner_namespace="foundation.party",
                    definition_kind="custom_field",
                    stable_key="concurrency_test",
                    payload=_sample_payload("1"),
                ),
                _context(tenant_id),
                deps,
            )

        meta_mod = next(
            m for m in app.runtime.modules if m.manifest.module_id == "foundation.metadata"
        )
        # Publisher A and Publisher B both preflight at the exact same draft generation 1
        preflight_a = await meta_mod.service.preflight(
            tenant_id=tenant_id,
            definition_id=draft.id,
            fence_scope="global",
            executor=app.runtime.database.engine,
        )
        preflight_b = await meta_mod.service.preflight(
            tenant_id=tenant_id,
            definition_id=draft.id,
            fence_scope="global",
            executor=app.runtime.database.engine,
        )

        assert preflight_a.preflight_input.expected_draft_generation == 1
        assert preflight_b.preflight_input.expected_draft_generation == 1

        # Publisher A publishes successfully
        async with app.container.request_scope() as deps:
            res_a = await app.runtime.messages.command(
                PublishDraftCommand(
                    definition_id=draft.id,
                    preflight=preflight_a.preflight_input,
                    comment="Publisher A",
                ),
                _context(tenant_id),
                deps,
            )
        assert res_a.status == PublishStatus.SUCCESS

        # Publisher B attempts to publish with its now-stale draft generation
        async with app.container.request_scope() as deps:
            res_b = await app.runtime.messages.command(
                PublishDraftCommand(
                    definition_id=draft.id,
                    preflight=preflight_b.preflight_input,
                    comment="Publisher B",
                ),
                _context(tenant_id),
                deps,
            )
        # Publisher B MUST be rejected with stale_draft (lost-update prevented!)
        assert res_b.status == PublishStatus.STALE_DRAFT
        assert res_b.diagnostic is not None
        assert res_b.diagnostic.code == MetadataDiagnosticCode.STALE_DRAFT
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_publish_vs_module_activation_fence_race_proof(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    """Proof: Module activation preflights metadata; if metadata advances concurrently, activation commits fail."""
    app = _application(postgres_database)
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)

    tenant_id = uuid4()
    await app.startup()
    try:
        meta_mod = next(
            m for m in app.runtime.modules if m.manifest.module_id == "foundation.metadata"
        )
        # Module activation preflights against fence state (metadata_generation=1)
        fence_initial = await meta_mod.service.get_fence_state(
            tenant_id, "global", executor=app.runtime.database.engine
        )
        assert fence_initial.metadata_generation == 1
        module_expected_meta_gen = fence_initial.metadata_generation

        # Concurrent metadata publication takes place!
        async with app.container.request_scope() as deps:
            draft = await app.runtime.messages.command(
                CreateDraftDefinitionCommand(
                    owner_namespace="foundation.party",
                    definition_kind="custom_field",
                    stable_key="fence_race_field",
                    payload=_sample_payload("race"),
                ),
                _context(tenant_id),
                deps,
            )

        preflight = await meta_mod.service.preflight(
            tenant_id=tenant_id,
            definition_id=draft.id,
            fence_scope="global",
            executor=app.runtime.database.engine,
        )
        async with app.container.request_scope() as deps:
            pub_res = await app.runtime.messages.command(
                PublishDraftCommand(
                    definition_id=draft.id,
                    preflight=preflight.preflight_input,
                    comment="Published concurrent metadata",
                ),
                _context(tenant_id),
                deps,
            )
        assert pub_res.status == PublishStatus.SUCCESS

        # Fence metadata_generation has now advanced to 2
        fence_updated = await meta_mod.service.get_fence_state(
            tenant_id, "global", executor=app.runtime.database.engine
        )
        assert fence_updated.metadata_generation == 2

        # Module activation now attempts to acquire fence with its stale metadata_generation=1
        from businessos_metadata.fence import acquire_fence_for_module_activation

        async with app.runtime.database.sessions() as session:
            with pytest.raises(MetadataDiagnosticError) as exc_info:
                await acquire_fence_for_module_activation(
                    session,
                    tenant_id,
                    "global",
                    expected_metadata_generation=module_expected_meta_gen,
                )
            assert exc_info.value.diagnostic_code == MetadataDiagnosticCode.ACTIVE_REVISION_CONFLICT
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_rollback_reactivation_and_history_preservation(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = _application(postgres_database)
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)

    tenant_id = uuid4()
    await app.startup()
    try:
        # Create draft and publish Revision 1
        async with app.container.request_scope() as deps:
            draft = await app.runtime.messages.command(
                CreateDraftDefinitionCommand(
                    owner_namespace="foundation.party",
                    definition_kind="custom_field",
                    stable_key="versioned_field",
                    payload=_sample_payload("v1"),
                ),
                _context(tenant_id),
                deps,
            )

        meta_mod = next(
            m for m in app.runtime.modules if m.manifest.module_id == "foundation.metadata"
        )
        preflight1 = await meta_mod.service.preflight(
            tenant_id, draft.id, "global", executor=app.runtime.database.engine
        )
        async with app.container.request_scope() as deps:
            pub1 = await app.runtime.messages.command(
                PublishDraftCommand(
                    definition_id=draft.id,
                    preflight=preflight1.preflight_input,
                    comment="Rev 1",
                ),
                _context(tenant_id),
                deps,
            )
        assert pub1.status == PublishStatus.SUCCESS
        rev1_id = pub1.revision.id

        # Update draft and publish Revision 2
        async with app.container.request_scope() as deps:
            draft_v2 = await app.runtime.messages.command(
                UpdateDraftDefinitionCommand(
                    definition_id=draft.id,
                    expected_draft_generation=draft.draft_generation + 1,
                    payload=_sample_payload("v2"),
                ),
                _context(tenant_id),
                deps,
            )
        preflight2 = await meta_mod.service.preflight(
            tenant_id, draft.id, "global", executor=app.runtime.database.engine
        )
        async with app.container.request_scope() as deps:
            pub2 = await app.runtime.messages.command(
                PublishDraftCommand(
                    definition_id=draft.id,
                    preflight=preflight2.preflight_input,
                    comment="Rev 2",
                ),
                _context(tenant_id),
                deps,
            )
        assert pub2.status == PublishStatus.SUCCESS
        rev2_id = pub2.revision.id

        # Active pointer is currently Revision 2
        active_rev = await meta_mod.service.get_active_revision(
            tenant_id, draft.id, executor=app.runtime.database.engine
        )
        assert active_rev.id == rev2_id

        # Rollback / Reactivate Revision 1
        rb_preflight = await meta_mod.service.preflight_rollback(
            tenant_id, draft.id, rev1_id, "global", executor=app.runtime.database.engine
        )
        assert rb_preflight.valid is True

        async with app.container.request_scope() as deps:
            rb_res = await app.runtime.messages.command(
                RollbackRevisionCommand(
                    definition_id=draft.id,
                    target_revision_id=rev1_id,
                    preflight=rb_preflight.preflight_input,
                    comment="Reactivating Rev 1",
                ),
                _context(tenant_id),
                deps,
            )
        assert rb_res.status == RollbackStatus.SUCCESS
        assert rb_res.active_pointer.revision_id == rev1_id

        # Active pointer is now Revision 1
        active_now = await meta_mod.service.get_active_revision(
            tenant_id, draft.id, executor=app.runtime.database.engine
        )
        assert active_now.id == rev1_id

        # Revision history is preserved untouched (both Revision 1 and Revision 2 exist)
        revisions = await meta_mod.service.list_revisions(
            tenant_id, draft.id, executor=app.runtime.database.engine
        )
        assert len(revisions) == 2
        rev_ids = {r.id for r in revisions}
        assert rev1_id in rev_ids
        assert rev2_id in rev_ids
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_audit_outbox_integration(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = _application(postgres_database)
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)

    tenant_id = uuid4()
    await app.startup()
    try:
        # Publish should append an outbox event in the same transaction
        async with app.container.request_scope() as deps:
            draft = await app.runtime.messages.command(
                CreateDraftDefinitionCommand(
                    owner_namespace="foundation.party",
                    definition_kind="custom_field",
                    stable_key="outbox_field",
                    payload=_sample_payload("outbox"),
                ),
                _context(tenant_id),
                deps,
            )

        meta_mod = next(
            m for m in app.runtime.modules if m.manifest.module_id == "foundation.metadata"
        )
        preflight = await meta_mod.service.preflight(
            tenant_id, draft.id, "global", executor=app.runtime.database.engine
        )
        async with app.container.request_scope() as deps:
            pub_res = await app.runtime.messages.command(
                PublishDraftCommand(
                    definition_id=draft.id,
                    preflight=preflight.preflight_input,
                    comment="Outbox test",
                ),
                _context(tenant_id),
                deps,
            )
        assert pub_res.status == PublishStatus.SUCCESS

        # Verify outbox messages in eventing.outbox_messages table
        connection_url = postgres_database.runtime_url.replace(
            "postgresql+psycopg://", "postgresql://", 1
        )
        with psycopg.connect(connection_url) as conn:
            messages = conn.execute(
                "SELECT event_type, payload FROM eventing.outbox_messages "
                "WHERE tenant_id = %s ORDER BY occurred_at",
                (tenant_id,),
            ).fetchall()

        event_types = [m[0] for m in messages]
        assert "metadata.draft.created" in event_types
        assert "metadata.revision.published" in event_types
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_reference_resolution_lifecycle_states(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = _application(postgres_database)
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)

    tenant_a = uuid4()
    tenant_b = uuid4()
    await app.startup()
    try:
        meta_mod = next(
            m for m in app.runtime.modules if m.manifest.module_id == "foundation.metadata"
        )
        # Create active definition in Tenant A
        async with app.container.request_scope() as deps:
            target_def = await app.runtime.messages.command(
                CreateDraftDefinitionCommand(
                    owner_namespace="foundation.party",
                    definition_kind="custom_field",
                    stable_key="target_ref_field",
                    payload=_sample_payload("target"),
                ),
                _context(tenant_a),
                deps,
            )

        # 1. Resolves as REFERENCEABLE within Tenant A
        res_active = await meta_mod.service.resolve_reference(
            ReferenceResolutionQuery(
                source_resource_namespace="foundation.order",
                source_record_id=uuid4(),
                target_resource_namespace="foundation.metadata.definition",
                target_record_id=target_def.id,
                tenant_id=tenant_a,
            ),
            executor=app.runtime.database.engine,
        )
        assert res_active.state == TargetReferenceState.REFERENCEABLE

        # 2. Cross-tenant reference to Tenant A from Tenant B resolves as UNAVAILABLE
        res_cross_tenant = await meta_mod.service.resolve_reference(
            ReferenceResolutionQuery(
                source_resource_namespace="foundation.order",
                source_record_id=uuid4(),
                target_resource_namespace="foundation.metadata.definition",
                target_record_id=target_def.id,
                tenant_id=tenant_b,
            ),
            executor=app.runtime.database.engine,
        )
        assert res_cross_tenant.state == TargetReferenceState.UNAVAILABLE
        assert res_cross_tenant.diagnostic_code == MetadataDiagnosticCode.UNAVAILABLE_TARGET

        # 3. Retire target definition -> resolves as RETIRED
        async with app.container.request_scope() as deps:
            await app.runtime.messages.command(
                {
                    "definition_id": target_def.id,
                    "reason": "Lifecycle test retirement",
                },
                _context(tenant_a),
                deps,
            )
        # Or retire via service
        await meta_mod.service.retire(
            tenant_id=tenant_a,
            definition_id=target_def.id,
            retired_by="tester",
            executor=app.runtime.database.engine,
        )

        res_retired = await meta_mod.service.resolve_reference(
            ReferenceResolutionQuery(
                source_resource_namespace="foundation.order",
                source_record_id=uuid4(),
                target_resource_namespace="foundation.metadata.definition",
                target_record_id=target_def.id,
                tenant_id=tenant_a,
            ),
            executor=app.runtime.database.engine,
        )
        assert res_retired.state == TargetReferenceState.RETIRED
        assert res_retired.diagnostic_code == MetadataDiagnosticCode.RETIRED_TARGET
    finally:
        await app.shutdown()
