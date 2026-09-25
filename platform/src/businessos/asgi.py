"""Uvicorn import target."""

from businessos.bootstrap import configured_infrastructure_providers, create_application
from businessos.config import get_settings
from businessos.modules import discover_context_resolver_factory, discover_modules
from businessos.modules.installation_inventory import (
    approved_artifacts_from_operator_inventory,
    read_operator_inventory,
)

operator_inventory = read_operator_inventory()
loaded_modules = tuple(discover_modules())
settings = get_settings()
application = create_application(
    settings,
    modules=loaded_modules,
    context_resolver_factory=discover_context_resolver_factory(),
    infrastructure_providers=configured_infrastructure_providers(settings),
    approved_module_artifacts=approved_artifacts_from_operator_inventory(
        loaded_modules, inventory=operator_inventory
    ),
    resource_coordinator_ids=frozenset({"foundation.data_governance"}),
)
