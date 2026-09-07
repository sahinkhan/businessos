import asyncio
from typing import Any, ClassVar, cast
from uuid import uuid4

import httpx
import pytest

from businessos.activation import ContributionState
from businessos.bootstrap import create_application
from businessos.config import Settings
from businessos.context import RequestContext, TenantContext
from businessos.di import DependencyKey, DependencyScope
from businessos.errors import ConfigurationError, ConflictError, NotFoundError
from businessos.features import FeatureFlag
from businessos.http import Request, Response
from businessos.http.middleware import CallNext
from businessos.jobs import Job
from businessos.messages import Command, DomainEvent, HandlingContext, Query
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


class SurfaceCommand(Command):
    pass


class SurfaceQuery(Query):
    pass


class SurfaceEvent(DomainEvent):
    event_type: ClassVar[str] = "example.surface.event"


class SurfaceContract:
    version = "1"


SURFACE_DEPENDENCY = DependencyKey[str]("example.surface.dependency")


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
        self.registrations: list[ModuleRegistration] = []

    async def register(self, registration: ModuleRegistration) -> None:
        self.lifecycle.append("register")
        self.registrations.append(registration)
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


@pytest.mark.asyncio
async def test_disable_unpublishes_contributions_and_reenable_uses_new_generation() -> None:
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
    first_registration = module.registrations[-1]

    await app.runtime.lifecycle.disable(module.manifest.module_id)
    with pytest.raises(NotFoundError):
        app.runtime.permissions.get("example.proof.read")
    with pytest.raises(NotFoundError):
        app.runtime.metadata.get("example.proof.view")
    with pytest.raises(NotFoundError):
        app.runtime.features.is_enabled("example.proof.enabled")

    transport = httpx.ASGITransport(app=cast(Any, app))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        disabled = await client.get("/proof")
    assert disabled.status_code == 404

    await app.runtime.lifecycle.enable(module.manifest.module_id)
    second_registration = module.registrations[-1]
    assert second_registration.generation.number > first_registration.generation.number
    await first_registration.rollback()
    assert app.runtime.permissions.get("example.proof.read").description == "Read proof"
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        enabled = await client.get("/proof")
    assert enabled.status_code == 200

    await app.shutdown()
    await app.runtime.lifecycle.retire(module.manifest.module_id)
    assert app.runtime.modules.get(module.manifest.module_id).state is ModuleState.RETIRED
    with pytest.raises(NotFoundError):
        app.router.match("GET", "/proof")
    with pytest.raises(NotFoundError):
        app.runtime.permissions.get("example.proof.read")
    await second_registration.remove()
    with pytest.raises(ConfigurationError, match="Retired module"):
        await app.runtime.lifecycle.enable(module.manifest.module_id)


@pytest.mark.asyncio
async def test_failed_registration_rolls_back_all_staged_contributions() -> None:
    class ConflictingModule(ProofModule):
        async def register(self, registration: ModuleRegistration) -> None:
            registration.permission(
                PermissionDeclaration(key="example.conflict.read", description="Temporary")
            )

            async def endpoint(_: Request, __: object) -> Response:
                return Response.text("never")

            registration.route("GET", "/livez", endpoint, name="conflict")

    module = ConflictingModule("example.conflict", migrations=())
    app = create_application(_settings(), modules=(module,))
    with pytest.raises(ConflictError):
        await app.startup()
    assert app.runtime is not None
    assert app.runtime.modules.get(module.manifest.module_id).state is ModuleState.FAILED
    with pytest.raises(NotFoundError):
        app.runtime.permissions.get("example.conflict.read")
    assert [route.path for route in app.router.routes].count("/livez") == 1


@pytest.mark.asyncio
async def test_failed_start_rolls_back_staged_contributions_and_calls_stop() -> None:
    class FailingStartModule(ProofModule):
        async def start(self) -> None:
            self.lifecycle.append("start")
            raise RuntimeError("start failed")

    module = FailingStartModule("example.failing", migrations=())
    app = create_application(_settings(), modules=(module,))
    with pytest.raises(RuntimeError, match="start failed"):
        await app.startup()
    assert app.runtime is not None
    assert module.lifecycle == ["register", "start", "stop"]
    assert app.runtime.modules.get(module.manifest.module_id).state is ModuleState.FAILED
    with pytest.raises(NotFoundError):
        app.runtime.permissions.get("example.failing.read")


