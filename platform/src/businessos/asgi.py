"""Uvicorn import target."""

from businessos.bootstrap import create_application
from businessos.modules import discover_modules

application = create_application(modules=discover_modules())
