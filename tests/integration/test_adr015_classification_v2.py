"""Real PostgreSQL guards for the additive classification V2 boundary."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from businessos_data_governance import (
    ClassificationResolutionV2,
    DataGovernanceModule,
    RegisterDataClassificationCommand,
    SensitiveFieldTagRecord,
    TagSensitiveFieldCommand,
)
from businessos_data_governance.classification_runtime import DataGovernanceClassificationV2
from businessos_data_governance.legacy_mapping import apply_reviewed_mapping, preflight
from businessos_data_governance.module import (
    CreateTenantClassificationV2Command,
    ResolveClassificationV2Query,
    ResolveHistoricalClassificationV2Query,
    ReviseTenantClassificationV2Command,
    SetCanonicalOverlayV2Command,
)
from psycopg.rows import dict_row
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from businessos.application import BusinessOSApplication
from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.context import RequestContext, TenantContext
from businessos.messages import handler_transaction_view
from businessos.modules import discover_modules
from businessos.modules.artifact import ApprovedModuleArtifact
from businessos.persistence.uow import SQLAlchemyUnitOfWork
from businessos.sdk import BusinessOSError
from businessos.security import Authorizer
from tests.conftest import PostgreSQLTestDatabase


class _AllowAllPolicy:
    async def is_allowed(self, principal_id: UUID, tenant: TenantContext, permission: str) -> bool:
        return True


def _context(tenant_id: UUID) -> RequestContext:
    return RequestContext(
        correlation_id=f"adr015-{tenant_id}",
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
    governance = next(module for module in modules if isinstance(module, DataGovernanceModule))
    grant = ApprovedModuleArtifact(
        loaded_module=governance,
        module_id="foundation.data_governance",
        publisher="BusinessOS",
        package_identity="businessos-foundation-data-governance",
        loaded_type="businessos_data_governance.module:DataGovernanceModule",
        install_identity="adr015-test-operator-grant",
        first_party=True,
        approved_aliases=frozenset(
            {
                (
                    "foundation.governance.data-classification",
                    "foundation.data_governance.data-classification",
                    "2",
                )
            }
        ),
    )
    return create_application(
        Settings(environment="test", database_url=database.runtime_url),
        modules=modules,
        authorizer=Authorizer(_AllowAllPolicy()),
        approved_module_artifacts={"foundation.data_governance": grant},
    )


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_classification_v2_grants_rls_and_tenant_identity(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = _application(postgres_database)
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    tenant_a, tenant_b = uuid4(), uuid4()
    await app.startup()
    try:
        async with app.container.request_scope() as dependencies:
            created = await app.runtime.messages.command(
                CreateTenantClassificationV2Command(
                    code="LOCAL_A", name="Local", sensitivity_level=3
                ),
                _context(tenant_a),
                dependencies,
            )
        assert isinstance(created, ClassificationResolutionV2)
        assert created.qualified_ref == f"tenant:{tenant_a}:LOCAL_A"
        with pytest.raises(Exception, match="Global V1 classification registration is retired"):
            async with app.container.request_scope() as dependencies:
                await app.runtime.messages.command(
                    RegisterDataClassificationCommand(
                        code="UNSAFE", name="Unsafe", sensitivity_level=2
                    ),
                    _context(tenant_a),
                    dependencies,
                )
        async with app.container.request_scope() as dependencies:
            other_tenant = await app.runtime.messages.command(
                CreateTenantClassificationV2Command(
                    code="LOCAL_A", name="Local", sensitivity_level=3
                ),
                _context(tenant_b),
                dependencies,
            )
        assert isinstance(other_tenant, ClassificationResolutionV2)
        assert other_tenant.definition_id != created.definition_id
        with pytest.raises(IntegrityError):
            async with app.container.request_scope() as dependencies:
                await app.runtime.messages.command(
                    CreateTenantClassificationV2Command(
                        code="LOCAL_A", name="Duplicate", sensitivity_level=3
                    ),
                    _context(tenant_a),
                    dependencies,
                )
        with pytest.raises(ValueError, match="cross-tenant"):
            async with app.container.request_scope() as dependencies:
                await app.runtime.messages.query(
                    ResolveClassificationV2Query(qualified_ref=created.qualified_ref),
                    _context(tenant_b),
                    dependencies,
                )
        async with app.container.request_scope() as dependencies:
            resolved = await app.runtime.messages.query(
                ResolveClassificationV2Query(qualified_ref=created.qualified_ref),
                _context(tenant_a),
                dependencies,
            )
        assert isinstance(resolved, ClassificationResolutionV2)
        assert resolved.definition_id == created.definition_id
        assert resolved.effective_controls.sensitivity_level == 3
        async with app.container.request_scope() as dependencies:
            revised = await app.runtime.messages.command(
                ReviseTenantClassificationV2Command(
                    qualified_ref=created.qualified_ref,
                    sensitivity_level=4,
                    required_controls=frozenset({"mfa"}),
                ),
                _context(tenant_a),
                dependencies,
            )
        assert isinstance(revised, ClassificationResolutionV2)
        assert revised.definition_version == "2"
        async with app.container.request_scope() as dependencies:
            historical = await app.runtime.messages.query(
                ResolveHistoricalClassificationV2Query(
                    qualified_ref=created.qualified_ref,
                    at=created.valid_from,
                ),
                _context(tenant_a),
                dependencies,
            )
        assert isinstance(historical, ClassificationResolutionV2)
        assert historical.definition_version == "1"
        assert historical.effective_controls.sensitivity_level == 3

        migration_url = postgres_database.migration_url.replace(
            "postgresql+psycopg://", "postgresql://"
        )
        with psycopg.connect(migration_url) as migration:
            migration.execute(
                "INSERT INTO platform_gov.data_classifications "
                "(code, name, sensitivity_level, description) "
                "VALUES ('tenant-map', 'Local', 3, '')"
            )
            migration.execute(
                "INSERT INTO platform_gov.classification_legacy_mappings "
                "(legacy_code, qualified_ref, definition_id, definition_version, "
                "legacy_description_sha256, tenant_id, approved_by, "
                "evidence_reference, tenant_provenance) "
                "VALUES ('tenant-map', %s, %s, 1, %s, %s, 'reviewer', 'review-1', 'source-1')",
                (
                    created.qualified_ref,
                    created.definition_id,
                    hashlib.sha256(b"").hexdigest(),
                    tenant_a,
                ),
            )

        runtime_url = postgres_database.runtime_url.replace(
            "postgresql+psycopg://", "postgresql://"
        )
        with psycopg.connect(runtime_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT has_table_privilege('businessos_app', "
                    "'platform_gov.data_classifications', 'SELECT')"
                )
                assert cursor.fetchone() == (True,)
                for privilege in ("INSERT", "UPDATE", "DELETE"):
                    cursor.execute(
                        "SELECT has_table_privilege('businessos_app', "
                        "'platform_gov.data_classifications', %s)",
                        (privilege,),
                    )
                    assert cursor.fetchone() == (False,)
                cursor.execute(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE oid = 'platform_gov.tenant_classifications'::regclass"
                )
                assert cursor.fetchone() == (True, True)
                for table in (
                    "tenant_classification_versions",
                    "classification_overlays",
                    "classification_legacy_mappings",
                ):
                    cursor.execute(
                        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                        "WHERE oid = %s::regclass",
                        (f"platform_gov.{table}",),
                    )
                    assert cursor.fetchone() == (True, True)
                for table in ("classification_definitions", "classification_versions"):
                    for privilege in ("INSERT", "UPDATE", "DELETE"):
                        cursor.execute(
                            "SELECT has_table_privilege('businessos_app', %s, %s)",
                            (f"platform_gov.{table}", privilege),
                        )
                        assert cursor.fetchone() == (False,)
                cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_b),))
                cursor.execute(
                    "SELECT legacy_code FROM platform_gov.classification_legacy_mappings "
                    "WHERE legacy_code = 'tenant-map'"
                )
                assert cursor.fetchall() == []
                cursor.execute(
                    "SELECT id FROM platform_gov.tenant_classifications WHERE id = %s",
                    (created.definition_id,),
                )
                assert cursor.fetchall() == []
                cursor.execute(
                    "UPDATE platform_gov.tenant_classifications SET name = 'bad' WHERE id = %s",
                    (created.definition_id,),
                )
                assert cursor.rowcount == 0
                with pytest.raises(psycopg.Error):
                    with connection.transaction():
                        cursor.execute(
                            "INSERT INTO platform_gov.tenant_classifications "
                            "(id, tenant_id, code, qualified_ref, name, is_active) "
                            "VALUES (%s, %s, 'OTHER', %s, 'bad', true)",
                            (uuid4(), tenant_a, f"tenant:{tenant_a}:OTHER"),
                        )
                for sql in (
                    "INSERT INTO platform_gov.data_classifications "
                    "(code, name, sensitivity_level) VALUES ('BAD', 'Bad', 1)",
                    "UPDATE platform_gov.data_classifications SET name = 'bad'",
                    "DELETE FROM platform_gov.data_classifications",
                    "DELETE FROM platform_gov.tenant_classifications",
                ):
                    with pytest.raises(psycopg.Error):
                        with connection.transaction():
                            cursor.execute(sql)
    finally:
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_locked_resolution_observes_overlay_committed_while_waiting(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = _application(postgres_database)
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    tenant_id = uuid4()
    definition_id = uuid4()
    url = postgres_database.migration_url.replace("postgresql+psycopg://", "postgresql://")
    engine = create_async_engine(postgres_database.runtime_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def resolve() -> bool:
        async with SQLAlchemyUnitOfWork(sessions, _context(tenant_id).tenant) as uow:
            facts = await DataGovernanceClassificationV2().resolve_locked(
                tenant_id, "core:PUBLIC", handler_transaction_view(uow)
            )
            return facts.sensitive

    task: asyncio.Task[bool] | None = None
    try:
        with psycopg.connect(url) as writer:
            writer.execute(
                "INSERT INTO platform_gov.classification_definitions "
                "(id, code, qualified_ref, name, is_active) "
                "VALUES (%s, 'PUBLIC', 'core:PUBLIC', 'Public', true)",
                (definition_id,),
            )
            writer.execute(
                "INSERT INTO platform_gov.classification_versions "
                "(id, definition_id, version, valid_from, sensitivity_level, "
                "required_controls, restrictions, mandatory_masking) "
                "VALUES (%s, %s, 1, %s, 1, '{}', '{}', false)",
                (uuid4(), definition_id, datetime(2025, 1, 1, tzinfo=UTC)),
            )
            writer.commit()
            writer.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended("
                "'classification-overlay:' || %s || ':PUBLIC', 0))",
                (str(tenant_id),),
            )
            task = asyncio.create_task(resolve())
            await asyncio.sleep(0.2)
            assert not task.done()
            writer.execute(
                "INSERT INTO platform_gov.classification_overlays "
                "(id, tenant_id, canonical_definition_id, version, valid_from, "
                "sensitivity_level, required_controls, restrictions, mandatory_masking) "
                "VALUES (%s, %s, %s, 1, %s, 4, '{}', '{}', true)",
                (uuid4(), tenant_id, definition_id, datetime.now(UTC)),
            )
            writer.commit()
        assert await asyncio.wait_for(task, timeout=10) is True
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await engine.dispose()
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_locked_tenant_base_uses_final_instant_after_row_wait(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = _application(postgres_database)
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    tenant_id = uuid4()
    canonical_id = uuid4()
    tenant_definition_id = uuid4()
    qualified_ref = f"tenant:{tenant_id}:LOCAL"
    transition = datetime.now(UTC) + timedelta(seconds=4)
    migration_url = postgres_database.migration_url.replace(
        "postgresql+psycopg://", "postgresql://"
    )
    admin_url = postgres_database.administrator_url
    engine = create_async_engine(postgres_database.runtime_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    backend_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    request = _context(tenant_id)

    async def resolve() -> bool:
        async with SQLAlchemyUnitOfWork(sessions, request.tenant) as uow:
            pid = await uow.persistence.execute(text("SELECT pg_backend_pid()"))
            backend_pid.set_result(pid.scalar_one())
            result = await DataGovernanceClassificationV2().resolve_assignable(
                qualified_ref, request, handler_transaction_view(uow)
            )
            return result.canonical_controls.mandatory_masking

    task: asyncio.Task[bool] | None = None
    try:
        with psycopg.connect(migration_url) as writer:
            writer.execute(
                "INSERT INTO platform_gov.classification_definitions "
                "(id, code, qualified_ref, name, is_active) "
                "VALUES (%s, 'BASE', 'core:BASE', 'Base', true)",
                (canonical_id,),
            )
            writer.execute(
                "INSERT INTO platform_gov.classification_versions "
                "(id, definition_id, version, valid_from, valid_until, "
                "sensitivity_level, required_controls, restrictions, mandatory_masking) "
                "VALUES (%s, %s, 1, %s, %s, 1, '{}', '{}', false)",
                (uuid4(), canonical_id, datetime(2025, 1, 1, tzinfo=UTC), transition),
            )
            writer.execute(
                "INSERT INTO platform_gov.classification_versions "
                "(id, definition_id, version, valid_from, sensitivity_level, "
                "required_controls, restrictions, mandatory_masking) "
                "VALUES (%s, %s, 2, %s, 4, '{}', '{}', true)",
                (uuid4(), canonical_id, transition),
            )
            writer.execute(
                "INSERT INTO platform_gov.tenant_classifications "
                "(id, tenant_id, code, qualified_ref, name, is_active, canonical_base_id) "
                "VALUES (%s, %s, 'LOCAL', %s, 'Local', true, %s)",
                (tenant_definition_id, tenant_id, qualified_ref, canonical_id),
            )
            writer.execute(
                "INSERT INTO platform_gov.tenant_classification_versions "
                "(id, tenant_id, definition_id, version, valid_from, "
                "sensitivity_level, required_controls, restrictions, mandatory_masking) "
                "VALUES (%s, %s, %s, 1, %s, 4, '{}', '{}', false)",
                (uuid4(), tenant_id, tenant_definition_id, datetime(2025, 1, 1, tzinfo=UTC)),
            )
            writer.commit()
            writer.execute(
                "SELECT id FROM platform_gov.tenant_classifications WHERE id = %s FOR UPDATE",
                (tenant_definition_id,),
            )
            task = asyncio.create_task(resolve())
            pid = await asyncio.wait_for(backend_pid, timeout=10)
            blocked = False
            for _ in range(200):
                with psycopg.connect(admin_url) as watcher:
                    row = watcher.execute(
                        "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s",
                        (pid,),
                    ).fetchone()
                if row is not None and row[0] == "Lock":
                    blocked = True
                    break
                await asyncio.sleep(0.02)
            assert blocked and task is not None and not task.done()
            await asyncio.sleep(max(0, (transition - datetime.now(UTC)).total_seconds() + 0.05))
            writer.commit()
        assert await asyncio.wait_for(task, timeout=10) is True
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await engine.dispose()
        await app.shutdown()


@pytest.mark.integration
@pytest.mark.postgres
def test_reviewed_legacy_mapping_is_atomic_and_never_infers_ownership(
    postgres_database: PostgreSQLTestDatabase, tmp_path: Path
) -> None:
    app = _application(postgres_database)
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    definition_id = uuid4()
    tenant_id = uuid4()
    url = postgres_database.migration_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url, row_factory=dict_row) as connection:
        connection.execute(
            "INSERT INTO platform_gov.data_classifications "
            "(code, name, sensitivity_level, description) VALUES "
            "('personal', 'Personal', 3, '')"
        )
        connection.execute(
            "INSERT INTO platform_gov.classification_definitions "
            "(id, code, qualified_ref, name, is_active) "
            "VALUES (%s, 'PERSONAL', 'core:PERSONAL', 'Personal', true)",
            (definition_id,),
        )
        connection.execute(
            "INSERT INTO platform_gov.classification_versions "
            "(id, definition_id, version, valid_from, sensitivity_level, "
            "required_controls, restrictions, mandatory_masking) "
            "VALUES (%s, %s, 1, %s, 3, '{}', '{}', true)",
            (uuid4(), definition_id, datetime(2025, 1, 1, tzinfo=UTC)),
        )
        connection.execute(
            "INSERT INTO platform_gov.sensitive_field_tags "
            "(id, tenant_id, entity_type, field_name, classification_code) "
            "VALUES (%s, %s, 'record', 'field', 'personal')",
            (uuid4(), tenant_id),
        )
        connection.commit()
        before = preflight(connection)
        assert before["status"] == "BLOCK"
        before_rows = cast(list[dict[str, Any]], before["rows"])
        assert before_rows[0]["provenance"] == "UNKNOWN_REVIEW_REQUIRED"
        assert before_rows[0]["description_sha256"] == hashlib.sha256(b"").hexdigest()
        reviewed = {
            "reviewed_mappings": [
                {
                    "legacy_code": "personal",
                    "legacy_name": "Personal",
                    "legacy_sensitivity_level": 3,
                    "legacy_description_sha256": hashlib.sha256(b"").hexdigest(),
                    "qualified_ref": "core:PERSONAL",
                    "definition_id": str(definition_id),
                    "definition_version": 1,
                    "tenant_id": None,
                    "approved_by": "operator-review-123",
                    "evidence_reference": "change-123",
                    "tenant_provenance": None,
                }
            ]
        }
        file = tmp_path / "reviewed.json"
        file.write_text(json.dumps(reviewed), encoding="utf-8")
        assert apply_reviewed_mapping(connection, file) == 1
        assert preflight(connection)["status"] == "PASS"
        ref_row = connection.execute(
            "SELECT classification_ref FROM platform_gov.sensitive_field_tags"
        ).fetchone()
        assert ref_row is not None and ref_row["classification_ref"] == "core:PERSONAL"

        late_tag_id = uuid4()
        connection.execute(
            "INSERT INTO platform_gov.sensitive_field_tags "
            "(id, tenant_id, entity_type, field_name, classification_code) "
            "VALUES (%s, %s, 'record', 'late-field', 'personal')",
            (late_tag_id, tenant_id),
        )
        connection.commit()
        late_preflight = preflight(connection)
        assert late_preflight["status"] == "BLOCK"
        assert (
            cast(dict[str, int], late_preflight["inconsistent_reference_counts"])[
                "sensitive_field_tags"
            ]
            == 1
        )
        assert apply_reviewed_mapping(connection, file) == 1
        assert preflight(connection)["status"] == "PASS"

        connection.execute(
            "UPDATE platform_gov.sensitive_field_tags "
            "SET classification_version = NULL WHERE id = %s",
            (late_tag_id,),
        )
        connection.commit()
        partial_preflight = preflight(connection)
        assert partial_preflight["status"] == "BLOCK"
        assert (
            cast(dict[str, int], partial_preflight["inconsistent_reference_counts"])[
                "sensitive_field_tags"
            ]
            == 1
        )
        with pytest.raises(ValueError, match="conflicts"):
            apply_reviewed_mapping(connection, file)
        connection.execute(
            "UPDATE platform_gov.sensitive_field_tags SET classification_version = 1 WHERE id = %s",
            (late_tag_id,),
        )
        connection.commit()
        assert preflight(connection)["status"] == "PASS"

        connection.execute(
            "UPDATE platform_gov.data_classifications SET description = 'Changed meaning' "
            "WHERE code = 'personal'"
        )
        connection.commit()
        changed_preflight = preflight(connection)
        assert changed_preflight["status"] == "BLOCK"
        assert changed_preflight["changed_mapping_meaning_count"] == 1
        with pytest.raises(ValueError, match="Legacy meaning changed"):
            apply_reviewed_mapping(connection, file)
        connection.execute(
            "UPDATE platform_gov.data_classifications SET description = '' WHERE code = 'personal'"
        )
        connection.commit()
        assert preflight(connection)["status"] == "PASS"

        reviewed["reviewed_mappings"][0]["definition_id"] = str(uuid4())
        file.write_text(json.dumps(reviewed), encoding="utf-8")
        with pytest.raises(ValueError, match="meaning"):
            apply_reviewed_mapping(connection, file)
        unchanged = connection.execute(
            "SELECT definition_id FROM platform_gov.classification_legacy_mappings "
            "WHERE legacy_code = 'personal'"
        ).fetchone()
        assert unchanged is not None and unchanged["definition_id"] == definition_id


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_canonical_overlay_only_strengthens_controls(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = _application(postgres_database)
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    definition_id = uuid4()
    url = postgres_database.migration_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as connection:
        connection.execute(
            "INSERT INTO platform_gov.data_classifications "
            "(code, name, sensitivity_level, description) "
            "VALUES ('personal', 'Personal', 3, '')"
        )
        connection.execute(
            "INSERT INTO platform_gov.classification_definitions "
            "(id, code, qualified_ref, name, is_active) "
            "VALUES (%s, 'PERSONAL', 'core:PERSONAL', 'Personal', true)",
            (definition_id,),
        )
        connection.execute(
            "INSERT INTO platform_gov.classification_versions "
            "(id, definition_id, version, valid_from, sensitivity_level, "
            "required_controls, restrictions, allowed_audience, mandatory_masking) "
            "VALUES (%s, %s, 1, %s, 3, %s, %s, %s, true)",
            (
                uuid4(),
                definition_id,
                datetime(2025, 1, 1, tzinfo=UTC),
                ["encrypt"],
                ["no_export"],
                ["staff", "manager"],
            ),
        )
        connection.execute(
            "INSERT INTO platform_gov.classification_legacy_mappings "
            "(legacy_code, qualified_ref, definition_id, definition_version, "
            "legacy_description_sha256, approved_by, evidence_reference) "
            "VALUES ('personal', 'core:PERSONAL', %s, 1, %s, 'reviewer', 'review-1')",
            (definition_id, hashlib.sha256(b"").hexdigest()),
        )
        connection.execute(
            "UPDATE platform_gov.classification_definitions SET name = 'Personal' WHERE id = %s",
            (definition_id,),
        )
    tenant_id = uuid4()
    await app.startup()
    try:
        async with app.container.request_scope() as dependencies:
            no_overlay = await app.runtime.messages.query(
                ResolveClassificationV2Query(qualified_ref="core:PERSONAL"),
                _context(tenant_id),
                dependencies,
            )
        assert isinstance(no_overlay, ClassificationResolutionV2)
        assert no_overlay.tenant_additions is None
        assert no_overlay.effective_controls.sensitivity_level == 3
        async with app.container.request_scope() as dependencies:
            composed = await app.runtime.messages.command(
                SetCanonicalOverlayV2Command(
                    canonical_ref="core:PERSONAL",
                    sensitivity_level=4,
                    required_controls=frozenset({"mfa"}),
                    restrictions=frozenset({"region_only"}),
                    allowed_audience=frozenset({"manager"}),
                ),
                _context(tenant_id),
                dependencies,
            )
        assert isinstance(composed, ClassificationResolutionV2)
        assert composed.effective_controls.sensitivity_level == 4
        assert composed.effective_controls.required_controls == frozenset({"encrypt", "mfa"})
        assert composed.effective_controls.restrictions == frozenset({"no_export", "region_only"})
        assert composed.effective_controls.allowed_audience == frozenset({"manager"})
        assert composed.effective_controls.mandatory_masking is True
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            SetCanonicalOverlayV2Command.model_validate(
                {
                    "canonical_ref": "core:PERSONAL",
                    "sensitivity_level": 4,
                    "unsupported_override": "weaker",
                }
            )
        async with app.container.request_scope() as dependencies:
            legacy_tag = await app.runtime.messages.command(
                TagSensitiveFieldCommand(
                    tenant_id=tenant_id,
                    entity_type="record",
                    field_name="secret",
                    classification_code="personal",
                    is_masked_by_default=False,
                ),
                _context(tenant_id),
                dependencies,
            )
        assert isinstance(legacy_tag, SensitiveFieldTagRecord)
        assert legacy_tag.is_masked_by_default is True
        with pytest.raises(ValueError, match="lower"):
            async with app.container.request_scope() as dependencies:
                await app.runtime.messages.command(
                    SetCanonicalOverlayV2Command(
                        canonical_ref="core:PERSONAL", sensitivity_level=2
                    ),
                    _context(tenant_id),
                    dependencies,
                )
        with pytest.raises(Exception, match="masking cannot be disabled"):
            async with app.container.request_scope() as dependencies:
                await app.runtime.messages.command(
                    SetCanonicalOverlayV2Command(
                        canonical_ref="core:PERSONAL",
                        sensitivity_level=4,
                        mandatory_masking=False,
                    ),
                    _context(tenant_id),
                    dependencies,
                )
        with psycopg.connect(url) as connection:
            connection.execute(
                "UPDATE platform_gov.classification_overlays "
                "SET valid_until = %s WHERE tenant_id = %s AND canonical_definition_id = %s "
                "AND valid_until IS NULL",
                (datetime.now(UTC), tenant_id, definition_id),
            )
        with pytest.raises(BusinessOSError, match="no effective version"):
            async with app.container.request_scope() as dependencies:
                await app.runtime.messages.query(
                    ResolveClassificationV2Query(qualified_ref="core:PERSONAL"),
                    _context(tenant_id),
                    dependencies,
                )
        async with app.container.request_scope() as dependencies:
            historical_overlay = await app.runtime.messages.query(
                ResolveHistoricalClassificationV2Query(
                    qualified_ref="core:PERSONAL", at=composed.valid_from
                ),
                _context(tenant_id),
                dependencies,
            )
        assert isinstance(historical_overlay, ClassificationResolutionV2)
        assert historical_overlay.tenant_additions is not None
    finally:
        await app.shutdown()
