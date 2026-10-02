"""Party adoption uses the existing exact owner/generation admission machinery."""

import json
from pathlib import Path

import pytest
from businessos_metadata import MetadataModule
from businessos_metadata.contracts import MetadataLimits
from businessos_metadata.custom_schema import PublishedSchemaReader
from businessos_party import PartyModule
from businessos_party.custom_fields import PartyRootFacts
from pydantic import ValidationError

from businessos.activation import ContributionGate
from businessos.custom_fields import PUBLISHED_CUSTOM_FIELD_SCHEMA
from businessos.di import Container
from businessos.errors import ConfigurationError, ConflictError, NotFoundError
from businessos.modules import ModuleManifest, ModuleRegistry
from businessos.modules.installation_inventory import approved_artifacts_from_operator_inventory
from businessos.resources import ResourceOwnershipRegistry


def test_exact_artifact_spoof_and_duplicate_owner_denied() -> None:
    real = PartyModule()
    inventory = json.loads(Path("tests/fixtures/approved-module-inventory.ci.json").read_text())
    grants = approved_artifacts_from_operator_inventory((real,), inventory=inventory)
    registry = ModuleRegistry(
        platform_version="0.2.0", sdk_version="0.1.0", approved_artifacts=grants
    )
    registry.add(real)
    with pytest.raises(ConflictError):
        registry.add(PartyModule())

    class FakeParty(PartyModule):
        pass

    other = ModuleRegistry(platform_version="0.2.0", sdk_version="0.1.0", approved_artifacts=grants)
    with pytest.raises(ConfigurationError):
        other.add(FakeParty())
    payload = MetadataModule().manifest.model_dump()
    payload["resource_ownership"] = real.manifest.model_dump()["resource_ownership"]
    with pytest.raises(ValidationError):
        ModuleManifest.model_validate(payload)
    with pytest.raises(ConfigurationError):
        Container().register(
            PUBLISHED_CUSTOM_FIELD_SCHEMA,
            lambda _: PublishedSchemaReader(MetadataLimits()),
            owner="foundation.party",
        )


@pytest.mark.asyncio
async def test_party_generation_disable_replacement_and_wrong_version() -> None:
    module = PartyModule()
    gate = ContributionGate()
    resources = ResourceOwnershipRegistry(gate)
    first = gate.reserve("foundation.party")
    resources.register_provider(
        module.manifest, first, "foundation.party.party", "1", "facts", PartyRootFacts()
    )
    resources.stage(module.manifest, first)
    duplicate = gate.reserve("foundation.party")
    with pytest.raises(ConflictError):
        resources.stage(module.manifest, duplicate)
    metadata = gate.reserve("foundation.metadata")
    with pytest.raises(ConfigurationError):
        resources.register_provider(
            module.manifest, metadata, "foundation.party.party", "1", "facts", PartyRootFacts()
        )
    gate.publish(first)
    old = resources.resolve_owner("foundation.party.party", "1")
    with pytest.raises(NotFoundError):
        resources.resolve_owner("foundation.party.party", "2")
    with pytest.raises(NotFoundError):
        resources.resolve_owner("foundation.party.person", "1")
    await gate.close_and_drain(first, timeout_seconds=1)
    resources.remove_owner_generation(first)
    with pytest.raises(NotFoundError):
        resources.resolve_owner("foundation.party.party", "1")
    second = gate.reserve("foundation.party")
    resources.register_provider(
        module.manifest, second, "foundation.party.party", "1", "facts", PartyRootFacts()
    )
    resources.stage(module.manifest, second)
    gate.publish(second)
    assert resources.resolve_owner("foundation.party.party", "1").generation == second
    assert not gate.is_active(old.generation)
    resources.remove_owner_generation(first)
    assert resources.resolve_owner("foundation.party.party", "1").generation == second