@pytest.mark.asyncio
async def test_cancelled_module_start_publishes_nothing() -> None:
    start_entered = asyncio.Event()

    class CancelledStartModule(ProofModule):
        async def start(self) -> None:
            self.lifecycle.append("start")
            start_entered.set()
            await asyncio.Event().wait()

    module = CancelledStartModule("example.cancelled", migrations=())
    app = create_application(_settings(), modules=(module,))
    startup = asyncio.create_task(app.startup())
    await start_entered.wait()
    startup.cancel()
    with pytest.raises(asyncio.CancelledError):
        await startup
    assert app.runtime is not None

    assert module.lifecycle == ["register", "start", "stop"]
    assert app.runtime.modules.get(module.manifest.module_id).state is ModuleState.FAILED
    with pytest.raises(NotFoundError):
        app.runtime.permissions.get("example.cancelled.read")
    with pytest.raises(NotFoundError):
        app.router.match("GET", "/proof")


@pytest.mark.asyncio
async def test_disable_stops_admission_then_drains_in_flight_route() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockingModule(ProofModule):
        async def register(self, registration: ModuleRegistration) -> None:
            self.lifecycle.append("register")
            self.registrations.append(registration)

            async def endpoint(_: Request, __: object) -> Response:
                entered.set()
                await release.wait()
                return Response.text("done")

            registration.route("GET", "/blocking", endpoint, name="blocking")

    module = BlockingModule("example.blocking", migrations=())
    app = create_application(_settings(), modules=(module,))
    await app.startup()
    assert app.runtime is not None
    transport = httpx.ASGITransport(app=cast(Any, app))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        in_flight = asyncio.create_task(client.get("/blocking"))
        await entered.wait()
        disabling = asyncio.create_task(app.runtime.lifecycle.disable(module.manifest.module_id))
        await asyncio.sleep(0)
        assert (
            app.runtime.contributions.state(module.registrations[-1].generation)
            is ContributionState.DRAINING
        )
        refused = await client.get("/blocking")
        assert refused.status_code == 404
        assert not disabling.done()
        release.set()
        assert (await in_flight).status_code == 200
        await disabling
    assert module.lifecycle == ["register", "start", "stop"]
    await app.shutdown()


@pytest.mark.asyncio
async def test_disable_timeout_fails_safe_and_can_finish_cleanup_on_retry() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockingModule(ProofModule):
        async def register(self, registration: ModuleRegistration) -> None:
            self.registrations.append(registration)

            async def endpoint(_: Request, __: object) -> Response:
                entered.set()
                await release.wait()
                return Response.text("done")

            registration.route("GET", "/timeout", endpoint, name="timeout")

    settings = Settings(
        environment="test",
        database_url="postgresql+psycopg://test:test@db/test",
        database_readiness_enabled=False,
        shutdown_timeout_seconds=0.01,
    )
    module = BlockingModule("example.timeout", migrations=())
    app = create_application(settings, modules=(module,))
    await app.startup()
    assert app.runtime is not None
    transport = httpx.ASGITransport(app=cast(Any, app))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        request = asyncio.create_task(client.get("/timeout"))
        await entered.wait()
        with pytest.raises(TimeoutError):
            await app.runtime.lifecycle.disable(module.manifest.module_id)
        assert app.runtime.modules.get(module.manifest.module_id).state is ModuleState.FAILED
        assert (await client.get("/timeout")).status_code == 404
        release.set()
        assert (await request).status_code == 200
        await app.runtime.lifecycle.disable(module.manifest.module_id)

    assert app.runtime.modules.get(module.manifest.module_id).state is ModuleState.DISABLED
    await app.shutdown()


