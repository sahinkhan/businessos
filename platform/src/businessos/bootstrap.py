"""BusinessOS composition root."""

from collections.abc import Iterable

from businessos.application import BusinessOSApplication
from businessos.config import Settings, get_settings
from businessos.contracts import ContractRegistry
from businessos.dependencies import AUTHORIZER, DATABASE, MESSAGE_DISPATCHER, UNIT_OF_WORK_FACTORY
from businessos.di import Container, DependencyScope
from businessos.diagnostics import Diagnostics
from businessos.features import FeatureFlagRegistry
from businessos.http import Router
from businessos.logging import configure_logging
from businessos.messages import EventBus, MessageDispatcher
from businessos.metadata import MetadataRegistry
from businessos.migrations import MigrationCoordinator
from businessos.modules import (
    BusinessOSModule,
    LifecycleManager,
    ModuleRegistration,
    ModuleRegistry,
    UpgradeCoordinator,
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
) -> BusinessOSApplication:
    """Compose the protected runtime without importing business modules."""
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    version = resolved_settings.app_version or runtime_version()
    configure_telemetry(service_name="businessos", service_version=version)
    router = Router()
    container = Container()
    database = Database(resolved_settings)
    unit_of_work_factory = SQLAlchemyUnitOfWorkFactory(database.sessions)
    event_bus = EventBus()
    message_dispatcher = MessageDispatcher(unit_of_work_factory, event_bus)
    resolved_authorizer = authorizer or Authorizer(DenyAllPolicyEvaluator())
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
    contracts = ContractRegistry()
    metadata = MetadataRegistry()
    permissions = PermissionRegistry()
    providers = ProviderRegistry()
    features = FeatureFlagRegistry()
    module_registry = ModuleRegistry(platform_version="0.1.0", sdk_version="0.1.0")
    for module in modules:
        module_registry.add(module)

    runtime_placeholder: dict[str, FrameworkRuntime] = {}

    def registration(owner: str) -> ModuleRegistration:
        return runtime_placeholder["runtime"].registration(owner)

    lifecycle = LifecycleManager(module_registry, registration)
    upgrades = UpgradeCoordinator(module_registry)
    migrations = MigrationCoordinator(module_registry)
    runtime = FrameworkRuntime(
        router=router,
        container=container,
        contracts=contracts,
        metadata=metadata,
        permissions=permissions,
        providers=providers,
        features=features,
        events=event_bus,
        messages=message_dispatcher,
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
    diagnostics.register_routes(router)
    application = BusinessOSApplication(
        resolved_settings,
        router=router,
        container=container,
        runtime=runtime,
        context_resolver=context_resolver,
    )
    application.on_startup(lifecycle.install_all)
    application.on_startup(lifecycle.enable_all)
    application.on_shutdown(database.close)
    application.on_shutdown(lifecycle.disable_all)
    return application
