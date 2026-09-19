"""Uvicorn import target."""

from businessos.bootstrap import configured_infrastructure_providers, create_application
from businessos.config import get_settings
from businessos.modules import discover_modules

settings = get_settings()
application = create_application(
    settings,
    modules=discover_modules(),
    infrastructure_providers=configured_infrastructure_providers(settings),
)