@pytest.mark.asyncio
async def test_concurrent_enable_disable_is_idempotent() -> None:
    module = ProofModule("example.concurrent", migrations=())
    app = create_application(_settings(), modules=(module,))
    await app.startup()
    assert app.runtime is not None
    await asyncio.gather(
        *(app.runtime.lifecycle.disable(module.manifest.module_id) for _ in range(20))
    )
    await asyncio.gather(
        *(app.runtime.lifecycle.enable(module.manifest.module_id) for _ in range(20))
    )
    assert module.lifecycle == ["register", "start", "stop", "register", "start"]
    await app.shutdown()


@pytest.mark.asyncio
async def test_all_module_contribution_surfaces_follow_one_activation_gate() -> None:
    start_entered = asyncio.Event()
    release_start = asyncio.Event()
    events_seen = 0

    class SurfaceMiddleware:
        async def __call__(self, request: Request, call_next: CallNext) -> Response:
            response = await call_next(request)
            response.headers["x-surface-middleware"] = "active"
            return response

    class SurfaceModule(ProofModule):
        async def register(self, registration: ModuleRegistration) -> None:
            self.registrations.append(registration)
            registration.permission(
                PermissionDeclaration(key="example.surface.read", description="Read surface")
            )
            registration.metadata(
                MetadataDeclaration(
                    key="example.surface.view",
                    kind="view",
                    value={"title": "Surface"},
                )
            )
            registration.feature(
                FeatureFlag(
                    key="example.surface.enabled",
                    description="Surface enabled",
                    default=True,
                )
            )
            registration.contract("example.surface.contract", SurfaceContract())
            registration.provider("example.surface.provider", object())
            registration.dependency(
                SURFACE_DEPENDENCY,
                lambda _: "dependency",
                scope=DependencyScope.SINGLETON,
            )

            async def command(_: SurfaceCommand, __: HandlingContext) -> object:
                return "command"

            async def query(_: SurfaceQuery, __: HandlingContext) -> object:
                return "query"

            async def event(
                _: SurfaceEvent,
                __: RequestContext,
                ___: object,
            ) -> None:
                nonlocal events_seen
                events_seen += 1

            async def job(_: Job, __: RequestContext, ___: object) -> None:
                return None

            async def endpoint(_: Request, __: object) -> Response:
                return Response.text("surface")

            registration.command(SurfaceCommand, command)
            registration.query(SurfaceQuery, query)
            registration.event(SurfaceEvent, "subscriber", event)
            registration.job("example.surface.job", job)
            registration.middleware("headers", SurfaceMiddleware())
            registration.route("GET", "/surface", endpoint, name="surface")

        async def start(self) -> None:
            start_entered.set()
            await release_start.wait()

    tenant = TenantContext(uuid4(), uuid4(), uuid4(), authentication_strength="test")
    module = SurfaceModule("example.surface", migrations=())
    app = create_application(
        _settings(),
        modules=(module,),
        context_resolver=FixedContextResolver(tenant),
        authorizer=Authorizer(AllowAllPolicy()),
    )
    assert app.runtime is not None
    startup = asyncio.create_task(app.startup())
    await start_entered.wait()
    assert (
        app.runtime.contributions.state(module.registrations[-1].generation)
        is ContributionState.STAGED
    )

    with pytest.raises(NotFoundError):
        app.router.match("GET", "/surface")
    with pytest.raises(NotFoundError):
        app.runtime.contracts.get("example.surface.contract")
    with pytest.raises(NotFoundError):
        app.runtime.metadata.get("example.surface.view")
    with pytest.raises(NotFoundError):
        app.runtime.permissions.get("example.surface.read")
    with pytest.raises(NotFoundError):
        app.runtime.providers.get("example.surface.provider")
    with pytest.raises(NotFoundError):
        app.runtime.features.is_enabled("example.surface.enabled")
    with pytest.raises(NotFoundError):
        app.runtime.messages.commands.get(SurfaceCommand())
    with pytest.raises(NotFoundError):
        app.runtime.messages.queries.get(SurfaceQuery())
    with pytest.raises(NotFoundError):
        app.runtime.jobs.get("example.surface.job")
    assert app.runtime.middleware.active() == ()
    async with app.container.request_scope() as dependencies:
        with pytest.raises(ConfigurationError, match="not active"):
            await dependencies.resolve(SURFACE_DEPENDENCY)

    release_start.set()
    await startup
    assert (
        app.runtime.contributions.state(module.registrations[-1].generation)
        is ContributionState.ACTIVE
    )
    assert app.runtime.contracts.get("example.surface.contract").version == "1"
    assert app.runtime.metadata.get("example.surface.view").kind == "view"
    assert app.runtime.permissions.get("example.surface.read").description
    assert app.runtime.providers.get("example.surface.provider") is not None
    assert app.runtime.features.is_enabled("example.surface.enabled")
    command_handler = app.runtime.messages.commands.get(SurfaceCommand())
    query_handler = app.runtime.messages.queries.get(SurfaceQuery())
    job_handler = app.runtime.jobs.get("example.surface.job")
    assert command_handler.__name__ == "command"
    assert query_handler.__name__ == "query"
    assert job_handler.__name__ == "job"
    assert len(app.runtime.middleware.active()) == 1
    async with app.container.request_scope() as dependencies:
        assert await dependencies.resolve(SURFACE_DEPENDENCY) == "dependency"
        await app.runtime.events.publish(
            SurfaceEvent(
                tenant_id=tenant.tenant_id,
                correlation_id="surface",
            ),
            RequestContext(tenant=tenant),
            dependencies,
        )
    assert events_seen == 1

    transport = httpx.ASGITransport(app=cast(Any, app))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/surface")
    assert response.status_code == 200
    assert response.headers["x-surface-middleware"] == "active"

    await app.runtime.lifecycle.disable(module.manifest.module_id)
    with pytest.raises(NotFoundError):
        app.router.match("GET", "/surface")
    with pytest.raises(NotFoundError):
        app.runtime.contracts.get("example.surface.contract")
    with pytest.raises(NotFoundError):
        app.runtime.jobs.get("example.surface.job")
    assert app.runtime.middleware.active() == ()
    await app.shutdown()


