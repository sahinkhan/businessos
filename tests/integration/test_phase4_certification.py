"""PostgreSQL certification checks for the Phase 4 foundations."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from businessos_data_governance import (
    CheckPurgeEligibilityQuery,
    ClassificationResolutionV2,
    ConsentRecordModel,
    ConsentVerificationResult,
    CreateRetentionPolicyV2Command,
    CreateTenantClassificationV2Command,
    LegalHoldRecord,
    PlaceLegalHoldCommand,
    PurgeEligibilityResult,
    RecordConsentCommand,
    ReleaseLegalHoldCommand,
    RevokeConsentCommand,
    VerifyConsentQuery,
)

from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.context import RequestContext, TenantContext
from businessos.modules import discover_modules
from businessos.security import Authorizer
from tests.conftest import PostgreSQLTestDatabase


def _raw(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _settings(url: str) -> Settings:
    return Settings(environment="test", database_url=url, database_pool_size=4)


class _AllowAllPolicy:
    async def is_allowed(self, principal_id: UUID, tenant: TenantContext, permission: str) -> bool:
        return True


def _context(tenant_id: UUID) -> RequestContext:
    return RequestContext(
        correlation_id=f"phase4-{tenant_id}",
        trace_id=uuid4().hex,
        tenant=TenantContext(
            installation_id=uuid4(),
            tenant_id=tenant_id,
            principal_id=uuid4(),
            authentication_strength="mfa",
        ),
    )


async def _dispatch(app: Any, message: object, context: RequestContext) -> object:
    assert app.runtime is not None
    async with app.container.request_scope() as dependencies:
        return await app.runtime.messages.command(message, context, dependencies)


async def _query(app: Any, message: object, context: RequestContext) -> object:
    assert app.runtime is not None
    async with app.container.request_scope() as dependencies:
        return await app.runtime.messages.query(message, context, dependencies)


@pytest.mark.integration
@pytest.mark.postgres
def test_phase4_migrations_runtime_access_rls_and_append_only_audit(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = create_application(_settings(postgres_database.runtime_url), modules=discover_modules())
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)

    tenant_a = uuid4()
    tenant_b = uuid4()
    role_id = uuid4()
    audit_id = uuid4()
    consent_id = uuid4()
    try:
        with psycopg.connect(_raw(postgres_database.runtime_url)) as connection:
            connection.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_a),))
            connection.execute(
                "INSERT INTO platform_policy.roles "
                "(id, tenant_id, code, name) VALUES (%s, %s, 'admin', 'Administrator')",
                (role_id, tenant_a),
            )
            connection.execute(
                "INSERT INTO platform_audit.audit_logs "
                "(id, tenant_id, actor_id, action, resource_type, checksum, integrity_version) "
                "VALUES (%s, %s, 'principal', 'create', 'role', %s, '2')",
                (audit_id, tenant_a, "0" * 64),
            )
            connection.execute(
                "INSERT INTO platform_gov.consent_records "
                "(id, tenant_id, subject_id, purpose_code) VALUES (%s, %s, %s, 'support')",
                (consent_id, tenant_a, uuid4()),
            )
            connection.commit()

            connection.execute("SELECT set_config('app.tenant_id', %s, false)", (str(tenant_b),))
            assert (
                connection.execute(
                    "SELECT id FROM platform_policy.roles WHERE id = %s", (role_id,)
                ).fetchall()
                == []
            )
            assert (
                connection.execute(
                    "SELECT id FROM platform_audit.audit_logs WHERE id = %s", (audit_id,)
                ).fetchall()
                == []
            )
            assert (
                connection.execute(
                    "SELECT id FROM platform_gov.consent_records WHERE id = %s", (consent_id,)
                ).fetchall()
                == []
            )

        with psycopg.connect(_raw(postgres_database.runtime_url)) as connection:
            privileges = connection.execute(
                "SELECT "
                "has_table_privilege(current_user, 'platform_policy.roles', "
                "'SELECT, INSERT, UPDATE, DELETE'), "
                "has_table_privilege(current_user, 'platform_gov.consent_records', "
                "'SELECT, INSERT, UPDATE, DELETE'), "
                "has_table_privilege(current_user, 'platform_audit.audit_logs', "
                "'SELECT, INSERT'), "
                "has_table_privilege(current_user, 'platform_audit.audit_logs', 'UPDATE'), "
                "has_table_privilege(current_user, 'platform_audit.audit_logs', 'DELETE')"
            ).fetchone()
        assert privileges == (True, True, True, False, False)

        with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
            heads = {
                row[0] for row in connection.execute("SELECT version_num FROM alembic_version")
            }
            rls = connection.execute(
                "SELECT n.nspname, c.relname, c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname IN ('platform_policy', 'platform_audit', 'platform_gov') "
                "AND c.relkind = 'r' AND c.relrowsecurity "
                "ORDER BY n.nspname, c.relname"
            ).fetchall()
        assert heads == {
            "audit_0002",
            "geography_0003",
            "gov_0003",
            "identity_0005",
            "organization_0003",
            "party_0002",
            "policy_0004",
            "proof_0003",
            "tenant_0002",
        }
        assert len(rls) >= 17
        assert all(row[2] and row[3] for row in rls)
    finally:
        with pytest.raises(Exception, match="gov_0003 downgrade refused"):
            app.runtime.migrations.downgrade(postgres_database.migration_url)


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_governance_retention_legal_hold_and_consent_lifecycle(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    app = create_application(
        _settings(postgres_database.runtime_url),
        modules=(
            module
            for module in discover_modules()
            if module.manifest.module_id.startswith("foundation.")
        ),
        authorizer=Authorizer(_AllowAllPolicy()),
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    tenant_id = uuid4()
    subject_id = uuid4()
    context = _context(tenant_id)
    await app.startup()
    try:
        classification = cast(
            ClassificationResolutionV2,
            await _dispatch(
                app,
                CreateTenantClassificationV2Command(
                    code="PERSONAL", name="Personal", sensitivity_level=3
                ),
                context,
            ),
        )
        await _dispatch(
            app,
            CreateRetentionPolicyV2Command(
                code="party-retention",
                name="Party retention",
                entity_type="party",
                classification_ref=classification.qualified_ref,
                retention_period_days=30,
            ),
            context,
        )
        eligible = await _query(
            app,
            CheckPurgeEligibilityQuery(
                tenant_id=tenant_id,
                entity_type="party",
                entity_id="party-1",
                record_age_days=31,
            ),
            context,
        )
        assert isinstance(eligible, PurgeEligibilityResult)
        assert eligible.can_purge

        hold = await _dispatch(
            app,
            PlaceLegalHoldCommand(
                tenant_id=tenant_id,
                code="litigation",
                name="Litigation hold",
                reason="Pending case",
                entity_type="party",
                entity_id="party-1",
                placed_by="legal-user",
            ),
            context,
        )
        assert isinstance(hold, LegalHoldRecord)
        blocked = await _query(
            app,
            CheckPurgeEligibilityQuery(
                tenant_id=tenant_id,
                entity_type="party",
                entity_id="party-1",
                record_age_days=365,
            ),
            context,
        )
        assert isinstance(blocked, PurgeEligibilityResult)
        assert not blocked.can_purge
        assert blocked.active_holds
        await _dispatch(
            app,
            ReleaseLegalHoldCommand(tenant_id=tenant_id, hold_id=hold.id, released_by="legal-user"),
            context,
        )
        released_result = await _query(
            app,
            CheckPurgeEligibilityQuery(
                tenant_id=tenant_id,
                entity_type="party",
                entity_id="party-1",
                record_age_days=365,
            ),
            context,
        )
        assert isinstance(released_result, PurgeEligibilityResult)
        assert released_result.can_purge

        consent = await _dispatch(
            app,
            RecordConsentCommand(
                tenant_id=tenant_id,
                subject_id=subject_id,
                purpose_code="support",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            ),
            context,
        )
        assert isinstance(consent, ConsentRecordModel)
        active_consent = await _query(
            app,
            VerifyConsentQuery(
                tenant_id=tenant_id,
                subject_id=subject_id,
                purpose_code="support",
            ),
            context,
        )
        assert isinstance(active_consent, ConsentVerificationResult)
        assert active_consent.has_consent
        await _dispatch(
            app,
            RevokeConsentCommand(tenant_id=tenant_id, consent_id=consent.id),
            context,
        )
        revoked_consent = await _query(
            app,
            VerifyConsentQuery(
                tenant_id=tenant_id,
                subject_id=subject_id,
                purpose_code="support",
            ),
            context,
        )
        assert isinstance(revoked_consent, ConsentVerificationResult)
        assert not revoked_consent.has_consent
    finally:
        await app.shutdown()
        with pytest.raises(Exception, match="gov_0003 downgrade refused"):
            app.runtime.migrations.downgrade(postgres_database.migration_url)
