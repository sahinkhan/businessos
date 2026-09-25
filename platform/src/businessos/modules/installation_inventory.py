"""Read protected operator installation grants, independent of module manifests.

The path is supplied by deployment, never by a module, tenant, or HTTP request.
An omitted inventory grants no resource ownership.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import cast

from businessos.errors import ConfigurationError
from businessos.modules.artifact import ApprovedModuleArtifact
from businessos.modules.sdk import BusinessOSModule

INVENTORY_ENV = "BOS_APPROVED_MODULE_INVENTORY"


def approved_artifacts_from_operator_inventory(
    modules: Iterable[BusinessOSModule],
    path: str | None = None,
    *,
    inventory: object | None = None,
) -> Mapping[str, ApprovedModuleArtifact]:
    if inventory is None:
        inventory = read_operator_inventory(path)
    if inventory is None:
        return {}
    if type(inventory) is not dict:
        raise ConfigurationError("Protected installation inventory has an invalid schema")
    inventory_values = cast(dict[str, object], inventory)
    if set(inventory_values) != {"approved_modules"}:
        raise ConfigurationError("Protected installation inventory has an invalid schema")
    entries = inventory_values["approved_modules"]
    if type(entries) is not list:
        raise ConfigurationError("Protected installation grants must be a list")
    entry_values = cast(list[object], entries)
    module_list = tuple(modules)
    loaded = {module.manifest.module_id: module for module in module_list}
    if len(loaded) != len(module_list):
        raise ConfigurationError("Loaded module IDs are duplicated")
    grants: dict[str, ApprovedModuleArtifact] = {}
    seen_ids: set[str] = set()
    required = {
        "module_id",
        "publisher",
        "package_identity",
        "loaded_type",
        "install_identity",
        "first_party",
        "approved_aliases",
    }
    for raw in entry_values:
        if type(raw) is not dict:
            raise ConfigurationError("Protected installation grant has an invalid schema")
        values = cast(dict[str, object], raw)
        if set(values) != required:
            raise ConfigurationError("Protected installation grant has an invalid schema")
        if any(
            type(values[key]) is not str or not values[key]
            for key in required - {"first_party", "approved_aliases"}
        ):
            raise ConfigurationError("Protected installation grant identity is invalid")
        if type(values["first_party"]) is not bool or type(values["approved_aliases"]) is not list:
            raise ConfigurationError("Protected installation grant approvals are invalid")
        module_id = cast(str, values["module_id"])
        if module_id in seen_ids:
            raise ConfigurationError("Protected installation grant is duplicated")
        seen_ids.add(module_id)
        module = loaded.get(module_id)
        if module is None:
            continue
        aliases: set[tuple[str, str, str]] = set()
        for alias in cast(list[object], values["approved_aliases"]):
            if type(alias) is not list:
                raise ConfigurationError("Protected alias approval is invalid")
            alias_items = cast(list[object], alias)
            if len(alias_items) != 3 or any(
                type(value) is not str or not value for value in alias_items
            ):
                raise ConfigurationError("Protected alias approval is invalid")
            alias_parts = cast(list[str], alias_items)
            aliases.add((alias_parts[0], alias_parts[1], alias_parts[2]))
        grant = ApprovedModuleArtifact(
            loaded_module=module,
            module_id=module_id,
            publisher=cast(str, values["publisher"]),
            package_identity=cast(str, values["package_identity"]),
            loaded_type=cast(str, values["loaded_type"]),
            install_identity=cast(str, values["install_identity"]),
            first_party=values["first_party"],
            approved_aliases=frozenset(aliases),
        )
        grant.verify(module, module.manifest)
        grants[module_id] = grant
    return grants


def read_operator_inventory(path: str | None = None) -> object | None:
    """Capture protected deployment input before loading executable modules."""
    location = path if path is not None else os.environ.get(INVENTORY_ENV)
    if not location:
        return None
    try:
        return cast(object, json.loads(Path(location).read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise ConfigurationError("Protected installation inventory cannot be read") from exc
