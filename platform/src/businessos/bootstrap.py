"""BusinessOS composition root."""

from businessos.application import BusinessOSApplication
from businessos.config import Settings, get_settings
from businessos.dependencies import DATABASE, UNIT_OF_WORK_FACTORY
from businessos.di import Container, DependencyScope
from businessos.diagnostics import Diagnostics
from businessos.http import Router
from businessos.logging import configure_logging
from businessos.persistence import Database, SQLAlchemyUnitOfWorkFactory
from businessos.version import runtime_version


def create_application(settings: Settings | None = None) -> BusinessOSApplication:
    """Compose the protected runtime without importing business modules."""
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    router = Router()
    container = Container()
    database = Database(resolved_settings)
    unit_of_work_factory = SQLAlchemyUnitOfWorkFactory(database.sessions)
    container.register(DATABASE, lambda _: database, scope=DependencyScope.SINGLETON)
    container.register(
        UNIT_OF_WORK_FACTORY,
        lambda _: unit_of_work_factory,
        scope=DependencyScope.SINGLETON,
    )
    diagnostics = Diagnostics(resolved_settings.app_version or runtime_version())
    if resolved_settings.database_readiness_enabled:
        diagnostics.add_readiness_check("postgresql", database.readiness)
    diagnostics.register_routes(router)
    application = BusinessOSApplication(resolved_settings, router=router, container=container)
    application.on_shutdown(database.close)
    return application