@pytest.mark.asyncio
async def test_enable_sequence_rolls_back_modules_started_before_later_failure() -> None:
    class MinimalModule(ProofModule):
        async def register(self, registration: ModuleRegistration) -> None:
            self.lifecycle.append("register")
            self.registrations.append(registration)
            registration.permission(
                PermissionDeclaration(
                    key=f"{self.manifest.module_id}.read",
                    description="Read minimal module",
                )
            )

    first = MinimalModule("example.first", migrations=())

    class FailingModule(MinimalModule):
        async def start(self) -> None:
            self.lifecycle.append("start")
            raise RuntimeError("later module failed")

    second = FailingModule("example.second", migrations=())
    app = create_application(_settings(), modules=(first, second))
    with pytest.raises(RuntimeError, match="later module failed"):
        await app.startup()
    assert app.runtime is not None

    assert first.lifecycle == ["register", "start", "stop"]
    assert first.registrations[0].generation.number == 1
    assert app.runtime.modules.get("example.first").state is ModuleState.DISABLED
    with pytest.raises(NotFoundError):
        app.runtime.permissions.get("example.first.read")


@pytest.mark.asyncio
async def test_retire_rejects_enabled_dependents() -> None:
    class MinimalModule(ProofModule):
        async def register(self, registration: ModuleRegistration) -> None:
            self.lifecycle.append("register")
            self.registrations.append(registration)

    foundation = MinimalModule("example.foundation", migrations=())
    dependent = MinimalModule(
        "example.dependent",
        dependencies=(ModuleDependency(module_id="example.foundation", version=">=1"),),
        migrations=(),
    )
    app = create_application(_settings(), modules=(foundation, dependent))
    await app.startup()
    assert app.runtime is not None

    with pytest.raises(ConfigurationError, match="enabled dependents"):
        await app.runtime.lifecycle.disable("example.foundation")
    with pytest.raises(ConfigurationError, match="enabled dependents"):
        await app.runtime.lifecycle.retire("example.foundation")
    assert app.runtime.modules.get("example.foundation").state is ModuleState.ENABLED
    await app.shutdown()
