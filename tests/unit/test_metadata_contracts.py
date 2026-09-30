"""Bounded, non-executable Phase 5A public contract validation."""

from uuid import uuid4

import pytest
from businessos_metadata.contracts import (
    BulkReferenceRequest,
    CanonicalResourceReference,
    DefinitionSnapshot,
    FieldDefinition,
    FieldType,
    MetadataLimits,
    ReferenceResolution,
    ReferenceState,
    require_referenceable,
)
from pydantic import ValidationError


def _field(name: str = "custom_code") -> FieldDefinition:
    return FieldDefinition(field_id=uuid4(), name=name, value_type=FieldType.TEXT, max_length=64)


def test_snapshot_is_versioned_bounded_and_digest_is_stable() -> None:
    snapshot = DefinitionSnapshot(kind="field_set", fields=(_field(),))
    assert len(snapshot.digest()) == 64
    assert (
        snapshot.digest()
        == DefinitionSnapshot.model_validate(snapshot.model_dump(mode="json")).digest()
    )
    snapshot.validate_limits(MetadataLimits())
    two_fields = DefinitionSnapshot(kind="field_set", fields=(_field("a"), _field("b")))
    with pytest.raises(ValueError, match="count quota"):
        two_fields.validate_limits(MetadataLimits(max_fields=1))
    large = DefinitionSnapshot(
        kind="field_set", fields=tuple(_field(f"f_{index}") for index in range(20))
    )
    with pytest.raises(ValueError, match="byte quota"):
        large.validate_limits(MetadataLimits(max_document_bytes=1024))


def test_contract_rejects_executable_and_protected_shapes() -> None:
    with pytest.raises(ValidationError):
        FieldDefinition.model_validate(
            {"field_id": str(uuid4()), "name": "tenant_id", "value_type": "text"}
        )
    with pytest.raises(ValidationError):
        FieldDefinition.model_validate(
            {"field_id": str(uuid4()), "name": "x", "value_type": "python"}
        )
    with pytest.raises(ValidationError):
        DefinitionSnapshot.model_validate(
            {
                "kind": "field_set",
                "fields": [_field().model_dump(mode="json")],
                "script": "__import__('os').system('true')",
            }
        )
    with pytest.raises(ValidationError):
        DefinitionSnapshot.model_validate(
            {
                "kind": "field_set",
                "fields": [_field().model_dump(mode="json")],
                "rules": [{"left_field": "custom_code", "comparison": "sql", "right_literal": "1"}],
            }
        )
    with pytest.raises(ValidationError):
        DefinitionSnapshot.model_validate(
            {
                "kind": "field_set",
                "fields": [_field().model_dump(mode="json")],
                "nested": {"x": {"y": []}},
            }
        )


def test_reference_bulk_is_tenant_bound_and_retirement_fails_new_writes() -> None:
    tenant = uuid4()
    reference = CanonicalResourceReference(
        tenant_id=tenant,
        resource_namespace="foundation.party.person",
        contract_version="1",
        record_id=uuid4(),
    )
    request = BulkReferenceRequest(tenant_id=tenant, references=(reference,))
    assert request.references == (reference,)
    require_referenceable(
        ReferenceResolution(
            reference=reference, state=ReferenceState.AVAILABLE, referenceable=True
        ),
        tenant,
    )
    with pytest.raises(ValueError, match="referenceable"):
        require_referenceable(
            ReferenceResolution(
                reference=reference, state=ReferenceState.RETIRED, referenceable=False
            ),
            tenant,
        )
    with pytest.raises(ValidationError):
        BulkReferenceRequest(tenant_id=uuid4(), references=(reference,))
    with pytest.raises(ValidationError):
        BulkReferenceRequest(tenant_id=tenant, references=(reference,) * 101)
    with pytest.raises(ValidationError):
        ReferenceResolution(
            reference=reference, state=ReferenceState.UNAVAILABLE, referenceable=True
        )
