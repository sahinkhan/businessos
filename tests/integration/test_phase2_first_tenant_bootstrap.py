"""The installation operator can bootstrap exactly one tenant without an HTTP bypass."""

from uuid import uuid4

import psycopg
import pytest
from businessos_tenant import DeploymentMode, ProvisionTenant, TenantModule
from scripts.bootstrap_first_tenant import BootstrapUnavailableError, bootstrap_first_tenant

from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.context import RequestContext, TenantContext
from businessos.errors import BusinessOSError
from businessos.security import Authorizer
from tests.conftest import PostgreSQLTestDatabase


def _raw(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


class _AllowAll:
    async def is_allowed(
        self, principal_id: object, tenant: TenantContext, permission: str
    ) -> bool:
        return True


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_first_tenant_bootstrap_is_operator_only_one_time_and_audited(
    postgres_database: PostgreSQLTestDatabase,
) -> None:
    settings = Settings(
        environment="test",
        database_url=postgres_database.runtime_url,
        database_readiness_enabled=False,
    )
    app = create_application(
        settings,
        modules=(TenantModule(),),
        authorizer=Authorizer(_AllowAll()),
    )
    assert app.runtime is not None
    app.runtime.migrations.upgrade(postgres_database.migration_url)
    await app.startup()
    command = ProvisionTenant(
        tenant_id=uuid4(),
        slug="first-tenant",
        name="First Tenant",
        deployment_mode=DeploymentMode.SHARED_SCHEMA,
        region="global",
    )
    try:
        async with app.container.request_scope() as dependencies:
            with pytest.raises(BusinessOSError, match="Authentication required"):
                await app.runtime.messages.command(command, RequestContext(), dependencies)
        with pytest.raises(BootstrapUnavailableError, match="disabled"):
            await bootstrap_first_tenant(
                settings, postgres_database.operations_url, command, enabled=False
            )
        with pytest.raises(BootstrapUnavailableError, match="businessos_ops"):
            await bootstrap_first_tenant(
                settings, postgres_database.runtime_url, command, enabled=True
            )

        result = await bootstrap_first_tenant(
            settings, postgres_database.operations_url, command, enabled=True
        )
        assert result == {"tenant_id": command.tenant_id, "status": "requested"}
        with psycopg.connect(_raw(postgres_database.migration_url)) as connection:
            assert connection.execute(
                "SELECT count(*) FROM platform_tenant.tenants WHERE tenant_id = %s",
                (command.tenant_id,),
            ).fetchone() == (1,)
            history = connection.execute(
                "SELECT changed_by FROM platform_tenant.tenant_status_history WHERE tenant_id = %s",
                (command.tenant_id,),
            ).fetchone()
            assert history is not None and history[0] is not None
            event = connection.execute(
                "SELECT event_type FROM eventing.outbox_messages WHERE tenant_id = %s",
                (command.tenant_id,),
            ).fetchone()
            assert event == ("tenant.created.v1",)
        with pytest.raises(BootstrapUnavailableError, match="already complete"):
            await bootstrap_first_tenant(
                settings,
                postgres_database.operations_url,
                command.model_copy(update={"tenant_id": uuid4(), "slug": "second-tenant"}),
                enabled=True,
            )
    finally:
        await app.shutdown()
        app.runtime.migrations.downgrade(postgres_database.migration_url)
