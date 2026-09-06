import asyncio
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
from businessos_proof import ProofModule

from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.context import RequestContext, TenantContext
from businessos.dependencies import OBJECT_STORAGE
from businessos.di import DependencyScope
from businessos.modules import ModuleState, discover_modules
from businessos.security import Authorizer, RequestIdentity


class InMemoryObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[tuple[UUID, str], bytes] = {}

    async def put(self, tenant_id: UUID, key: str, content: bytes) -> None:
        self.objects[(tenant_id, key)] = content

    async def get(self, tenant_id: UUID, key: str) -> bytes:
        return self.objects[(tenant_id, key)]

    async def readiness(self) -> None:
        return None


class AllowAllPolicy:
    async def is_allowed(self, principal_id: UUID, tenant: TenantContext, permission: str) -> bool:
        return True


class FixedContextResolver:
    def __init__(self, tenant: TenantContext) -> None:
        self.tenant = tenant

    async def resolve(self, identity: RequestIdentity) -> RequestContext:
        return RequestContext(
            correlation_id=identity.correlation_id,
            trace_id=identity.trace_id,
            tenant=self.tenant,
        )


def _settings(database_url: str) -> Settings:
    return Settings(environment="test", database_url=database_url, database_pool_size=2)


@pytest.mark.integration
@pytest.mark.postgres
def test_external_module_owns_replayable_v1_to_v2_migrations(
    postgres_database_url: str,
    postgres_migration_database_url: str,
) -> None:
    module = ProofModule()
    app = create_application(_settings(postgres_database_url), modules=(module,))
    assert app.runtime is not None

    app.runtime.migrations.upgrade(postgres_migration_database_url, "proof_0001")
    connection_url = postgres_migration_database_url.replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    with psycopg.connect(connection_url) as connection:
        columns_v1 = connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'mod_example_phase1_proof' "
            "AND table_name = 'proof_records' ORDER BY ordinal_position"
        ).fetchall()
    assert [row[0] for row in columns_v1] == ["id", "tenant_id", "value"]

    app.runtime.migrations.upgrade(postgres_migration_database_url)
    with psycopg.connect(connection_url) as connection:
        columns_v2 = connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'mod_example_phase1_proof' "
            "AND table_name = 'proof_records' ORDER BY ordinal_position"
        ).fetchall()
        policies = connection.execute(
            "SELECT policyname FROM pg_policies "
            "WHERE schemaname = 'mod_example_phase1_proof' AND tablename = 'proof_records'"
        ).fetchall()
    assert [row[0] for row in columns_v2] == ["id", "tenant_id", "value", "description"]
    assert policies == [("proof_records_tenant_isolation",)]

    app.runtime.migrations.downgrade(postgres_migration_database_url)
    app.runtime.migrations.upgrade(postgres_migration_database_url)
    app.runtime.migrations.downgrade(postgres_migration_database_url)


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.asyncio
async def test_external_module_conforms_without_protected_core_edits(
    postgres_database_url: str,
    postgres_migration_database_url: str,
) -> None:
    discovered = tuple(module for module in discover_modules() if isinstance(module, ProofModule))
    assert len(discovered) == 1
    module = discovered[0]
    tenant = TenantContext(uuid4(), uuid4(), uuid4(), authentication_strength="test")
    storage = InMemoryObjectStorage()
    app = create_application(
        _settings(postgres_database_url),
        modules=(module,),
        context_resolver=FixedContextResolver(tenant),
        authorizer=Authorizer(AllowAllPolicy()),
    )
    assert app.runtime is not None
    await asyncio.to_thread(app.runtime.migrations.upgrade, postgres_migration_database_url)
    app.container.register(
        OBJECT_STORAGE,
        lambda _: storage,
        scope=DependencyScope.SINGLETON,
    )

    await app.startup()
    assert app.runtime.modules.get(module.manifest.module_id).state is ModuleState.ENABLED
    transport = httpx.ASGITransport(app=cast(Any, app))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        stored = await client.post("/proof/value", json={"value": "external-module"})
        loaded = await client.get("/proof/value")
        invalid = await client.post("/proof/value", json={})

    assert stored.status_code == 202
    assert stored.json() == {"stored": True}
    assert loaded.status_code == 200
    assert loaded.json() == {"value": "external-module"}
    assert invalid.status_code == 422
    assert module.events_consumed == 1
    assert storage.objects[(tenant.tenant_id, "phase1-proof/value.txt")] == b"external-module"
    assert app.runtime.metadata.get("example.phase1-proof.form").version == 2
    assert app.runtime.permissions.get("example.phase1-proof.write").description

    connection_url = postgres_migration_database_url.replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    with psycopg.connect(connection_url) as connection:
        outbox_count = connection.execute(
            "SELECT count(*) FROM eventing.outbox_messages WHERE tenant_id = %s",
            (tenant.tenant_id,),
        ).fetchone()
    assert outbox_count == (1,)

    plan = app.runtime.upgrades.plan((module.manifest,))
    assert plan.ordered_module_ids == (module.manifest.module_id,)
    assert plan.migration_locations == ((module.manifest.module_id, module.manifest.migrations[0]),)

    await app.shutdown()
    await app.runtime.lifecycle.retire(module.manifest.module_id)
    assert app.runtime.modules.get(module.manifest.module_id).state is ModuleState.REMOVED
    await asyncio.to_thread(app.runtime.migrations.downgrade, postgres_migration_database_url)
