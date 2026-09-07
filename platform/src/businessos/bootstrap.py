"""BusinessOS composition root."""

from collections.abc import Callable, Iterable, Mapping
from typing import cast

from businessos.activation import ContributionGate
from businessos.application import BusinessOSApplication
from businessos.config import Settings, get_settings
from businessos.contracts import ContractRegistry
from businessos.dependencies import (
    AUTHORIZER,
    CACHE,
    DATABASE,
    EVENT_PUBLISHER,
    MESSAGE_DISPATCHER,
    OBJECT_STORAGE,
    UNIT_OF_WORK_FACTORY,
)
from businessos.di import Container, DependencyKey, DependencyResolver, DependencyScope
from businessos.diagnostics import Diagnostics
from businessos.eventing import DurableEventConsumer
from businessos.features import FeatureFlagRegistry
from businessos.http import Router
from businessos.http.middleware import MiddlewareRegistry
from businessos.jobs import JobHandlerRegistry
from businessos.logging import configure_logging
from businessos.messages import EventBus, MessageDispatcher
from businessos.metadata import MetadataRegistry
from businessos.migrations import MigrationCoordinator
from businessos.modules import (
    BusinessOSModule,
    LifecycleManager,
    ModuleRegistry,
    RegistrationController,
    UpgradeCoordinator,
    discover_modules,
)
from businessos.permissions import PermissionRegistry
from businessos.persistence import Database, SQLAlchemyUnitOfWorkFactory
from businessos.providers import ProviderRegistry
from businessos.runtime import FrameworkRuntime
from businessos.security import Authorizer, DenyAllPolicyEvaluator, TrustedContextResolver
from businessos.telemetry import configure_telemetry
from businessos.version import runtime_version


