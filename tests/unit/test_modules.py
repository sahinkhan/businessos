from typing import Any, cast
from uuid import uuid4

import httpx
import pytest

from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.context import RequestContext, TenantContext
from businessos.errors import ConfigurationError, ConflictError
from businessos.features import FeatureFlag
from businessos.http import Request, Response
from businessos.metadata import MetadataDeclaration
from businessos.modules import (
    ModuleDependency,
    ModuleManifest,
    ModuleRegistration,
    ModuleRegistry,
    ModuleState,
)
from businessos.permissions import PermissionDeclaration
from businessos.security import Authorizer, RequestIdentity


class AllowAllPolicy:
    async def is_allowed(
        self, principal_id: object, tenant: TenantContext, permission: str
    ) -> bool:
        return True


class FixedContextResolver:
    def __init__(self, tenant: TenantContext) -> None:
        self._tenant = tenant

    async def resolve(self, identity: RequestIdentity) -> RequestContext:
        return RequestContext(
            correlation_id=identity.correlation_id,
            trace_id=identity.trace_id,
            tenant=self._tenant,
        )


class ProofModule:
    def __init__(
        self,
        module_id: str = "example.proof",
        *,
        dependencies: tuple[ModuleDependency, ...] = (),
        version: str = "1.0.0",
        migrations: tuple[str, ...] = ("migrations/v1",),
        migration_namespace: str | None = "example_proof",
    ) -> None:
        self.manifest = ModuleManifest(
            module_id=module_id,
            name=module_id,
            publisher="example",
            version=version,
            platform=">=0.1,<1",
            sdk=">=0.1,<1",
            python=">=3.13",
            entry_point="proof:module",
            dependencies=dependencies,
            migrations=migrations,
            migration_namespace=migration_namespace if migrations else None,
        )
        self.lifecycle: list[str] = []

    async def register(self, registration: ModuleRegistration) -> None:
        self.lifecycle.append("register")
        registration.permission(
            PermissionDeclaration(key=f"{self.manifest.module_id}.read", description="Read proof")
        )
        registration.metadata(
            MetadataDeclaration(
                key=f"{self.manifest.module_id}.view",
                kind="view",
                value={"title": "Proof"},
            )
        )
        registration.feature(
            FeatureFlag(
                key=f"{self.manifest.module_id}.enabled",
                description="Enable proof module",
                default=True,
            )
        )

        async def endpoint(request: Request, _: object) -> Response:
            assert request.context.tenant is not None
            return Response.json({"tenant_id": str(request.context.tenant.tenant_id)})

        registration.route(
            "GET",
            "/proof",
            endpoint,
            name="read",
            permission=f"{self.manifest.module_id}.read",
        )

    async def start(self) -> None:
        self.lifecycle.append("start")

    async def stop(self) -> None:
        self.lifecycle.append("stop")


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://test:test@db/test",
        database_readiness_enabled=False,
    )


@pytest.mark.asyncio
async def test_module_lifecycle_registries_permissions_and_upgrade_plan() -> None:
    tenant = TenantContext(uuid4(), uuid4(), uuid4(), authentication_strength="test")
    module = ProofModule()
    app = create_application(
        _settings(),
        modules=(module,),
        context_resolver=FixedContextResolver(tenant),
        authorizer=Authorizer(AllowAllPolicy()),
    )

    await app.startup()
    assert app.runtime is not None
    assert app.runtime.modules.get("example.proof").state is ModuleState.ENABLED
    assert app.runtime.permissions.get("example.proof.read").description == "Read proof"
    assert app.runtime.metadata.get("example.proof.view").kind == "view"
    assert app.runtime.features.is_enabled("example.proof.enabled")

    transport = httpx.ASGITransport(app=cast(Any, app))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/proof")
        diagnostics = await client.get("/diagnostics/modules")
    assert response.status_code == 200
    assert response.json() == {"tenant_id": str(tenant.tenant_id)}
    assert diagnostics.json() == {
        "modules": [
            {
                "module_id": "example.proof",
                "version": "1.0.0",
                "state": "enabled",
                "error": None,
            }
        ]
    }

    target = module.manifest.model_copy(
        update={"version": "2.0.0", "migrations": ("migrations/v1", "migrations/v2")}
    )
    plan = app.runtime.upgrades.plan((target,))
    assert plan.ordered_module_ids == ("example.proof",)
    assert plan.migration_locations[-1] == ("example.proof", "migrations/v2")

    await app.shutdown()
    assert module.lifecycle == ["register", "start", "stop"]
    assert app.runtime.modules.get("example.proof").state is ModuleState.DISABLED


def test_module_registry_rejects_missing_and_circular_dependencies() -> None:
    registry = ModuleRegistry(platform_version="0.1.0", sdk_version="0.1.0")
    registry.add(
        ProofModule(
            "example.a",
            dependencies=(ModuleDependency(module_id="example.missing", version=">=1"),),
        )
    )
    with pytest.raises(ConfigurationError, match="missing module"):
        registry.ordered()

    circular = ModuleRegistry(platform_version="0.1.0", sdk_version="0.1.0")
    circular.add(
        ProofModule(
            "example.a",
            dependencies=(ModuleDependency(module_id="example.b", version=">=1"),),
        )
    )
    circular.add(
        ProofModule(
            "example.b",
            dependencies=(ModuleDependency(module_id="example.a", version=">=1"),),
        )
    )
    with pytest.raises(ConfigurationError, match="Circular"):
        circular.ordered()


def test_module_registry_rejects_duplicate_and_incompatible_modules() -> None:
    registry = ModuleRegistry(platform_version="0.1.0", sdk_version="0.1.0")
    module = ProofModule()
    registry.add(module)
    with pytest.raises(ConflictError, match="already registered"):
        registry.add(module)

    incompatible = ProofModule()
    incompatible.manifest = incompatible.manifest.model_copy(update={"python": ">=99"})
    other = ModuleRegistry(platform_version="0.1.0", sdk_version="0.1.0")
    with pytest.raises(ConfigurationError, match="incompatible"):
        other.add(incompatible)


@pytest.mark.asyncio
async def test_protected_route_denies_anonymous_request() -> None:
    module = ProofModule()
    app = create_application(_settings(), modules=(module,))
    await app.startup()
    transport = httpx.ASGITransport(app=cast(Any, app))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/proof")
    await app.shutdown()

    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"
