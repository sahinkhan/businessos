"""Canonical Phase 5A grammar reuse and bounded Phase 5B public contracts."""

import json
from dataclasses import FrozenInstanceError
from typing import Any
from uuid import uuid4

import pytest
from businessos_metadata.contracts import (
    DefinitionSnapshot,
    FieldDefinition,
    MetadataLimits,
    ValidationRule,
)
from businessos_metadata.custom_schema import _PublishedSchema
from businessos_party import PartyModule
from businessos_party.custom_fields import PARTY_CUSTOMIZABLE, WritePartyCustomValues
from pydantic import ValidationError

from businessos.custom_fields import CustomFieldValue, CustomSchemaPin
from businessos.errors import BusinessOSError, ConfigurationError
from businessos.modules import ModuleRegistry


def _schema(field: FieldDefinition, **limits: Any) -> _PublishedSchema:
    snapshot = DefinitionSnapshot(kind="field_set", fields=(field,))
    return _PublishedSchema(
        CustomSchemaPin(uuid4(), uuid4(), snapshot.digest()), snapshot, MetadataLimits(**limits)
    )


@pytest.mark.parametrize(
    ("kind", "valid", "invalid", "attributes"),
    [
        ("text", "hello", 7, {"max_length": 10}),
        ("long_text", "hello", [], {"max_length": 10}),
        ("integer", 42, True, {}),
        ("boolean", False, 0, {}),
        ("decimal", "12.50", 12.5, {"precision": 4, "scale": 2}),
        (
            "money",
            {"amount": "12.50", "currency": "USD"},
            {"amount": "12.50", "currency": "usd"},
            {"precision": 4, "scale": 2},
        ),
        ("enum", "open", "closed", {"enum_choices": ["open", "pending"]}),
        ("uuid", "12345678-1234-1234-1234-123456789012", "bad", {}),
        ("date", "2026-10-02", "2026-02-30", {}),
        ("instant", "2026-10-02T12:00:00+06:00", "2026-10-02T12:00:00", {}),
        ("email", "a@example.test", "invalid", {}),
        ("phone", "+880 123456789", "no number", {}),
        ("url", "https://example.test/path", "javascript:alert(1)", {}),
    ],
)
def test_supported_types_reuse_certified_literal_validation(
    kind: str, valid: Any, invalid: Any, attributes: dict[str, Any]
) -> None:
    field = FieldDefinition.model_validate(
        {"field_id": uuid4(), "name": "custom_value", "value_type": kind, **attributes}
    )
    schema = _schema(field)
    assert (
        json.loads(schema.validate_values({str(field.field_id): valid}))[str(field.field_id)]
        == valid
    )
    with pytest.raises(BusinessOSError, match="violate published schema"):
        schema.validate_values({str(field.field_id): invalid})
    assert kind in schema.supported_field_types


def test_required_null_unknown_over_budget_and_clear_tombstone() -> None:
    field = FieldDefinition(
        field_id=uuid4(), name="custom_label", value_type="text", nullable=False
    )
    schema = _schema(field, max_document_bytes=1024)
    for values in (
        {},
        {str(field.field_id): None},
        {str(uuid4()): "unknown"},
        {str(field.field_id): "x" * 1100},
    ):
        with pytest.raises(BusinessOSError):
            schema.validate_values(values)
    assert schema.validate_values({}, cleared=True) == "{}"
    with pytest.raises(BusinessOSError):
        schema.validate_values({str(field.field_id): "bad clear"}, cleared=True)
    with pytest.raises(FrozenInstanceError):
        schema.pin = CustomSchemaPin(uuid4(), uuid4(), "bad")  # type: ignore[misc]


