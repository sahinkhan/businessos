"""Uvicorn import target."""

from businessos.bootstrap import configured_infrastructure_providers, create_application
from businessos.config import get_settings
from businessos.modules import discover_context_resolver_factory, discover_modules

settings = get_settings()
application = create_application(
    settings,
    modules=discover_modules(),
    context_resolver_factory=discover_context_resolver_factory(),
    infrastructure_providers=configured_infrastructure_providers(settings),
)