def create_application(
    settings: Settings | None = None,
    *,
    modules: Iterable[BusinessOSModule] = (),
    context_resolver: TrustedContextResolver | None = None,
    authorizer: Authorizer | None = None,
    infrastructure_providers: Mapping[str, object] | None = None,
) -> BusinessOSApplication:
    """Compose the protected runtime without importing business modules."""
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    version = resolved_settings.app_version or runtime_version()
    configure_telemetry(service_name="businessos", service_version=version)
    contributions = ContributionGate()
    router = Router(contributions)
    middleware = MiddlewareRegistry(contributions)
    container = Container()
    database = Database(resolved_settings)
    unit_of_work_factory = SQLAlchemyUnitOfWorkFactory(
        database.sessions, tenant_sessions=database.sessions_for_tenant
    )
    resolved_authorizer = authorizer or Authorizer(DenyAllPolicyEvaluator())
    event_bus = EventBus(contributions, resolved_authorizer)
    message_dispatcher = MessageDispatcher(
        unit_of_work_factory,
        event_bus,
        contributions,
        resolved_authorizer,
    )
    event_consumer = DurableEventConsumer(unit_of_work_factory, event_bus)
    container.register(DATABASE, lambda _: database, scope=DependencyScope.SINGLETON)
    container.register(
        UNIT_OF_WORK_FACTORY,
        lambda _: unit_of_work_factory,
        scope=DependencyScope.SINGLETON,
    )
    container.register(AUTHORIZER, lambda _: resolved_authorizer, scope=DependencyScope.SINGLETON)
    container.register(
        MESSAGE_DISPATCHER,
        lambda _: message_dispatcher,
        scope=DependencyScope.SINGLETON,
    )
    contracts = ContractRegistry(contributions)
    metadata = MetadataRegistry(contributions)
    permissions = PermissionRegistry(contributions)
    providers = ProviderRegistry(contributions)
    provider_dependencies = {
        "cache": cast(DependencyKey[object], CACHE),
        "event-publisher": cast(DependencyKey[object], EVENT_PUBLISHER),
        "object-storage": cast(DependencyKey[object], OBJECT_STORAGE),
    }

    def dependency_provider(value: object) -> Callable[[DependencyResolver], object]:
        def provide(_: DependencyResolver) -> object:
            return value

        return provide

    for capability, provider in sorted((infrastructure_providers or {}).items()):
        providers.register(capability, "businessos.infrastructure", provider)
        dependency = provider_dependencies.get(capability)
        if dependency is not None:
            container.register(
                dependency,
                dependency_provider(provider),
                scope=DependencyScope.SINGLETON,
            )
    features = FeatureFlagRegistry(contributions)
    jobs = JobHandlerRegistry(contributions, resolved_authorizer)
    module_registry = ModuleRegistry(platform_version="0.2.0", sdk_version="0.2.0")
    for module in modules:
        module_registry.add(module)

    runtime_placeholder: dict[str, FrameworkRuntime] = {}

    def registration(owner: str) -> RegistrationController:
        return runtime_placeholder["runtime"].registration(owner)

    lifecycle = LifecycleManager(
        module_registry,
        registration,
        providers=providers,
        drain_timeout_seconds=resolved_settings.shutdown_timeout_seconds,
        disabled_modules=frozenset(resolved_settings.disabled_modules),
    )
    upgrades = UpgradeCoordinator(module_registry)
    migrations = MigrationCoordinator(module_registry)
    runtime = FrameworkRuntime(
        contributions=contributions,
        router=router,
        middleware=middleware,
        container=container,
        contracts=contracts,
        metadata=metadata,
        permissions=permissions,
        providers=providers,
        features=features,
        events=event_bus,
        event_consumer=event_consumer,
        messages=message_dispatcher,
        jobs=jobs,
        modules=module_registry,
        lifecycle=lifecycle,
        upgrades=upgrades,
        migrations=migrations,
    )
    runtime_placeholder["runtime"] = runtime
    diagnostics = Diagnostics(
        version,
        module_snapshot=lambda: tuple(
            {
                "module_id": registered.module.manifest.module_id,
                "version": registered.module.manifest.version,
                "state": registered.state.value,
                "error": registered.error,
            }
            for registered in module_registry.entries()
        ),
    )
    if resolved_settings.database_readiness_enabled:
        diagnostics.add_readiness_check("postgresql", database.readiness)
    for capability in sorted(infrastructure_providers or {}):

        async def provider_readiness(name: str = capability) -> None:
            await providers.readiness(name)

        diagnostics.add_readiness_check(f"provider:{capability}", provider_readiness)
    diagnostics.register_routes(router)
    application = BusinessOSApplication(
        resolved_settings,
        router=router,
        container=container,
        runtime=runtime,
        context_resolver=context_resolver,
    )

    async def start_modules() -> None:
        await lifecycle.install_all()
        await lifecycle.enable_all()

    application.add_lifecycle(
        "providers",
        providers.start_infrastructure,
        providers.close_infrastructure,
    )
    application.add_lifecycle("modules", start_modules, lifecycle.disable_all)
    application.on_shutdown(database.close)
    diagnostics.add_readiness_check("application", application.readiness)
    return application


def create_installed_application() -> BusinessOSApplication:
    """Production composition: discover installed packages and operator-owned adapters."""
    from importlib import import_module

    from businessos.errors import ConfigurationError
    from businessos.providers import RedisCacheProvider, S3ObjectStorageProvider
    from businessos.security import PolicyEvaluator

    failed = False
    try:
        settings = get_settings()
        providers: dict[str, object] = {}
        if settings.redis_url:
            providers["cache"] = RedisCacheProvider(settings.redis_url)
        if settings.s3_bucket:
            providers["object-storage"] = S3ObjectStorageProvider(
                bucket=settings.s3_bucket,
                endpoint_url=settings.s3_endpoint_url,
                access_key=settings.s3_access_key,
                secret_key=settings.s3_secret_key,
                provision_bucket=settings.s3_provision_bucket,
            )

        def adapter(path: str) -> object:
            module_name, factory_name = path.split(":", 1)
            factory = getattr(import_module(module_name), factory_name)
            return cast(object, factory())

        resolver = (
            cast(TrustedContextResolver, adapter(settings.context_resolver_factory))
            if settings.context_resolver_factory
            else None
        )
        authorizer = (
            Authorizer(cast(PolicyEvaluator, adapter(settings.policy_evaluator_factory)))
            if settings.policy_evaluator_factory
            else None
        )
        application = create_application(
            settings,
            modules=discover_modules(),
            context_resolver=resolver,
            authorizer=authorizer,
            infrastructure_providers=providers,
        )
    except Exception:
        failed = True
    if failed:
        raise ConfigurationError("Installed runtime configuration or module composition failed")
    return application