@pytest.mark.parametrize("classified", [True, False])
def test_classified_and_reference_retained_schemas_never_fall_back(classified: bool) -> None:
    field = FieldDefinition.model_validate(
        {
            "field_id": uuid4(),
            "name": "custom_value",
            "value_type": "text" if classified else "reference",
            **(
                {"classification_ref": "foundation.data_governance.restricted"}
                if classified
                else {
                    "reference_namespace": "foundation.party.party",
                    "reference_contract_version": "1",
                }
            ),
        }
    )
    for cleared in (True, False):
        with pytest.raises(BusinessOSError) as failure:
            _schema(field).validate_values({}, cleared=cleared)
        assert failure.value.code == (
            "classification_unavailable" if classified else "custom_reference_unsupported"
        )


def test_duplicate_and_browser_schema_authority_rejected() -> None:
    value = CustomFieldValue(field_id=uuid4(), value="x")
    payload = {
        "tenant_id": uuid4(),
        "party_id": uuid4(),
        "expected_version": 0,
        "values": (value, value),
    }
    with pytest.raises(ValidationError):
        WritePartyCustomValues.model_validate(payload)
    payload["values"] = (value,)
    for authority in ("owner_module_id", "revision_id", "classification_ref", "field_types"):
        with pytest.raises(ValidationError):
            WritePartyCustomValues.model_validate({**payload, authority: "browser-authority"})


def test_exact_party_owner_requires_operator_artifact_and_display_only() -> None:
    module = PartyModule()
    assert [
        (owner.resource_namespace, owner.owner_module_id, owner.contract_version)
        for owner in module.manifest.resource_ownership
    ] == [("foundation.party.party", "foundation.party", "1")]
    registry = ModuleRegistry(platform_version="0.2.0", sdk_version="0.1.0")
    with pytest.raises(ConfigurationError):
        registry.add(module)
    PARTY_CUSTOMIZABLE.query.require("display")
    for operation in ("filter", "sort", "search", "uniqueness", "range", "unknown"):
        with pytest.raises(BusinessOSError) as failure:
            PARTY_CUSTOMIZABLE.query.require(operation)
        assert failure.value.code == "custom_query_unsupported"
    assert PARTY_CUSTOMIZABLE.optimistic_concurrency
    assert not PARTY_CUSTOMIZABLE.reference_fields
    assert not PARTY_CUSTOMIZABLE.classified_fields


def test_bounded_comparisons_conditional_required_and_precision() -> None:
    amount = FieldDefinition(
        field_id=uuid4(), name="custom_amount", value_type="decimal", precision=5, scale=2
    )
    reason = FieldDefinition(field_id=uuid4(), name="custom_reason", value_type="text")
    snapshot = DefinitionSnapshot(
        kind="field_set",
        fields=(amount, reason),
        rules=(
            ValidationRule(left_field="custom_amount", comparison="gt", right_literal="0.00"),
            ValidationRule(
                left_field="custom_amount",
                comparison="ge",
                right_literal="100.00",
                require_field="custom_reason",
            ),
        ),
    )
    schema = _PublishedSchema(
        CustomSchemaPin(uuid4(), uuid4(), snapshot.digest()), snapshot, MetadataLimits()
    )
    for number in ("0.00", "-1.00", "100.00", "1000.00", "1.001"):
        with pytest.raises(BusinessOSError):
            schema.validate_values({str(amount.field_id): number})
    assert json.loads(schema.validate_values({str(amount.field_id): "99.00"}))
    assert json.loads(
        schema.validate_values({str(amount.field_id): "100.00", str(reason.field_id): "approved"})
    )


def test_field_quota_and_document_budget_cannot_be_bypassed() -> None:
    fields = tuple(
        FieldDefinition(field_id=uuid4(), name=f"custom_{index}", value_type="text")
        for index in range(129)
    )
    snapshot = DefinitionSnapshot(kind="field_set", fields=fields)
    schema = _PublishedSchema(
        CustomSchemaPin(uuid4(), uuid4(), snapshot.digest()), snapshot, MetadataLimits()
    )
    with pytest.raises(BusinessOSError):
        schema.validate_values({}, cleared=True)
    value = FieldDefinition(field_id=uuid4(), name="custom_label", value_type="text")
    with pytest.raises(BusinessOSError):
        _schema(value).validate_values({str(value.field_id): "x" * 65536})
