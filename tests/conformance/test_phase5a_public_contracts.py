"""Public Metadata contracts are versioned without leaking persistence models."""

from businessos_metadata import MetadataModule
from businessos_metadata.contracts import (
    BulkReferenceRequest,
    DefinitionIdentity,
    DefinitionSnapshot,
    PublicationResult,
    PublishPreflight,
    RevisionRecord,
)


def test_phase5a_manifest_advertises_versioned_public_contracts() -> None:
    module = MetadataModule()
    assert {(item.contract_id, item.version) for item in module.manifest.public_contracts} == {
        ("foundation.metadata.definition", "1.0"),
        ("foundation.metadata.publication", "1.0"),
        ("foundation.metadata.reference-resolution", "1.0"),
        ("foundation.metadata.published-custom-field-schema.v1", "1.0"),
        ("foundation.metadata.custom-entity.v1", "1.0"),
        ("foundation.metadata.custom-entity-query.v1", "1.0"),
    }
    for contract in (
        DefinitionIdentity,
        DefinitionSnapshot,
        RevisionRecord,
        PublishPreflight,
        PublicationResult,
        BulkReferenceRequest,
    ):
        assert contract.__module__ == "businessos_metadata.contracts"
