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


@pytest.mark.parametrize(
    ("kind", "value", "options"),
    [
        ("date", "2025-02-29", {}),
        ("date", "20260101", {}),
        ("instant", "2026-01-01T10:00:00", {}),
        ("instant", "invalid", {}),
        ("uuid", "not-a-uuid", {}),
        ("email", "a@@example.com", {}),
        ("email", "a@-invalid.example", {}),
        ("url", "javascript:alert(1)", {}),
        ("url", "https://user:password@example.com", {}),
        ("url", "https://example.com:99999", {}),
        ("boolean", "false", {}),
        ("integer", True, {}),
        ("integer", 1.5, {}),
        ("integer", 2**63, {}),
        ("text", 1, {}),
        ("text", "long", {"max_length": 2}),
        ("phone", "call-me", {}),
        ("enum", "other", {"enum_choices": ["yes", "no"]}),
        ("decimal", "1.2", {}),
        ("money", None, {}),
        ("decimal", "NaN", {"precision": 6, "scale": 2}),
        ("decimal", "1e5", {"precision": 6, "scale": 2}),
        ("decimal", "100.00", {"precision": 4, "scale": 2}),
        ("decimal", "1.234", {"precision": 6, "scale": 2}),
        ("money", "1.00", {"precision": 6, "scale": 2}),
        ("money", {"amount": "1.00", "currency": "usd"}, {"precision": 6, "scale": 2}),
    ],
)
def test_invalid_typed_defaults_rejected(
    kind: str, value: object, options: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        FieldDefinition.model_validate(
            {
                "field_id": str(uuid4()),
                "name": "x",
                "value_type": kind,
                "literal_default": value,
                **options,
            }
        )


@pytest.mark.parametrize(
    ("kind", "value", "options"),
    [
        ("date", "2024-02-29", {}),
        ("instant", "2026-01-01T10:00:00Z", {}),
        ("uuid", "00000000-0000-0000-0000-000000000001", {}),
        ("email", "first.last@example.com", {}),
        ("url", "https://example.com/a?q=x", {}),
        ("phone", "+880 123456789", {}),
        ("boolean", False, {}),
        ("integer", 123, {}),
        ("enum", "yes", {"enum_choices": ["yes", "no"]}),
        ("decimal", "99.99", {"precision": 4, "scale": 2}),
        ("money", {"amount": "99.99", "currency": "USD"}, {"precision": 4, "scale": 2}),
    ],
)
def test_supported_typed_defaults_round_trip(
    kind: str, value: object, options: dict[str, object]
) -> None:
    field = FieldDefinition.model_validate(
        {
            "field_id": str(uuid4()),
            "name": "x",
            "value_type": kind,
            "literal_default": value,
            **options,
        }
    )
    assert FieldDefinition.model_validate_json(field.model_dump_json()) == field


@pytest.mark.parametrize(
    ("kind", "comparison", "operand"),
    [
        ("boolean", "eq", "true"),
        ("boolean", "gt", True),
        ("integer", "lt", "twelve"),
        ("integer", "eq", True),
        ("text", "ge", "alpha"),
        ("date", "lt", "2025-02-29"),
        ("uuid", "eq", "bad"),
        ("email", "eq", "not-an-email"),
    ],
)
def test_rule_operands_and_operators_are_typed(kind: str, comparison: str, operand: object) -> None:
    with pytest.raises(ValidationError):
        DefinitionSnapshot.model_validate(
            {
                "kind": "field_set",
                "fields": [{"field_id": str(uuid4()), "name": "x", "value_type": kind}],
                "rules": [{"left_field": "x", "comparison": comparison, "right_literal": operand}],
            }
        )


def test_zero_decimal_fits_precision_equal_to_scale() -> None:
    field = FieldDefinition(
        field_id=uuid4(),
        name="fraction",
        value_type=FieldType.DECIMAL,
        precision=2,
        scale=2,
        literal_default="0",
    )
    assert field.literal_default == "0"
