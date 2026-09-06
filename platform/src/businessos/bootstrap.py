"""BusinessOS composition root."""

from businessos.application import BusinessOSApplication
from businessos.config import Settings, get_settings
from businessos.di import Container
from businessos.diagnostics import Diagnostics
from businessos.http import Router
from businessos.logging import configure_logging
from businessos.version import runtime_version


def create_application(settings: Settings | None = None) -> BusinessOSApplication:
    """Compose the protected runtime without importing business modules."""
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    router = Router()
    container = Container()
    diagnostics = Diagnostics(resolved_settings.app_version or runtime_version())
    diagnostics.register_routes(router)
    return BusinessOSApplication(resolved_settings, router=router, container=container)
